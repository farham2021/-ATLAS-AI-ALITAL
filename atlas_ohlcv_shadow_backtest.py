"""ATLAS OHLCV shadow backtest. Research only; no live order or alert.
Uses last CLOSED cached candles, one position at a time per asset/timeframe.
Conservative intrabar assumption: if stop and target both touched, STOP wins.
"""
import os,json,urllib.request,urllib.parse,statistics
from collections import defaultdict
def load():
 base=os.environ["SUPABASE_URL"].rstrip("/")
 key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 q=urllib.parse.urlencode({"select":"symbol,timeframe,provider,last_closed_ts,rows_json,updated_at","limit":1000})
 req=urllib.request.Request(base+"/rest/v1/atlas_ohlcv_closed_cache?"+q,headers={"apikey":key,"Authorization":"Bearer "+key})
 with urllib.request.urlopen(req,timeout=45) as r:return json.load(r)
def normalize(raw):
 if isinstance(raw,str):raw=json.loads(raw)
 if isinstance(raw,dict):raw=raw.get("rows",raw.get("data",raw.get("ohlcv",[])))
 out=[]
 for a in raw:
  try:
   if isinstance(a,dict):
    t=a.get("timestamp",a.get("ts",a.get("time")));o,h,l,c,v=(float(a[k]) for k in ("open","high","low","close","volume"))
   else:t,o,h,l,c,v=a[:6];o,h,l,c,v=map(float,(o,h,l,c,v))
   if t is None or not (l>0 and h>=max(o,c) and l<=min(o,c) and v>=0):continue
   out.append((int(t),o,h,l,c,v))
  except (TypeError,ValueError,KeyError):continue
 return sorted({a[0]:a for a in out}.values())
def simulate(bars):
 # Prior 20-candle breakout, 14-bar ATR, entry next candle OPEN, stop 1.5 ATR, target 3 ATR.
 # Signals only after candle close; no lookahead into next candle for decisions.
 trades=[];i=21
 while i<len(bars)-1:
  hist=bars[i-20:i];c=bars[i][4]
  ranges=[max(hist[j][2]-hist[j][3],abs(hist[j][2]-hist[j-1][4]),abs(hist[j][3]-hist[j-1][4])) for j in range(1,len(hist))]
  atr=statistics.mean(ranges[-14:])
  if atr<=0:i+=1;continue
  direction=1 if c>max(x[2] for x in hist) else -1 if c<min(x[3] for x in hist) else 0
  if not direction:i+=1;continue
  entry=bars[i+1][1];risk=1.5*atr
  if entry<=0 or risk/entry>0.10:i+=1;continue
  stop=entry-direction*risk;target=entry+direction*2*risk
  if stop<=0:i+=1;continue
  exit_price=None;end=min(i+13,len(bars)-1)
  for j in range(i+1,end+1):
   high,low=bars[j][2],bars[j][3]
   hit_stop=low<=stop if direction==1 else high>=stop
   hit_target=high>=target if direction==1 else low<=target
   if hit_stop:exit_price=stop;end=j;break
   if hit_target:exit_price=target;end=j;break
  if exit_price is None:exit_price=bars[end][4]
  # fixed illustrative 0.20% round-trip trading costs, no funding or execution impact
  net_pct=direction*(exit_price/entry-1)*100-0.20
  trades.append({"time":bars[i][0],"net_pct":net_pct,"r":net_pct/(risk/entry*100)})
  i=end+1
 return trades
def summarize(ts):
 if not ts:return {"trades":0,"promotion_eligible":False}
 values=[x["net_pct"] for x in ts]
 return {"trades":len(ts),"win_rate_pct":round(100*sum(x>0 for x in values)/len(values),2),
         "mean_net_pct":round(statistics.mean(values),3),"median_net_pct":round(statistics.median(values),3),
         "mean_r":round(statistics.mean(x["r"] for x in ts),3),"promotion_eligible":False}
def main():
 records=load();output=[]
 for r in records:
  try:
   bars=normalize(r["rows_json"])
   if len(bars)<90:continue
   ts=simulate(bars)
   cut=int(len(bars)*0.7)
   border=bars[cut][0]
   dev=[x for x in ts if x["time"]<border]
   hold=[x for x in ts if x["time"]>=border]
   output.append({"symbol":r["symbol"],"timeframe":r["timeframe"],"provider":r["provider"],
     "candles":len(bars),"development":summarize(dev),"holdout":summarize(hold)})
  except (ValueError,TypeError,KeyError,IndexError) as e:
   print("SKIP invalid cached series",r.get("symbol"),type(e).__name__)
 print(json.dumps({"mode":"SHADOW_ONLY","strategy":"20-bar closed breakout / 1.5 ATR stop / 3 ATR target",
   "cost_assumption_pct":0.20,"caveats":"Cache is a latest-window snapshot, not point-in-time history; no exchange spread/funding; same-bar stop priority; no cross-validation; NOT live-trade-ready",
   "series_tested":len(output),"results":output[:120],"production_promotion_allowed":False},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
