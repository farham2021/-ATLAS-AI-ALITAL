import json
import pytest
from atlas import alert_log as L
ALERT={"asset":"BTC","model_version":"v1","config_hash":"c","event_definition_id":"e","alert_level":"HIGH","score":0.8,"reference_price":100,"horizon_hours":24,"features_snapshot_hash":"f"}
def test_chain(tmp_path):
 p=tmp_path/"a.jsonl";a=L.append(p,ALERT);b=L.append(p,ALERT)
 assert b["prev_record_hash"]==a["record_hash"] and L.verify(p)[0]
def test_tamper_rejected(tmp_path):
 p=tmp_path/"a.jsonl";L.append(p,ALERT);p.write_text(p.read_text().replace("BTC","ETH"))
 before=p.read_text()
 with pytest.raises(L.LogIntegrityError):L.append(p,ALERT)
 assert p.read_text()==before
@pytest.mark.parametrize("field",list(L.RESERVED_FIELDS))
def test_reserved(tmp_path,field):
 with pytest.raises(ValueError):L.append(tmp_path/"a.jsonl",{**ALERT,field:"bad"})
@pytest.mark.parametrize("status,extra",[
 ("sent",{}),("sent",{"telegram_message_id":0}),("sent",{"telegram_message_id":"1"}),
 ("failed",{}),("failed",{"error":" "}),("unknown",{"telegram_message_id":1})])
def test_delivery_fields(tmp_path,status,extra):
 p=tmp_path/"a.jsonl";a=L.append(p,ALERT)
 fields={"alert_seq":a["seq"],"alert_record_hash":a["record_hash"],"status":status,**extra}
 if status=="unknown":
  assert L.append(p,fields,kind="delivery")["status"]=="unknown"
 else:
  with pytest.raises(ValueError):L.append(p,fields,kind="delivery")
def test_sent_and_failed(tmp_path):
 p=tmp_path/"a.jsonl";a=L.append(p,ALERT)
 link={"alert_seq":a["seq"],"alert_record_hash":a["record_hash"]}
 L.append(p,{**link,"status":"sent","telegram_message_id":42},kind="delivery")
 L.append(p,{**link,"status":"failed","error":"HTTP 403"},kind="delivery")
 assert L.verify(p)[0]
def test_wrong_alert_reference(tmp_path):
 p=tmp_path/"a.jsonl";a=L.append(p,ALERT)
 with pytest.raises(ValueError):L.append(p,{"alert_seq":a["seq"],"alert_record_hash":"0"*64,"status":"sent","telegram_message_id":1},kind="delivery")
def test_anchor_mismatch_after_tail_delete(tmp_path):
 p=tmp_path/"a.jsonl";L.append(p,ALERT);L.append(p,ALERT)
 d=L._records(p)[-1]["ts_utc"][:10];a=L.anchor(p,d)
 anchors=tmp_path/"trusted.jsonl";anchors.write_text(json.dumps(a)+"\n")
 assert L.check_anchors(p,anchors)[0]
 p.write_text(p.read_text().splitlines()[0]+"\n")
 assert L.verify(p)[0]
 with pytest.raises(L.LogIntegrityError):L.check_anchors(p,anchors)
def test_anchor_mismatch_and_empty(tmp_path):
 p=tmp_path/"a.jsonl";L.append(p,ALERT);a=L.anchor(p,"2999-01-01")
 anchors=tmp_path/"trusted.jsonl";anchors.write_text(json.dumps({**a,"record_hash":"f"*64})+"\n")
 with pytest.raises(L.LogIntegrityError):L.check_anchors(p,anchors)
 anchors.write_text("")
 with pytest.raises(L.LogIntegrityError):L.check_anchors(p,anchors)
