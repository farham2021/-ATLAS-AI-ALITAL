"""ATLAS risk early-warning scanner. No orders. Closed-candle confirmation only."""
import json,os,urllib.request,urllib.parse,datetime,statistics,sys
BASE="https://api.binance.com/api/v3/klines"
SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","LINKUSDT","AVAXUSDT","SUIUSDT")
def fetch(symbol,interval,limit=90):
 q=urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":limit})
 req=urllib.request.Request(BASE+"?"+q,headers={"User-Agent":"ATLAS-RiskGuard/1"})
 with urllib.request.urlopen(req,timeout=15) as r:rows=json.load(r)
 now=int(datetime.datetime.now(datetime.timezone.utc).timestamp()*1000)
 return [r for r in rows if int(r[6])<now]
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
      "\nچارت: https://www.tradingview.com/chart/?symbol=BINANCE%3A"+symbol)
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
   result=score(fetch(symbol,"4h"),fetch(symbol,"1d"))
   print(symbol,json.dumps(result))
   if alert(symbol,result):sent+=1
  except Exception as e:
   failed.append(symbol+": "+str(e))
 for f in failed:print("::warning::"+f)
 print("ATLAS risk alerts sent:",sent)
 if failed:sys.exit(2)
if __name__=="__main__":main()
