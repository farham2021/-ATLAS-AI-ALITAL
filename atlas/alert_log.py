"""ATLAS prospective hash-chain audit log. Research-only; external anchors required."""
import argparse, datetime, hashlib, json, os
from pathlib import Path
try:
 import fcntl
except ImportError:
 fcntl=None
GENESIS_HASH="0"*64
PROTOCOL_VERSION="1.0"
RESERVED_FIELDS={"seq","ts_utc","kind","protocol_version","prev_record_hash","record_hash"}
REQUIRED_ALERT_FIELDS={"asset","model_version","config_hash","event_definition_id","alert_level","score","reference_price","horizon_hours","features_snapshot_hash"}
KINDS={"alert","delivery","error","outage"}
class LogIntegrityError(RuntimeError): pass
def compute_hash(record):
 return hashlib.sha256(json.dumps({k:v for k,v in record.items() if k!="record_hash"},sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def _records(path):
 with open(path,encoding="utf-8") as f:
  return [json.loads(line) for line in f if line.strip()]
def _verify(records):
 prev=GENESIS_HASH; ts=""
 for i,r in enumerate(records,1):
  if not isinstance(r,dict) or type(r.get("seq")) is not int or r["seq"]!=i:return False,f"invalid sequence at {i}"
  if r.get("prev_record_hash")!=prev or r.get("record_hash")!=compute_hash(r):return False,f"broken chain at {i}"
  if not isinstance(r.get("ts_utc"),str) or r["ts_utc"]<ts:return False,f"timestamp order at {i}"
  ts=r["ts_utc"];prev=r["record_hash"]
 return True,f"OK: {len(records)} records, head={prev}"
def verify(log_path):
 try:return _verify(_records(log_path))
 except (OSError,ValueError,TypeError,KeyError) as e:return False,str(e)
def _validate_delivery(fields,records):
 if not {"alert_seq","alert_record_hash","status"}<=fields.keys():raise ValueError("delivery requires alert_seq, alert_record_hash, status")
 if fields["status"] not in {"sent","failed","unknown"}:raise ValueError("invalid delivery status")
 if fields["status"]=="sent" and (type(fields.get("telegram_message_id")) is not int or fields["telegram_message_id"]<=0):raise ValueError("sent requires positive telegram_message_id")
 if fields["status"]=="failed" and (not isinstance(fields.get("error"),str) or not fields["error"].strip()):raise ValueError("failed requires nonempty error")
 if type(fields["alert_seq"]) is not int or fields["alert_seq"]<=0 or fields["alert_seq"]>len(records):raise ValueError("invalid alert_seq")
 alert=records[fields["alert_seq"]-1]
 if alert.get("kind")!="alert" or alert["record_hash"]!=fields["alert_record_hash"]:raise ValueError("delivery must reference existing alert")
def append(log_path,fields,kind="alert"):
 if kind not in KINDS:raise ValueError("invalid kind")
 if not isinstance(fields,dict):raise ValueError("fields must be object")
 if RESERVED_FIELDS & fields.keys():raise ValueError("reserved fields")
 if kind=="alert" and not REQUIRED_ALERT_FIELDS<=fields.keys():raise ValueError("missing alert fields")
 path=Path(log_path);path.parent.mkdir(parents=True,exist_ok=True)
 with open(path,"a+",encoding="utf-8") as f:
  if fcntl:fcntl.flock(f,fcntl.LOCK_EX)
  try:
   f.seek(0)
   try:records=[json.loads(line) for line in f if line.strip()]
   except (ValueError,TypeError) as e:raise LogIntegrityError("corrupt JSON") from e
   ok,msg=_verify(records)
   if not ok:raise LogIntegrityError(msg)
   if kind=="delivery":_validate_delivery(fields,records)
   prev=records[-1] if records else None
   now=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
   if prev and now<prev["ts_utc"]:raise LogIntegrityError("clock moved backwards")
   record={"seq":len(records)+1,"ts_utc":now,"kind":kind,"protocol_version":PROTOCOL_VERSION,**fields,"prev_record_hash":prev["record_hash"] if prev else GENESIS_HASH}
   record["record_hash"]=compute_hash(record)
   f.seek(0,os.SEEK_END);f.write(json.dumps(record,sort_keys=True,ensure_ascii=False)+"\\n");f.flush();os.fsync(f.fileno())
   return record
  finally:
   if fcntl:fcntl.flock(f,fcntl.LOCK_UN)
def anchor(log_path,date_utc):
 datetime.date.fromisoformat(date_utc)
 ok,msg=verify(log_path)
 if not ok:raise LogIntegrityError(msg)
 records=[r for r in _records(log_path) if r["ts_utc"][:10]<=date_utc]
 return {"date":date_utc,"seq":len(records),"record_hash":records[-1]["record_hash"] if records else GENESIS_HASH,"records":len(records)}
def check_anchors(log_path,anchors_path):
 """Compare against a trusted independently retrieved JSONL anchor snapshot; no network trust implied."""
 ok,msg=verify(log_path)
 if not ok:raise LogIntegrityError(msg)
 entries=_records(anchors_path)
 if not entries:raise LogIntegrityError("no anchors supplied")
 dates=set()
 for a in entries:
  date=a.get("date")
  if not isinstance(date,str) or date in dates:raise LogIntegrityError("duplicate or invalid anchor date")
  dates.add(date)
  expected=anchor(log_path,date)
  if any(a.get(k)!=expected[k] for k in ("date","seq","record_hash","records")):raise LogIntegrityError("anchor mismatch: "+date)
 return True,f"OK: {len(entries)} external anchors match"
def main(argv=None):
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest="cmd",required=True)
 for cmd in ("append","verify","anchor","check-anchors"):
  a=sub.add_parser(cmd);a.add_argument("--log",required=True)
  if cmd=="append":
   a.add_argument("--json",required=True);a.add_argument("--kind",default="alert",choices=sorted(KINDS))
  if cmd=="anchor":a.add_argument("--date",required=True)
  if cmd=="check-anchors":a.add_argument("--anchors",required=True,help="trusted independently retrieved JSONL snapshot")
 a=p.parse_args(argv)
 try:
  if a.cmd=="append":print(json.dumps(append(a.log,json.loads(a.json),a.kind)))
  elif a.cmd=="anchor":print(json.dumps(anchor(a.log,a.date)))
  else:
   ok,msg=(verify(a.log) if a.cmd=="verify" else check_anchors(a.log,a.anchors));print(msg);return 0 if ok else 1
  return 0
 except (ValueError,OSError,LogIntegrityError) as e:print(str(e));return 1
if __name__=="__main__":
 import sys
 sys.exit(main())
