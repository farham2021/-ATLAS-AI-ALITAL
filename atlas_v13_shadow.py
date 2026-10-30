"""ATLAS v13 shadow-only decision research. Never executes trades or sends Telegram."""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite

def _num(v):
    try:
        x=float(v)
        return x if isfinite(x) else None
    except (ValueError,TypeError): return None

def _verified(row):
    return row.get("market_data_verified") is True and row.get("signal_verified") is True

def early_warning(row):
    """Pre-confirmation risk/growth watch, never executable."""
    symbol=str(row.get("symbol") or "").upper()
    if not symbol or not _verified(row): return {"symbol":symbol,"state":"DATA_UNAVAILABLE","direction":None}
    change=_num(row.get("change_pct_24h"))
    vol=_num(row.get("volume_ratio"))
    oi=_num(row.get("oi_change_pct_24h"))
    if None in (change,vol,oi): return {"symbol":symbol,"state":"INSUFFICIENT_EVIDENCE","direction":None}
    if change<=-3 and vol>=1.5 and oi>=2: direction="RISK_OFF"
    elif change>=3 and vol>=1.5 and oi>=2: direction="BREAKOUT_WATCH"
    else: direction=None
    return {"symbol":symbol,"state":"WATCH" if direction else "NO_ALERT","direction":direction,"inputs":{"change_pct_24h":change,"volume_ratio":vol,"oi_change_pct_24h":oi}}

def rank_opportunities(rows,limit=5):
    """Only verified confirmed signals; no synthetic prices or orders."""
    out=[]
    for r in rows:
        if not isinstance(r,dict) or not _verified(r): continue
        side=str(r.get("decision") or r.get("decision_state") or "").upper()
        if side not in ("BUY","SELL","CONFIRMED_BUY","CONFIRMED_SELL"): continue
        entry,stop,target=(_num(r.get(k)) for k in ("entry","sl","tp1"))
        confidence=_num(r.get("confidence"))
        if None in (entry,stop,target,confidence) or not 0<=confidence<=100: continue
        risk=abs(entry-stop)
        reward=(target-entry) if "BUY" in side else (entry-target)
        valid=(stop<entry<target) if "BUY" in side else (target<entry<stop)
        if not valid or risk<=0 or reward/risk<2: continue
        out.append({"symbol":r.get("symbol"),"side":side,"entry":entry,"sl":stop,"tp1":target,"rr":round(reward/risk,3),"confidence":confidence})
    return sorted(out,key=lambda r:(r["confidence"],r["rr"]),reverse=True)[:limit]

def allocation_gap(holdings,target_weights,total_value):
    """Amounts in the SAME currency as total_value. No exchange-rate inference."""
    total=_num(total_value)
    if total is None or total<=0: raise ValueError("total_value must be positive")
    if any((_num(v) is None or _num(v)<0) for v in target_weights.values()): raise ValueError("invalid target weight")
    if abs(sum(float(v) for v in target_weights.values())-1)>1e-6: raise ValueError("target weights must sum to 1")
    if any((_num(v) is None or _num(v)<0) for v in holdings.values()): raise ValueError("invalid holdings")
    if sum(float(v) for v in holdings.values())>total*1.000001: raise ValueError("holdings exceed total value")
    return {k:round(total*float(w)-float(holdings.get(k,0)),2) for k,w in target_weights.items()}

def score_outcomes(records):
    """Closed-only, fee/slippage-adjusted R; no claim of predictive validity."""
    vals=[]
    for r in records:
        if not r.get("closed"): continue
        gross,fees,slip=(_num(r.get(k)) for k in ("gross_r","fee_r","slippage_r"))
        if None in (gross,fees,slip) or fees<0 or slip<0: continue
        vals.append(gross-fees-slip)
    if not vals: return {"count":0,"expectancy_r":None,"win_rate":None,"max_drawdown_r":None}
    equity=peak=drawdown=0.0
    for v in vals:
        equity+=v;peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return {"count":len(vals),"expectancy_r":round(sum(vals)/len(vals),4),"win_rate":round(sum(v>0 for v in vals)/len(vals),4),"max_drawdown_r":round(drawdown,4)}

def delivery_audit(expected,receipts):
    """Receipt requires Telegram ok=True and a message_id for each destination/report."""
    confirmed={(r.get("destination"),r.get("report")) for r in receipts if r.get("ok") is True and r.get("message_id") is not None}
    missing=sorted(set(tuple(x) for x in expected)-confirmed)
    return {"complete":not missing,"missing":[{"destination":d,"report":r} for d,r in missing],"confirmed":len(set(tuple(x) for x in expected)&confirmed)}
