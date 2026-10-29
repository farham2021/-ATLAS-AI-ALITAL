"""ATLAS v2 research audit: time-ordered, asset-separated, fail-closed.
No trading, no public signal promotion, no DB writes.
Snapshot proxy evaluation; NOT OHLCV stop/target execution simulation.
"""
import os,json,urllib.request,urllib.parse
from collections import defaultdict
from datetime import datetime

STATES={"BUY CONFIRMATION":1,"SELL CONFIRMATION":-1,"BULLISH WATCH":1,"BEARISH WATCH":-1}
def parse_time(v): return datetime.fromisoformat(v.replace("Z","+00:00"))
def fetch():
    base=os.environ["SUPABASE_URL"].rstrip("/")
    key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    rows=[]
    for offset in range(0,30000,1000):
        params=urllib.parse.urlencode({"select":"symbol,asset_group,captured_at,price,decision_state","order":"captured_at.desc","limit":1000,"offset":offset})
        req=urllib.request.Request(base+"/rest/v1/atlas_hourly_signal_snapshots?"+params,headers={"apikey":key,"Authorization":"Bearer "+key})
        with urllib.request.urlopen(req,timeout=45) as response: chunk=json.load(response)
        rows.extend(chunk)
        if len(chunk)<1000: break
    return rows

def audit(rows):
    assets=defaultdict(list)
    for row in rows:
        try:
            price=float(row["price"])
            if price>0 and row.get("captured_at") and row.get("symbol"):
                assets[(row.get("asset_group","UNKNOWN"),row["symbol"])].append((parse_time(row["captured_at"]),price,row.get("decision_state","")))
        except (TypeError,ValueError,KeyError): continue
    events=[]
    for (group,symbol),series in assets.items():
        series.sort()
        for i,(t,p,state) in enumerate(series):
            direction=STATES.get(state)
            if not direction or i+4>=len(series): continue
            later,exit_price,_=series[i+4]
            if not 0<(later-t).total_seconds()<=12*3600: continue
            # Proxy only: assumed round-trip cost 0.20%; not measured from exchange.
            gross=100*direction*(exit_price/p-1)
            events.append((t,group,state,gross,gross-0.20))
    events.sort()
    cutoff=int(len(events)*0.7)
    result={"method":"4-snapshot forward proxy; 12h max; assumed 0.20% round-trip costs; overlapping events",
            "rows_read":len(rows),"eligible_events":len(events),"split":"chronological 70/30 across all events",
            "limits":"NOT an OHLCV stop/target backtest; no slippage model, no independent events, no live execution authorization",
            "groups":{}}
    for partition,subset in (("development",events[:cutoff]),("out_of_sample",events[cutoff:])):
        for group in sorted(set(e[1] for e in subset)):
            for state in STATES:
                values=[e for e in subset if e[1]==group and e[2]==state]
                if not values: continue
                gross=sum(e[3] for e in values)/len(values)
                net=sum(e[4] for e in values)/len(values)
                result["groups"].setdefault(partition,[]).append({"asset_group":group,"state":state,"n":len(values),
                    "win_pct":round(100*sum(e[3]>0 for e in values)/len(values),1),
                    "mean_gross_pct":round(gross,3),"mean_cost_adjusted_pct":round(net,3)})
    # Conservative promotion gate: no promotion is ever authorized by this proxy audit.
    result["production_promotion_allowed"]=False
    return result

if __name__=="__main__":
    result=audit(fetch())
    print(json.dumps(result,indent=2,ensure_ascii=False))
