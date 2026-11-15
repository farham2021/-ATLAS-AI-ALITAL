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
def contiguous(bars):
 return all(bars[i][0]-bars[i-1][0]==MS for i in range(1,len(bars)))
def simulate(symbol,bars,rates,split_ms,end_ms):
 trades=[];i=220
 while i<len(bars)-1:
  window=bars[max(0,i-250):i+1]
  if len(window)<220 or not contiguous(window):i+=1;continue
  signal_at=bars[i][0]+MS
  if signal_at<split_ms:i+=1;continue
  setup=make_setup(symbol,"BYBIT_LINEAR",window,signal_at)
  if not setup:i+=1;continue
  # Never use future bars to create the signal; future bars only settle its outcome.
  future=bars[i+1:min(len(bars),i+43)]
  if not future:break
  outcome=audit_one(setup,window+future,end_ms)
  if not outcome or outcome["exit_price"] is None:break
  opened=datetime.datetime.fromtimestamp(signal_at/1000,UTC)
  closed=datetime.datetime.fromisoformat(outcome["exit_at"])
  direction=1 if setup["side"]=="LONG" else -1
  signed_funding=sum(direction*r for t,r in rates if signal_at<t<=int(closed.timestamp()*1000))
  duration=(closed-opened).total_seconds()
  # Use exact signed funding cash flow as a proportion of entry notional;
  # dynamic stop/market slippage is a stress assumption, not measured fills.
  atr_ratio=setup["indicators"]["atr14"]/setup["entry"]
  slip=min(.005,max(.0002,.1*atr_ratio))
  costs=ExecutionCostModel(entry_slippage_rate=slip,exit_slippage_rate=slip,funding_rate_8h=0)
  result=evaluate_trade_net_r(setup["side"],setup["entry"],setup["sl"],outcome["exit_price"],opened,closed,outcome["status"]=="WIN_TP2",costs)
  funding_r=signed_funding/(abs(setup["entry"]-setup["sl"])/setup["entry"])
  net=result["net_r"]-funding_r
  trades.append({"symbol":symbol,"signal_at":setup["signal_at"],"exit_at":outcome["exit_at"],"side":setup["side"],"status":outcome["status"],"gross_r":result["gross_r"],"net_r":round(net,6),"funding_r":round(funding_r,6),"slippage_rate":slip})
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
 summary={"start":start.isoformat(),"end":end.isoformat(),"oos_start":split.isoformat(),"symbols":{},"assumptions":"Bybit linear perpetual, taker fees scenario, ATR-based stress slippage, actual signed funding events, conservative OHLC stops; no real fills"}
 all_trades=[]
 for symbol in a.symbols.split(","):
  symbol=symbol.strip().upper()
  try:
   bars=history(symbol,int(start.timestamp()*1000),int(end.timestamp()*1000))
   rates=funding(symbol,int(start.timestamp()*1000),int(end.timestamp()*1000))
   expected=math.ceil((end-start).total_seconds()/(MS/1000))
   coverage={"candles":len(bars),"expected":expected,"funding_events":len(rates),"first":datetime.datetime.fromtimestamp(bars[0][0]/1000,UTC).isoformat() if bars else None,"last":datetime.datetime.fromtimestamp(bars[-1][0]/1000,UTC).isoformat() if bars else None,"gaps":sum(bars[i][0]-bars[i-1][0]!=MS for i in range(1,len(bars)))}
   coverage["missing_candles"]=expected-len(bars)
   coverage["funding_max_gap_hours"]=round(max((rates[i][0]-rates[i-1][0])/3600000 for i in range(1,len(rates))),2) if len(rates)>1 else None
   if len(bars)!=expected or coverage["gaps"] or not rates or rates[0][0]>int(start.timestamp()*1000)+86400000 or rates[-1][0]<int(end.timestamp()*1000)-86400000 or (coverage["funding_max_gap_hours"] is not None and coverage["funding_max_gap_hours"]>24):
    summary["symbols"][symbol]={"coverage":coverage,"verdict":"DATA_INCOMPLETE"};continue
   trades=simulate(symbol,bars,rates,int(split.timestamp()*1000),int(end.timestamp()*1000))
   all_trades.extend(trades)
   summary["symbols"][symbol]={"coverage":coverage,"metrics":metrics(trades)}
  except Exception as exc:
   summary["symbols"][symbol]={"verdict":"FETCH_FAILED","error":str(exc)[:250]}
 summary["aggregate_oos"]=metrics(all_trades)
 summary["all_symbols_covered"]=all("metrics" in x for x in summary["symbols"].values()) and len(summary["symbols"])>0
 summary["verdict"]="RESEARCH_COMPLETE" if summary["all_symbols_covered"] else "INCOMPLETE"
 (out/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False))
 (out/"trades.json").write_text(json.dumps(all_trades,indent=2))
 print(json.dumps(summary,ensure_ascii=False))
 if not summary["all_symbols_covered"]:sys.exit(2)
if __name__=="__main__":main()
