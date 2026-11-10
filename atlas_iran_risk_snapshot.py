"""Iran early-risk candidates from timestamped Supabase snapshots.
Fail closed: only explicit provider pct decline, recent observations, never synthetic candles.
"""
from datetime import datetime,timezone,timedelta
import json,os,urllib.parse,urllib.request,math
TABLES=("atlas_tse_snapshots","atlas_fund_snapshots","atlas_iran_fx_snapshots","atlas_market_snapshots")
def scan_iran(now=None):
 now=now or datetime.now(timezone.utc)
 base=os.environ["SUPABASE_URL"].rstrip("/")
 key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
 headers={"apikey":key,"Authorization":"Bearer "+key}
 found=[];coverage={}
 for table in TABLES:
  q=urllib.parse.urlencode({"select":"captured_at,symbol,price,payload","order":"captured_at.desc","limit":"1000"})
  req=urllib.request.Request(base+"/rest/v1/"+table+"?"+q,headers=headers)
  with urllib.request.urlopen(req,timeout=20) as r:rows=json.load(r)
  if not isinstance(rows,list):raise ValueError(table+" invalid response")
  seen=set();valid=0
  for row in rows:
   symbol=str(row.get("symbol") or "").strip()
   if not symbol or symbol in seen:continue
   seen.add(symbol)
   try:
    stamp=datetime.fromisoformat(str(row["captured_at"]).replace("Z","+00:00"))
    if stamp.tzinfo is None or not timedelta(0)<=now-stamp<=timedelta(hours=26):continue
    payload=row.get("payload")
    if not isinstance(payload,dict):continue
    raw=payload.get("pct")
    if isinstance(raw,bool) or not isinstance(raw,(int,float,str)):continue
    pct=float(raw)
    if not math.isfinite(pct) or not -100<=pct<=100:continue
    valid+=1
    if pct<=-5:level="CRITICAL"
    elif pct<=-3:level="HIGH"
    elif pct<=-1.5:level="WATCH"
    else:continue
    price=row.get("price")
    if price is None or not math.isfinite(float(price)) or float(price)<=0:continue
    found.append((symbol,{"level":level,"price":float(price),"decline24":pct,"volume_ratio":"","flags":["Iran provider reported pct decline","source="+table,"observed_at="+stamp.isoformat()],"market":"IRAN"}))
   except (ValueError,TypeError,KeyError,OverflowError):continue
  coverage[table]={"recent_valid_pct":valid,"returned":len(rows)}
 return found,coverage
