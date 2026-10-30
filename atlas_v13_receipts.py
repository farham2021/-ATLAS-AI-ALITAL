"""Privacy-minimized Telegram photo delivery acknowledgements (per-run)."""
import json
import os
from datetime import datetime,timezone
from pathlib import Path

def record_photo_receipt(filename,caption,response,path=None):
    message=response.get("result") if isinstance(response,dict) else None
    if not isinstance(message,dict) or response.get("ok") is not True or message.get("message_id") is None:
        raise ValueError("Telegram response lacks acknowledged message_id")
    # Never persist chat ID, token, text or private Telegram payload.
    title=str(caption or "").split("|")[0].strip()[:100]
    record={"report":title,"message_id":message["message_id"],
            "timestamp_utc":datetime.now(timezone.utc).isoformat(),"ok":True}
    target=Path(path or os.environ.get("ATLAS_V13_RECEIPTS_PATH","/tmp/atlas_v13_receipts.jsonl"))
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("a",encoding="utf-8") as f: f.write(json.dumps(record,ensure_ascii=False)+"\n")
    return record

def audit_photo_receipts(path=None):
    target=Path(path or os.environ.get("ATLAS_V13_RECEIPTS_PATH","/tmp/atlas_v13_receipts.jsonl"))
    if not target.exists():return {"state":"NO_ACKNOWLEDGEMENTS","count":0}
    try:
        rows=[json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
        return {"state":"ACKNOWLEDGEMENTS_RECORDED","count":len(rows),
                "reports":sorted(set(r["report"] for r in rows if r.get("ok") is True))}
    except (OSError,ValueError,KeyError):
        return {"state":"AUDIT_CORRUPT","count":0}
