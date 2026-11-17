#!/usr/bin/env python3
"""ATLAS closed-candle cache backfill (research only).
CoinGecko remains the price/universe reference. Exchange OHLCV is explicitly
labelled as Kraken primary candle provider, Binance secondary fallback.
Never blends candles from different venues into one series.
"""
import os,json,time,datetime,urllib.request,urllib.parse,urllib.error,math
BASE=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
LIMIT=max(1,min(100,int(os.getenv("ATLAS_CANDLE_SYMBOL_LIMIT","100"))))
TIMEFRAMES={"4h":(14400,240),"1d":(86400,1440)}
H={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json"}
def get(url,headers=None):
    req=urllib.request.Request(url,headers=headers or {"User-Agent":"ATLAS-Candle-Research/1.0"})
    with urllib.request.urlopen(req,timeout=22) as r:return json.load(r)
def rest(path):
    return get(BASE+"/rest/v1/"+path,H)
def save(row):
    h={**H,"Prefer":"resolution=merge-duplicates,return=minimal"}
    req=urllib.request.Request(BASE+"/rest/v1/atlas_ohlcv_closed_cache?on_conflict=symbol,timeframe",data=json.dumps(row).encode(),headers=h,method="POST")
    with urllib.request.urlopen(req,timeout=30) as r:r.read()
def valid(raw,seconds):
    now=int(time.time()*1000)
    rows=[]
    for x in raw:
        try:
            t=int(float(x[0]));o,h,l,c,v=[float(x[i]) for i in (1,2,3,4,5)]
            if t<1e11:t*=1000
            if t+seconds*1000>now or not all(map(math.isfinite,(o,h,l,c,v))) or min(o,h,l,c)<=0 or v<0 or h<max(o,c,l) or l>min(o,c,h):continue
            rows.append([t,o,h,l,c,v])
        except (TypeError,ValueError,IndexError):continue
    rows.sort(key=lambda r:r[0]);rows=list({r[0]:r for r in rows}.values());rows.sort(key=lambda r:r[0])
    # Strictly contiguous last 250 candles, never fill holes synthetically.
    segment=[]
    for r in rows:
        if segment and r[0]-segment[-1][0]!=seconds*1000:segment=[]
        segment.append(r)
    return segment[-350:]
def kraken(sym,tf):
    alias={"BTC":"XBT","DOGE":"XDG"}.get(sym,sym)
    d=get("https://api.kraken.com/0/public/OHLC?"+urllib.parse.urlencode({"pair":alias+"USD","interval":TIMEFRAMES[tf][1]}))
    if d.get("error"):raise ValueError(str(d["error"]))
    result=d.get("result",{});key=next((k for k in result if k!="last"),None)
    if not key:raise ValueError("pair missing")
    return [[int(x[0])*1000,x[1],x[2],x[3],x[4],x[6]] for x in result[key]]
def binance(sym,tf):
    d=get("https://api.binance.com/api/v3/klines?"+urllib.parse.urlencode({"symbol":sym+"USDT","interval":tf,"limit":350}))
    if not isinstance(d,list):raise ValueError("invalid response")
    return [[x[0],x[1],x[2],x[3],x[4],x[5]] for x in d]
def existing(sym,tf):
    q=urllib.parse.urlencode({"select":"rows_json,updated_at,provider","symbol":"eq."+sym,"timeframe":"eq."+tf,"limit":"1"})
    rows=rest("atlas_ohlcv_closed_cache?"+q)
    return rows[0] if rows else None
def main():
    catalog=rest("atlas_ohlcv_closed_cache?select=symbol&timeframe=eq.4h&limit=1000")
    symbols=list(dict.fromkeys(str(x["symbol"]).upper() for x in catalog if str(x.get("symbol","")).isalnum()))
    symbols=symbols[:LIMIT]
    if not symbols:raise RuntimeError("No existing universe; refuse empty ingestion")
    counts={"written":0,"skipped":0,"failed":0};failures=[]
    for sym in symbols:
        for tf,(seconds,_) in TIMEFRAMES.items():
            old=existing(sym,tf)
            try:
                if old and len(valid(json.loads(old["rows_json"]),seconds))>=250:
                    stamp=datetime.datetime.fromisoformat(old["updated_at"].replace("Z","+00:00")).timestamp()
                    if time.time()-stamp<max(seconds*2,18000):counts["skipped"]+=1;continue
            except Exception:pass
            selected=None
            for provider,fn in (("KRAKEN",kraken),("BINANCE_FALLBACK",binance)):
                try:
                    candles=valid(fn(sym,tf),seconds)
                    if len(candles)<250:raise ValueError("only "+str(len(candles))+" contiguous closed candles")
                    last_age=time.time()-((candles[-1][0]/1000)+seconds)
                    if last_age>max(seconds*2,18000):raise ValueError("stale last candle")
                    selected=(provider,candles);break
                except Exception as e:failures.append(sym+"/"+tf+"/"+provider+":"+str(e)[:90])
            if not selected:counts["failed"]+=1;continue
            provider,candles=selected
            save({"symbol":sym,"timeframe":tf,"provider":provider,"limit_n":len(candles),"last_closed_ts":candles[-1][0]+seconds*1000,"rows_json":json.dumps(candles,separators=(",",":")),"updated_at":datetime.datetime.now(datetime.timezone.utc).isoformat()})
            counts["written"]+=1
            time.sleep(.15)
    print(json.dumps({"summary":counts,"symbols":len(symbols),"failures":failures[:25]},ensure_ascii=False))
    if counts["written"]==0 and counts["skipped"]==0:raise RuntimeError("No usable OHLCV backfill")
if __name__=="__main__":main()
