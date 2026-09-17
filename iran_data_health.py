#!/usr/bin/env python3
import os,json,urllib.parse,urllib.request
from datetime import datetime,timezone
SB=os.getenv("SUPABASE_URL","").rstrip("/");KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY","");STRICT=os.getenv("ATLAS_IRAN_HEALTH_STRICT","0")=="1"
FUNDS_CONFIGURED=bool(os.getenv("ATLAS_FUNDS_JSON_URL","").strip())
def fetch(t):
 q=urllib.parse.urlencode({"select":"captured_at,symbol,price,payload","order":"captured_at.desc","limit":"500"});r=urllib.request.Request(f"{SB}/rest/v1/{t}?{q}",headers={"apikey":KEY,"Authorization":f"Bearer {KEY}"})
 with urllib.request.urlopen(r,timeout=20) as x:return json.loads(x.read())
def age(s):return (datetime.now(timezone.utc)-datetime.fromisoformat(s.replace("Z","+00:00"))).total_seconds()/3600
def main():
 rules=[("atlas_iran_fx_snapshots",{"USD_IRR","GOLD18","COIN_EMAMI"},4),("atlas_market_snapshots",{"XAGUSD","SILVER999_FAIR"},4),("atlas_tse_snapshots",{"TSE_MARKET"},30),("atlas_fund_snapshots",set(),36)]
 rep={};bad=[]
 for t,req,mx in rules:
  try:rows=fetch(t)
  except Exception as e:rep[t]={"ok":False,"error":str(e)};bad.append(t);continue
  latest={}
  for r in rows:
   s=str(r.get("symbol") or "")
   if s and s not in latest:latest[s]=r
  miss=sorted(req-set(latest));ages={s:age(r["captured_at"]) for s,r in latest.items() if r.get("captured_at")};stale=[s for s,a in ages.items() if a>mx];ok=not miss and not any(s in stale for s in req)
  if t=="atlas_fund_snapshots" and not FUNDS_CONFIGURED:
   # Funds are optional until an authorized feed is configured.
   ok=True
   rep[t]={"ok":True,"optional":True,"configured":False,"symbols":len(latest),"status":"NOT_CONFIGURED"}
   continue
  if t=="atlas_fund_snapshots" and not latest:ok=False
  rep[t]={"ok":ok,"symbols":len(latest),"missing":miss,"stale":stale[:20],"youngest_age_h":round(min(ages.values()),2) if ages else None}
  if not ok:bad.append(t)
 print(json.dumps({"health":rep,"critical":bad},ensure_ascii=False,indent=2))
 if STRICT and bad:raise SystemExit(2)
if __name__=="__main__":main()
