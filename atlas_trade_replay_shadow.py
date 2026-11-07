"""ATLAS shadow trade replay inspired by day-trader-skill Time Machine.

Historical bar-path bootstrap; NOT a calibrated forecast or live trading.
Conservative stop-first when stop and target occur in the same OHLC bar.
"""
from dataclasses import dataclass
from random import Random
from math import isfinite

@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float

def validate(bars):
    if len(bars) < 2:
        raise ValueError("at least two historical bars required")
    for b in bars:
        if not all(isfinite(v) and v > 0 for v in (b.open,b.high,b.low,b.close)):
            raise ValueError("invalid OHLC")
        if b.low > min(b.open,b.close) or b.high < max(b.open,b.close):
            raise ValueError("inconsistent OHLC")

def replay(bars, *, entry, stop, target, side="long", horizon=12, runs=1000, seed=19):
    validate(bars)
    if side not in ("long","short") or not (1 <= horizon <= 500):
        raise ValueError("invalid side or horizon")
    if not (1 <= runs <= 100000) or not all(isfinite(v) and v>0 for v in (entry,stop,target)):
        raise ValueError("invalid runs or price")
    if not (stop < entry < target if side=="long" else target < entry < stop):
        raise ValueError("stop/target on wrong side")
    # OHLC relative to previous close; no future information beyond supplied historical bars.
    pool=[]
    for previous, current in zip(bars,bars[1:]):
        pool.append(tuple(v/previous.close for v in (current.open,current.high,current.low,current.close)))
    rng=Random(seed)
    counts={"stop":0,"target":0,"timeout":0}
    r_values=[]
    risk=abs(entry-stop)
    for _ in range(runs):
        price=entry
        outcome="timeout"
        for _ in range(horizon):
            op,hi,lo,cl=pool[rng.randrange(len(pool))]
            high=price*hi
            low=price*lo
            close=price*cl
            stop_hit=(low<=stop if side=="long" else high>=stop)
            target_hit=(high>=target if side=="long" else low<=target)
            if stop_hit:
                outcome="stop"
                price=stop
                break
            if target_hit:
                outcome="target"
                price=target
                break
            price=close
        counts[outcome]+=1
        signed=(price-entry) if side=="long" else (entry-price)
        r_values.append(signed/risk)
    return {"runs":runs,"horizon":horizon,"side":side,"seed":seed,
            "outcomes":counts,"target_frequency":counts["target"]/runs,
            "stop_frequency":counts["stop"]/runs,"mean_r":sum(r_values)/runs,
            "shadow_only":True,"not_calibrated_probability":True}
