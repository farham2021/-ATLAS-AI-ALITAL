"""ATLAS closed-candle PAPER strategy backtest (research-only).
No credentials or network. Input is a JSON list of cached OHLCV rows.
Usage: python research/phase312/paper_backtest.py candles.json
"""
import json,sys,math,statistics

def backtest(bars,horizon=12,fee_bps=0.0,slippage_bps=0.0):
    """Conservative TP/SL event-first evaluation, no intrabar profit assumption."""
    bars=sorted(bars,key=lambda x:int(x[0]))
    events=[]
    for i in range(65,len(bars)-horizon):
        a=bars[:i+1]
        p=float(bars[i][4])
        if not math.isfinite(p) or p<=0: continue
        highs=[float(x[2]) for x in a[-21:-1]]
        lows=[float(x[3]) for x in a[-21:-1]]
        closes=[float(x[4]) for x in a]
        vols=[float(x[5]) for x in a]
        vbase=statistics.mean(vols[-21:-1])
        vr=vols[-1]/vbase if vbase>0 else 0
        sma20=statistics.mean(closes[-20:])
        sma50=statistics.mean(closes[-50:])
        direction=(1 if p>max(highs) and sma20>sma50 and vr>=1.2
                   else -1 if p<min(lows) and sma20<sma50 and vr>=1.2 else 0)
        if not direction: continue
        tr=[max(float(bars[j][2])-float(bars[j][3]),
                abs(float(bars[j][2])-float(bars[j-1][4])),
                abs(float(bars[j][3])-float(bars[j-1][4])))
            for j in range(i-13,i+1)]
        atr=statistics.mean(tr)
        if not 0<atr/p<.1:continue
        stop=p-direction*1.5*atr
        target=p+direction*3*atr
        if min(stop,target)<=0:continue
        outcome="TIMEOUT"
        for x in bars[i+1:i+1+horizon]:
            hi,lo=float(x[2]),float(x[3])
            hit_tp=hi>=target if direction==1 else lo<=target
            hit_sl=lo<=stop if direction==1 else hi>=stop
            if hit_tp and hit_sl:outcome="AMBIGUOUS";break
            if hit_sl:outcome="SL_FIRST";break
            if hit_tp:outcome="TP_FIRST";break
        # Cost expressed in R, round-trip; fee/slippage both sides.
        risk=abs(p-stop)
        cost_r=p*(2*(fee_bps+slippage_bps)/10000)/risk
        gross_r=2 if outcome=="TP_FIRST" else -1 if outcome=="SL_FIRST" else None
        events.append({"signal_ts":int(bars[i][0]),"direction":"LONG" if direction==1 else "SHORT",
                       "entry":p,"sl":stop,"tp1":target,"label":outcome,
                       "gross_r":gross_r,"net_r":None if gross_r is None else round(gross_r-cost_r,6)})
    resolved=[x for x in events if x["net_r"] is not None]
    return {"signals":len(events),"tp_first":sum(x["label"]=="TP_FIRST" for x in events),
            "sl_first":sum(x["label"]=="SL_FIRST" for x in events),
            "ambiguous":sum(x["label"]=="AMBIGUOUS" for x in events),
            "timeout":sum(x["label"]=="TIMEOUT" for x in events),
            "resolved_expectancy_r":round(statistics.mean(x["net_r"] for x in resolved),6) if resolved else None,
            "warning":"Research only; overlapping events, execution assumptions, and provider coverage require further audit.",
            "events":events}

if __name__=="__main__":
    with open(sys.argv[1],encoding="utf-8") as f: bars=json.load(f)
    print(json.dumps(backtest(bars),indent=2))
