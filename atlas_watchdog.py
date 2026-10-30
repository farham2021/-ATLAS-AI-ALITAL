"""ATLAS independent read-only watchdog. Never marks a cycle done or sends trades."""
import json, os, urllib.request
from datetime import datetime, timezone, timedelta

URL=os.environ["SUPABASE_URL"].rstrip("/")
KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEAD={"apikey":KEY,"Authorization":"Bearer "+KEY}
def get(path):
    req=urllib.request.Request(URL+path,headers=HEAD)
    with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
def check(now=None):
    now=now or datetime.now(timezone.utc)
    rows=get("/rest/v1/atlas_scheduler_runs?select=cycle,status,completed_at,lease_until&order=completed_at.desc.nullslast&limit=400")
    thresholds={"HOURLY":4,"DEEP4H":30,"DAILY16":30,"NIGHTLY23":30}
    last={}
    for row in rows:
        if row.get("status")!="DONE" or row.get("cycle") not in thresholds or not row.get("completed_at"):continue
        ts=datetime.fromisoformat(row["completed_at"].replace("Z","+00:00"))
        key=row["cycle"]
        if key not in last or ts>last[key]:last[key]=ts
    warnings=[]
    for cycle,hours in thresholds.items():
        age=(now-last[cycle]).total_seconds()/3600 if cycle in last else None
        if age is None or age>hours:warnings.append(f"{cycle}: last successful completion "+(f"{age:.1f}h ago" if age is not None else "unknown"))
    expired=[r for r in rows if r.get("status")=="RUNNING" and r.get("lease_until") and datetime.fromisoformat(r["lease_until"].replace("Z","+00:00"))<now]
    if expired:warnings.append(f"{len(expired)} expired RUNNING leases (manual review; no forced DONE)")
    return {"checked_at":now.isoformat(),"last_done":{k:v.isoformat() for k,v in last.items()},"warnings":warnings}
if __name__=="__main__":
    try:
        result=check()
        print(json.dumps(result,ensure_ascii=False))
        if result["warnings"]:
            for warning in result["warnings"]:print("::warning::ATLAS watchdog: "+warning)
            raise SystemExit(2)
    except Exception as exc:
        print("::error::ATLAS watchdog unavailable: "+str(exc))
        raise SystemExit(3)
