import os
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

import ccxt

# ============================================================
# ATLAS AI v7 — Multi-Exchange Decision Engine
# Binance + XT + LBank via CCXT
# CoinGecko + CoinPaprika + optional CMC validation
# Binance Futures: funding / OI
# Fear & Greed + RSS/CryptoPanic news
# No order execution. Analysis only.
#
# IMPORTANT:
# A 3x return in one year is a goal, NOT a guarantee.
# This engine prioritizes asymmetric setups and capital protection.
# ============================================================

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
CMC_API_KEY = os.environ.get("CMC_API_KEY", "").strip()
CRYPTOPANIC_TOKEN = os.environ.get("CRYPTOPANIC_TOKEN", "").strip()

TEHRAN = ZoneInfo("Asia/Tehran")
TIMEFRAME = "4h"

# Capital-protection defaults
RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE_PCT", "0.75"))
MAX_PORTFOLIO_RISK = float(os.environ.get("MAX_PORTFOLIO_OPEN_RISK_PCT", "3.0"))

# The static radar contains the user's important assets.
# Dynamic top-30 adds market-cap leaders that are not already here.
STATIC = [
    "BTC","ETH","XRP","SOL","BNB","TON","ADA","DOGE","TRX","LINK",
    "XLM","SUI","AVAX","LTC","SHIB","HBAR","DOT","BCH","XMR","NEAR",
    "QNT","GRT","TAO","ONDO","UNI","ETHFI","ATOM","FIL","AAVE","MKR",
    "APT","ARB","OP","INJ","TIA","SEI","PEPE","FET","ICP","ETC",
]

# ---------- HTTP ----------
def http_get(url, timeout=12, headers=None):
    h = {"User-Agent":"ATLAS-AI/7.0","Accept":"application/json,application/xml,text/xml,*/*"}
    if headers: h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        if raw.lstrip().startswith("<") or "xml" in (r.headers.get("Content-Type") or "").lower():
            return ET.fromstring(raw)
        return __import__("json").loads(raw)

def f(x):
    try: return float(x)
    except Exception: return None

def fmt(x):
    if x is None: return "N/A"
    if x >= 1000: return f"${x:,.2f}"
    if x >= 1: return f"${x:,.4f}"
    return f"${x:,.6f}"

def spread(a,b):
    if not a or not b: return None
    return abs(a-b)/((abs(a)+abs(b))/2)*100

# ---------- CCXT ----------
def make_exchange(exchange_id):
    cls = getattr(ccxt, exchange_id)
    return cls({"enableRateLimit": True, "timeout": 15000})

EX = {}
for eid in ("binance","xt","lbank"):
    try:
        EX[eid] = make_exchange(eid)
    except Exception:
        pass

MARKETS = {}
for eid, ex in EX.items():
    try:
        MARKETS[eid] = ex.load_markets()
    except Exception:
        MARKETS[eid] = {}

def symbol_for(eid, coin):
    markets = MARKETS.get(eid,{})
    for s in (f"{coin}/USDT", f"{coin}/USDT:USDT"):
        if s in markets:
            return s
    return None

def exchange_ticker(eid, coin):
    ex = EX[eid]
    sym = symbol_for(eid, coin)
    if not sym: raise RuntimeError(f"{eid}: pair unavailable")
    t = ex.fetch_ticker(sym)
    return {
        "source": eid.upper(),
        "price": f(t.get("last")),
        "change": f(t.get("percentage")),
        "quoteVolume": f(t.get("quoteVolume")),
    }

def exchange_ohlcv(eid, coin):
    ex = EX[eid]
    sym = symbol_for(eid, coin)
    if not sym: raise RuntimeError(f"{eid}: 4H pair unavailable")
    rows = ex.fetch_ohlcv(sym, timeframe=TIMEFRAME, limit=120)
    if len(rows) < 60: raise RuntimeError(f"{eid}: insufficient 4H candles")
    now = int(time.time()*1000)
    if rows and rows[-1][0] + 4*60*60*1000 > now:
        rows = rows[:-1]
    return rows

# ---------- external validation ----------
def gecko_markets():
    headers = {}
    if COINGECKO_API_KEY: headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    url = "https://api.coingecko.com/api/v3/coins/markets?" + urllib.parse.urlencode({
        "vs_currency":"usd","order":"market_cap_desc","per_page":"30","page":"1","sparkline":"false"
    })
    try:
        return http_get(url, headers=headers)
    except Exception:
        return []

def gecko_price(coin_id):
    headers={}
    if COINGECKO_API_KEY: headers["x-cg-demo-api-key"]=COINGECKO_API_KEY
    d=http_get("https://api.coingecko.com/api/v3/simple/price?"+urllib.parse.urlencode({
        "ids":coin_id,"vs_currencies":"usd","include_24hr_change":"true"}),headers=headers)
    x=d.get(coin_id,{})
    if x.get("usd") is None: raise RuntimeError("CoinGecko unavailable")
    return f(x["usd"]),f(x.get("usd_24h_change"))

def paprika_slug(coin):
    slugs={
        "BTC":"btc-bitcoin","ETH":"eth-ethereum","XRP":"xrp-xrp","SOL":"sol-solana",
        "BNB":"bnb-binance-coin","TON":"ton-toncoin","ADA":"ada-cardano",
        "DOGE":"doge-dogecoin","TRX":"trx-tron","LINK":"link-chainlink",
        "SUI":"sui-sui","AVAX":"avax-avalanche","LTC":"ltc-litecoin",
        "DOT":"dot-polkadot","NEAR":"near-near-protocol","TAO":"tao-bittensor",
        "ONDO":"ondo-ondo-finance","UNI":"uni-uniswap","ETHFI":"ethfi-ether-fi",
    }
    return slugs.get(coin)

def paprika_price(coin):
    slug=paprika_slug(coin)
    if not slug: raise RuntimeError("Paprika slug unavailable")
    d=http_get("https://api.coinpaprika.com/v1/tickers/"+slug)
    p=f(d.get("quotes",{}).get("USD",{}).get("price"))
    if p is None: raise RuntimeError("CoinPaprika unavailable")
    return p

def cmc_price(coin):
    if not CMC_API_KEY: raise RuntimeError("CMC key not configured")
    d=http_get(
        "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?"+
        urllib.parse.urlencode({"symbol":coin,"convert":"USD"}),
        headers={"X-CMC_PRO_API_KEY":CMC_API_KEY})
    x=d.get("data",{}).get(coin)
    if isinstance(x,list): x=x[0] if x else None
    p=f((x or {}).get("quote",{}).get("USD",{}).get("price"))
    if p is None: raise RuntimeError("CMC unavailable")
    return p

def price_consensus(coin):
    vals=[]
    sources=[]
    errors=[]
    for eid in EX:
        try:
            x=exchange_ticker(eid,coin)
            if x["price"] is not None:
                vals.append(x["price"]); sources.append(x)
        except Exception as e: errors.append(str(e))
    # external validators are only validation; exchange prices remain execution references
    try:
        rows=gecko_markets()
        gx=next((x for x in rows if (x.get("symbol") or "").upper()==coin),None)
        if gx and f(gx.get("current_price")):
            vals.append(f(gx["current_price"])); sources.append({"source":"CoinGecko","price":f(gx["current_price"])})
    except Exception as e: errors.append("CoinGecko: "+str(e))
    try:
        p=paprika_price(coin); vals.append(p); sources.append({"source":"CoinPaprika","price":p})
    except Exception: pass
    if CMC_API_KEY:
        try:
            p=cmc_price(coin); vals.append(p); sources.append({"source":"CMC","price":p})
        except Exception: pass
    if not vals: raise RuntimeError("NO PRICE DATA")
    med=sorted(vals)[len(vals)//2]
    sp=max([(spread(x,med) or 0) for x in vals],default=0)
    quality="HIGH" if len(vals)>=4 and sp<=1.5 else "MEDIUM" if len(vals)>=3 and sp<=3 else "LOW"
    return med,sources,quality,sp,errors

# ---------- indicators ----------
def ema(v,n):
    if len(v)<n:return None
    a=2/(n+1); e=sum(v[:n])/n
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
    avg=sum(vols[-21:-1])/20; ratio=vols[-1]/avg if avg else 0
    return ("STRONG",ratio) if ratio>=1.35 else ("WEAK",ratio) if ratio<=.75 else ("NORMAL",ratio)

# ---------- macro / derivatives ----------
def context():
    out={}
    try:
        d=http_get("https://api.alternative.me/fng/?limit=1")
        x=d["data"][0];out["fg"]=f(x["value"]);out["fg_label"]=x["value_classification"]
    except Exception: pass
    try:
        d=http_get("https://api.coingecko.com/api/v3/global")
        x=d["data"];out["btc_dom"]=f(x["market_cap_percentage"]["btc"])
    except Exception: pass
    try:
        d=http_get("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1")
        out["funding"]=f(d[-1]["fundingRate"])
    except Exception: pass
    try:
        d=http_get("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT")
        out["oi"]=f(d["openInterest"])
    except Exception: pass
    return out

# ---------- news ----------
RSS=[
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://www.theblock.co/rss.xml",
]
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
            d=http_get("https://cryptopanic.com/api/developer/v2/posts/?"+urllib.parse.urlencode({
                "auth_token":CRYPTOPANIC_TOKEN,"public":"true","kind":"news","regions":"en","limit":"10"}))
            items += [x.get("title","") for x in d.get("results",[])]
        except Exception: pass
    neg=("hack","exploit","lawsuit","ban","delist","liquidation","fraud","sec","investigation","outflow","stolen","sanction")
    pos=("approval","approved","etf","inflow","partnership","launch","adoption","upgrade","listing","integration","record")
    score=0
    for t in items:
        t=t.lower()
        score += sum(1 for w in pos if w in t)
        score -= sum(1 for w in neg if w in t)
    label="NEGATIVE" if score<=-3 else "POSITIVE" if score>=3 else "MIXED/LIMITED"
    return label,items[:8]

# ---------- BTC regime ----------
def btc_regime():
    try:
        rows=exchange_ohlcv("binance","BTC")
        c=[f(x[4]) for x in rows]
        e20,e50=ema(c,20),ema(c,50)
        rr=rsi(c)
        s=(2 if c[-1]>e20 else -2)+(2 if c[-1]>e50 else -2)+(2 if e20>e50 else -2)+(1 if rr and rr>=50 else -1)
        return ("BULLISH" if s>=4 else "BEARISH" if s<=-4 else "NEUTRAL"),s
    except Exception:return "UNKNOWN",0

# ---------- asset ----------
def analyze(coin, regime):
    price,sources,quality,sp,errors=price_consensus(coin)
    # Binance is preferred for 4H; XT/LBank are fallbacks.
    rows=None;engine=None
    for eid in ("binance","xt","lbank"):
        try:
            rows=exchange_ohlcv(eid,coin);engine=eid.upper();break
        except Exception: pass
    if not rows: raise RuntimeError("4H DATA UNAVAILABLE")
    c=[f(x[4]) for x in rows]
    e20,e50=ema(c,20),ema(c,50)
    rr=rsi(c);ml,ms=macd(c);av=atr(rows);vs,vr=vol_state(rows)
    sup=min(f(x[3]) for x in rows[-30:]);res=max(f(x[2]) for x in rows[-30:])
    score=(2 if price>e20 else -2)+(2 if price>e50 else -2)+(2 if e20>e50 else -2)
    if rr is not None:
        score += 2 if 52<=rr<68 else 1 if 68<=rr<75 else -1 if rr<48 else -1
    if ml is not None and ms is not None:
        score += 2 if ml>ms and ml>0 else 1 if ml>ms else -2 if ml<ms and ml<0 else -1
    score += 1 if vs=="STRONG" else -1 if vs=="WEAK" else 0
    if coin!="BTC": score += 1 if regime=="BULLISH" else -1 if regime=="BEARISH" else 0

    conf=max(25,min(92,50+abs(score)*3+(8 if quality=="HIGH" else -3 if quality=="MEDIUM" else -15)))
    # Strict action gate: low quality can NEVER produce an actionable trade.
    long_ok=score>=9 and quality!="LOW" and vs!="WEAK" and rr is not None and rr<72
    short_ok=score<=-9 and quality!="LOW" and rr is not None and rr>28
    if long_ok: action="BUY CONFIRMATION"; direction="LONG"
    elif short_ok: action="SHORT CONFIRMATION"; direction="SHORT"
    elif score>=6: action="BULLISH WATCH"; direction="WATCH_LONG"
    elif score<=-6: action="SELL WATCH"; direction="WATCH_SHORT"
    else: action="NO TRADE"; direction="NONE"
    if quality=="LOW": action="NO TRADE";direction="NONE"

    entry=sl=tp1=tp2=None
    if direction=="LONG":
        entry=max(price,res*1.002);sl=min(sup*.995,entry-1.5*(av or entry*.03))
        risk=max(entry-sl,entry*.005);tp1=entry+2*risk;tp2=entry+3*risk
    elif direction=="SHORT":
        entry=min(price,sup*.998);sl=max(res*1.005,entry+1.5*(av or entry*.03))
        risk=max(sl-entry,entry*.005);tp1=entry-2*risk;tp2=entry-3*risk
    return {
        "coin":coin,"price":price,"change":next((x.get("change") for x in sources if x["source"]=="BINANCE"),None),
        "trend":"BULLISH" if price>e20 and e20>e50 else "BEARISH" if price<e20 and e20<e50 else "MIXED",
        "rsi":rr,"macd":"BULLISH" if ml is not None and ms is not None and ml>ms else "BEARISH",
        "volume":vs,"score":score,"confidence":int(conf),"support":sup,"resistance":res,
        "entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"action":action,"quality":quality,"spread":sp,
        "sources":[x["source"] for x in sources],"engine":engine,
    }

# ---------- report ----------
def report():
    regime,rs=btc_regime()
    ctx=context();nl,headlines=news()
    # Dynamic top 30; merge with static radar.
    dynamic=gecko_markets()
    universe=list(dict.fromkeys(STATIC+[(x.get("symbol") or "").upper() for x in dynamic]))
    universe=[x for x in universe if x and x not in {"USDT","USDC"}][:50]

    results=[];failed=0
    for coin in universe:
        try: results.append(analyze(coin,regime))
        except Exception: failed+=1
        time.sleep(.08)

    results.sort(key=lambda x:(x["action"] in ("BUY CONFIRMATION","SHORT CONFIRMATION"),x["confidence"],abs(x["score"])),reverse=True)

    now=datetime.now(TEHRAN)
    L=[
        "🤖 ATLAS AI — SNIPER v7",
        "━━━━━━━━━━━━━━━━━━",
        now.strftime("%Y/%m/%d  %H:%M")+" 🇮🇷","Timeframe: 4H","",
        f"🌎 BTC REGIME: {'🟢' if regime=='BULLISH' else '🔴' if regime=='BEARISH' else '🟡'} {regime}",
    ]
    if ctx.get("fg") is not None:L.append(f"😨 Fear & Greed: {ctx['fg']:.0f} — {ctx.get('fg_label','')}")
    if ctx.get("btc_dom") is not None:L.append(f"₿ BTC Dominance: {ctx['btc_dom']:.2f}%")
    if ctx.get("funding") is not None:L.append(f"BTC Funding: {ctx['funding']*100:.4f}%")
    L += [f"📰 NEWS: {nl}",""]

    for r in results:
        L += [
            f"🔹 {r['coin']}",f"Price: {fmt(r['price'])}",
            f"24H: {r['change']:+.2f}%" if r["change"] is not None else "24H: N/A",
            f"Trend: {'🟢' if r['trend']=='BULLISH' else '🔴' if r['trend']=='BEARISH' else '🟡'} {r['trend']}",
            f"RSI14: {r['rsi']:.1f}" if r["rsi"] is not None else "RSI14: N/A",
            f"MACD: {'🟢' if r['macd']=='BULLISH' else '🔴'} {r['macd']}",
            f"Volume: {'🟢' if r['volume']=='STRONG' else '🔴' if r['volume']=='WEAK' else '🟡'} {r['volume']}",
            f"4H Score: {r['score']:+d}",f"Confidence: {r['confidence']}%",
            f"Support: {fmt(r['support'])}",f"Resistance: {fmt(r['resistance'])}",
        ]
        if r["entry"] is not None:
            risk=abs(r["entry"]-r["sl"]);reward=abs(r["tp1"]-r["entry"])
            L += [f"Entry: {fmt(r['entry'])}",f"SL: {fmt(r['sl'])}",f"TP1: {fmt(r['tp1'])}",f"TP2: {fmt(r['tp2'])}",f"R:R: 1:{reward/risk:.1f}"]
        L += [f"🎯 ACTION: {r['action']}",f"Data: {r['quality']}",f"Exchanges: {', '.join(r['sources'])}",f"4H Engine: {r['engine']}"]
        if r["spread"]>3:L.append(f"⚠️ DATA CONFLICT: {r['spread']:.2f}%")
        L.append("")

    L += ["━━━━━━━━━━━━━━━━━━","🏆 TOP OPPORTUNITIES"]
    picks=[r for r in results if r["action"] in ("BUY CONFIRMATION","SHORT CONFIRMATION")]
    if picks:
        for i,r in enumerate(picks[:8],1):L.append(f"{i}. {'🟢' if r['action'].startswith('BUY') else '🔴'} {r['coin']} — {r['action']} — {r['confidence']}%")
    else:L.append("⛔ No high-quality actionable setup.")

    L += [
        "","🛡️ ATLAS CAPITAL PROTECTION",
        f"Risk cap/trade: {RISK_PER_TRADE:.2f}%",
        f"Max portfolio open risk: {MAX_PORTFOLIO_RISK:.2f}%",
        "No automatic orders. No leverage by default.",
        "",
        "📡 DATA ENGINE",
        f"Assets scanned: {len(universe)} | Successful: {len(results)} | Unavailable: {failed}",
        "4H incomplete candles excluded.",
        "Low-confidence / conflicting data => NO TRADE.",
        "",
        "🎯 ATLAS SNIPER v7: ACTIVE",
        "",
        "⚠️ هدف 3x در یک سال تضمین‌شدنی نیست. موتور برای شکار فرصت‌های با کیفیت، مدیریت ریسک و جلوگیری از معاملات ضعیف طراحی شده است؛ نه قمار و نه تضمین سود.",
    ]
    text="\n".join(L)
    return text[:3950]+"\n\n⚠️ Telegram length protection." if len(text)>4000 else text

def send(text):
    GROUP_CHAT_ID = "-1003961443232"


def telegram_send(chat_id, text):
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
    }).encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )

    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

GROUP_CHAT_ID = "-1003961443232"


def telegram_send(chat_id, text):
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
    }).encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )

    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def send(text):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram secrets missing")

    # ارسال اصلی
    telegram_send(CHAT_ID, text)
    print("ATLAS report sent to primary Telegram chat.")

    # کپی دقیق همان پیام در سوپرگروه
    try:
        telegram_send(GROUP_CHAT_ID, text)
        print("ATLAS report copied to Telegram supergroup.")

    except Exception as e:
        # شکست ارسال گروه نباید ارسال اصلی را مختل کند
        print(
            "WARNING: Telegram supergroup send failed: "
            f"{type(e).__name__}: {e}"
        )

def main():
    # گزارش فقط یک بار ساخته می‌شود
    text = report()

    print(text)

    # ارسال به چت اصلی + کپی در سوپرگروه
    send(text)

    print("ATLAS v7 sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
