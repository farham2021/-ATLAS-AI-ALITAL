"""ATLAS v13 production-data shadow adapter; never executes orders."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from atlas_v13_shadow import early_warning, rank_opportunities, score_outcomes, allocation_gap

def _rows(value):
    if isinstance(value,list): return [x for x in value if isinstance(x,dict)]
    if isinstance(value,dict):
        for key in ("results","rows","data","assets"):
            if isinstance(value.get(key),list): return _rows(value[key])
    return []

def run_v13_cycle(crypto,metals,scoped,output_path=None):
    rows=_rows(crypto)+_rows(metals)
    alerts=[x for x in (early_warning(r) for r in rows) if x["state"]=="WATCH"]
    picks=rank_opportunities(_rows(scoped))
    # Real allocation requires portfolio holdings, total value and target weights;
    # don't infer these from market quotes.
    allocation={"state":"AWAITING_VERIFIED_PORTFOLIO"}
    # Closed outcomes must come from a dedicated audited ledger, not from live rows.
    performance=score_outcomes([])
    report={"schema_version":"13.0","mode":"SHADOW","timestamp_utc":datetime.now(timezone.utc).isoformat(),
            "input_rows":len(rows),"verified_rows":sum(r.get("market_data_verified") is True and r.get("signal_verified") is True for r in rows),
            "alerts":alerts,"ranked_opportunities":picks,"allocation":allocation,
            "performance":performance,"delivery_audit":{"state":"AWAITING_TELEGRAM_RECEIPTS"}}
    path=output_path or os.environ.get("ATLAS_V13_REPORT_PATH","/tmp/atlas_v13_latest.json")
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix(target.suffix+".tmp")
    tmp.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding="utf-8")
    os.replace(tmp,target)
    return {"mode":"SHADOW","rows":len(rows),"verified":report["verified_rows"],"alerts":len(alerts),"picks":len(picks),"report_path":str(target)}
