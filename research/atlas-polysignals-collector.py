#!/usr/bin/env python3
"""PolySignals research feed: never treat intrawindow market-implied odds as forecasts."""
import os,json,urllib.request,datetime,math
BASE=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
URL="https://polysignals.net/api/v1/signals.json"
req=urllib.request.Request(URL,headers={"Accept":"application/json","User-Agent":"ATLAS-Research/1.0"})
with urllib.request.urlopen(req,timeout=25) as r:data=json.load(r)
if not isinstance(data,dict) or not isinstance(data.get("coins"),dict):raise RuntimeError("PolySignals response invalid")
generated=data.get("generated_at")
stamp=datetime.datetime.fromisoformat(str(generated).replace("Z","+00:00"))
now=datetime.datetime.now(datetime.timezone.utc)
if abs((now-stamp).total_seconds())>900:raise RuntimeError("PolySignals feed stale")
rows=[]
for coin,info in data["coins"].items():
    if not isinstance(info,dict):continue
    for timeframe,frame in info.get("timeframes",{}).items():
        if not isinstance(frame,dict):continue
        current=((frame.get("combined") or {}).get("current") or {})
        if not current:continue
        confidence=current.get("confidence") or {}
        score=current.get("score")
        conf=confidence.get("score") if isinstance(confidence,dict) else None
        if score is not None and (not isinstance(score,(int,float)) or not math.isfinite(score)):continue
        rows.append({"provider":"polysignals","symbol":str(coin).upper()[:40],"timeframe":str(timeframe)[:12],
            "observed_at":stamp.isoformat(),"direction":str(current.get("direction") or "unknown")[:30],
            "score":score,"confidence":conf if isinstance(conf,(int,float)) and math.isfinite(conf) else None,
            "payload":{"source_url":URL,"generated_at":generated,"prob_up":current.get("prob_up"),
            "late_window":current.get("late_window"),"independent_sources":confidence.get("independent_sources") if isinstance(confidence,dict) else None,
            "interpretation":"current-window market-implied reading; NOT future prediction","research_only":True}})
if not rows:raise RuntimeError("No PolySignals observations")
h={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","Prefer":"resolution=ignore-duplicates,return=minimal"}
for i in range(0,len(rows),100):
    req=urllib.request.Request(BASE+"/rest/v1/atlas_external_signal_observations?on_conflict=provider,symbol,timeframe,observed_at",
        data=json.dumps(rows[i:i+100]).encode(),headers=h,method="POST")
    with urllib.request.urlopen(req,timeout=30) as res:res.read()
print("PolySignals observations processed:",len(rows),"timestamp:",stamp.isoformat())
