"""Fail-closed OHLCV adapter for optional Kronos research inference.

No model weights downloaded, no production predictions, no trading.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

def prepare_ohlcv(candles, *, min_bars=32, max_gap_factor=1.5):
    if len(candles)<min_bars:
        raise ValueError("insufficient history")
    times=[c.timestamp for c in candles]
    if any(not isinstance(t,int) or isinstance(t,bool) for t in times):
        raise ValueError("timestamps must be integer milliseconds")
    steps=[b-a for a,b in zip(times,times[1:])]
    if any(s<=0 for s in steps):
        raise ValueError("duplicate or unordered timestamps")
    interval=min(steps)
    if any(s>interval*max_gap_factor for s in steps):
        raise ValueError("missing candles or irregular interval")
    for c in candles:
        if not all(isfinite(v) for v in (c.open,c.high,c.low,c.close,c.volume)):
            raise ValueError("nonfinite OHLCV")
        if min(c.open,c.high,c.low,c.close)<=0 or c.volume<0:
            raise ValueError("nonpositive price or negative volume")
        if c.low>min(c.open,c.close) or c.high<max(c.open,c.close):
            raise ValueError("inconsistent OHLC")
    return [{"timestamps":c.timestamp,"open":c.open,"high":c.high,
             "low":c.low,"close":c.close,"volume":c.volume} for c in candles]

def model_readiness(candles, *, model_loaded=False):
    prepared=prepare_ohlcv(candles)
    return {"status":"READY_FOR_SHADOW_INFERENCE" if model_loaded else "MODEL_NOT_LOADED",
            "bars":len(prepared),"interval_ms":prepared[1]["timestamps"]-prepared[0]["timestamps"],
            "shadow_only":True,"live_signal_allowed":False}
