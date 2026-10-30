"""ATLAS read-only futures opportunity board. No synthetic trade levels."""
import math
from datetime import datetime, timezone

def _num(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except (TypeError,ValueError):
        return None

def select_five(rows, capital=2000.0, risk_pct=1.0, max_leverage=3.0):
    """Five ranked opportunities, not a promise of five executable trades."""
    selected=[]
    for r in rows or []:
        if not isinstance(r,dict): continue
        symbol=str(r.get("coin") or r.get("symbol") or "").upper().strip()
        if not symbol or symbol in ("XAU","XAG","XCU","GOLD","SILVER","COPPER"): continue
        action=str(r.get("decision") or r.get("action") or "").upper()
        direction="LONG" if action in ("BUY","ACCUMULATE") else "SHORT" if action in ("SELL","REDUCE") else "WAIT"
        entry=_num(r.get("entry")); sl=_num(r.get("sl"))
        tp1=_num(r.get("tp1")); tp2=_num(r.get("tp2"))
        confidence=_num(r.get("decision_confidence")) or _num(r.get("confidence")) or 0
        executable=r.get("executable") is True and action in ("BUY","SELL")
        valid=(direction!="WAIT" and executable and all(v is not None and v>0 for v in (entry,sl,tp1,tp2))
               and ((sl<entry<tp1<=tp2) if direction=="LONG" else (tp2<=tp1<entry<sl)))
        rr=(abs(tp1-entry)/abs(entry-sl)) if valid else None
        if valid and rr<2: valid=False
        # Unknown perpetual-market venue, liquidity or funding fails closed.
        if not (r.get("futures_venue_verified") is True
                and r.get("futures_liquidity_verified") is True
                and r.get("futures_funding_verified") is True):
            valid=False
        lev=min(max(1.0,float(max_leverage)),3.0)
        risk_usd=max(0.0,float(capital))*max(0.0,float(risk_pct))/100.0
        qty=(risk_usd/abs(entry-sl)) if valid else None
        notional=(qty*entry) if valid else None
        if valid and notional>float(capital)*lev:
            qty=float(capital)*lev/entry
            notional=qty*entry
            risk_usd=qty*abs(entry-sl)
        selected.append(dict(symbol=symbol,side=direction if valid else "WAIT",state="VALID" if valid else "NOT_CONFIRMED",
            entry=entry if valid else None,sl=sl if valid else None,tp1=tp1 if valid else None,tp2=tp2 if valid else None,
            rr=rr if valid else None,confidence=confidence,leverage=lev if valid else None,
            risk_usd=risk_usd if valid else None,notional_usd=notional if valid else None,
            reason="Canonical + verified futures market + RR>=2" if valid else "WAIT: canonical plan, RR, venue, liquidity or funding not verified"))
    selected.sort(key=lambda x:(x["state"]!="VALID",-x["confidence"],x["symbol"]))
    from atlas_conditional_opportunities import discover
    conditional=discover(rows,limit=5)
    # Conditional direction is visible, but cannot be mistaken for a trade order.
    by_symbol={p["symbol"]:p for p in conditional if p["state"]=="CONDITIONAL"}
    for item in selected:
        if item["state"]=="VALID": continue
        watch=by_symbol.get(item["symbol"])
        if watch:
            item["side"]=watch["side"]
            item["state"]="CONDITIONAL"
            item["reason"]="CONDITIONAL "+watch["side"]+" watch only; trigger requires confirmation"
            item["trigger"]=watch["trigger"]
    selected.sort(key=lambda x:({"VALID":0,"CONDITIONAL":1}.get(x["state"],2),-x["confidence"],x["symbol"]))
    return selected[:5]

def render_png(picks, filename="atlas_futures_top5.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(15,8.8))
    fig.patch.set_facecolor("#0b1726");ax.set_facecolor("#0b1726");ax.axis("off")
    ax.text(.035,.95,"ATLAS  |  TOP 5 FUTURES OPPORTUNITIES",color="white",fontsize=20,weight="bold",transform=ax.transAxes)
    ax.text(.035,.905,datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")+"  |  Research decision board, not automatic orders",color="#a6b9cb",fontsize=10,transform=ax.transAxes)
    for i,p in enumerate(picks[:5]):
        y=.81-i*.155
        color="#54d3a4" if p["state"]=="VALID" and p["side"]=="LONG" else "#f4a0a0" if p["state"]=="VALID" else "#f3ca79"
        ax.text(.04,y,f'{i+1}. {p["symbol"]}   {p["side"]}   |   Confidence {p["confidence"]:.0f}%',color=color,fontsize=14,weight="bold",transform=ax.transAxes)
        if p["state"]=="VALID":
            line=f'Entry {p["entry"]:.8g}   SL {p["sl"]:.8g}   TP1 {p["tp1"]:.8g}   TP2 {p["tp2"]:.8g}   RR {p["rr"]:.2f}'
            extra=f'Leverage <= {p["leverage"]:.1f}x   Risk <= ${p["risk_usd"]:.2f}   Notional <= ${p["notional_usd"]:.2f}'
        else:
            line=("CONDITIONAL "+p["side"]+" | watch trigger "+format(p["trigger"],".8g")+" | NOT AN ORDER") if p["state"]=="CONDITIONAL" else "WAIT / NO TRADE - no verified actionable levels"
            extra=p["reason"]
        ax.text(.055,y-.043,line,color="#e2eaf1",fontsize=10.3,transform=ax.transAxes)
        ax.text(.055,y-.082,extra,color="#9eb3c8",fontsize=9.6,transform=ax.transAxes)
    if not picks:ax.text(.04,.65,"No candidates with reliable market data.",color="#f3ca79",fontsize=14,transform=ax.transAxes)
    ax.text(.035,.035,"Five ranked slots are not five guaranteed trades. Verify exchange liquidity, funding and liquidation before execution.",color="#a6b9cb",fontsize=9,transform=ax.transAxes)
    fig.savefig(filename,dpi=170,bbox_inches="tight",facecolor=fig.get_facecolor())
    plt.close(fig)
    return filename
