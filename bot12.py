#!/usr/bin/env python3
"""ATLAS AI v12 - Reliable Analytical Engine. No forced signals."""
from __future__ import annotations
import csv,json,re
from dataclasses import dataclass,asdict
from datetime import datetime
from typing import Optional,Dict,Any,List
import requests

# ============================================================
# IMPORT TELEGRAM DELIVERY - FIXED
# ============================================================
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

def _tgju(url):
    r=requests.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    text=re.sub(r'<[^>]+>',' ',r.text); text=re.sub(r'\s+',' ',text)
    # Prefer explicit price/result markers; never use another provider.
    candidates=[]
    for pat in (r'(?:قیمت|ارزش|آخرین)[^0-9]{0,80}([0-9,٬]{4,})',
                r'(?:USD|USDT)[^0-9]{0,80}([0-9,٬]{4,})'):
        for m in re.finditer(pat,text,re.I):
            n=_number(m.group(1))
            if n and n>1000:candidates.append(n)
    if not candidates: raise RuntimeError(f"TGJU rate unavailable: {url}")
    return candidates[0]

def fetch_tgju_rates():
    usd=_tgju(TGJU_USD_URL); usdt=_tgju(TGJU_USDT_URL)
    return {"usd_toman":usd,"usdt_toman":usdt,"source":"tgju.org","timestamp":datetime.now().astimezone().isoformat(),"quality":1.0}

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
    rates=fetch_tgju_rates(); eng=ReliableAnalyticalEngine()
    mr=[eng.analyze_coin(s,d) for s,d in market.items()]
    best=next((r for r in mr if r.level=="EXECUTABLE"),None)
    lines=["🤖 ATLAS AI — MARKET 4H","━━━━━━━━━━━━━━━━━━",
      f"💵 دلار: {rates['usd_toman']:,.0f} تومان | تتر: {rates['usdt_toman']:,.0f} تومان",
      f"📡 Source: {rates['source']} | Updated: {rates['timestamp']}","",
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

# ============================================================
# FIXED: send_report and send_csv_report are now imported
# from telegram_delivery_v12 at the top of the file.
# The old empty functions have been removed.
# ============================================================

if __name__=="__main__":
    # ============================================================
    # SAMPLE DATA - REPLACE WITH YOUR ACTUAL DATA
    # ============================================================
    
    # Example market data structure
    market = {
        "BTC": {
            "current_price": 65000,
            "support": 64000,
            "resistance": 66000,
            "trend": "bullish",
            "rsi": 55,
            "volume_ratio": 1.3,
            "support_confirmations": 2,
            "confirmed_breakout": True,
            "volume_trend": "HIGH",
            "data_quality": 0.9
        },
        "ETH": {
            "current_price": 3200,
            "support": 3100,
            "resistance": 3300,
            "trend": "neutral",
            "rsi": 60,
            "volume_ratio": 0.9,
            "support_confirmations": 1,
            "confirmed_breakout": False,
            "volume_trend": "LOW",
            "data_quality": 0.8
        }
    }
    
    # Example portfolio data structure
    portfolio = {
        "SOL": {
            "current_price": 150,
            "support": 140,
            "resistance": 160,
            "trend": "bullish",
            "rsi": 45,
            "volume_ratio": 1.5,
            "support_confirmations": 3,
            "confirmed_breakout": True,
            "volume_trend": "HIGH",
            "data_quality": 0.95
        }
    }
    
    print("ATLAS AI v12 starting...")
    
    # Build the report
    try:
        report_text = build_report(market, portfolio)
        print("Report built successfully.")
        
        # SEND TO TELEGRAM - FIXED
        print("Sending report to Telegram...")
        parts_count, sent_count, errors = send_report(report_text)
        
        if errors:
            print(f"WARNING: {len(errors)} errors occurred during delivery:")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"SUCCESS: Report sent to {sent_count} destinations ({parts_count} parts)")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
