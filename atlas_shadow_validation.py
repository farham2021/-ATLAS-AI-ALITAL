"""ATLAS read-only forward-return research gate (shadow only).
No order placement, no Telegram delivery, no DB writes.
Measures four future observations within 12 hours; not a trading P&L backtest.
"""
import json, os, urllib.request
from collections import defaultdict

TABLE="atlas_hourly_signal_snapshots"
DIRECTIONS={"BUY CONFIRMATION":1,"SELL CONFIRMATION":-1,
            "BULLISH WATCH":1,"BEARISH WATCH":-1}
def assess(rows):
    by_symbol=defaultdict(list)
    for r in rows:
        if r.get("symbol") and r.get("captured_at") and isinstance(r.get("price"),(int,float)) and r["price"]>0:
            by_symbol[r["symbol"]].append(r)
    grouped=defaultdict(list)
    from datetime import datetime,timezone
    def dt(s): return datetime.fromisoformat(s.replace("Z","+00:00"))
    for symbol,rs in by_symbol.items():
        rs.sort(key=lambda r:r["captured_at"])
        for i,r in enumerate(rs):
            direction=DIRECTIONS.get(r.get("decision_state"))
            if direction is None or i+4>=len(rs):continue
            later=rs[i+4]
            hours=(dt(later["captured_at"])-dt(r["captured_at"])).total_seconds()/3600
            if not 0<hours<=12:continue
            ret=direction*(later["price"]/r["price"]-1)*100
            grouped[r["decision_state"]].append(ret)
    out={}
    for state,returns in sorted(grouped.items()):
        out[state]={"matched":len(returns),"directional_win_pct":round(100*sum(v>0 for v in returns)/len(returns),1),
                    "mean_directional_return_pct":round(sum(returns)/len(returns),3)}
    return out

def main():
    url=os.environ.get("SUPABASE_URL","").rstrip("/")
    key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")
    if not url.startswith("https://") or not key:raise SystemExit("Missing Supabase configuration")
    # bounded historical sample; paginate to avoid PostgREST max_rows truncation
    rows=[]
    for start in range(0,12000,1000):
        req=urllib.request.Request(f"{url}/rest/v1/{TABLE}?select=symbol,captured_at,price,decision_state&order=captured_at.desc&limit=1000&offset={start}",
            headers={"apikey":key,"Authorization":"Bearer "+key})
        with urllib.request.urlopen(req,timeout=30) as resp: batch=json.load(resp)
        rows.extend(batch)
        if len(batch)<1000:break
    print("ATLAS SHADOW ONLY | no trade authorization | rows:",len(rows))
    print(json.dumps(assess(rows),ensure_ascii=False,indent=2))
    print("LIMITATIONS: overlapping samples, snapshot-based 4-step horizon, no spread/slippage/fees/stop-loss, not walk-forward validated.")
if __name__=="__main__":main()
