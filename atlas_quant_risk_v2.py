"""ATLAS Quant Risk V2: closed-candle-only research, not a probability or trading signal."""
from math import sqrt,isfinite
WEIGHTS={"trend":.25,"momentum":.20,"volatility":.20,"mean_reversion":.15,"volume":.10,"multi_timeframe":.10}
def clamp(v,lo=0.,hi=100.): return max(lo,min(hi,v))
def ema(values,n):
 a=2/(n+1);v=sum(values[:n])/n
 for x in values[n:]:v=a*x+(1-a)*v
 return v
def compute(closed_4h,closed_1d):
 """Each row: close,high,low,volume. Both inputs must contain ONLY CLOSED bars."""
 if len(closed_4h)<250 or len(closed_1d)<250:return {"status":"INSUFFICIENT_DATA"}
 for bars in (closed_4h,closed_1d):
  if any(not all(isfinite(float(b[k])) and float(b[k])>0 for k in ("close","high","low","volume")) or float(b["high"])<float(b["low"]) for b in bars):
   return {"status":"INVALID_DATA"}
 c=[float(x["close"]) for x in closed_4h];d=[float(x["close"]) for x in closed_1d]
 h=[float(x["high"]) for x in closed_4h];lo=[float(x["low"]) for x in closed_4h]
 v=[float(x["volume"]) for x in closed_4h]
 tr=[max(h[i]-lo[i],abs(h[i]-c[i-1]),abs(lo[i]-c[i-1])) for i in range(1,len(c))]
 atr=sum(tr[-14:])/14;atr_long=sum(tr[-50:])/50
 regime="HIGH" if atr>1.5*atr_long else ("LOW" if atr<.75*atr_long else "NORMAL")
 e=ema(c,200);prev_e=ema(c[:-1],200);daily=ema(d,200)
 gains=[max(c[i]-c[i-1],0) for i in range(1,len(c))]
 losses=[max(c[i-1]-c[i],0) for i in range(1,len(c))]
 ag=sum(gains[:14])/14;al=sum(losses[:14])/14
 for g,l in zip(gains[14:],losses[14:]):ag=(13*ag+g)/14;al=(13*al+l)/14
 rsi=100 if al==0 else 100-100/(1+ag/al)
 m=sum(c[-20:])/20;sd=sqrt(sum((x-m)**2 for x in c[-20:])/20)
 pb=.5 if sd==0 else (c[-1]-(m-2*sd))/(4*sd)
 vr=v[-1]/max(sum(v[-21:-1])/20,1e-12)
 atr_pct=100*atr/c[-1];atr_base=100*atr_long/c[-1]
 trend=clamp(abs(c[-1]/e-1)*700+abs(e/prev_e-1)*1000)
 momentum=clamp(abs(rsi-50)*2)
 volatility=clamp(50*atr_pct/max(atr_base,1e-9))
 meanrev=clamp(abs(pb-.5)*200)
 volume=clamp(abs(vr-1)*65)
 align=100 if (c[-1]>e)==(d[-1]>daily) else 0
 components={"trend":trend,"momentum":momentum,"volatility":volatility,"mean_reversion":meanrev,"volume":volume,"multi_timeframe":align}
 weights=dict(WEIGHTS)
 if regime=="HIGH":
  weights["volatility"]+=.10;weights["trend"]-=.10
 risk=round(sum(components[k]*weights[k] for k in weights),2)
 bias=round(clamp(((c[-1]/e-1)*800+(rsi-50)*1.2+(d[-1]/daily-1)*600),-100,100),2)
 return {"status":"RESEARCH","risk_score":risk,"bias_score":bias,"regime":regime,"rsi":round(rsi,2),"components":{k:round(x,2) for k,x in components.items()},"weights":weights,"signal":False,"validated":False}
