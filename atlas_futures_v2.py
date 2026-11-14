"""ATLAS Futures v2 canonical closed-4H signal + outcome shadow audit.
Supabase is the authoritative store. No live orders. No Telegram until calibrated.
"""
import os,json,urllib.request,urllib.parse,datetime,hashlib,math
from statistics import mean,pstdev
UTC=datetime.timezone.utc
MS=14400000
MODEL="v2-wilder-atr"
BASE=os.environ.get("SUPABASE_URL","").rstrip("/")
KEY=os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
def api(table,params="",data=None,method="GET"):
 if not BASE or not KEY:raise RuntimeError("Supabase credentials missing")
 url=BASE+"/rest/v1/"+table+("?"+params if params else "")
 headers={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=minimal"}
 req=urllib.request.Request(url,headers=headers,data=json.dumps(data).encode() if data is not None else None,method=method)
 with urllib.request.urlopen(req,timeout=40) as r:return json.loads(r.read() or b"[]")
def candles(raw,now_ms):
 if isinstance(raw,str):raw=json.loads(raw)
 if isinstance(raw,dict):raw=raw.get("rows",[])
 out=[]
 for a in raw:
  try:
   t,o,h,l,c,v=a[:6];t=int(t);o,h,l,c,v=map(float,(o,h,l,c,v))
   if not all(math.isfinite(x) for x in (o,h,l,c,v)) or l<=0 or l>min(o,c) or h<max(o,c) or v<0 or t+MS>now_ms:continue
   out.append((t,o,h,l,c,v))
  except (TypeError,ValueError,IndexError):continue
 return sorted({x[0]:x for x in out}.values())
def indicators(bars):
 if len(bars)<220:raise ValueError("Need >=220 closed bars")
 a=bars[-min(250,len(bars)):]
 if any(a[i][0]-a[i-1][0]!=MS for i in range(1,len(a))):raise ValueError("Non-contiguous 4h candles")
 c=[x[4] for x in a];p=c[-1]
 ema=mean(c[:200])
 for x in c[200:]:ema+=(x-ema)*2/201
 gains=[];losses=[];trs=[]
 for i in range(1,len(a)):
  d=c[i]-c[i-1];gains.append(max(d,0));losses.append(max(-d,0))
  trs.append(max(a[i][2]-a[i][3],abs(a[i][2]-c[i-1]),abs(a[i][3]-c[i-1])))
 g,l,atr=mean(gains[:14]),mean(losses[:14]),mean(trs[:14])
 for i in range(14,len(gains)):
  g=(13*g+gains[i])/14;l=(13*l+losses[i])/14;atr=(13*atr+trs[i])/14
 rsi=50 if g==l==0 else 100 if l==0 else 100-100/(1+g/l)
 avg=mean(c[-20:]);sd=pstdev(c[-20:]);percent_b=(p-(avg-2*sd))/(4*sd) if sd else .5
 vb=mean(x[5] for x in a[-21:-1]);vr=a[-1][5]/vb if vb else 0
 return dict(price=p,ema200=ema,rsi14=rsi,atr14=atr,percent_b=percent_b,volume_ratio=vr)
def make_setup(symbol,provider,bars,now_ms):
 if now_ms-(bars[-1][0]+MS)>MS+300000:return None
 x=indicators(bars);p=x["price"];ema=x["ema200"];r=x["rsi14"];b=x["percent_b"];atr=x["atr14"]
 side="LONG" if p>ema and (35<=r<=55 or b<.2) else "SHORT" if p<ema and (55<=r<=72 or b>.85) else None
 if not side or atr<=0 or x["volume_ratio"]<.6:return None
 d=1 if side=="LONG" else -1
 sl=p-d*1.5*atr;tp1=p+d*2.25*atr;tp2=p+d*3.75*atr
 if min(sl,tp1,tp2)<=0:return None
 pct=abs(p-sl)/p*100;lev=3 if pct<=1.5 else 2 if pct<=3 else 1
 at=datetime.datetime.fromtimestamp((bars[-1][0]+MS)/1000,UTC).isoformat()
 sid=hashlib.sha256(f"{MODEL}|{symbol}|4h|{at}|{side}".encode()).hexdigest()[:32]
 return dict(id=sid,symbol=symbol,timeframe="4h",side=side,signal_at=at,source=provider,model_version=MODEL,entry=p,sl=sl,tp1=tp1,tp2=tp2,suggested_leverage=lev,sl_pct=pct,rr1=1.5,rr2=2.5,indicators=x,status="NEW")
def audit_one(s,bars,now_ms):
 start=int(datetime.datetime.fromisoformat(s["signal_at"].replace("Z","+00:00")).timestamp()*1000)
 d=1 if s["side"]=="LONG" else -1
 entry=float(s["entry"]);sl=float(s["sl"]);tp1=float(s["tp1"]);tp2=float(s["tp2"]);risk=abs(entry-sl)
 if risk<=0:return None
 # All OHLC candles start AFTER the signal close. Conservative same-bar ordering.
 after=[b for b in bars if b[0]>=start and b[0]+MS<=now_ms]
 touched=False;exit_price=None;state="OPEN";exit_at=None
 for bar in after:
  high,low=bar[2],bar[3];stop=entry if touched else sl
  hit_sl=low<=stop if d==1 else high>=stop
  hit_tp1=high>=tp1 if d==1 else low<=tp1
  hit_tp2=high>=tp2 if d==1 else low<=tp2
  if hit_sl:
   exit_price=stop;state="TP1_EXIT" if touched else "LOSS";exit_at=bar[0]+MS;break
  if hit_tp2:
   exit_price=tp2;state="WIN_TP2";exit_at=bar[0]+MS;break
  if hit_tp1:touched=True
 if state=="OPEN" and len(after)>=42:
  exit_price=after[41][4];state="EXPIRED";exit_at=after[41][0]+MS
 realized=(d*(exit_price-entry)/risk) if exit_price is not None else None
 return dict(signal_id=s["id"],symbol=s["symbol"],side=s["side"],status=state,last_checked_at=datetime.datetime.now(UTC).isoformat(),exit_at=datetime.datetime.fromtimestamp(exit_at/1000,UTC).isoformat() if exit_at else None,exit_price=exit_price,realized_r=realized,details={"tp1_touched":touched,"candles_seen":len(after),"fee_funding_slippage_not_included":True})
def upsert_outcome(outcome):
 url=BASE+"/rest/v1/atlas_futures_outcomes_v2?on_conflict=signal_id"
 headers={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=minimal"}
 with urllib.request.urlopen(urllib.request.Request(url,data=json.dumps([outcome]).encode(),headers=headers,method="POST"),timeout=40):pass
def deliver_telegram():
 token=os.getenv("TELEGRAM_TOKEN","")
 targets=list(dict.fromkeys(x for x in (os.getenv("TELEGRAM_CHAT_ID"),os.getenv("TELEGRAM_GROUP_CHAT_ID")) if x))
 if not token or len(targets)<2:
  print("Telegram disabled: token or BOTH destinations missing");return
 # No uncalibrated probability or fabricated confidence; alerts explicitly shadow research.
 now=datetime.datetime.now(UTC)
 recent=api("atlas_futures_setups_v2","select=*&status=eq.NEW&order=signal_at.desc&limit=100")
 receipts=api("atlas_futures_v2_delivery","select=signal_id,destination&limit=1000")
 sent={(r["signal_id"],r["destination"]) for r in receipts}
 for sig in recent:
  age=(now-datetime.datetime.fromisoformat(sig["signal_at"].replace("Z","+00:00"))).total_seconds()
  if age<0 or age>6*3600:continue
  symbol=sig["symbol"];side=sig["side"]
  tv="https://www.tradingview.com/chart/?symbol=BINANCE%3A"+symbol+"USDT"
  message=(f"ATLAS v2 | PAPER RESEARCH (not validated)\n{symbol}/USDT {side} 4H\n"
   f"Entry {sig['entry']} | SL {sig['sl']}\\nTP1 {sig['tp1']} | TP2 {sig['tp2']}\\n"
   f"RR 1.5 / 2.5 | Max leverage {sig['suggested_leverage']}x\\n"
   f"Model {MODEL} | {sig['signal_at']}\\n{tv}\\nNo real order; profitability unverified.")
  for chat in targets:
   # A successful Telegram response is recorded per destination. Retries after a
   # crash between send and receipt may duplicate; Telegram offers no idempotency key.
   if (sig["id"],chat) in sent:continue
   payload=urllib.parse.urlencode({"chat_id":chat,"text":message}).encode()
   response=request_telegram(token,payload)
   if not response.get("ok"):raise RuntimeError("Telegram rejected alert")
   mid=response["result"]["message_id"]
   url=BASE+"/rest/v1/atlas_futures_v2_delivery?on_conflict=signal_id,destination"
   h={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"resolution=ignore-duplicates,return=minimal"}
   body=json.dumps([{"signal_id":sig["id"],"destination":chat,"message_id":mid}]).encode()
   with urllib.request.urlopen(urllib.request.Request(url,data=body,headers=h,method="POST"),timeout=40):pass
   print("telegram delivered",symbol,side,"message_id",mid)
  if all((sig["id"],chat) in sent or (sig["id"],chat) in {(x["signal_id"],x["destination"]) for x in api("atlas_futures_v2_delivery","select=signal_id,destination&signal_id=eq."+sig["id"])} for chat in targets):
   url=BASE+"/rest/v1/atlas_futures_setups_v2?id=eq."+sig["id"]
   h={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json"}
   with urllib.request.urlopen(urllib.request.Request(url,data=b'{"status":"SENT","sent_at":"'+now.isoformat().encode()+b'"}',headers=h,method="PATCH"),timeout=40):pass
def request_telegram(token,payload):
 with urllib.request.urlopen(urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",data=payload),timeout=30) as r:return json.load(r)

WATCHLIST=("BTC","ETH","SOL","BNB","XRP","ADA","DOGE","TRX","LINK","SUI","AVAX","LTC","DOT","BCH","NEAR","ATOM","TON","HBAR","XLM","TAO","ZEC")
def fresh_exchange_bars(symbol,now_ms):
 """Use closed spot candles as research proxy; derivatives basis may differ."""
 pair=symbol+"USDT"
 sources=[
  ("OKX","https://www.okx.com/api/v5/market/history-candles?"+urllib.parse.urlencode({"instId":symbol+"-USDT","bar":"4H","limit":300}),lambda x:x["data"] if x.get("code")=="0" else []),
  ("BYBIT","https://api.bybit.com/v5/market/kline?"+urllib.parse.urlencode({"category":"spot","symbol":pair,"interval":"240","limit":300}),lambda x:x["result"]["list"] if x.get("retCode")==0 else []),
  ("BINANCE","https://api.binance.com/api/v3/klines?"+urllib.parse.urlencode({"symbol":pair,"interval":"4h","limit":300}),lambda x:x)
 ]
 for name,url,parse in sources:
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"ATLAS-Research/2.0"})
   with urllib.request.urlopen(req,timeout=12) as response:rows=parse(json.load(response))
   bars=candles(rows,now_ms)
   if len(bars)>=220 and now_ms-(bars[-1][0]+MS)<=MS+300000:return (name,bars)
  except (OSError,ValueError,KeyError,TypeError):continue
 return None

def main():
 now_ms=int(datetime.datetime.now(UTC).timestamp()*1000)
 records=api("atlas_ohlcv_closed_cache","select=symbol,timeframe,provider,rows_json,updated_at&timeframe=eq.4h&limit=500")
 by_symbol={}
 for rec in records:
  try:
   bars=candles(rec["rows_json"],now_ms)
   if len(bars)<220:continue
   symbol=rec["symbol"].upper().replace("USDT","")
   # Respect provider order; cached LBANK remains eligible as untrusted research fallback only.
   rank={"OKX":0,"BYBIT":1,"BINANCE":2}.get(str(rec["provider"]).upper(),3)
   old=by_symbol.get(symbol)
   if old is None or (bars[-1][0],-rank)>(old[2][-1][0],-old[0]):by_symbol[symbol]=(rank,rec["provider"],bars)
  except (ValueError,KeyError,TypeError):continue
 # Refresh from primary public providers before relying on the legacy cache.
 # Fail closed on stale data: never emit a signal from an outdated snapshot.
 for symbol in WATCHLIST:
  fresh=fresh_exchange_bars(symbol,now_ms)
  if fresh:
   provider,bars=fresh
   by_symbol[symbol]=({"OKX":0,"BYBIT":1,"BINANCE":2}[provider],provider,bars)
 setups=[]
 for symbol,(_,provider,bars) in by_symbol.items():
  try:
   s=make_setup(symbol,provider,bars,now_ms)
   if s:setups.append(s)
  except ValueError:continue
 # Do not overwrite SENT/CLOSED statuses on re-runs: only insert if absent.
 for s in setups:
  insert_new(s)
 active=api("atlas_futures_setups_v2","select=*&status=in.(NEW,SENT,OPEN)&limit=500")
 terminal={x["signal_id"] for x in api("atlas_futures_outcomes_v2","select=signal_id&status=in.(LOSS,WIN_TP2,TP1_EXIT,EXPIRED)&limit=1000")}
 audited=0
 for s in active:
  if s["id"] in terminal:continue
  item=by_symbol.get(s["symbol"])
  if not item:continue
  outcome=audit_one(s,item[2],now_ms)
  if outcome:
   upsert_outcome(outcome)
   audited+=1
 if os.getenv("ATLAS_V2_TELEGRAM","0")=="1":deliver_telegram()
 print(json.dumps({"model":MODEL,"mode":"SHADOW_PAPER_TELEGRAM" if os.getenv("ATLAS_V2_TELEGRAM")=="1" else "SHADOW_NO_TELEGRAM","available_symbols":len(by_symbol),"new_candidates":len(setups),"audited":audited,"notes":"No win-rate promotion without costs and holdout."}))
def insert_new(s):
 # POST without merge is idempotent only when absent. Prefer duplicate-ignore resolution.
 url=BASE+"/rest/v1/atlas_futures_setups_v2?on_conflict=id"
 req=urllib.request.Request(url,data=json.dumps([s]).encode(),headers={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"resolution=ignore-duplicates,return=minimal"},method="POST")
 with urllib.request.urlopen(req,timeout=40):pass
if __name__=="__main__":main()
