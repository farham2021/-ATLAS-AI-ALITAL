import os, json, urllib.request, urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TOKEN=os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID=os.environ.get("TELEGRAM_CHAT_ID","").strip()
CG_KEY=os.environ.get("COINGECKO_API_KEY","").strip()

HOSTS=["https://data-api.binance.vision","https://api-gcp.binance.com","https://api.binance.com","https://api1.binance.com"]
WATCH={
"BTCUSDT":("BTC","XBTUSD","bitcoin","btc-bitcoin"),
"ETHUSDT":("ETH","ETHUSD","ethereum","eth-ethereum"),
"XRPUSDT":("XRP","XRPUSD","ripple","xrp-xrp"),
"SOLUSDT":("SOL","SOLUSD","solana","sol-solana"),
"TONUSDT":("TON","TONUSD","the-open-network","ton-toncoin"),
"UNIUSDT":("UNI","UNIUSD","uniswap","uni-uniswap"),
"ETHFIUSDT":("ETHFI","ETHFIUSD","ether-fi","ethfi-ether-fi")}

def get(url,timeout=15,headers=None):
    h={"User-Agent":"ATLAS-AI/5.0","Accept":"application/json"}
    if headers:h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=timeout) as r:
        if not 200<=r.getcode()<300: raise RuntimeError(f"HTTP {r.getcode()}")
        return json.loads(r.read().decode())

def f(x):
    try:return float(x)
    except:return None

def fmt(x):
    if x is None:return "N/A"
    if x>=1000:return f"${x:,.2f}"
    if x>=1:return f"${x:,.4f}"
    return f"${x:,.6f}"

def diff(a,b):
    if not a or not b:return 0
    return abs(a-b)/((a+b)/2)*100

def b24(sym):
    err=None
    for h in HOSTS:
        try:
            d=get(f"{h}/api/v3/ticker/24hr?symbol={sym}",12)
            return {"price":f(d["lastPrice"]),"change":f(d["priceChangePercent"]),"source":"Binance"}
        except Exception as e:err=e
    raise RuntimeError(f"Binance 24H: {err}")

def candles(sym):
    err=None
    for h in HOSTS:
        try:
            d=get(f"{h}/api/v3/klines?symbol={sym}&interval=4h&limit=100",15)
            if len(d)>=60:return d
        except Exception as e:err=e
    raise RuntimeError(f"Binance 4H: {err}")

def paprika(cid):
    d=get("https://api.coinpaprika.com/v1/tickers/"+cid,12)
    q=d.get("quotes",{}).get("USD",{})
    p=f(q.get("price"))
    if p is None:raise RuntimeError("CoinPaprika unavailable")
    return {"price":p,"change":f(q.get("percent_change_24h")),"source":"CoinPaprika"}

def gecko(cid):
    hd={"x-cg-demo-api-key":CG_KEY} if CG_KEY else {}
    d=get(f"https://api.coingecko.com/api/v3/simple/price?ids={cid}&vs_currencies=usd&include_24hr_change=true",15,hd)
    q=d.get(cid)
    if not q or f(q.get("usd")) is None:raise RuntimeError("CoinGecko unavailable")
    return {"price":f(q["usd"]),"change":f(q.get("usd_24h_change")),"source":"CoinGecko"}

def consensus(sym,info):
    s=[];e=[]
    for fn,arg in ((b24,sym),(paprika,info[3]),(gecko,info[2])):
        try:s.append(fn(arg))
        except Exception as x:e.append(str(x))
    if not s:raise RuntimeError("No price source available")
    ps=sorted(x["price"] for x in s); med=ps[len(ps)//2]
    md=max((diff(x["price"],med) for x in s),default=0)
    q="🟢 HIGH" if md<=.5 else "🟡 MEDIUM" if md<=1.5 else "🟠 LOW"
    return {"price":med,"sources":s,"conflict":md,"quality":q}

def ema(v,n):
    if len(v)<n:return None
    k=2/(n+1);z=sum(v[:n])/n
    for x in v[n:]:z=x*k+z*(1-k)
    return z

def rsi(v,n=14):
    if len(v)<=n:return None
    g=[];l=[]
    for i in range(1,len(v)):
        d=v[i]-v[i-1];g.append(max(d,0));l.append(max(-d,0))
    a=sum(g[:n])/n;b=sum(l[:n])/n
    for i in range(n,len(g)):
        a=(a*(n-1)+g[i])/n;b=(b*(n-1)+l[i])/n
    if b==0:return 100
    return 100-100/(1+a/b)

def macd(v):
    series=[]
    for i in range(26,len(v)+1):
        a=ema(v[:i],12);b=ema(v[:i],26)
        if a is not None and b is not None:series.append(a-b)
    if len(series)<9:return None
    m=series[-1];sig=ema(series,9)
    return m-sig

def atr(c,n=14):
    tr=[]
    for i in range(1,len(c)):
        h,l,pc=map(float,(c[i][2],c[i][3],c[i-1][4]))
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    if len(tr)<n:return None
    a=sum(tr[:n])/n
    for x in tr[n:]:a=(a*(n-1)+x)/n
    return a

def analyze(sym,info):
    m=consensus(sym,info);c=candles(sym)
    now=int(datetime.now(timezone.utc).timestamp()*1000)
    if int(c[-1][0])+14400000>now:c=c[:-1]
    v=[float(x[4]) for x in c];p=v[-1]
    e20,e50=ema(v,20),ema(v,50);r=rsi(v);mh=macd(v);a=atr(c)
    vs=[float(x[5]) for x in c]
    avg=sum(vs[-21:-1])/20;vr=vs[-1]/avg if avg else 0
    vol="STRONG" if vr>=1.25 else "NORMAL" if vr>=.8 else "WEAK"
    trend="BULLISH" if e20 and e50 and p>e20>e50 else "BEARISH" if e20 and e50 and p<e20<e50 else "MIXED"
    score=(3 if trend=="BULLISH" else -3 if trend=="BEARISH" else 0)
    score+=(2 if p>e20 else -2)+(2 if p>e50 else -2)
    score+=(2 if mh and mh>0 else -2 if mh is not None else 0)
    if r is not None:
        score+=2 if 52<=r<68 else -2 if r>=70 else -1 if 32<r<45 else 1 if r<=32 else 0
    score+=1 if vol=="STRONG" and score>0 else -1 if vol=="WEAK" else 0
    conf=50+(10 if trend!="MIXED" else 0)+(10 if mh is not None else 0)+(10 if vol=="STRONG" else -5 if vol=="WEAK" else 0)+(10 if m["quality"]=="🟢 HIGH" else -15 if m["quality"]=="🟠 LOW" else 0)
    conf=max(35,min(95,conf))
    sup=min(float(x[3]) for x in c[-20:]);res=max(float(x[2]) for x in c[-20:])
    if score>=6:
        entry=max(p,res*1.002);sl=max(sup-.5*(a or p*.02),p*.94);risk=max(entry-sl,entry*.005);tp1=entry+1.5*risk;tp2=entry+2.5*risk;action="🟡 BUY ON CONFIRMATION"
    elif score>=3:
        entry=p;sl=max(sup-.35*(a or p*.02),p*.95);risk=max(entry-sl,entry*.005);tp1=entry+1.5*risk;tp2=entry+2.5*risk;action="🟡 WATCH"
    elif score<=-6:
        entry=sl=tp1=tp2=None;action="🔴 SELL WATCH"
    else:
        entry=sl=tp1=tp2=None;action="⚪ NO TRADE"
    return locals()

def report():
    tz=ZoneInfo("Asia/Tehran");now=datetime.now(tz);R={}
    for s,i in WATCH.items():
        try:R[s]=analyze(s,i)
        except Exception as e:R[s]={"error":str(e)}
    btc=R.get("BTCUSDT");reg="🟡 NEUTRAL / TRANSITION"
    if btc and "error" not in btc:reg="🟢 BULLISH" if btc["score"]>=6 and btc["trend"]=="BULLISH" else "🔴 BEARISH" if btc["score"]<=-6 and btc["trend"]=="BEARISH" else reg
    L=["🤖 ATLAS AI — SNIPER v5","━━━━━━━━━━━━━━━━━━",now.strftime("%Y/%m/%d  %H:%M")+" 🇮🇷","Timeframe: 4H","",f"🌎 BTC REGIME: {reg}",""]
    bc=wa=nt=sw=un=0
    for s,i in WATCH.items():
        n=i[0];a=R[s]
        if "error" in a:
            un+=1;L += [f"🔹 {n}","⚫ DATA UNAVAILABLE","🎯 ACTION: NO TRADE",f"Reason: {a['error'][:160]}",""];continue
        act=a["action"];bc+=act=="🟡 BUY ON CONFIRMATION";wa+=act=="🟡 WATCH";nt+=act=="⚪ NO TRADE";sw+=act=="🔴 SELL WATCH"
        bn=next((x["change"] for x in a["m"]["sources"] if x["source"]=="Binance"),None)
        ml="🟢 BULLISH" if (a["mh"] or 0)>0 else "🔴 BEARISH"
        tl="🟢 BULLISH" if a["trend"]=="BULLISH" else "🔴 BEARISH" if a["trend"]=="BEARISH" else "🟡 MIXED"
        vl="🟢 STRONG" if a["vol"]=="STRONG" else "🟡 NORMAL" if a["vol"]=="NORMAL" else "🔴 WEAK"
        L += [f"🔹 {n}",f"Price: {fmt(a['m']['price'])}",f"24H: {bn:+.2f}%" if bn is not None else "24H: N/A",f"Trend: {tl}",f"RSI14: {a['r']:.1f}" if a["r"] is not None else "RSI14: N/A",f"MACD: {ml}",f"Volume: {vl}",f"4H Score: {a['score']:+d}",f"Confidence: {a['conf']}%",f"Support: {fmt(a['sup'])}",f"Resistance: {fmt(a['res'])}"]
        if a["entry"] is not None:L += [f"Entry: {fmt(a['entry'])}",f"SL: {fmt(a['sl'])}",f"TP1: {fmt(a['tp1'])}",f"TP2: {fmt(a['tp2'])}","R:R: 1:2.5"]
        L += [f"🎯 ACTION: {act}",f"Data: {a['m']['quality']}","Sources: "+", ".join(x["source"] for x in a["m"]["sources"]),"4H Engine: Binance"]
        if a["m"]["conflict"]>1.5:L.append(f"⚠️ DATA CONFLICT: {a['m']['conflict']:.2f}%")
        L.append("")
    status="🟢 MARKET STATUS: BUY CONFIRMATION ZONE" if bc>=3 and btc and "error" not in btc and btc["score"]>=6 else "🔴 MARKET STATUS: SELL/SHORT ZONE" if sw>=3 and btc and "error" not in btc and btc["score"]<=-6 else "🟡 MARKET STATUS: SELECTIVE BULLISH" if bc>sw else "🟠 MARKET STATUS: SELECTIVE BEARISH" if sw>bc else "⚪ MARKET STATUS: WAIT"
    L += ["━━━━━━━━━━━━━━━━━━",status,f"🟢 BUY CONFIRMATION: {bc}",f"🟡 WATCH: {wa}",f"⚪ NO TRADE: {nt}",f"🔴 SELL WATCH: {sw}",f"⚫ DATA UNAVAILABLE: {un}/7","","🛡️ ATLAS RISK ENGINE: ACTIVE","🎯 ATLAS SNIPER v5: ACTIVE","","⚠️ Entry/SL/TP are analytical levels, not automatic orders.","⚠️ سیگنال‌ها قطعی نیستند؛ قبل از معامله ریسک کل سبد و نقدشوندگی بررسی شود."]
    return "\n".join(L)

def main():
    if not TOKEN: print("ERROR: TELEGRAM_TOKEN missing");return 1
    text=report();print(text);chat=CHAT_ID or find_chat_id()
    if not chat: print("ERROR: TELEGRAM_CHAT_ID missing");return 1
    send(text,chat);print("✅ ATLAS v5 sent");return 0

def find_chat_id():
    try:
        d=get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?timeout=5",10)
        for u in reversed(d.get("result",[])):
            if u.get("message",{}).get("chat",{}).get("id"):return u["message"]["chat"]["id"]
    except:pass
    return None

def send(text,chat):
    if len(text)>4000:text=text[:3950]+"\n\n⚠️ Report truncated."
    data=urllib.parse.urlencode({"chat_id":str(chat),"text":text}).encode()
    req=urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",data=data,headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req,timeout=20):pass

if __name__=="__main__":raise SystemExit(main())
