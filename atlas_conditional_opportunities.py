"""Read-only opportunity discovery. Conditional plans are NOT executable signals."""
import math

def _n(x):
    try:
        z=float(x)
        return z if math.isfinite(z) else None
    except (ValueError,TypeError): return None

def discover(rows, limit=5):
    out=[]
    for r in rows or []:
        if not isinstance(r,dict): continue
        sym=str(r.get("coin") or r.get("symbol") or "").upper()
        if not sym: continue
        canonical=str(r.get("decision") or r.get("action") or "WAIT").upper()
        side=str(r.get("direction") or r.get("side") or "").upper()
        if side not in ("LONG","SHORT"):
            side="LONG" if canonical in ("BUY","ACCUMULATE") else "SHORT" if canonical in ("SELL","REDUCE") else ""
        if not side: continue
        trigger=_n(r.get("trigger"))
        if trigger is None: trigger=_n(r.get("watch_trigger"))
        confidence=_n(r.get("decision_confidence"))
        if confidence is None: confidence=_n(r.get("confidence"))
        state="CONFIRMED" if canonical in ("BUY","SELL") and r.get("executable") is True else "CONDITIONAL"
        if state=="CONDITIONAL" and (trigger is None or trigger<=0): continue
        out.append(dict(symbol=sym,side=side,state=state,trigger=trigger if state=="CONDITIONAL" else None,
                        confidence=confidence,reason="Canonical executable" if state=="CONFIRMED" else "Watch only: trigger requires confirmation"))
    out.sort(key=lambda x:(x["state"]!="CONFIRMED",-(x["confidence"] if x["confidence"] is not None else -1),x["symbol"]))
    return out[:max(0,min(5,int(limit)))]
