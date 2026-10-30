"""ATLAS read-only research bridge. No Supabase writes, no Telegram, no orders.
Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in a trusted CI environment.
Run: python research/phase312/shadow_bridge.py
"""
import json,os,urllib.parse,urllib.request,datetime,collections
from data_quality import validate_closed_candles,continuous_forward_window
from evidence_lab import evaluate_signal,summarize

def fetch(table,params):
    base=os.environ["SUPABASE_URL"].rstrip("/")
    key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    url=base+"/rest/v1/"+table+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"apikey":key,"Authorization":"Bearer "+key})
    with urllib.request.urlopen(req,timeout=30) as resp:
        return json.load(resp)

def research(asof=None):
    asof=asof or datetime.datetime.now(datetime.timezone.utc)
    asof_ms=int(asof.timestamp()*1000)
    cache=fetch("atlas_ohlcv_closed_cache",{"select":"symbol,timeframe,rows_json,updated_at,provider","timeframe":"in.(1h,4h)","limit":200})
    series={}
    quality=collections.Counter()
    for r in cache:
        try:
            bars=json.loads(r["rows_json"])
            if isinstance(bars,dict): bars=bars.get("rows",[])
            clean,issues=validate_closed_candles(bars,r["timeframe"],asof_ms)
            for k,v in issues.items():quality[k]+=v
            series[(r["symbol"],r["timeframe"])]=clean
        except (ValueError,TypeError,KeyError):
            quality["invalid_cache"]+=1
    # Fetch recent candidate snapshots; never assume confirmation means executable.
    snapshots=fetch("atlas_hourly_signal_snapshots",{
        "select":"id,symbol,model_version,decision_state,direction,payload",
        "decision_state":"in.(BUY CONFIRMATION,SELL CONFIRMATION)",
        "order":"captured_at.desc","limit":500})
    results=[]
    seen=set()
    for s in snapshots:
        p=s.get("payload") or {}
        try:
            tf=str(p.get("timeframe") or "4h").lower()
            if tf not in ("1h","4h"):quality["unknown_timeframe"]+=1;continue
            ts=int(p["signal_candle_ts"])
            key=(s["symbol"],tf,ts,s["direction"],s["model_version"])
            if key in seen:quality["duplicate_signal"]+=1;continue
            seen.add(key)
            entry=float(p["entry"]);sl=float(p["sl"]);tp=float(p["tp1"])
            signal={"signal_candle_ts":ts,"direction":s["direction"],"entry":entry,"sl":sl,"tp1":tp}
            candles=series.get((s["symbol"],tf),[])
            for horizon in (1,4,12,24):
                window=continuous_forward_window(candles,ts,horizon,tf)
                if window is None:
                    results.append({"model_version":s["model_version"],"regime":str(p.get("regime","UNKNOWN")),
                                    "horizon_candles":horizon,"label":"IMMATURE"})
                    continue
                result=evaluate_signal(signal,window,(horizon,))[0]
                results.append({"model_version":s["model_version"],"regime":str(p.get("regime","UNKNOWN")),**result})
        except (KeyError,ValueError,TypeError,OverflowError):
            quality["invalid_signal"]+=1
    return {"mode":"SHADOW_READ_ONLY","asof_utc":asof.isoformat(),
            "cache_series":len(series),"candidate_snapshots":len(snapshots),
            "quality":dict(quality),"cohorts":summarize(results)}

if __name__=="__main__":
    print(json.dumps(research(),ensure_ascii=False,indent=2))
