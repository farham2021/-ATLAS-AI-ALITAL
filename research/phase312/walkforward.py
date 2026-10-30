"""Research-only walk-forward replay. Closed candles, 70/30 chronology,
one active position per symbol, conservative intrabar collision handling.
No execution, no DB writes, no Telegram. Results are NOT production signals.
"""
import math,statistics

def replay(bars, train_fraction=.70, horizon=12, fee_bps=10, slippage_bps=5):
    if not 0.5<=train_fraction<=0.9:raise ValueError("train_fraction")
    if not isinstance(horizon,int) or horizon<1:raise ValueError("horizon")
    if min(fee_bps,slippage_bps)<0:raise ValueError("cost")
    b=sorted(bars,key=lambda x:int(x[0]))
    if len(b)<80:return {"train":[],"test":[],"split_index":None}
    # Reject malformed, duplicate, or non-contiguous timestamps rather than interpolate.
    ts=[int(x[0]) for x in b]
    widths=[ts[i]-ts[i-1] for i in range(1,len(ts))]
    if len(set(ts))!=len(ts) or len(set(widths))!=1 or widths[0]<=0:
        raise ValueError("noncontiguous or duplicate timestamps")
    for x in b:
        if len(x)<6:raise ValueError("short OHLCV")
        o,hi,lo,c,v=map(float,x[1:6])
        if not all(map(math.isfinite,(o,hi,lo,c,v))) or min(o,hi,lo,c)<=0 or v<0 or hi<max(o,c) or lo>min(o,c):
            raise ValueError("invalid OHLCV")
    split=int(len(b)*train_fraction)
    results={"train":[],"test":[],"split_index":split}
    next_allowed=65
    for i in range(65,len(b)-horizon):
        if i<next_allowed:continue
        closes=[float(x[4]) for x in b[:i+1]]
        highs=[float(x[2]) for x in b[i-20:i]]
        lows=[float(x[3]) for x in b[i-20:i]]
        vols=[float(x[5]) for x in b[i-20:i]]
        p=closes[-1]
        base=statistics.mean(vols)
        vr=float(b[i][5])/base if base>0 else 0
        d=(1 if p>max(highs) and statistics.mean(closes[-20:])>statistics.mean(closes[-50:]) and vr>=1.2
           else -1 if p<min(lows) and statistics.mean(closes[-20:])<statistics.mean(closes[-50:]) and vr>=1.2 else 0)
        if not d:continue
        tr=[max(float(b[j][2])-float(b[j][3]),abs(float(b[j][2])-float(b[j-1][4])),abs(float(b[j][3])-float(b[j-1][4])) for j in range(i-13,i+1)]
        atr=statistics.mean(tr)
        if not 0<atr/p<.1:continue
        stop=p-d*1.5*atr
        target=p+d*3*atr
        if min(stop,target)<=0:continue
        label="TIMEOUT";exit_idx=i+horizon
        for j in range(i+1,i+1+horizon):
            hi,lo=float(b[j][2]),float(b[j][3])
            tp=(hi>=target if d==1 else lo<=target)
            sl=(lo<=stop if d==1 else hi>=stop)
            if tp and sl:label="AMBIGUOUS";exit_idx=j;break
            if sl:label="SL_FIRST";exit_idx=j;break
            if tp:label="TP_FIRST";exit_idx=j;break
        next_allowed=exit_idx+1
        # Purge train signals whose outcomes cross into the test period.
        if i<split and exit_idx>=split:continue
        risk=1.5*atr
        gross=(2 if label=="TP_FIRST" else -1 if label in ("SL_FIRST","AMBIGUOUS") else d*(float(b[exit_idx][4])-p)/risk)
        cost=p*2*(fee_bps+slippage_bps)/10000/risk
        row={"signal_ts":int(b[i][0]),"exit_ts":int(b[exit_idx][0]),"label":label,"gross_r":round(gross,6),"net_r":round(gross-cost,6)}
        results["train" if i<split else "test"].append(row)
    return results

def summary(result):
    out={}
    for cohort in ("train","test"):
        rows=result[cohort]
        out[cohort]={"trades":len(rows),"tp_first":sum(r["label"]=="TP_FIRST" for r in rows),
                     "sl_first":sum(r["label"]=="SL_FIRST" for r in rows),
                     "ambiguous":sum(r["label"]=="AMBIGUOUS" for r in rows),
                     "net_r_sum":round(sum(r["net_r"] for r in rows),6),
                     "net_r_mean":round(statistics.mean(r["net_r"] for r in rows),6) if rows else None}
    return out
