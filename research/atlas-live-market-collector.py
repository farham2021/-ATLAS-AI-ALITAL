#!/usr/bin/env python3
"""ATLAS independent research collector. No orders, alerts or Telegram."""
import os,json,urllib.request,urllib.parse,datetime,math,statistics,time
BASE=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
CG=os.environ.get("COINGECKO_API_KEY","")
CMC=os.environ.get("COINMARKETCAP_API_KEY","")
NOW=datetime.datetime.now(datetime.timezone.utc)
def request(url,headers=None,data=None,method=None):
    req=urllib.request.Request(url,data=data,headers=headers or {},method=method)
    with urllib.request.urlopen(req,timeout=35) as r:return json.loads(r.read() or b'null')
def db(table,params=""):
    h={"apikey":KEY,"Authorization":"Bearer "+KEY}
    return request(BASE+"/rest/v1/"+table+params,h)
def insert(table,rows):
    if not rows:return
    h={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"return=minimal"}
    for i in range(0,len(rows),100):
        request(BASE+"/rest/v1/"+table,h,json.dumps(rows[i:i+100],allow_nan=False).encode(),"POST")
def parse(t):
    return datetime.datetime.fromisoformat(t.replace("Z","+00:00"))
def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None
headers={"Accept":"application/json","User-Agent":"ATLAS-Research/1.0"}
if CG:headers["x-cg-demo-api-key"]=CG
params=urllib.parse.urlencode({"vs_currency":"usd","order":"market_cap_desc","per_page":100,"page":1,"sparkline":"false","price_change_percentage":"1h,24h"})
coins=request("https://api.coingecko.com/api/v3/coins/markets?"+params,headers)
if not isinstance(coins,list) or len(coins)<70:raise RuntimeError("CoinGecko top 100 incomplete; no writes")
valid={}
for c in coins:
    sym=str(c.get("symbol","")).upper()
    price=num(c.get("current_price"))
    if sym and price and price>0 and sym not in valid:valid[sym]=c
if len(valid)<60:raise RuntimeError("Insufficient distinct CoinGecko assets")
# CMC is independent cross-validation, not a substitute for CoinGecko OHLCV.
cmc_quotes={}
if CMC:
    try:
        result=request("https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest?start=1&limit=100&convert=USD",{"X-CMC_PRO_API_KEY":CMC,"Accept":"application/json"})
        for x in result.get("data",[]):
            p=num(x.get("quote",{}).get("USD",{}).get("price"))
            if p and p>0:cmc_quotes[str(x.get("symbol","")).upper()]=p
    except Exception as e:print("CMC unavailable:",str(e)[:160])
stamp=NOW.isoformat()
snapshots=[]
for sym,c in valid.items():
    p=num(c["current_price"])
    cp=cmc_quotes.get(sym)
    divergence=abs(cp/p-1)*100 if cp else None
    snapshots.append({"captured_at":stamp,"symbol":sym,"asset":c.get("id"),"price":p,"value":p,
        "payload":{"source":"coingecko","research_only":True,"currency":"USD","rank":c.get("market_cap_rank"),
        "volume_24h":c.get("total_volume"),"change_1h_pct":c.get("price_change_percentage_1h_in_currency"),
        "change_24h_pct":c.get("price_change_percentage_24h_in_currency"),"provider_updated_at":c.get("last_updated"),
        "cmc_price_usd":cp,"cmc_divergence_pct":divergence,
        "cross_source_disagreement":divergence is not None and divergence>5}})
insert("atlas_market_snapshots",snapshots)
print("CoinGecko snapshots stored:",len(snapshots),"CMC matched:",sum(s in cmc_quotes for s in valid))
# Radar based on observed 1h/24h price changes and volumes, explicitly research-only.
radar=[]
for sym,c in valid.items():
    p=num(c["current_price"])
    h1=num(c.get("price_change_percentage_1h_in_currency"))
    h24=num(c.get("price_change_percentage_24h_in_currency"))
    if h1 is None and h24 is None:continue
    vol=abs(h24) if h24 is not None else abs(h1)
    score=min(100,round(abs(h1 or 0)*7+abs(h24 or 0)*3,2))
    if (h24 or 0)<-5 or (h1 or 0)<-2:level="high"
    elif score>=35:level="medium"
    else:level="low"
    radar.append({"symbol":sym,"asset_group":"crypto","captured_at":stamp,"price":p,
        "change_1h_pct":h1,"volatility_24h_pct":vol,"risk_score":score,
        "alert_level":level,"model_version":"cg-cmc-market-movement-research-v1"})
insert("atlas_risk_radar_snapshots",radar)
print("Research radar rows stored:",len(radar))
# Evaluate only actual previously recorded ATLAS signals after their 24h horizon.
# Use a stored market price captured at/after the horizon; never substitute today's price for an earlier horizon.
signals=db("atlas_hourly_signal_snapshots","?select=id,symbol,asset_group,direction,confidence,price,captured_at&order=captured_at.desc&limit=1000")
existing=db("atlas_signal_audit","?select=source_id&source=eq.hourly_snapshot&limit=10000")
seen={int(x["source_id"]) for x in existing if x.get("source_id") is not None}
audit=[]
for x in signals:
    sid=x.get("id");sym=str(x.get("symbol","")).upper().replace("USDT","")
    if sid in seen or sym not in valid:continue
    direction=str(x.get("direction") or "").upper()
    if direction not in ("LONG","SHORT","BUY","SELL","BULLISH","BEARISH"):continue
    start=num(x.get("price"))
    if not start or start<=0:continue
    at=parse(x["captured_at"])
    horizon=at+datetime.timedelta(hours=24)
    if NOW<horizon:continue
    lower=urllib.parse.quote(horizon.isoformat(),safe="")
    upper=urllib.parse.quote((horizon+datetime.timedelta(hours=2)).isoformat(),safe="")
    prices=db("atlas_market_snapshots","?select=price,captured_at&symbol=eq."+urllib.parse.quote(sym)+"&captured_at=gte."+lower+"&captured_at=lte."+upper+"&order=captured_at.asc&limit=1")
    if not prices:continue
    end=num(prices[0].get("price"))
    if not end or end<=0:continue
    ret=(end/start-1)*100
    bullish=direction in ("LONG","BUY","BULLISH")
    audit.append({"source":"hourly_snapshot","source_id":sid,"symbol":sym,"asset_group":x.get("asset_group") or "crypto",
        "direction":direction,"score":num(x.get("confidence")),"price_at_signal":start,"signal_at":x["captured_at"],
        "horizon_hours":24,"evaluated_at":stamp,"price_at_horizon":end,"return_pct":ret,
        "directional_hit":ret>0 if bullish else ret<0,"status":"evaluated","model_version":"actual-signal-24h-forward-v1"})
insert("atlas_signal_audit",audit)
print("Genuine matured signal evaluations stored:",len(audit))
