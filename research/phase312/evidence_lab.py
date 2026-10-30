"""ATLAS Phase 3.12: pure shadow-only, event-first outcome labeling.
No DB writes, Telegram messages, order execution, or time-based minimum history.
Signals use signal_candle_ts in milliseconds; candles are CLOSED OHLCV arrays.
"""
from collections import defaultdict
import math

def evaluate_signal(signal, candles, horizons=(1,4,12,24)):
    """Forward labels from strictly later candles. Ambiguous intrabar hits are not wins."""
    ts=int(signal["signal_candle_ts"])
    side=str(signal.get("direction","")).upper()
    if side not in ("LONG","SHORT"): raise ValueError("direction must be LONG/SHORT")
    sign=1 if side=="LONG" else -1
    entry,sl,tp=(float(signal[k]) for k in ("entry","sl","tp1"))
    if not all(math.isfinite(x) and x>0 for x in (entry,sl,tp)):
        raise ValueError("entry/sl/tp1 must be positive finite")
    if sign*(entry-sl)<=0 or sign*(tp-entry)<=0:
        raise ValueError("invalid stop/target geometry")
    risk=abs(entry-sl)
    later=sorted((b for b in candles if int(b[0])>ts),key=lambda b:int(b[0]))
    outcomes=[]
    for h in horizons:
        if not isinstance(h,int) or h<1: raise ValueError("positive integer horizons required")
        if len(later)<h:
            outcomes.append({"horizon_candles":h,"label":"IMMATURE","mfe_r":None,"mae_r":None,"close_return_r":None})
            continue
        bars=later[:h]
        mfe=max((float(b[2])-entry if sign==1 else entry-float(b[3]))/risk for b in bars)
        mae=min((float(b[3])-entry if sign==1 else entry-float(b[2]))/risk for b in bars)
        label="TIMEOUT"
        for b in bars:
            hi,lo=float(b[2]),float(b[3])
            hit_tp=hi>=tp if sign==1 else lo<=tp
            hit_sl=lo<=sl if sign==1 else hi>=sl
            if hit_tp and hit_sl: label="AMBIGUOUS";break
            if hit_sl: label="SL_FIRST";break
            if hit_tp: label="TP_FIRST";break
        outcomes.append({"horizon_candles":h,"label":label,"mfe_r":round(mfe,6),
                         "mae_r":round(mae,6),
                         "close_return_r":round(sign*(float(bars[-1][4])-entry)/risk,6)})
    return outcomes

def evaluate_batch(signals,candles_by_symbol,horizons=(1,4,12,24)):
    rows=[]
    for signal in signals:
        for result in evaluate_signal(signal,candles_by_symbol.get(signal["symbol"],[]),horizons):
            rows.append({"symbol":signal["symbol"],"signal_candle_ts":signal["signal_candle_ts"],
                         "model_version":signal.get("model_version","UNKNOWN"),
                         "regime":signal.get("regime","UNKNOWN"),
                         "direction":signal["direction"],**result})
    return rows

def summarize(rows):
    counts=defaultdict(lambda:defaultdict(int))
    for r in rows:
        counts[(r["model_version"],r["regime"],r["horizon_candles"])][r["label"]]+=1
    return [{"model_version":k[0],"regime":k[1],"horizon_candles":k[2],
             "mature":sum(n for label,n in v.items() if label!="IMMATURE"),
             "tp_first":v["TP_FIRST"],"sl_first":v["SL_FIRST"],
             "ambiguous":v["AMBIGUOUS"],"timeout":v["TIMEOUT"],
             "immature":v["IMMATURE"]} for k,v in sorted(counts.items())]
