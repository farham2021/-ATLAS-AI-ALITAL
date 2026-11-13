#!/usr/bin/env python3
"""ATLAS signal audit and risk radar; SHADOW ONLY, never trades or sends alerts."""
import datetime as dt
import json
import math
import os
import urllib.parse
import urllib.request
from collections import defaultdict

BASE=os.environ["SUPABASE_URL"].rstrip("/")+"/rest/v1/"
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEAD={"apikey":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json"}
NOW=dt.datetime.now(dt.timezone.utc)

def request(path, method="GET", data=None, prefer=None):
    headers=dict(HEAD)
    if prefer: headers["Prefer"]=prefer
    req=urllib.request.Request(BASE+path,method=method,headers=headers,
        data=json.dumps(data,allow_nan=False).encode() if data is not None else None)
    with urllib.request.urlopen(req,timeout=22) as r:
        return json.loads(r.read() or b"null")
def when(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00"))
def price(x):
    try:
        v=float(x)
        return v if math.isfinite(v) and v>0 else None
    except (ValueError,TypeError): return None
def fetch(table,query):return request(table+"?"+query)
def insert(table,rows,conflict):
    if rows:
        request(table+"?on_conflict="+conflict,"POST",rows,"resolution=ignore-duplicates,return=minimal")

def main():
    audit=[]
    for source,table in [("hourly","atlas_hourly_signal_snapshots"),("deep4h","atlas_deep_4h_snapshots")]:
        rows=fetch(table,"select=id,symbol,asset_group,direction,confidence,price,captured_at,model_version&order=captured_at.desc&limit=300")
        for r in rows:
            p=price(r.get("price"))
            if not p or not r.get("captured_at"):continue
            audit.append({"source":source,"source_id":r["id"],"symbol":r["symbol"],"asset_group":r.get("asset_group"),
                "direction":r.get("direction"),"score":r.get("confidence"),"price_at_signal":p,
                "signal_at":r["captured_at"],"horizon_hours":24,"model_version":r.get("model_version")})
    insert("atlas_signal_audit",audit,"source,source_id,horizon_hours")
    pending=fetch("atlas_signal_audit","select=id,symbol,direction,price_at_signal,signal_at,horizon_hours&status=eq.pending&order=signal_at.asc&limit=250")
    for row in pending:
        target=when(row["signal_at"])+dt.timedelta(hours=row["horizon_hours"])
        if NOW<target+dt.timedelta(minutes=15):continue
        # A point-in-time evaluation must not use a snapshot before the target horizon.
        q=("select=price,captured_at&symbol=eq."+urllib.parse.quote(row["symbol"],safe="")+
           "&captured_at=gte."+urllib.parse.quote(target.isoformat(),safe="")+
           "&captured_at=lte."+urllib.parse.quote((target+dt.timedelta(hours=3)).isoformat(),safe="")+
           "&order=captured_at.asc&limit=1")
        snapshots=fetch("atlas_market_snapshots",q)
        if not snapshots:
            snapshots=fetch("atlas_hourly_signal_snapshots",q)
        if not snapshots:continue
        end_price=price(snapshots[0].get("price"))
        if not end_price:continue
        pct=(end_price/float(row["price_at_signal"])-1)*100
        direction=str(row.get("direction") or "").upper()
        is_long=any(x in direction for x in ("LONG","BUY","BULL","UP"))
        is_short=any(x in direction for x in ("SHORT","SELL","BEAR","DOWN"))
        hit=(pct>0 if is_long else pct<0) if (is_long or is_short) else None
        request("atlas_signal_audit?id=eq."+str(row["id"]),"PATCH",
            {"evaluated_at":NOW.isoformat(),"price_at_horizon":end_price,"return_pct":round(pct,5),
             "directional_hit":hit,"status":"evaluated"})
    snapshots=fetch("atlas_market_snapshots","select=symbol,asset,price,captured_at&order=captured_at.desc&limit=2000")
    grouped=defaultdict(list)
    for row in snapshots:
        if price(row.get("price")):grouped[row["symbol"]].append(row)
    radar=[]
    for symbol,rows in grouped.items():
        if len(rows)<3:continue
        latest=rows[0];ts=when(latest["captured_at"])
        if NOW-ts>dt.timedelta(hours=3):continue
        old=next((r for r in rows[1:] if dt.timedelta(minutes=45)<=ts-when(r["captured_at"])<=dt.timedelta(minutes=100)),None)
        history=[r for r in rows if ts-when(r["captured_at"])<=dt.timedelta(hours=24)]
        if not old or len(history)<4:continue
        pct=(float(latest["price"])/float(old["price"])-1)*100
        values=[float(r["price"]) for r in history]
        vol=(max(values)/min(values)-1)*100
        # Transparent heuristic score; NOT a calibrated probability.
        score=min(100,round(abs(pct)*10+vol*2,2))
        level="high" if score>=70 else "moderate" if score>=35 else "low"
        radar.append({"symbol":symbol,"asset_group":latest.get("asset"),"captured_at":latest["captured_at"],
            "price":float(latest["price"]),"change_1h_pct":round(pct,5),
            "volatility_24h_pct":round(vol,5),"risk_score":score,"alert_level":level})
    insert("atlas_risk_radar_snapshots",radar,"symbol,captured_at")
    print(json.dumps({"audit_candidates":len(audit),"pending_checked":len(pending),"radar_candidates":len(radar),
        "mode":"shadow","live_trades":False,"telegram_alerts":False}))

if __name__=="__main__":main()
