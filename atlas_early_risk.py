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
   print("ATLAS candle source",symbol,interval,name,len(rows))
   return rows
  except Exception as exc:
   errors.append(name+": "+str(exc))
 raise ValueError("no validated OHLCV provider: "+"; ".join(errors))

def score(rows4,rowsd):
 if len(rows4)<55 or len(rowsd)<55:raise ValueError("insufficient candles")
 c=[float(r[4]) for r in rows4];v=[float(r[5]) for r in rows4];d=[float(r[4]) for r in rowsd]
 if min(c)<=0 or min(d)<=0:raise ValueError("bad price")
 last=c[-1];ema20=sum(c[-20:])/20;ema50=sum(c[-50:])/50
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
 level="CRITICAL" if strength>=5 and ("4H support break" in flags) else "HIGH" if strength>=4 else "WATCH" if strength>=3 else "NONE"
 return {"level":level,"flags":flags,"price":last,"volume_ratio":round(volume_ratio,2),"decline24":round(decline24,2)}
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
 msg=("🚨 ATLAS | هشدار ریسک "+symbol+"\nسطح: "+level+
      "\nقیمت مرجع: "+str(result["price"])+
      "\nتغییر ۲۴ ساعت: "+str(result["decline24"])+"٪"+
      "\nنسبت حجم: "+str(result["volume_ratio"])+
      "\nنشانه‌ها: "+", ".join(result["flags"])+
      "\nتحلیل مبتنی بر کندل بسته‌شده 4H و 1D؛ پیش‌بینی قطعی نیست."+
      "\nچارت: https://www.tradingview.com/chart/?symbol=COINBASE%3A"+symbol.removesuffix("USDT")+"USD")
 token=os.environ["TELEGRAM_TOKEN"];chat=os.environ["TELEGRAM_GROUP_CHAT_ID"]
 body=urllib.parse.urlencode({"chat_id":chat,"text":msg}).encode()
 req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",data=body)
 with urllib.request.urlopen(req,timeout=20) as r:
  response=json.load(r)
  if not response.get("ok"):raise RuntimeError("Telegram send failed")
 db_request("POST","atlas_risk_alert_state?on_conflict=symbol",{"symbol":symbol,"level":level,"notified_at":now.isoformat()})
 return True
def main():
 failed=[];sent=0
 for symbol in SYMBOLS:
  try:
   result=score(fetch_validated(symbol,"4h"),fetch_validated(symbol,"1d"))
   print(symbol,json.dumps(result))
   if alert(symbol,result):sent+=1
  except Exception as e:
   failed.append(symbol+": "+str(e))
 for f in failed:print("::warning::"+f)
 print("ATLAS risk alerts sent:",sent)
 if failed:sys.exit(2)
if __name__=="__main__":main()
