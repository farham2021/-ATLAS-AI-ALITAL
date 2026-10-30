"""ATLAS v13 production-data shadow adapter; never executes orders."""
import json
import urllib.request
import urllib.parse
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

def _supabase_rows(table, query="", limit=500):
    """Read-only, service-role server-side query. Never expose credentials."""
    base=os.environ.get("SUPABASE_URL","").rstrip("/")
    key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
    if not base or not key: return None
    suffix=("&"+query) if query else ""
    url=base+"/rest/v1/"+table+"?select=*"+suffix+"&limit="+str(limit)
    req=urllib.request.Request(url,headers={"apikey":key,"Authorization":"Bearer "+key})
    try:
        with urllib.request.urlopen(req,timeout=12) as resp:
            result=json.loads(resp.read())
        return result if isinstance(result,list) else None
    except Exception:
        return None

def _portfolio_allocation():
    prefs=_supabase_rows("atlas_desk_allocation_preferences",limit=100)
    snapshots=_supabase_rows("atlas_desk_allocation_snapshots",limit=100)
    if prefs is None or snapshots is None: return {"state":"SOURCE_UNAVAILABLE"}
    # No cross-user aggregation, and no default invented holdings/targets.
    return {"state":"NO_VERIFIED_ALLOCATION" if not snapshots else "EXISTING_SNAPSHOTS",
            "preference_count":len(prefs),"snapshot_count":len(snapshots)}

def _closed_performance():
    events=_supabase_rows("atlas_signal_lifecycle_events","pnl_r=not.is.null&order=timestamp.desc",limit=500)
    if events is None: return {"state":"SOURCE_UNAVAILABLE"}
    closed=[]
    for e in events:
        event=str(e.get("event") or "").upper()
        if any(token in event for token in ("CLOSE","STOP","TARGET","EXIT","TP","SL")) and e.get("pnl_r") is not None:
            # Fee/slippage unknown: never present gross R as net expectancy.
            closed.append(e)
    return {"state":"NET_PERFORMANCE_UNAVAILABLE","closed_gross_r_count":len(closed),
            "reason":"No verified fee/slippage ledger; net performance not inferred"}

def _delivery_receipts():
    # Existing atlas_desk_deliveries contains dedupe keys, not Telegram message_id.
    # Never mislabel those records as Telegram API delivery acknowledgements.
    return {"state":"AWAITING_TELEGRAM_MESSAGE_ID","source":"telegram_send_photo_response"}

def run_v13_cycle(crypto,metals,scoped,output_path=None):
    rows=_rows(crypto)+_rows(metals)
    alerts=[x for x in (early_warning(r) for r in rows) if x["state"]=="WATCH"]
    picks=rank_opportunities(_rows(scoped))
    # Real allocation requires portfolio holdings, total value and target weights;
    # don't infer these from market quotes.
    allocation=_portfolio_allocation()
    # Closed outcomes must come from a dedicated audited ledger, not from live rows.
    performance=_closed_performance()
    report={"schema_version":"13.0","mode":"SHADOW","timestamp_utc":datetime.now(timezone.utc).isoformat(),
            "input_rows":len(rows),"verified_rows":sum(r.get("market_data_verified") is True and r.get("signal_verified") is True for r in rows),
            "alerts":alerts,"ranked_opportunities":picks,"allocation":allocation,
            "performance":performance,"delivery_audit":_delivery_receipts()}
    path=output_path or os.environ.get("ATLAS_V13_REPORT_PATH","/tmp/atlas_v13_latest.json")
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix(target.suffix+".tmp")
    tmp.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding="utf-8")
    os.replace(tmp,target)
    return {"mode":"SHADOW","rows":len(rows),"verified":report["verified_rows"],"alerts":len(alerts),"picks":len(picks),"report_path":str(target)}
