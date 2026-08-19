import os
import time
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

import ccxt

# ============================================================
# ATLAS AI v8 — SIGNAL MEMORY + GOOGLE SHEETS + PRE-CHECK
# ============================================================
# v8 adds:
# - Google Sheets persistent signal journal
# - 30-minute pre-signal verification run
# - Previous SIGNAL comparison by coin
# - Alignment / divergence assessment before a new signal
# - Main SIGNAL rows + PRECHECK rows stored in Sheets
# - Telegram pre-check summary
# - No order execution
#
# GitHub Actions should run this file in two modes:
#   RUN_MODE=PRECHECK  -> 30 min before signal
#   RUN_MODE=SIGNAL    -> actual signal time
# ============================================================

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
GOOGLE_SHEETS_SECRET = os.environ.get("GOOGLE_SHEETS_SECRET", "").strip()
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
CMC_API_KEY = os.environ.get("CMC_API_KEY", "").strip()
CRYPTOPANIC_TOKEN = os.environ.get("CRYPTOPANIC_TOKEN", "").strip()
RUN_MODE = os.environ.get("RUN_MODE", "SIGNAL").strip().upper()

TEHRAN = ZoneInfo("Asia/Tehran")
TIMEFRAME = "4h"
RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE_PCT", "0.75"))
MAX_PORTFOLIO_RISK = float(os.environ.get("MAX_PORTFOLIO_OPEN_RISK_PCT", "3.0"))

STATIC = [
    "BTC","ETH","XRP","SOL","BNB","TON","ADA","DOGE","TRX","LINK",
    "XLM","SUI","AVAX","LTC","SHIB","HBAR","DOT","BCH","XMR","NEAR",
    "QNT","GRT","TAO","ONDO","UNI","ETHFI","ATOM","FIL","AAVE","MKR",
    "APT","ARB","OP","INJ","TIA","SEI","PEPE","FET","ICP","ETC",
]

# ---------------- HTTP ----------------
def http_get(url, timeout=12, headers=None):
    h = {"User-Agent":"ATLAS-AI/8.0","Accept":"application/json,application/xml,text/xml,*/*"}
    if headers: h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        ct = (r.headers.get("Content-Type") or "").lower()
        if raw.lstrip().startswith("<") or "xml" in ct:
            return ET.fromstring(raw)
        return json.loads(raw)

def http_post_json(url, payload, timeout=15):
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=raw,
        headers={"Content-Type":"application/json","User-Agent":"ATLAS-AI/8.0"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def f(x):
    try: return float(x)
    except Exception: return None

def fmt(x):
    if x is None: return "N/A"
    if x >= 1000: return f"${x:,.2f}"
    if x >= 1: return f"${x:,.4f}"
    return f"${x:,.6f}"

def spread(a,b):
    if a is None or b is None or a == 0 or b == 0: return None
    return abs(a-b)/((abs(a)+abs(b))/2)*100

# ---------------- CCXT ----------------
def make_exchange(exchange_id):
    cls = getattr(ccxt, exchange_id)
    return cls({"enableRateLimit": True, "timeout": 15000})

EX = {}
for eid in ("binance","xt","lbank"):
    try: EX[eid] = make_exchange(eid)
    except Exception: pass

MARKETS = {}
for eid, ex in EX.items():
    try: MARKETS[eid] = ex.load_markets()
    except Exception: MARKETS[eid] = {}

def symbol_for(eid, coin):
    markets = MARKETS.get(eid,{})
    for s in (f"{coin}/USDT", f"{coin}/USDT:USDT"):
        if s in markets: return s
    return None

def exchange_ticker(eid, coin):
    ex = EX[eid]; sym = symbol_for(eid, coin)
    if not sym: raise RuntimeError(f"{eid}: pair unavailable")
    t = ex.fetch_ticker(sym)
    return {"source":eid.upper(),"price":f(t.get("last")),"change":f(t.get("percentage")),"quoteVolume":f(t.get("quoteVolume"))}

def exchange_ohlcv(eid, coin):
    ex = EX[eid]; sym = symbol_for(eid, coin)
    if not sym: raise RuntimeError(f"{eid}: 4H pair unavailable")
    rows = ex.fetch_ohlcv(sym, timeframe=TIMEFRAME, limit=120)
    if len(rows) < 60: raise RuntimeError(f"{eid}: insufficient 4H candles")
    now = int(time.time()*1000)
    if rows and rows[-1][0] + 4*60*60*1000 > now: rows = rows[:-1]
    return rows

# ---------------- external validation ----------------
def gecko_markets():
    headers={}
    if COINGECKO_API_KEY: headers["x-cg-demo-api-key"]=COINGECKO_API_KEY
    url="https://api.coingecko.com/api/v3/coins/markets?"+urllib.parse.urlencode({"vs_currency":"usd","order":"market_cap_desc","per_page":"30","page":"1","sparkline":"false"})
    try: return http_get(url,headers=headers)
    except Exception: return []

def paprika_slug(coin):
    return {
        "BTC":"btc-bitcoin","ETH":"eth-ethereum","XRP":"xrp-xrp","SOL":"sol-solana","BNB":"bnb-binance-coin",
        "TON":"ton-toncoin","ADA":"ada-cardano","DOGE":"doge-dogecoin","TRX":"trx-tron","LINK":"link-chainlink",
        "SUI":"sui-sui","AVAX":"avax-avalanche","LTC":"ltc-litecoin","DOT":"dot-polkadot","NEAR":"near-near-protocol",
        "TAO":"tao-bittensor","ONDO":"ondo-ondo-finance","UNI":"uni-uniswap","ETHFI":"ethfi-ether-fi",
    }.get(coin)

def paprika_price(coin):
    slug=paprika_slug(coin)
    if not slug: raise RuntimeError("Paprika slug unavailable")
    d=http_get("https://api.coinpaprika.com/v1/tickers/"+slug)
    p=f(d.get("quotes",{}).get("USD",{}).get("price"))
    if p is None: raise RuntimeError("CoinPaprika unavailable")
    return p

def cmc_price(coin):
    if not CMC_API_KEY: raise RuntimeError("CMC key not configured")
    d=http_get("https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?"+urllib.parse.urlencode({"symbol":coin,"convert":"USD"}),headers={"X-CMC_PRO_API_KEY":CMC_API_KEY})
    x=d.get("data",{}).get(coin)
    if isinstance(x,list): x=x[0] if x else None
    p=f((x or {}).get("quote",{}).get("USD",{}).get("price"))
    if p is None: raise RuntimeError("CMC unavailable")
    return p

def price_consensus(coin):
    vals=[];sources=[];errors=[]
    for eid in EX:
        try:
            x=exchange_ticker(eid,coin)
            if x["price"] is not None: vals.append(x["price"]);sources.append(x)
        except Exception as e: errors.append(str(e))
    try:
        rows=gecko_markets(); gx=next((x for x in rows if (x.get("symbol") or "").upper()==coin),None)
        if gx and f(gx.get("current_price")):
            vals.append(f(gx["current_price"]));sources.append({"source":"CoinGecko","price":f(gx["current_price"])})
    except Exception as e: errors.append("CoinGecko: "+str(e))
    try:
        p=paprika_price(coin);vals.append(p);sources.append({"source":"CoinPaprika","price":p})
    except Exception: pass
    if CMC_API_KEY:
        try:
            p=cmc_price(coin);vals.append(p);sources.append({"source":"CMC","price":p})
        except Exception: pass
    if not vals: raise RuntimeError("NO PRICE DATA")
    med=sorted(vals)[len(vals)//2]
    sp=max([(spread(x,med) or 0) for x in vals],default=0)
    quality="HIGH" if len(vals)>=4 and sp<=1.5 else "MEDIUM" if len(vals)>=3 and sp<=3 else "LOW"
    return med,sources,quality,sp,errors

# ---------------- indicators ----------------
def ema(v,n):
    if len(v)<n:return None
    a=2/(n+1);e=sum(v[:n])/n
    for x in v[n:]: e=(x-e)*a+e
    return e

def rsi(v,n=14):
    if len(v)<=n:return None
    g=[];l=[]
    for i in range(1,len(v)):
        d=v[i]-v[i-1];g.append(max(d,0));l.append(max(-d,0))
    ag=sum(g[:n])/n;al=sum(l[:n])/n
    for i in range(n,len(g)):
        ag=((n-1)*ag+g[i])/n;al=((n-1)*al+l[i])/n
    return 100 if al==0 else 100-100/(1+ag/al)

def macd(v):
    vals=[]
    for i in range(26,len(v)+1):
        a=ema(v[:i],12);b=ema(v[:i],26)
        if a is not None and b is not None: vals.append(a-b)
    if len(vals)<9:return None,None
    return vals[-1],ema(vals,9)

def atr(rows,n=14):
    if len(rows)<n+1:return None
    tr=[]
    for i in range(1,len(rows)):
        h,l,pc=rows[i][2],rows[i][3],rows[i-1][4]
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(tr[-n:])/n

def vol_state(rows):
    vols=[f(x[5]) for x in rows if f(x[5]) is not None]
    if len(vols)<21:return "UNKNOWN",0
    avg=sum(vols[-21:-1])/20;ratio=vols[-1]/avg if avg else 0
    return ("STRONG",ratio) if ratio>=1.35 else ("WEAK",ratio) if ratio<=.75 else ("NORMAL",ratio)

# ---------------- context / news ----------------
def context():
    out={}
    try:
        d=http_get("https://api.alternative.me/fng/?limit=1");x=d["data"][0];out["fg"]=f(x["value"]);out["fg_label"]=x["value_classification"]
    except Exception: pass
    try:
        d=http_get("https://api.coingecko.com/api/v3/global");out["btc_dom"]=f(d["data"]["market_cap_percentage"]["btc"])
    except Exception: pass
    try:
        d=http_get("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1");out["funding"]=f(d[-1]["fundingRate"])
    except Exception: pass
    try:
        d=http_get("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT");out["oi"]=f(d["openInterest"])
    except Exception: pass
    return out

RSS=["https://www.coindesk.com/arc/outboundfeeds/rss/","https://cointelegraph.com/rss","https://www.theblock.co/rss.xml"]
def news():
    items=[]
    for url in RSS:
        try:
            root=http_get(url,timeout=10)
            for x in root.findall(".//item")[:5]:
                title=(x.findtext("title") or "").strip()
                if title: items.append(title)
        except Exception: pass
    if CRYPTOPANIC_TOKEN:
        try:
            d=http_get("https://cryptopanic.com/api/developer/v2/posts/?"+urllib.parse.urlencode({"auth_token":CRYPTOPANIC_TOKEN,"public":"true","kind":"news","regions":"en","limit":"10"}))
            items += [x.get("title","") for x in d.get("results",[])]
        except Exception: pass
    neg=("hack","exploit","lawsuit","ban","delist","liquidation","fraud","sec","investigation","outflow","stolen","sanction","war","attack")
    pos=("approval","approved","etf","inflow","partnership","launch","adoption","upgrade","listing","integration","record","institutional")
    score=0
    for t in items:
        tl=t.lower();score += sum(1 for w in pos if w in tl);score -= sum(1 for w in neg if w in tl)
    label="NEGATIVE" if score<=-3 else "POSITIVE" if score>=3 else "MIXED/LIMITED"
    return label,items[:8]

def btc_regime():
    try:
        rows=exchange_ohlcv("binance","BTC");c=[f(x[4]) for x in rows];e20,e50=ema(c,20),ema(c,50);rr=rsi(c)
        s=(2 if c[-1]>e20 else -2)+(2 if c[-1]>e50 else -2)+(2 if e20>e50 else -2)+(1 if rr and rr>=50 else -1)
        return ("BULLISH" if s>=4 else "BEARISH" if s<=-4 else "NEUTRAL"),s
    except Exception:return "UNKNOWN",0

# ---------------- analysis ----------------
def analyze(coin,regime):
    price,sources,quality,sp,errors=price_consensus(coin)
    rows=None;engine=None
    for eid in ("binance","xt","lbank"):
        try: rows=exchange_ohlcv(eid,coin);engine=eid.upper();break
        except Exception: pass
    if not rows: raise RuntimeError("4H DATA UNAVAILABLE")
    c=[f(x[4]) for x in rows];e20,e50=ema(c,20),ema(c,50);rr=rsi(c);ml,ms=macd(c);av=atr(rows);vs,vr=vol_state(rows)
    sup=min(f(x[3]) for x in rows[-30:]);res=max(f(x[2]) for x in rows[-30:])
    score=(2 if price>e20 else -2)+(2 if price>e50 else -2)+(2 if e20>e50 else -2)
    if rr is not None: score += 2 if 52<=rr<68 else 1 if 68<=rr<75 else -1 if rr<48 else -1
    if ml is not None and ms is not None: score += 2 if ml>ms and ml>0 else 1 if ml>ms else -2 if ml<ms and ml<0 else -1
    score += 1 if vs=="STRONG" else -1 if vs=="WEAK" else 0
    if coin!="BTC": score += 1 if regime=="BULLISH" else -1 if regime=="BEARISH" else 0
    conf=max(25,min(92,50+abs(score)*3+(8 if quality=="HIGH" else -3 if quality=="MEDIUM" else -15)))
    long_ok=score>=9 and quality!="LOW" and vs!="WEAK" and rr is not None and rr<72
    short_ok=score<=-9 and quality!="LOW" and rr is not None and rr>28
    if long_ok: action="BUY CONFIRMATION";direction="LONG"
    elif short_ok: action="SHORT CONFIRMATION";direction="SHORT"
    elif score>=6: action="BULLISH WATCH";direction="WATCH_LONG"
    elif score<=-6: action="SELL WATCH";direction="WATCH_SHORT"
    else: action="NO TRADE";direction="NONE"
    if quality=="LOW": action="NO TRADE";direction="NONE"
    entry=sl=tp1=tp2=None
    if direction=="LONG":
        entry=max(price,res*1.002);sl=min(sup*.995,entry-1.5*(av or entry*.03));risk=max(entry-sl,entry*.005);tp1=entry+2*risk;tp2=entry+3*risk
    elif direction=="SHORT":
        entry=min(price,sup*.998);sl=max(res*1.005,entry+1.5*(av or entry*.03));risk=max(sl-entry,entry*.005);tp1=entry-2*risk;tp2=entry-3*risk
    return {"coin":coin,"price":price,"change":next((x.get("change") for x in sources if x["source"]=="BINANCE"),None),"trend":"BULLISH" if price>e20 and e20>e50 else "BEARISH" if price<e20 and e20<e50 else "MIXED","rsi":rr,"macd":"BULLISH" if ml is not None and ms is not None and ml>ms else "BEARISH","volume":vs,"score":score,"confidence":int(conf),"support":sup,"resistance":res,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"action":action,"direction":direction,"quality":quality,"spread":sp,"sources":[x["source"] for x in sources],"engine":engine}

# ---------------- Google Sheets signal memory ----------------
def sheets_call(payload):
    if not GOOGLE_SHEETS_WEBHOOK_URL or not GOOGLE_SHEETS_SECRET: return {"ok":False,"disabled":True}
    p=dict(payload);p["secret"]=GOOGLE_SHEETS_SECRET
    try: return http_post_json(GOOGLE_SHEETS_WEBHOOK_URL,p,timeout=15)
    except Exception as e: return {"ok":False,"error":str(e)}

def previous_signal(coin):
    r=sheets_call({"action":"get_previous","coin":coin})
    if r.get("ok") and r.get("found"): return r.get("row") or {}
    return None

def direction_of(action):
    if not action: return "NONE"
    a=str(action).upper()
    if "BUY" in a or "BULLISH" in a: return "LONG"
    if "SHORT" in a or "SELL" in a: return "SHORT"
    return "NONE"

def compare_signal(current, previous):
    if not previous: return {"alignment":"NO_PREVIOUS_SIGNAL","note":"First stored signal for this coin."}
    pa=str(previous.get("action", "")); ps=f(previous.get("score")); pc=f(previous.get("confidence"))
    cd=direction_of(current["action"]); pd=direction_of(pa)
    if cd==pd and cd!="NONE": alignment="ALIGNED"
    elif cd!="NONE" and pd!="NONE" and cd!=pd: alignment="CONTRADICTED"
    else: alignment="NEUTRAL/UNCHANGED"
    score_delta=current["score"]-(ps or 0)
    if alignment=="ALIGNED" and ((cd=="LONG" and score_delta>=0) or (cd=="SHORT" and score_delta<=0)):
        note="Trend and prior signal remain aligned."
    elif alignment=="CONTRADICTED":
        note="New signal conflicts with the previous stored signal: confirmation required."
    else:
        note="Signal changed or remains neutral; avoid treating it as confirmation by itself."
    return {"alignment":alignment,"note":note,"previous_action":pa,"previous_score":ps,"previous_confidence":pc,"score_delta":score_delta}

def apply_confirmation_gate(r, cmp, regime):
    """Protect the official signal when the pre-check/history disagrees with it."""
    original = r["action"]
    d = direction_of(original)
    blocked = False
    reason = []

    if r["quality"] == "LOW":
        blocked = True; reason.append("low data quality")
    if r["spread"] is not None and r["spread"] > 3:
        blocked = True; reason.append("price conflict >3%")
    if cmp.get("alignment") == "CONTRADICTED":
        blocked = True; reason.append("previous SIGNAL contradicted")
    if d == "LONG":
        if r["trend"] != "BULLISH":
            blocked = True; reason.append("trend not bullish")
        if regime == "BEARISH":
            blocked = True; reason.append("BTC regime bearish")
    elif d == "SHORT":
        if r["trend"] != "BEARISH":
            blocked = True; reason.append("trend not bearish")
        if regime == "BULLISH":
            blocked = True; reason.append("BTC regime bullish")

    if blocked and original == "BUY CONFIRMATION":
        r["action"] = "BULLISH WATCH"
        r["direction"] = "WATCH_LONG"
    elif blocked and original == "SHORT CONFIRMATION":
        r["action"] = "SELL WATCH"
        r["direction"] = "WATCH_SHORT"

    if blocked:
        r["gate"] = "BLOCKED"
        r["gate_reason"] = "; ".join(reason)
    else:
        r["gate"] = "PASSED"
        r["gate_reason"] = "Trend, BTC regime, data quality and previous-signal check passed."
    r["raw_action"] = original
    return r

def row_for_sheet(r,run_type,regime,news_bias,cmp):
    return {
        "timestamp":datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M:%S"),"run_type":run_type,"coin":r["coin"],"action":r["action"],"direction":direction_of(r["action"]),"score":r["score"],"confidence":r["confidence"],"price":r["price"],"trend":r["trend"],"rsi":r["rsi"],"macd":r["macd"],"volume":r["volume"],"support":r["support"],"resistance":r["resistance"],"entry":r["entry"],"sl":r["sl"],"tp1":r["tp1"],"tp2":r["tp2"],"data_quality":r["quality"],"spread_pct":r["spread"],"exchanges":",".join(r["sources"]),"btc_regime":regime,"news_bias":news_bias,"previous_action":cmp.get("previous_action",""),"previous_score":cmp.get("previous_score",""),"previous_confidence":cmp.get("previous_confidence",""),"alignment":cmp.get("alignment",""),"notes":(cmp.get("note","") + " | Gate: " + r.get("gate","N/A") + " | " + r.get("gate_reason",""))
    }

# ---------------- build analysis set ----------------
def universe():
    dynamic=gecko_markets()
    u=list(dict.fromkeys(STATIC+[(x.get("symbol") or "").upper() for x in dynamic]))
    return [x for x in u if x and x not in {"USDT","USDC"}][:50]

def run_analysis():
    regime,_=btc_regime();ctx=context();news_bias,_=news();results=[];failed=0
    for coin in universe():
        try: results.append(analyze(coin,regime))
        except Exception: failed+=1
        time.sleep(.08)
    results.sort(key=lambda x:(x["action"] in ("BUY CONFIRMATION","SHORT CONFIRMATION"),x["confidence"],abs(x["score"])),reverse=True)
    return results,failed,regime,ctx,news_bias

# ---------------- Telegram report ----------------
def build_report(results,failed,regime,ctx,news_bias,mode,comparisons=None):
    now=datetime.now(TEHRAN)
    L=["🤖 ATLAS AI — SNIPER v8","━━━━━━━━━━━━━━━━━━",now.strftime("%Y/%m/%d  %H:%M")+" 🇮🇷","Timeframe: 4H","",f"🌎 BTC REGIME: {'🟢' if regime=='BULLISH' else '🔴' if regime=='BEARISH' else '🟡'} {regime}"]
    if ctx.get("fg") is not None:L.append(f"😨 Fear & Greed: {ctx['fg']:.0f} — {ctx.get('fg_label','')}")
    if ctx.get("btc_dom") is not None:L.append(f"₿ BTC Dominance: {ctx['btc_dom']:.2f}%")
    if ctx.get("funding") is not None:L.append(f"BTC Funding: {ctx['funding']*100:.4f}%")
    L += [f"📰 NEWS: {news_bias}",f"⏱️ RUN MODE: {mode}",""]
    if mode=="PRECHECK":
        L += ["🛡️ 30-MINUTE PRE-SIGNAL CHECK","Comparing current market structure with the previous stored SIGNAL.",""]
    for r in results:
        cmp=(comparisons or {}).get(r["coin"],{})
        L += [f"🔹 {r['coin']}",f"Price: {fmt(r['price'])}",f"Trend: {'🟢' if r['trend']=='BULLISH' else '🔴' if r['trend']=='BEARISH' else '🟡'} {r['trend']}",f"RSI14: {r['rsi']:.1f}" if r["rsi"] is not None else "RSI14: N/A",f"MACD: {'🟢' if r['macd']=='BULLISH' else '🔴'} {r['macd']}",f"Volume: {r['volume']}",f"4H Score: {r['score']:+d}",f"Confidence: {r['confidence']}%",f"🎯 ACTION: {r['action']}",f"Data: {r['quality']}"]
        if mode=="PRECHECK":
            L.append(f"🔎 PRECHECK: {cmp.get('alignment','NO_PREVIOUS_SIGNAL')}")
            if cmp.get("previous_action"): L.append(f"Previous: {cmp['previous_action']} | ΔScore: {cmp.get('score_delta',0):+.0f}")
            L.append(f"Check: {cmp.get('note','')}")
        if r["spread"]>3:L.append(f"⚠️ DATA CONFLICT: {r['spread']:.2f}%")
        L.append("")
    L += ["━━━━━━━━━━━━━━━━━━"]
    if mode=="PRECHECK":
        aligned=sum(1 for c in (comparisons or {}).values() if c.get("alignment")=="ALIGNED")
        contrad=sum(1 for c in (comparisons or {}).values() if c.get("alignment")=="CONTRADICTED")
        L += [f"🧭 PRECHECK RESULT: ALIGNED {aligned} | CONTRADICTED {contrad}","If a new signal contradicts the previous signal, ATLAS will require confirmation rather than treating the change as a clean continuation."]
    else:
        picks=[r for r in results if r["action"] in ("BUY CONFIRMATION","SHORT CONFIRMATION")]
        L += ["🏆 TOP OPPORTUNITIES"]
        if picks:
            for i,r in enumerate(picks[:8],1): L.append(f"{i}. {'🟢' if r['action'].startswith('BUY') else '🔴'} {r['coin']} — {r['action']} — {r['confidence']}%")
        else: L.append("⛔ No high-quality actionable setup.")
    L += ["","🛡️ ATLAS CAPITAL PROTECTION",f"Risk cap/trade: {RISK_PER_TRADE:.2f}%",f"Max portfolio open risk: {MAX_PORTFOLIO_RISK:.2f}%","No automatic orders. No leverage by default.","", "📡 DATA ENGINE",f"Assets scanned: {len(universe())} | Successful: {len(results)} | Unavailable: {failed}","Incomplete 4H candles excluded.","Conflicting/low-quality data => NO TRADE.","",f"🎯 ATLAS SNIPER v8: {mode}","", "⚠️ هدف 3x تضمین‌شدنی نیست؛ اولویت ATLAS حفظ سرمایه و شکار معاملات با نسبت ریسک/بازده مناسب است."]
    text="\n".join(L)
    return text[:3950]+"\n\n⚠️ Telegram length protection." if len(text)>4000 else text

def send(text):
    if not TOKEN or not CHAT_ID: raise RuntimeError("Telegram secrets missing")
    data=urllib.parse.urlencode({"chat_id":CHAT_ID,"text":text}).encode()
    req=urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",data=data,headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req,timeout=20) as r:return r.read()

# ---------------- main ----------------
def main():
    results,failed,regime,ctx,news_bias=run_analysis()
    comparisons={}
    for r in results:
        prev=previous_signal(r["coin"])
        comparisons[r["coin"]]=compare_signal(r,prev)
    # Persist PRECHECK rows but do not make them the official previous SIGNAL.
    if RUN_MODE=="PRECHECK":
        rows=[row_for_sheet(r,"PRECHECK",regime,news_bias,comparisons[r["coin"]]) for r in results]
        sheets_call({"action":"append_batch","rows":rows})
        text=build_report(results,failed,regime,ctx,news_bias,"PRECHECK",comparisons)
        send(text)
        print(text);return 0

    # Official signal run: apply the confirmation gate using the 30-minute/history check.
    for r in results:
        apply_confirmation_gate(r, comparisons[r["coin"]], regime)

    rows=[row_for_sheet(r,"SIGNAL",regime,news_bias,comparisons[r["coin"]]) for r in results]
    sheets_call({"action":"append_batch","rows":rows})
    text=build_report(results,failed,regime,ctx,news_bias,"SIGNAL",comparisons)
    send(text);print(text);return 0

if __name__=="__main__": raise SystemExit(main())
