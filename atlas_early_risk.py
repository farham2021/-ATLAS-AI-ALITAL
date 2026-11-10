"""ATLAS risk early-warning scanner. No orders. Closed-candle confirmation only."""
import json,os,urllib.request,urllib.parse,datetime,statistics,sys
BASE="https://api.exchange.coinbase.com/products/"
SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","LINKUSDT","AVAXUSDT","SUIUSDT")
def fetch(symbol,interval,limit=90):
 product=symbol.removesuffix("USDT")+"-USD"
 granularity={"4h":3600,"1d":86400}[interval]
 q=urllib.parse.urlencode({"granularity":granularity})
 req=urllib.request.Request(BASE+urllib.parse.quote(product)+"/candles?"+q,headers={"User-Agent":"ATLAS-RiskGuard/1","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=20) as response:
  rows=json.load(response)
 if not isinstance(rows,list):raise ValueError("unexpected candle response")
 now=datetime.datetime.now(datetime.timezone.utc).timestamp()
 candles={}
 for row in rows:
  if not isinstance(row,list) or len(row)<6:continue
  t,low,high,opening,close,volume=row[:6]
  t=int(t)
  if t+granularity>now:continue
  candles[t]=[t*1000,float(opening),float(high),float(low),float(close),float(volume),(t+granularity)*1000]
 ordered=[candles[t] for t in sorted(candles)]
 if interval=="1d":return ordered[-limit:]
 groups={}
 for row in ordered:
  bucket=(row[0]//14400000)*14400000
  groups.setdefault(bucket,[]).append(row)
 result=[]
 for bucket,group in sorted(groups.items()):
  if len(group)!=4 or [row[0] for row in group]!=[bucket+i*3600000 for i in range(4)]:continue
  result.append([bucket,group[0][1],max(row[2] for row in group),min(row[3] for row in group),group[-1][4],sum(row[5] for row in group),bucket+14400000])
 return result[-limit:]
def fetch_kraken(symbol,interval,limit=90):
 asset=symbol.removesuffix("USDT")
 pair={"BTC":"XBTUSD","DOGE":"XDGUSD"}.get(asset,asset+"USD")
 minutes={"4h":240,"1d":1440}[interval]
 url="https://api.kraken.com/0/public/OHLC?"+urllib.parse.urlencode({"pair":pair,"interval":minutes})
 req=urllib.request.Request(url,headers={"User-Agent":"ATLAS-RiskGuard/1"})
 with urllib.request.urlopen(req,timeout=20) as response: data=json.load(response)
 if data.get("error"):raise ValueError("Kraken: "+str(data["error"]))
 keys=[k for k in data.get("result",{}) if k!="last"]
 if not keys:raise ValueError("Kraken returned no pair")
 now=datetime.datetime.now(datetime.timezone.utc).timestamp()
 step=minutes*60
 out=[]
 for row in data["result"][keys[0]]:
  t=int(row[0])
  if t+step>now:continue
  out.append([t*1000,float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[6]),(t+step)*1000])
 out.sort(key=lambda row:row[0])
 return out[-limit:]

def fetch_validated(symbol,interval):
 errors=[]
 for name,provider in (("Kraken",fetch_kraken),("Coinbase",fetch)):
  try:
   rows=provider(symbol,interval)
   if len(rows)<55:raise ValueError("only "+str(len(rows))+" closed candles")
   step={"4h":14400000,"1d":86400000}[interval]
   if any(rows[i][0]-rows[i-1][0]!=step for i in range(len(rows)-54,len(rows))):
    raise ValueError("gaps in recent candles")
   if rows[-1][6]>int(datetime.datetime.now(datetime.timezone.utc).timestamp()*1000):
    raise ValueError("unclosed last candle")
   if int(datetime.datetime.now(datetime.timezone.utc).timestamp()*1000)-rows[-1][6]>3*step:raise ValueError("stale candles")
   if any(float(row[2])<float(row[3]) or float(row[4])<=0 or float(row[5])<0 for row in rows[-55:]):raise ValueError("invalid OHLCV values")
   print("ATLAS candle source",symbol,interval,name,len(rows))
   return rows
  except Exception as exc:
   errors.append(name+": "+str(exc))
 raise ValueError("no validated OHLCV provider: "+"; ".join(errors))

def ema(values,period):
 if len(values)<period:raise ValueError("insufficient EMA history")
 k=2/(period+1);value=sum(values[:period])/period
 for price in values[period:]:value=price*k+value*(1-k)
 return value

def score(rows4,rowsd):
 if len(rows4)<55 or len(rowsd)<55:raise ValueError("insufficient candles")
 c=[float(r[4]) for r in rows4];v=[float(r[5]) for r in rows4];d=[float(r[4]) for r in rowsd]
 if min(c)<=0 or min(d)<=0:raise ValueError("bad price")
 last=c[-1];ema20=ema(c,20);ema50=ema(c,50)
 daily20=sum(d[-20:])/20
 recent_low=min(float(r[3]) for r in rows4[-13:-1])
 volume_ratio=v[-1]/max(statistics.mean(v[-21:-1]),1e-12)
 decline24=(last/c[-7]-1)*100
 flags=[]
 if last<ema20:flags.append("4H below MA20")
 if ema20<ema50:flags.append("4H MA20 below MA50")
 if d[-1]<daily20:flags.append("daily below MA20")
 if last<recent_low:flags.append("4H support break")
 if volume_ratio>1.6 and c[-1]<c[-2]:flags.append("selling volume expansion")
 if decline24<=-4:flags.append("24h momentum loss")
 strength=len(flags)
 # Earlier risk escalation: do not wait for five simultaneous confirmations.
 support_break="4H support break" in flags
 selling="selling volume expansion" in flags
 trend_weak=("4H below MA20" in flags and "daily below MA20" in flags)
 level=("CRITICAL" if support_break and selling and (trend_weak or decline24<=-4) else
        "HIGH" if (support_break and (selling or trend_weak)) or (decline24<=-4 and trend_weak) or strength>=4 else
        "WATCH" if support_break or (selling and last<ema20) or strength>=2 else "NONE")
 return {"level":level,"flags":flags,"price":last,"volume_ratio":round(volume_ratio,2),"decline24":round(decline24,2)}
def score_growth(rows4,rowsd):
 if len(rows4)<55 or len(rowsd)<55:raise ValueError("insufficient candles")
 c=[float(r[4]) for r in rows4];v=[float(r[5]) for r in rows4];d=[float(r[4]) for r in rowsd]
 last=c[-1];ma20=ema(c,20);ma50=ema(c,50)
 daily20=sum(d[-20:])/20
 resistance=max(float(r[2]) for r in rows4[-13:-1])
 volume_ratio=v[-1]/max(statistics.mean(v[-21:-1]),1e-12)
 advance24=(last/c[-7]-1)*100
 breakout=last>resistance
 strong_volume=volume_ratio>=1.6 and last>c[-2]
 trend=last>ma20 and ma20>ma50 and d[-1]>daily20
 level=("GROWTH_HIGH" if breakout and strong_volume and trend else
        "GROWTH_WATCH" if breakout and (strong_volume or trend) else "NONE")
 flags=[]
 if breakout:flags.append("4H resistance break")
 if strong_volume:flags.append("buying volume expansion")
 if trend:flags.append("4H and daily uptrend")
 return {"level":level,"flags":flags,"price":last,"volume_ratio":round(volume_ratio,2),"decline24":round(advance24,2)}

def db_request(method,path,payload=None):
 url=os.environ["SUPABASE_URL"].rstrip("/")+"/rest/v1/"+path
 key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 headers={"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json"}
 if method=="POST":headers["Prefer"]="resolution=merge-duplicates,return=minimal"
 req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers=headers,method=method)
 with urllib.request.urlopen(req,timeout=15) as r:return json.loads(r.read() or b"null")
def alert(symbol,result):
 level=result["level"]
 if level=="NONE":return False
 rows=db_request("GET","atlas_risk_alert_state?symbol=eq."+urllib.parse.quote(symbol)+"&select=level,notified_at")
 now=datetime.datetime.now(datetime.timezone.utc)
 previous=rows[0] if rows else {}
 if previous.get("level")==level and previous.get("notified_at"):
  age=(now-datetime.datetime.fromisoformat(previous["notified_at"].replace("Z","+00:00"))).total_seconds()
  if age<6*3600:return False
 msg=(("🚀 ATLAS | هشدار رشد " if level.startswith("GROWTH") else "🚨 ATLAS | هشدار ریزش ")+symbol+"\nسطح: "+level+
      "\nقیمت مرجع: "+str(result["price"])+
      "\nتغییر ۲۴ ساعت: "+str(result["decline24"])+"٪"+
      "\nنسبت حجم: "+str(result["volume_ratio"])+
      "\nنشانه‌ها: "+", ".join(result["flags"])+
      ("\nهشدار رشد مبتنی بر شکست مقاومت؛ تضمین ادامه رشد نیست." if level.startswith("GROWTH") else "\nهشدار ریزش مبتنی بر ضعف روند؛ تضمین ادامه ریزش نیست.")+
      "\nچارت: https://www.tradingview.com/chart/?symbol=COINBASE%3A"+symbol.removesuffix("USDT")+"USD")
 token=os.environ["TELEGRAM_TOKEN"]
 for chat in (os.environ["TELEGRAM_GROUP_CHAT_ID"],os.getenv("ATLAS_PRIVATE_CHAT_ID","414890497")):
  body=urllib.parse.urlencode({"chat_id":chat,"text":msg}).encode()
  req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",data=body)
  with urllib.request.urlopen(req,timeout=20) as r:
   response=json.load(r)
   if not response.get("ok"):raise RuntimeError("Telegram send failed")
 db_request("POST","atlas_risk_alert_state?on_conflict=symbol",{"symbol":symbol,"level":level,"notified_at":now.isoformat()})
 return True
def main():
 from concurrent.futures import ThreadPoolExecutor,as_completed
 from atlas_top100_universe import discover_top100
 from atlas_iran_risk_snapshot import scan_iran
 from atlas_risk_csv_digest import send_digest
 from atlas_risk_top20_selection import select,DESK
 failed=[];pending=[];now=datetime.datetime.now(datetime.timezone.utc)
 universe=discover_top100()
 def scan(item):
  symbol=item["symbol"]
  try:
   rows4=fetch_validated(symbol,"4h");rowsd=fetch_validated(symbol,"1d")
   downside=score(rows4,rowsd);upside=score_growth(rows4,rowsd)
   result=downside if downside["level"]!="NONE" else upside
   result["market"]="CRYPTO"
   return symbol,result,None
  except Exception as exc:return symbol,None,str(exc)
 with ThreadPoolExecutor(max_workers=8) as pool:
  outcomes=[future.result() for future in as_completed([pool.submit(scan,item) for item in universe])]
 coverage=sum(result is not None for _,result,_ in outcomes)
 for symbol,result,error in outcomes:
  if error:print("::warning::Crypto data gap "+symbol+": "+error[:250])
  elif result is not None:pending.append((symbol,result))
 # Iran: only timestamped provider-supplied percent changes; never infer stale prices.
 try:
  iran,iran_coverage=scan_iran(now)
  print("Iran data coverage:",json.dumps(iran_coverage))
  # Iran alerts remain separate from the requested crypto top-20 digest.
  print("Iran candidate alerts:",len(iran))
 except Exception as exc:
  failed.append("Iran snapshot scan: "+str(exc))
 print("Crypto coverage:",coverage,"of",len(universe))
 if coverage<len(universe):
  print("::warning::Partial crypto coverage; unsupported markets are excluded, not represented as safe")
 if failed:
  for error in failed:print("::error::"+error)
  sys.exit(2)
 # Rank 10 fixed desk symbols and 10 strongest dynamic signals, not all 100.
 pending=select(pending)
 # Deduplicate only after successful delivery; never mark failed sends as notified.
 unique={}
 for symbol,result in pending:
  key=(result.get("market","CRYPTO"),symbol)
  unique[key]=(symbol,result)
 pending=[]
 for symbol,result in unique.values():
  state_key=("IRAN_" if result.get("market")=="IRAN" else "")+symbol
  rows=db_request("GET","atlas_risk_alert_state?symbol=eq."+urllib.parse.quote(state_key)+"&select=level,notified_at")
  previous=rows[0] if rows else {}
  if symbol not in DESK and previous.get("level")==result["level"] and previous.get("notified_at"):
   age=(now-datetime.datetime.fromisoformat(previous["notified_at"].replace("Z","+00:00"))).total_seconds()
   if age<6*3600:continue
  pending.append((symbol,result,state_key))
 if pending:
  receipts=send_digest([(symbol,result) for symbol,result,_ in pending])
  print("ATLAS Telegram CSV confirmed message ids:",receipts)
  for symbol,result,state_key in pending:
   if result["level"]=="NONE":continue
   db_request("POST","atlas_risk_alert_state?on_conflict=symbol",{"symbol":state_key,"level":result["level"],"notified_at":now.isoformat()})
 print("ATLAS risk digest rows:",len(pending))
if __name__=="__main__":main()
