"""Conservative daily cross-asset decision board. No invented prices or levels."""
from datetime import datetime, timezone

GROUPS = (
    ("IRAN EQUITIES / FUNDS", ("TSE", "TEPIX", "STOCKS", "EQUITY", "FUND", "ETF")),
    ("METALS", ("XAU", "XAG", "XCU", "GOLD", "SILVER", "COPPER")),
    ("USD / USDT IRAN", ("USD", "USDT", "USD_IRR", "USD_TOMAN", "USDT_IRR")),
)
def _group(symbol):
    name=str(symbol or "").upper().strip()
    for label, terms in GROUPS:
        if name in terms: return label
    return None

def summarize(rows):
    """Unverified and missing markets stay DATA UNAVAILABLE, never BUY."""
    grouped={label:[] for label,_ in GROUPS}
    for r in rows or []:
        if not isinstance(r,dict): continue
        symbol=str(r.get("symbol") or r.get("coin") or "").upper().strip()
        group=_group(symbol)
        if not group: continue
        decision=str(r.get("decision") or r.get("action") or "WAIT").upper()
        verified=r.get("market_data_verified") is True and r.get("signal_verified") is True
        action=decision if verified and decision in ("BUY","ACCUMULATE","HOLD","WAIT","REDUCE","SELL") else "WAIT"
        grouped[group].append(dict(symbol=symbol,action=action,reason="Verified canonical decision" if verified else "Data or canonical decision unverified"))
    return grouped

def render_png(groups, filename="atlas_iran_daily_decisions.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(14,9))
    fig.patch.set_facecolor("#101b2c");ax.set_facecolor("#101b2c");ax.axis("off")
    ax.text(.04,.95,"ATLAS | IRAN DAILY DECISION BOARD",color="white",fontsize=20,weight="bold",transform=ax.transAxes)
    ax.text(.04,.905,datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")+" | Verification-first | Not an order",color="#b4c6d8",fontsize=10,transform=ax.transAxes)
    y=.82
    for title,terms in GROUPS:
        ax.text(.04,y,title,color="#7dc3ff",fontsize=14,weight="bold",transform=ax.transAxes)
        y-=.06
        items=groups.get(title,[])
        if not items:
            ax.text(.06,y,"DATA UNAVAILABLE - no verified canonical market decision",color="#eac88b",fontsize=10,transform=ax.transAxes)
            y-=.07
        else:
            for item in items[:5]:
                ax.text(.06,y,f'{item["symbol"]}: {item["action"]} | {item["reason"]}',color="#e7edf5",fontsize=10,transform=ax.transAxes)
                y-=.055
        y-=.09
    ax.text(.04,.035,"No levels or trade advice when prices, timestamps or confirmations are missing.",color="#b4c6d8",fontsize=9,transform=ax.transAxes)
    fig.savefig(filename,dpi=160,bbox_inches="tight",facecolor=fig.get_facecolor())
    plt.close(fig)
    return filename
