"""ATLAS six equity research strategies. Point-in-time, fail-closed, SHADOW ONLY."""
from datetime import date
from math import isfinite, sqrt
from statistics import pstdev

STRATEGIES = ("santa","sue","low_vol","piotroski","high_52w","magic_formula")

def day(x):
    return x if type(x) is date else date.fromisoformat(x)

def num(x):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not isfinite(x):
        raise ValueError("missing or invalid metric")
    return float(x)

def known(row, asof):
    if "available_at" not in row or day(row["available_at"]) > day(asof):
        raise ValueError("lookahead / missing publication date")

def santa(asof, december_sessions, january_sessions):
    d=day(asof)
    dec=sorted(map(day,december_sessions)); jan=sorted(map(day,january_sessions))
    if len(dec)<5 or len(jan)<2 or len(set(dec))!=len(dec) or len(set(jan))!=len(jan):
        raise ValueError("incomplete or duplicate trading calendar")
    if any(x.month!=12 or x.year!=(d.year if d.month==12 else d.year-1) for x in dec) or any(x.month!=1 or x.year!=(d.year if d.month==1 else d.year+1) for x in jan):
        raise ValueError("calendar year mismatch")
    return {"strategy":"santa","signal":int(d in dec[-5:] or d in jan[:2]),"shadow_only":True}

def sue(asof, report, prior_reports):
    known(report,asof)
    if len(prior_reports)<4: raise ValueError("requires four prior earnings surprises")
    values=[]
    for r in prior_reports:
        known(r,asof)
        if day(r["available_at"])>=day(report["available_at"]): raise ValueError("future surprise")
        values.append(num(r["actual_eps"])-num(r["consensus_eps"]))
    sd=pstdev(values)
    if sd<=0: raise ValueError("zero surprise variance")
    score=(num(report["actual_eps"])-num(report["consensus_eps"]))/sd
    return {"strategy":"sue","score":score,"shadow_only":True}

def low_vol(asof, returns, min_days=60):
    if len(returns)<min_days: raise ValueError("insufficient returns")
    seen=set(); values=[]
    for r in returns:
        known(r,asof); dt=day(r["available_at"])
        if dt in seen: raise ValueError("duplicate session")
        seen.add(dt); v=num(r["return"])
        if v < -1: raise ValueError("invalid simple return")
        values.append(v)
    return {"strategy":"low_vol","score":pstdev(values)*sqrt(252),"rank":"ascending","shadow_only":True}

def piotroski(asof, current, previous):
    known(current,asof); known(previous,asof)
    if day(previous["available_at"])>=day(current["available_at"]): raise ValueError("out-of-order statements")
    keys=("roa","cfo","leverage","current_ratio","shares","gross_margin","asset_turnover")
    c={k:num(current[k]) for k in keys}; p={k:num(previous[k]) for k in keys}
    if min(c["shares"],p["shares"])<=0: raise ValueError("invalid shares")
    flags=(c["roa"]>0,c["cfo"]>0,c["roa"]>p["roa"],c["cfo"]>c["roa"],c["leverage"]<p["leverage"],c["current_ratio"]>p["current_ratio"],c["shares"]<=p["shares"],c["gross_margin"]>p["gross_margin"],c["asset_turnover"]>p["asset_turnover"])
    return {"strategy":"piotroski","score":sum(flags),"components":flags,"shadow_only":True}

def high_52w(asof, prices, min_days=200):
    if len(prices)<min_days: raise ValueError("insufficient 52-week coverage")
    seen=set()
    for r in prices:
        known(r,asof)
        if r["available_at"] in seen: raise ValueError("duplicate session")
        seen.add(r["available_at"])
    ordered=sorted(prices,key=lambda r:r["available_at"])[-252:]
    highs=[num(r["adjusted_high"]) for r in ordered]
    closes=[num(r["adjusted_close"]) for r in ordered]
    if min(highs)<=0 or min(closes)<=0 or any(c>h for c,h in zip(closes,highs)): raise ValueError("invalid adjusted OHLC")
    return {"strategy":"high_52w","score":closes[-1]/max(highs),"rank":"descending","shadow_only":True}

def magic_formula(asof, row):
    known(row,asof)
    ebit=num(row["ebit"]); ev=num(row["enterprise_value"])
    capital=num(row["net_working_capital"])+num(row["net_fixed_assets"])
    if ev<=0 or capital<=0: raise ValueError("invalid denominator")
    return {"strategy":"magic_formula","earnings_yield":ebit/ev,"return_on_capital":ebit/capital,"shadow_only":True}

def magic_rank(rows):
    if len(rows)<2 or len(set(r["symbol"] for r in rows))!=len(rows): raise ValueError("invalid eligible universe")
    for r in rows: num(r["earnings_yield"]); num(r["return_on_capital"])
    ey={r["symbol"]:i+1 for i,r in enumerate(sorted(rows,key=lambda r:(-r["earnings_yield"],r["symbol"])))}
    roc={r["symbol"]:i+1 for i,r in enumerate(sorted(rows,key=lambda r:(-r["return_on_capital"],r["symbol"])))}
    return sorted(({"symbol":r["symbol"],"rank_sum":ey[r["symbol"]]+roc[r["symbol"]]} for r in rows),key=lambda r:(r["rank_sum"],r["symbol"]))
