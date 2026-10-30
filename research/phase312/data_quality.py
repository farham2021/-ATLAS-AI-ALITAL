"""Read-only quality gates for ATLAS closed OHLCV research datasets."""
import math

WIDTH_MS={"1h":3600000,"4h":14400000}

def validate_closed_candles(rows,timeframe,asof_ms):
    """Return sorted valid closed candles plus explicit rejection counts."""
    width=WIDTH_MS[timeframe]
    accepted={}
    rejected={"malformed":0,"open":0,"duplicate":0}
    for row in rows:
        try:
            if len(row)<6: raise ValueError("short candle")
            ts=int(row[0])
            o,h,l,c,v=(float(x) for x in row[1:6])
            if not all(math.isfinite(x) for x in (o,h,l,c,v)):
                raise ValueError("nonfinite")
            if min(o,h,l,c)<=0 or v<0 or h<max(o,c,l) or l>min(o,c,h):
                raise ValueError("invalid OHLCV")
            if ts+width>asof_ms:
                rejected["open"]+=1
                continue
            if ts in accepted:
                rejected["duplicate"]+=1
                # Conflicting duplicate candles must not be silently accepted.
                if tuple(accepted[ts][:6])!=tuple(row[:6]):
                    del accepted[ts]
                continue
            accepted[ts]=row
        except (TypeError,ValueError,IndexError,OverflowError):
            rejected["malformed"]+=1
    return [accepted[t] for t in sorted(accepted)],rejected

def continuous_forward_window(candles,signal_ts,horizon,timeframe):
    """Return a mature contiguous window, or None when missing a candle."""
    width=WIDTH_MS[timeframe]
    by_ts={int(b[0]):b for b in candles}
    expected=[signal_ts+width*i for i in range(1,horizon+1)]
    if not all(ts in by_ts for ts in expected): return None
    return [by_ts[ts] for ts in expected]
