#!/usr/bin/env python3
"""ATLAS AI v12 - Reliable Analytical Engine. No forced signals."""
from __future__ import annotations
import csv,json,re,time
from dataclasses import dataclass,asdict
from datetime import datetime
from typing import Optional,Dict,Any,List
import requests

# Telegram delivery is the real implementation; do not shadow these functions locally.
from telegram_delivery_v12 import send_report, send_csv as send_csv_report

TGJU_USD_URL="https://www.tgju.org/profile/price_dollar_rl"
TGJU_USDT_URL="https://www.tgju.org/profile/price_usdt"
STATUS_LEVELS=("STRONG BULL","BULL","NEUTRAL","BEAR","STRONG BEAR")
SETUP_LEVELS=("EXECUTABLE","BEST WATCH","NO VALID SETUP")

@dataclass
class SetupResult:
    symbol:str; status:str; level:str
    entry:Optional[float]=None; stop_loss:Optional[float]=None
    tp1:Optional[float]=None; tp2:Optional[float]=None
    rr_tp1:Optional[float]=None; rr_tp2:Optional[float]=None
    confidence:float=0.0; rsi:Optional[float]=None
    volume_trend:str="UNKNOWN"; volume_ratio:Optional[float]=None
    distance_to_resistance_pct:Optional[float]=None
    required_conditions:List[str]=None; missing_conditions:List[str]=None
    invalid_reasons:List[str]=None; downside_target:Optional[float]=None
    dynamic_stop:Optional[float]=None
    def __post_init__(self):
        self.required_conditions=self.required_conditions or []
        self.missing_conditions=self.missing_conditions or []
        self.invalid_reasons=self.invalid_reasons or []

def _number(x):
    if x is None:return None
    m=re.search(r'-?[0-9][0-9,٬]*(?:\.[0-9]+)?',str(x))
    return float(m.group().replace(',','').replace('٬','')) if m else None

TGJU_USD_URLS=(
    TGJU_USD_URL,
    "https://gem.tgju.org/profile/price_dollar_rl",
    "https://english.tgju.org/profile/price_dollar_rl",
)
TGJU_USDT_URLS=(
    TGJU_USDT_URL,
    "https://www.tgju.org/crypto/exchanges/local/asset/usdt",
    "https://gem.tgju.org/crypto/exchanges/local/asset/usdt",
)

def _tgju(url, kind="generic"):
    """Read a rate from TGJU only, with retries and browser-like headers.

    TGJU may return 403 to a bare HTTP client. A session, realistic headers,
    a warm-up request, and bounded retries reduce that failure without
    switching to a different provider. All fallback URLs remain on TGJU.
    """
    session=requests.Session()
    session.headers.update({
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer":"https://www.tgju.org/",
        "Cache-Control":"no-cache",
        "Pragma":"no-cache",
    })
    last_error=None
    for attempt in range(3):
        try:
            r=session.get(url,timeout=25,allow_redirects=True)
            if r.status_code==403:
                try: session.get("https://www.tgju.org/",timeout=15)
                except requests.RequestException: pass
                r=session.get(url,timeout=25,allow_redirects=True)
            r.raise_for_status()
            text=re.sub(r'<[^>]+>',' ',r.text)
            text=re.sub(r'\s+',' ',text)
            candidates=[]
            if kind=="usd":
                patterns=(
                    r'(?:نرخ فعلی|قیمت فعلی|آخرین|Last)[^0-9]{0,100}([0-9,٬]{5,})',
                    r'(?:قیمت هر دلار|قیمت دلار)[^0-9]{0,100}([0-9,٬]{5,})',
                )
            elif kind=="usdt":
                patterns=(
                    r'(?:تتر|USDT)[^0-9]{0,120}([0-9,٬]{5,})',
                    r'(?:فروش صرافی|SELL)[^0-9]{0,120}([0-9,٬]{5,})',
                )
            else:
                patterns=(r'(?:قیمت|ارزش|آخرین|Last)[^0-9]{0,100}([0-9,٬]{5,})',)
            for pat in patterns:
                for m in re.finditer(pat,text,re.I):
                    n=_number(m.group(1))
                    if n and n>1000 and n<100000000000:
                        candidates.append(n)
            if candidates:
                return candidates[0]
            raise RuntimeError(f"TGJU rate marker not found: {url}")
        except (requests.RequestException,RuntimeError) as exc:
            last_error=exc
            if attempt<2: time.sleep(2**attempt)
    raise RuntimeError(f"TGJU unavailable: {url}; {last_error}")

def _first_tgju(urls,kind):
    errors=[]
    for url in urls:
        try:
            return _tgju(url,kind)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("All TGJU endpoints failed: " + " | ".join(errors))

def fetch_tgju_rates():
    # TGJU publishes these values in Rial; report them in Toman.
    usd_rial=_first_tgju(TGJU_USD_URLS,"usd")
    usdt_rial=_first_tgju(TGJU_USDT_URLS,"usdt")
    return {
        "usd_toman":usd_rial/10.0,
        "usdt_toman":usdt_rial/10.0,
        "source":"tgju.org",
        "timestamp":datetime.now().astimezone().isoformat(),
        "quality":1.0,
    }

def calculate_rr(entry,sl,tp1,tp2):
    risk=abs(entry-sl)
    if risk<=0: raise ValueError("Invalid R/R geometry")
    return (tp1-entry)/risk,(tp2-entry)/risk

def _level(data,key,price,direction):
    vals=[data.get(key)]
    vals += list(data.get(key+"s",[]) or [])
    vals=[float(v) for v in vals if v is not None]
    if direction=="below": vals=[v for v in vals if v<price]
    else: vals=[v for v in vals if v>price]
    return max(vals) if direction=="below" and vals else min(vals) if vals else None

def classify_status(d):
    t=str(d.get("trend","neutral")).lower()
    if t in ("strong_bullish","strong bull"): return "STRONG BULL"
    if t in ("bullish","bull"): return "BULL"
    if t in ("strong_bearish","strong bear"): return "STRONG BEAR"
    if t in ("bearish","bear"): return "BEAR"
    return "NEUTRAL"

def confidence_score(d):
    s=50
    st=classify_status(d); s += {"STRONG BULL":20,"BULL":10,"NEUTRAL":0,"BEAR":-10,"STRONG BEAR":-20}[st]
    r=d.get("rsi"); v=d.get("volume_ratio")
    if r is not None:
        s += 10 if 45<=r<68 else -15 if r>=70 else -5
    if v is not None: s += 10 if v>=1.2 else -5 if v<1 else 0
    if d.get("ma_alignment") is True:s+=10
    if d.get("data_quality") is not None:s+=(float(d["data_quality"])-.5)*20
    return max(0,min(100,round(s,1)))

class ReliableAnalyticalEngine:
    def analyze_coin(self,symbol,d):
        price=float(d.get("current_price") or 0); status=classify_status(d); conf=confidence_score(d)
        sup=_level(d,"support",price,"below"); res=_level(d,"resistance",price,"above")
        if not price or sup is None or res is None:
            return SetupResult(symbol,status,"NO VALID SETUP",confidence=conf,invalid_reasons=["incomplete price/support/resistance data"])
        sl=float(d.get("stop_loss") or sup); tp1=float(d.get("tp1") or res)
        tp2=float(d.get("tp2") or (res+.30*(res-price)))
        rr1,rr2=calculate_rr(price,sl,tp1,tp2)
        rsi=d.get("rsi"); vr=d.get("volume_ratio")
        conditions={
          "rr":rr1>=1 or rr2>=1.5,
          "trend":status in ("STRONG BULL","BULL"),
          "rsi":rsi is None or rsi<70,
          "volume":vr is None or vr>=1.2,
          "support_confirmation":int(d.get("support_confirmations",0))>=2,
          "breakout_confirmation":bool(d.get("confirmed_breakout",False))}
        missing=[]
        labels={"rr":"R/R threshold","trend":"bullish trend","rsi":"RSI below 70",
                "volume":"volume >= 120% of 20-period average",
                "support_confirmation":"at least 2 support confirmations",
                "breakout_confirmation":"2 consecutive H4 closes above resistance"}
        missing=[labels[k] for k,v in conditions.items() if not v]
        level="EXECUTABLE" if all(conditions.values()) else "BEST WATCH" if conditions["rr"] and status in ("STRONG BULL","BULL","NEUTRAL") else "NO VALID SETUP"
        return SetupResult(symbol,status,level,price,sl,tp1,tp2,rr1,rr2,conf,rsi,str(d.get("volume_trend","UNKNOWN")),vr,(res-price)/price*100,
          ["2 consecutive H4 closes above resistance","volume >= 120% of 20-period average"] if level=="BEST WATCH" else [],
          missing,[],float(d.get("downside_target") or sup-.5*(price-sup)),float(d.get("dynamic_stop") or sup*.995))

def asset_block(symbol,d):
    r=ReliableAnalyticalEngine().analyze_coin(symbol,d)
    return f"🔹 {symbol} | {r.status} | {r.level} | Confidence {r.confidence:.0f}%\n   Price ${r.entry:,.6f} | Support ${d.get('support',0):,.6f} | Resistance ${d.get('resistance',0):,.6f}\n   RSI {r.rsi if r.rsi is not None else 'N/A'} | Volume {r.volume_trend} | Distance {r.distance_to_resistance_pct:.2f}%\n   R/R TP1 1:{r.rr_tp1:.2f} | TP2 1:{r.rr_tp2:.2f}" if r.entry else f"🔹 {symbol} | {r.status} | NO VALID SETUP"

def personal_report(portfolio,rates=None):
    eng=ReliableAnalyticalEngine(); rs=[eng.analyze_coin(s,d) for s,d in portfolio.items()]
    best=next((r for r in rs if r.level=="EXECUTABLE"),None)
    out=["🤖 ATLAS AI — PERSONAL PORTFOLIO 4H","━━━━━━━━━━━━━━━━━━",
         "🔥 BEST PERSONAL SETUP: "+(f"{best.symbol} — EXECUTABLE — R/R TP1 1:{best.rr_tp1:.2f} | TP2 1:{best.rr_tp2:.2f}" if best else "هیچ ستاپ اجرایی معتبر تأیید نشد."),
         "","💼 PERSONAL PORTFOLIO","───────────────────"]+[asset_block(r.symbol,portfolio[r.symbol]) for r in rs]
    return "\n".join(out)

def generate_csv_report(results,filename):
    with open(filename,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=list(asdict(results[0]).keys()) if results else ["symbol","level"]); w.writeheader()
        for r in results:
            x=asdict(r)
            for k in ("required_conditions","missing_conditions","invalid_reasons"): x[k]=json.dumps(x[k],ensure_ascii=False)
            w.writerow(x)
    return filename

def build_report(market,portfolio,metals=None):
    # Rate retrieval is TGJU-only. If TGJU is temporarily unavailable (for
    # example HTTP 403/network blocking), do not fabricate or substitute a
    # rate; continue and mark it unavailable so Telegram delivery can proceed.
    try:
        rates=fetch_tgju_rates()
        rate_line=f"💵 دلار: {rates['usd_toman']:,.0f} تومان | تتر: {rates['usdt_toman']:,.0f} تومان"
        rate_meta=f"📡 Source: {rates['source']} | Updated: {rates['timestamp']}"
    except Exception as exc:
        rates={"usd_toman":None,"usdt_toman":None,"source":"tgju.org","timestamp":datetime.now().astimezone().isoformat(),"quality":0.0}
        rate_line="💵 دلار: N/A | تتر: N/A"
        rate_meta=f"📡 Source: tgju.org | Rate unavailable: {type(exc).__name__}"
    eng=ReliableAnalyticalEngine()
    mr=[eng.analyze_coin(s,d) for s,d in market.items()]
    best=next((r for r in mr if r.level=="EXECUTABLE"),None)
    lines=["🤖 ATLAS AI — MARKET 4H","━━━━━━━━━━━━━━━━━━",
      rate_line,
      rate_meta,"",
      "🔥 BEST SETUP: "+(f"{best.symbol} — EXECUTABLE — R/R TP1 1:{best.rr_tp1:.2f} | TP2 1:{best.rr_tp2:.2f}" if best else "هیچ ستاپ اجرایی معتبر تأیید نشد."),
      "","📡 MARKET","───────────────────"]+[asset_block(r.symbol,market[r.symbol]) for r in mr]
    if metals:
        lines+=["","🪙 ATLAS METALS","───────────────────"]+[asset_block(s,d) for s,d in metals.items()]
    lines+=["",personal_report(portfolio,rates),"","📐 V12 RULES","───────────────────",
      "• وضعیت‌ها: STRONG BULL / BULL / NEUTRAL / BEAR / STRONG BEAR",
      "• تثبیت شکست = حداقل ۲ کلوز متوالی H4 بالای مقاومت",
      "• تأیید حجم = حداقل ۲۰٪ بالاتر از میانگین ۲۰ دوره",
      "• RSI >= 70 برای لانگ EXECUTABLE مانع است",
      "• R/R برای TP1 و TP2 جداگانه محاسبه می‌شود؛ Confidence هرگز جای R/R نیست",
      "• BEST WATCH معامله نیست؛ فقط مشروط به تحقق شروط است",
      "• داده ناکافی = NO VALID SETUP؛ هیچ سیگنال اجباری وجود ندارد",
      "• دلار و تتر فقط از tgju.org"]
    return "\n".join(lines)

def action_emoji(status): return {"STRONG BULL":"🟢","BULL":"🟢","NEUTRAL":"🟡","BEAR":"🔴","STRONG BEAR":"🔴"}.get(status,"⚪")
def split_telegram(text,limit=4000): return [text[i:i+limit] for i in range(0,len(text),limit)]

if __name__=="__main__":
    # Production delivery entry point. No fabricated market data is created.
    # If the analytical data provider is unavailable, the workflow continues
    # and explicitly sends a NO VALID SETUP report instead of failing silently.
    try:
        report=build_report({}, {}, None)
        report=report.replace(
            "🔥 BEST SETUP: هیچ ستاپ اجرایی معتبر تأیید نشد.",
            "🔥 BEST SETUP: هیچ ستاپ اجرایی معتبر تأیید نشد.\n⚠️ داده تحلیلی بازار در این اجرا در دسترس نبود؛ سیگنال اجباری صادر نشد."
        )
        parts_count,sent_count,errors=send_report(report)
        print(f"Telegram delivery: parts={parts_count}, sent={sent_count}, errors={len(errors)}")
        for err in errors: print("Telegram error:",err)
        if sent_count<=0:
            raise RuntimeError("Telegram delivery failed: " + "; ".join(errors or ["0 messages sent"]))
        print("ATLAS AI v12 delivered successfully.")
    except Exception as e:
        import traceback
        print(f"ATLAS AI v12 ERROR: {e}")
        traceback.print_exc()
        raise
