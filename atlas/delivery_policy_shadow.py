"""ATLAS notification schedule policy (shadow; not wired to production).
All times Asia/Tehran. Delivery is separate from analysis/persistence.
"""
from datetime import datetime,time
from zoneinfo import ZoneInfo
TEHRAN=ZoneInfo("Asia/Tehran")
CSV_SLOTS=((10,30),(16,0),(21,30))
def policy(now,market,kind,critical=False):
 if now.tzinfo is None:raise ValueError("timezone required")
 t=now.astimezone(TEHRAN)
 if market not in ("IRAN","CRYPTO") or kind not in ("TABLE","CSV"):raise ValueError("unknown delivery type")
 # Iranian exchange generally trades Saturday-Wednesday, 09:00-12:30 Tehran.
 iran_session=t.weekday() in (5,6,0,1,2) and time(9,0)<=t.time()<time(12,30)
 if kind=="TABLE":
  if market=="IRAN":
   return {"deliver":iran_session and time(10,30)<=t.time()<time(11,0),"reason":"iran_market_actionable_only"}
  return {"deliver":time(16,0)<=t.time()<time(16,30),"reason":"crypto_daily16_only"}
 slot=next(((h,m) for h,m in CSV_SLOTS if time(h,m)<=t.time()< (datetime(2000,1,1,h,m).replace(minute=m)+__import__("datetime").timedelta(minutes=30)).time()),None)
 return {"deliver":bool(slot or critical),"reason":"critical" if critical else ("csv_session" if slot else "outside_csv_sessions"),"slot":slot}
