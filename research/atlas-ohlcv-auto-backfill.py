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
def coinbase(sym,tf):
    # Coinbase Exchange public candles: 1h bars aggregated into aligned 4h,
    # or native daily bars. Multiple requests required for 250 4h bars.
    gran=3600 if tf=="4h" else 86400
    end=int(time.time()//gran*gran)
    pages=5 if tf=="4h" else 2
    out=[]
    for i in range(pages):
        hi=end-i*290*gran
        lo=hi-290*gran
        url="https://api.exchange.coinbase.com/products/"+urllib.parse.quote(sym+"-USD")+"/candles?"+urllib.parse.urlencode({"granularity":gran,"start":datetime.datetime.fromtimestamp(lo,datetime.timezone.utc).isoformat(),"end":datetime.datetime.fromtimestamp(hi,datetime.timezone.utc).isoformat()})
        data=get(url,{"User-Agent":"ATLAS-Research/1.0","Accept":"application/json"})
        if not isinstance(data,list):raise ValueError("Coinbase response not candles")
        out.extend([[int(x[0])*1000,x[3],x[2],x[1],x[4],x[5]] for x in data])
        time.sleep(.08)
    if tf=="1d":return out
    buckets={}
    for x in out:
        t=x[0]//1000
        bucket=t//14400*14400
        buckets.setdefault(bucket,[]).append(x)
    result=[]
    for bucket,bars in sorted(buckets.items()):
        bars=sorted({x[0]:x for x in bars}.values(),key=lambda x:x[0])
        if len(bars)!=4 or [x[0] for x in bars]!=[(bucket+j*3600)*1000 for j in range(4)]:continue
        result.append([bucket*1000,bars[0][1],max(x[2] for x in bars),min(x[3] for x in bars),bars[-1][4],sum(x[5] for x in bars)])
    return result
def existing(sym,tf):
    q=urllib.parse.urlencode({"select":"rows_json,updated_at,provider","symbol":"eq."+sym,"timeframe":"eq."+tf,"limit":"1"})
    rows=rest("atlas_ohlcv_closed_cache?"+q)
    return rows[0] if rows else None
def main():
    catalog=rest("atlas_ohlcv_closed_cache?select=symbol,timeframe,limit_n&timeframe=in.(4h,1d)&limit=1000")
    by_symbol={}
    for row in catalog:
        sym=str(row.get("symbol","")).upper()
        if not sym.isascii() or not sym.isalnum() or not 2<=len(sym)<=12:continue
        by_symbol.setdefault(sym,{})[row["timeframe"]]=int(row.get("limit_n") or 0)
    symbols=sorted(by_symbol,key=lambda x:(min(by_symbol[x].get("4h",0),by_symbol[x].get("1d",0))>=250,min(by_symbol[x].get("4h",0),by_symbol[x].get("1d",0)),x))[:LIMIT]
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
            for provider,fn in (("KRAKEN",kraken),("COINBASE_FALLBACK",coinbase),("BINANCE_FALLBACK",binance)):
                try:
                    candles=valid(fn(sym,tf),seconds)
                    if len(candles)<250:raise ValueError("only "+str(len(candles))+" contiguous closed candles")
                    last_age=time.time()-((candles[-1][0]/1000)+seconds)
                    if last_age>max(seconds*2,18000):raise ValueError("stale last candle")
                    if old:
                        try:
                            prior=valid(json.loads(old["rows_json"]),seconds)
                            if len(prior)>=250 and prior[-1][0]>=candles[-1][0] and len(prior)>=len(candles):
                                counts["skipped"]+=1
                                selected=("SKIP",prior)
                                break
                        except (ValueError,TypeError,KeyError):pass
                    selected=(provider,candles);break
                except Exception as e:failures.append(sym+"/"+tf+"/"+provider+":"+str(e)[:90])
            if not selected:counts["failed"]+=1;continue
            provider,candles=selected
            if provider=="SKIP":continue
            save({"symbol":sym,"timeframe":tf,"provider":provider,"limit_n":len(candles),"last_closed_ts":candles[-1][0]+seconds*1000,"rows_json":json.dumps(candles,separators=(",",":")),"updated_at":datetime.datetime.now(datetime.timezone.utc).isoformat()})
            counts["written"]+=1
            time.sleep(.15)
    print(json.dumps({"summary":counts,"symbols":len(symbols),"failures":failures[:25]},ensure_ascii=False))
    if counts["written"]==0 and counts["skipped"]==0:raise RuntimeError("No usable OHLCV backfill")
if __name__=="__main__":main()
