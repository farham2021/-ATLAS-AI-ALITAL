"""ATLAS 3.0 portfolio drawdown shield — SHADOW ONLY, no orders/Telegram.

Inputs are time-ordered, flow-adjusted portfolio NAV observations. A new high
water mark resets the drawdown. Never use raw balance changes as market loss.
"""
from dataclasses import dataclass
from math import isfinite

THRESHOLDS={"WATCH":0.05,"HIGH":0.08,"CRITICAL":0.12}
SEVERITY={"NONE":0,"WATCH":1,"HIGH":2,"CRITICAL":3}

@dataclass(frozen=True)
class Observation:
    timestamp: str
    nav: float
    external_flow: float = 0.0

def classify(drawdown):
    if not 0<=drawdown<=1:raise ValueError("invalid drawdown")
    for level in ("CRITICAL","HIGH","WATCH"):
        if drawdown+1e-12>=THRESHOLDS[level]:return level
    return "NONE"

def evaluate(observations):
    """Time-weighted NAV index removes contributions/withdrawals.

    Flow is assumed to occur immediately before valuation; for large or intraday
    flows, exact time-weighted valuations are required. Do not use this shortcut
    for live risk decisions without a verified flow ledger.
    """
    if not observations:raise ValueError("no observations")
    if any(not isfinite(o.nav) or not isfinite(o.external_flow) for o in observations):
        raise ValueError("non-finite NAV or flow")
    if any(observations[i].timestamp>=observations[i+1].timestamp for i in range(len(observations)-1)):
        raise ValueError("timestamps not strictly increasing")
    if observations[0].nav<=0 or observations[0].external_flow!=0:
        raise ValueError("invalid initial NAV/flow")
    index=1.0;peak=1.0;out=[]
    previous=observations[0].nav
    for i,o in enumerate(observations):
        if i:
            base=previous+o.external_flow
            if base<=0 or o.nav<0:raise ValueError("invalid flow-adjusted NAV")
            index*=o.nav/base
            previous=o.nav
        peak=max(peak,index)
        drawdown=max(0.0,1-index/peak)
        level=classify(drawdown)
        out.append({"timestamp":o.timestamp,"nav_index":round(index,10),
                    "drawdown_pct":round(100*drawdown,4),"level":level,
                    "shadow_only":True})
    return out

def transitions(results):
    """Record only new severity escalations; no repeated alert spam."""
    prev="NONE";events=[]
    for r in results:
        if SEVERITY[r["level"]]>SEVERITY[prev]:
            events.append({"timestamp":r["timestamp"],"level":r["level"],
                           "drawdown_pct":r["drawdown_pct"],"shadow_only":True})
        prev=r["level"]
    return events
