"""ATLAS cross-market risk sentinel: supplemental evidence, not trading advice.
Reads existing Supabase market snapshots; external news and CoinGecko are optional.
Never manufactures prices, trades, or an exit instruction from missing data.
"""
import datetime as dt,json,os,urllib.parse,urllib.request,statistics,sys
UTC=dt.timezone.utc
NOW=lambda:dt.datetime.now(UTC)
def request(url,headers=None):
 req=urllib.request.Request(url,headers={"User-Agent":"ATLAS-RiskSentinel/1",**(headers or {})})
 with urllib.request.urlopen(req,timeout=18) as r:return json.load(r)
def sb(table,limit=180):
 base=os.environ["SUPABASE_URL"].rstrip("/")
 key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 return request(f"{base}/rest/v1/{table}?select=*&order=captured_at.desc&limit={limit}",{"apikey":key,"Authorization":"Bearer "+key})
def age(ts):
 return (NOW()-dt.datetime.fromisoformat(ts.replace("Z","+00:00"))).total_seconds()/3600
def number(x):
 try:
  v=float(x)
  return v if v>0 and v<1e20 else None
 except (ValueError,TypeError):return None
def market_risks(table,max_age=32):
 rows=sb(table);groups={}
 for r in rows:
  s=r.get("symbol")
  if s and s not in groups:groups[s]=r
 output=[]
 for symbol,r in groups.items():
  if age(r["captured_at"])>max_age:continue
  payload=r.get("payload") or {}
  if not isinstance(payload,dict):payload={}
  signals=[]
  if table=="atlas_tse_snapshots" and symbol=="TSE_MARKET":
   breadth=payload.get("breadth")
   flow=number(abs(float(payload.get("real_money_flow") or 0)))
   try:
    if breadth is not None and float(breadth)<0.35:signals.append("پهنای بازار ضعیف")
    if flow and float(payload.get("real_money_flow"))<0:signals.append("خروج پول حقیقی")
   except (ValueError,TypeError):pass
   if len(signals)>=2:output.append((symbol,"WATCH",signals))
  elif table=="atlas_market_snapshots" and symbol in ("XAGUSD","XAUUSD","COPPER"):
   # A single snapshot is never enough for a directional sell warning.
   pass
 return output
def crypto_context():
 key=os.getenv("COINGECKO_API_KEY","").strip()
 headers={"x-cg-demo-api-key":key} if key else {}
 global_data=request("https://api.coingecko.com/api/v3/global",headers).get("data",{})
 change=global_data.get("market_cap_change_percentage_24h_usd")
 btc=global_data.get("market_cap_percentage",{}).get("btc")
 return {"market_cap_24h_pct":change,"btc_dominance_pct":btc}
def news_context():
 key=os.getenv("NEWSAPI_KEY","").strip()
 if not key:return {"status":"unconfigured","headlines":[]}
 since=(NOW()-dt.timedelta(hours=12)).isoformat(timespec="seconds").replace("+00:00","Z")
 params=urllib.parse.urlencode({"q":"(bitcoin OR cryptocurrency OR crypto) AND (SEC OR ETF OR regulation OR hack OR liquidation OR interest rates)","language":"en","sortBy":"publishedAt","pageSize":10,"from":since,"apiKey":key})
 data=request("https://newsapi.org/v2/everything?"+params)
 return {"status":"ok","headlines":[{"title":a.get("title"),"source":(a.get("source") or {}).get("name"),"url":a.get("url")} for a in data.get("articles",[]) if a.get("title")]}
def main():
 findings=[];errors=[]
 for table,hours in (("atlas_tse_snapshots",36),("atlas_market_snapshots",8)):
  try:findings+=market_risks(table,hours)
  except Exception as e:errors.append(table+": "+str(e))
 try:cg=crypto_context()
 except Exception as e:cg={"status":"unavailable"};errors.append("CoinGecko: "+str(e))
 try:news=news_context()
 except Exception as e:news={"status":"unavailable","headlines":[]};errors.append("NewsAPI: "+str(e))
 print(json.dumps({"checked_at":NOW().isoformat(),"market_risks":findings,"coingecko":cg,"news":news,"errors":errors},ensure_ascii=False))
 # Only independently confirmed TSE breadth+flow gets an informational warning.
 # No autonomous Telegram sends from unvalidated news or isolated metal snapshots.
 if findings:
  # Deduplicate warnings across scheduled scans.
  key=os.environ["SUPABASE_SERVICE_ROLE_KEY"];base=os.environ["SUPABASE_URL"].rstrip("/")
  state=request(base+"/rest/v1/atlas_risk_alert_state?symbol=eq.TSE_MARKET&select=level,notified_at",{"apikey":key,"Authorization":"Bearer "+key})
  if state and age(state[0]["notified_at"])<6:
   print("TSE alert cooldown active")
   findings=[]
  token=os.getenv("TELEGRAM_TOKEN");chat=os.getenv("TELEGRAM_GROUP_CHAT_ID")
  if token and chat:
   for symbol,level,flags in findings:
    msg="⚠️ ATLAS | پایش ریسک بورس ایران\\n"+symbol+" | "+level+"\\n"+"؛ ".join(flags)+"\\nهشدار احتیاط، نه دستور فروش."
    data=urllib.parse.urlencode({"chat_id":chat,"text":msg}).encode()
    req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",data=data)
    with urllib.request.urlopen(req,timeout=20) as r:
     if not json.load(r).get("ok"):raise RuntimeError("Telegram delivery failed")
    body=json.dumps({"symbol":"TSE_MARKET","level":level,"notified_at":NOW().isoformat()}).encode()
    headers={"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=minimal"}
    save=urllib.request.Request(base+"/rest/v1/atlas_risk_alert_state?on_conflict=symbol",data=body,headers=headers,method="POST")
    with urllib.request.urlopen(save,timeout=15):pass
 for e in errors:print("::warning::"+e)
if __name__=="__main__":main()
