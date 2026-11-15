"""Historical 4H perpetual research: paginated Bybit candles, signed funding, OOS evaluation.
No live orders, Telegram, or production-table writes. Fail closed on missing data.
"""
import argparse,datetime,json,math,time,urllib.parse,urllib.request,calendar,sys
from pathlib import Path
from atlas_futures_v2 import MS,candles,indicators,make_setup,audit_one
from atlas_futures_costs import ExecutionCostModel,evaluate_trade_net_r
UTC=datetime.timezone.utc
def get(path,params):
 url="https://api.bybit.com"+path+"?"+urllib.parse.urlencode(params)
 req=urllib.request.Request(url,headers={"User-Agent":"ATLAS-Research/2.0"})
 for retry in range(4):
  try:
   with urllib.request.urlopen(req,timeout=30) as r:obj=json.load(r)
   if obj.get("retCode")!=0:raise RuntimeError(str(obj.get("retMsg")))
   return obj["result"]
  except (OSError,ValueError,RuntimeError):
   if retry==3:raise
   time.sleep(2**retry)
def history(symbol,start_ms,end_ms):
 result={};cursor=end_ms
 while cursor>=start_ms:
  rows=get("/v5/market/kline",{"category":"linear","symbol":symbol+"USDT","interval":"240","end":cursor,"limit":1000}).get("list",[])
  if not rows:break
  for row in rows:
   t=int(row[0])
   if start_ms<=t<end_ms:result[t]=row[:6]
  oldest=min(int(x[0]) for x in rows)
  if oldest>=cursor:raise RuntimeError("Pagination did not advance")
  cursor=oldest-1
  time.sleep(.12)
 return candles(list(result.values()),end_ms)
def funding(symbol,start_ms,end_ms):
 result={};cursor=end_ms
 while cursor>=start_ms:
  rows=get("/v5/market/funding/history",{"category":"linear","symbol":symbol+"USDT","endTime":cursor,"limit":200}).get("list",[])
  if not rows:break
  for row in rows:
   t=int(row["fundingRateTimestamp"])
   if start_ms<=t<end_ms:result[t]=float(row["fundingRate"])
  oldest=min(int(x["fundingRateTimestamp"]) for x in rows)
  if oldest>=cursor:raise RuntimeError("Funding pagination did not advance")
  cursor=oldest-1
  time.sleep(.12)
 return sorted(result.items())

def okx_get(path,params):
 url="https://www.okx.com"+path+"?"+urllib.parse.urlencode(params)
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 ATLAS-Research"})
 for retry in range(4):
  try:
   with urllib.request.urlopen(req,timeout=30) as response:obj=json.load(response)
   if obj.get("code")!="0":raise RuntimeError(str(obj.get("msg")))
   return obj["data"]
  except (OSError,ValueError,RuntimeError):
   if retry==3:raise
   time.sleep(2**retry)

def okx_history(symbol,start_ms,end_ms):
 # OKX history-candles uses 'after' for older timestamps.
 result={};cursor=end_ms
 while cursor>=start_ms:
  rows=okx_get("/api/v5/market/history-candles",{"instId":symbol+"-USDT-SWAP","bar":"4H","after":cursor,"limit":100})
  if not rows:break
  for row in rows:
   t=int(row[0])
   if start_ms<=t<end_ms and row[8]=="1":
    # OKX swap volume field 5 is contracts; use quote currency volume (field 7).
    result[t]=[t,*row[1:5],row[7]]
  oldest=min(int(x[0]) for x in rows)
  if oldest>=cursor:raise RuntimeError("OKX candles pagination stalled")
  cursor=oldest-1
  time.sleep(.13)
 return candles(list(result.values()),end_ms)

def okx_funding(symbol,start_ms,end_ms):
 # Funding history is public but exchange may cap lookback; fail closed if so.
 result={};cursor=end_ms
 while cursor>=start_ms:
  rows=okx_get("/api/v5/public/funding-rate-history",{"instId":symbol+"-USDT-SWAP","after":cursor,"limit":100})
  if not rows:break
  for row in rows:
   t=int(row["fundingTime"])
   if start_ms<=t<end_ms:result[t]=float(row.get("realizedRate") or row["fundingRate"])
  oldest=min(int(x["fundingTime"]) for x in rows)
  if oldest>=cursor:raise RuntimeError("OKX funding pagination stalled")
  cursor=oldest-1
  time.sleep(.13)
 return sorted(result.items())

def source_data(symbol,start_ms,end_ms):
 errors=[]
 for provider,history_fn,funding_fn in (("OKX_SWAP",okx_history,okx_funding),("BYBIT_LINEAR",history,funding)):
  try:
   bars=history_fn(symbol,start_ms,end_ms)
   rates=funding_fn(symbol,start_ms,end_ms)
   if not bars or not rates:raise ValueError("No historical candles or funding")
   return provider,bars,rates
  except Exception as exc:errors.append(provider+": "+str(exc))
 raise RuntimeError("; ".join(errors))

def contiguous(bars):
 return all(bars[i][0]-bars[i-1][0]==MS for i in range(1,len(bars)))
def simulate(symbol,bars,rates,split_ms,end_ms,provider="BYBIT_LINEAR",funding_mode="empirical"):
 trades=[];i=220
 while i<len(bars)-1:
  window=bars[max(0,i-250):i+1]
  if len(window)<220 or not contiguous(window):i+=1;continue
  signal_at=bars[i][0]+MS
  if signal_at<split_ms:i+=1;continue
  setup=make_setup(symbol,provider,window,signal_at)
  if not setup:i+=1;continue
  # Never use future bars to create the signal; future bars only settle its outcome.
  future=bars[i+1:min(len(bars),i+43)]
  if not future:break
  outcome=audit_one(setup,window+future,end_ms)
  if not outcome or outcome["exit_price"] is None:break
  opened=datetime.datetime.fromtimestamp(signal_at/1000,UTC)
  closed=datetime.datetime.fromisoformat(outcome["exit_at"])
  direction=1 if setup["side"]=="LONG" else -1
  signed_funding=sum(direction*r for t,r in rates if signal_at<t<=int(closed.timestamp()*1000)) if funding_mode=="empirical" else direction*0.0001*math.floor((closed-opened).total_seconds()/28800)
  duration=(closed-opened).total_seconds()
  # Use exact signed funding cash flow as a proportion of entry notional;
  # dynamic stop/market slippage is a stress assumption, not measured fills.
  atr_ratio=setup["indicators"]["atr14"]/setup["entry"]
  slip=min(.005,max(.0002,.1*atr_ratio))
  costs=ExecutionCostModel(entry_slippage_rate=slip,exit_slippage_rate=slip,funding_rate_8h=0)
  result=evaluate_trade_net_r(setup["side"],setup["entry"],setup["sl"],outcome["exit_price"],opened,closed,outcome["status"]=="WIN_TP2",costs)
  funding_r=signed_funding/(abs(setup["entry"]-setup["sl"])/setup["entry"])
  net=result["net_r"]-funding_r
  trades.append({"symbol":symbol,"signal_at":setup["signal_at"],"exit_at":outcome["exit_at"],"side":setup["side"],"status":outcome["status"],"gross_r":result["gross_r"],"net_r":round(net,6),"funding_r":round(funding_r,6),"slippage_rate":slip,"funding_mode":funding_mode})
  i+=max(1,len([b for b in future if b[0]+MS<=int(closed.timestamp()*1000)]))
 return trades
def metrics(trades):
 r=[x["net_r"] for x in sorted(trades,key=lambda x:x["exit_at"])]
 if not r:return {"trades":0,"verdict":"INSUFFICIENT"}
 wins=sum(x>0 for x in r);gp=sum(x for x in r if x>0);gl=-sum(x for x in r if x<0)
 equity=peak=drawdown=0
 for x in r:
  equity+=x;peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
 return {"trades":len(r),"win_rate":round(wins/len(r),4),"mean_net_r":round(sum(r)/len(r),5),"profit_factor":round(gp/gl,4) if gl else None,"max_drawdown_r":round(drawdown,4),"verdict":"RESEARCH_ONLY"}
def walk_forward(trades,start,end):
 """Three non-overlapping 4-month calibration / 2-month OOS windows.
 No parameter optimization occurs: canonical strategy remains frozen.
 """
 windows=[]
 for k in range(3):
  train_start=start+datetime.timedelta(days=round(k*6*365.25/12))
  train_end=train_start+datetime.timedelta(days=round(4*365.25/12))
  test_end=train_end+datetime.timedelta(days=round(2*365.25/12))
  if test_end>end:break
  subset=[t for t in trades if train_end<=datetime.datetime.fromisoformat(t["signal_at"])<test_end]
  windows.append({"index":k+1,"train_start":train_start.isoformat(),"train_end":train_end.isoformat(),"test_start":train_end.isoformat(),"test_end":test_end.isoformat(),"metrics":metrics(subset)})
 return windows

def main():
 p=argparse.ArgumentParser();p.add_argument("--symbols",default="BTC,ETH,SOL");p.add_argument("--months",type=int,default=18);p.add_argument("--out",default="atlas_backtest_results");a=p.parse_args()
 if a.months<12 or a.months>24:raise ValueError("months must be 12..24")
 out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 end=datetime.datetime.now(UTC).replace(minute=0,second=0,microsecond=0)
 end=end-datetime.timedelta(hours=end.hour%4)
 # Calendar-month approximation for reproducible fixed-day windows.
 start=end-datetime.timedelta(days=round(a.months*365.25/12))
 # Start/end must be 4H aligned for exact candle coverage.
 start=datetime.datetime.fromtimestamp((int(start.timestamp()*1000)//MS)*MS/1000,UTC)
 split=end-datetime.timedelta(days=183)
 summary={"start":start.isoformat(),"end":end.isoformat(),"oos_start":split.isoformat(),"symbols":{},"assumptions":"OKX/Bybit perpetual, scenario taker fees and ATR slippage; empirical signed funding only when complete, otherwise explicitly scenario 0.01%/8h. Scenario is NOT acceptance evidence; no real fills"}
 all_trades=[]
 for symbol in a.symbols.split(","):
  symbol=symbol.strip().upper()
  try:
   provider,bars,rates=source_data(symbol,int(start.timestamp()*1000),int(end.timestamp()*1000))
   expected=math.ceil((end-start).total_seconds()/(MS/1000))
   coverage={"provider":provider,"candles":len(bars),"expected":expected,"funding_events":len(rates),"first":datetime.datetime.fromtimestamp(bars[0][0]/1000,UTC).isoformat() if bars else None,"last":datetime.datetime.fromtimestamp(bars[-1][0]/1000,UTC).isoformat() if bars else None,"gaps":sum(bars[i][0]-bars[i-1][0]!=MS for i in range(1,len(bars)))}
   coverage["missing_candles"]=expected-len(bars)
   coverage["funding_max_gap_hours"]=round(max((rates[i][0]-rates[i-1][0])/3600000 for i in range(1,len(rates))),2) if len(rates)>1 else None
   if len(bars)!=expected or coverage["gaps"] or bars[0][0]!=int(start.timestamp()*1000) or bars[-1][0]!=int(end.timestamp()*1000)-MS:
    summary["symbols"][symbol]={"coverage":coverage,"verdict":"DATA_INCOMPLETE"};continue
   funding_complete=bool(rates) and rates[0][0]<=int(start.timestamp()*1000)+86400000 and rates[-1][0]>=int(end.timestamp()*1000)-86400000 and coverage["funding_max_gap_hours"] is not None and coverage["funding_max_gap_hours"]<=24
   mode="empirical" if funding_complete else "scenario_0.01pct_per_8h"
   coverage["funding_complete"]=funding_complete
   trades=simulate(symbol,bars,rates,int(start.timestamp()*1000),int(end.timestamp()*1000),provider,"empirical" if funding_complete else "scenario")
   windows=walk_forward(trades,start,end)
   oos=[t for t in trades if any(datetime.datetime.fromisoformat(w["test_start"])<=datetime.datetime.fromisoformat(t["signal_at"])<datetime.datetime.fromisoformat(w["test_end"]) for w in windows)]
   all_trades.extend(oos)
   summary["symbols"][symbol]={"coverage":coverage,"funding_mode":mode,"windows":windows,"metrics":metrics(oos),"verdict":"EMPIRICAL_RESEARCH" if funding_complete else "SCENARIO_ONLY_NOT_ACCEPTED"}
  except Exception as exc:
   summary["symbols"][symbol]={"verdict":"FETCH_FAILED","error":str(exc)[:250]}
 summary["aggregate_oos"]=metrics(all_trades)
 summary["aggregate_oos"]["long_trades"]=sum(t["side"]=="LONG" for t in all_trades)
 summary["aggregate_oos"]["short_trades"]=sum(t["side"]=="SHORT" for t in all_trades)
 summary["aggregate_oos"]["minimum_sample_met"]=len(all_trades)>=50
 summary["all_symbols_covered"]=all("metrics" in x for x in summary["symbols"].values()) and len(summary["symbols"])>0
 summary["all_funding_empirical"]=summary["all_symbols_covered"] and all(x["coverage"]["funding_complete"] for x in summary["symbols"].values())
 summary["verdict"]="EMPIRICAL_RESEARCH_COMPLETE" if summary["all_funding_empirical"] else "SCENARIO_ONLY_NOT_ACCEPTED" if summary["all_symbols_covered"] else "INCOMPLETE"
 (out/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False))
 (out/"trades.json").write_text(json.dumps(all_trades,indent=2))
 print(json.dumps(summary,ensure_ascii=False))
 if not summary["all_symbols_covered"]:sys.exit(2)
if __name__=="__main__":main()
