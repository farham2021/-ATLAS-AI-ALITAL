#!/usr/bin/env python3
"""Historical daily CoinGecko market-chart prices for ranked assets.
Binance is not used for primary historical ingestion.
Research-only; preserves observed candle timestamps and provenance.
"""
import os,json,urllib.request,urllib.parse,datetime,time,math
BASE=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
DAYS=min(365,max(30,int(os.getenv("ATLAS_HISTORY_DAYS","30"))))
LIMIT=min(100,max(1,int(os.getenv("ATLAS_HISTORY_SYMBOLS","30"))))
headers={"Accept":"application/json","User-Agent":"ATLAS-Research/1.0"}
if os.getenv("COINGECKO_API_KEY"):headers["x-cg-demo-api-key"]=os.environ["COINGECKO_API_KEY"]
def fetch(url,h=None):
    req=urllib.request.Request(url,headers=h or headers)
    with urllib.request.urlopen(req,timeout=25) as resp:return json.load(resp)
def post(rows):
    h={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"return=minimal"}
    for i in range(0,len(rows),100):
        req=urllib.request.Request(BASE+"/rest/v1/atlas_market_snapshots",data=json.dumps(rows[i:i+100]).encode(),headers=h,method="POST")
        with urllib.request.urlopen(req,timeout=35) as response:response.read()
def existing(sym):
    q=urllib.parse.urlencode({"select":"captured_at","symbol":"eq."+sym,"payload->>source":"eq.coingecko_market_chart","order":"captured_at.desc","limit":"1"})
    h={"apikey":KEY,"Authorization":"Bearer "+KEY}
    try:return fetch(BASE+"/rest/v1/atlas_market_snapshots?"+q,h)
    except Exception:return []
params=urllib.parse.urlencode({"vs_currency":"usd","order":"market_cap_desc","per_page":100,"page":1,"sparkline":"false"})
coins=fetch("https://api.coingecko.com/api/v3/coins/markets?"+params)
if not isinstance(coins,list) or len(coins)<70:raise RuntimeError("CoinGecko catalog unavailable")
now=datetime.datetime.now(datetime.timezone.utc)
done=0;stored=0;errors=[]
for c in coins:
    if done>=LIMIT:break
    sym=str(c.get("symbol","")).upper()
    if not sym.isalnum() or sym in ("USDT","USDC","DAI","FDUSD","TUSD","BUSD"):continue
    # Skip already-populated recent daily series. Never rewrite historical records.
    prior=existing(sym)
    latest_prior=None
    if prior:
        try:
            age=(now-datetime.datetime.fromisoformat(prior[0]["captured_at"].replace("Z","+00:00"))).total_seconds()
            latest_prior=datetime.datetime.fromisoformat(prior[0]["captured_at"].replace("Z","+00:00"))
            if age<40*3600:continue
        except Exception:pass
    coin_id=str(c.get("id",""))
    if not coin_id:continue
    url="https://api.coingecko.com/api/v3/coins/"+urllib.parse.quote(coin_id,safe="")+"/market_chart?"+urllib.parse.urlencode({"vs_currency":"usd","days":DAYS,"interval":"daily"})
    try:
        history=fetch(url)
        points=history.get("prices",[])
        if not isinstance(points,list) or len(points)<20:raise ValueError("insufficient CoinGecko history")
        rows=[]
        seen=set()
        for ts,p in points:
            captured=datetime.datetime.fromtimestamp(float(ts)/1000,datetime.timezone.utc)
            price=float(p)
            if (latest_prior and captured<=latest_prior) or captured>=now or price<=0 or not math.isfinite(price):continue
            day=captured.date()
            if day in seen:continue
            seen.add(day)
            rows.append({"captured_at":captured.isoformat(),"symbol":sym,"asset":coin_id,"price":price,"value":price,
                "payload":{"source":"coingecko_market_chart","research_only":True,"currency":"USD",
                "price_type":"aggregated_historical","historical":True,"coin_gecko_rank":c.get("market_cap_rank")}})
        if not rows:continue
        post(rows);done+=1;stored+=len(rows)
    except Exception as e:errors.append(coin_id+":"+str(e)[:70])
    time.sleep(2.5)
print("Backfill assets:",done,"daily historical candles:",stored,"skipped/unavailable:",len(errors))
if errors:print("Examples:",errors[:12])
if done==0 and not any(existing(str(c.get("symbol","")).upper()) for c in coins[:LIMIT]):
    raise RuntimeError("No historical series loaded; inspect API access and Supabase schema")
