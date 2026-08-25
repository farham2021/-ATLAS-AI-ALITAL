#!/usr/bin/env python3
"""ATLAS AI v12 reporting, TGJU and Telegram CSV layer."""
from __future__ import annotations
import csv,io,os,re
from datetime import datetime
from typing import Any,Optional
import requests
from atlas_v12_upgrade import ReliableAnalyticalEngine
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN",""); TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","")
TGJU_USD="https://www.tgju.org/profile/price_dollar_rl"; TGJU_USDT="https://www.tgju.org/profile/price_dollar_usdt"

def _num(x):
    try:return float(str(x).replace(",","").strip())
    except:return None

def fetch_tgju_rate(url,timeout=10):
    try:
        t=requests.get(url,timeout=timeout,headers={"User-Agent":"Mozilla/5.0 ATLAS-AI/12"}).text
        for p in [r'class=["\'][^"\']*(?:price|value)[^"\']*["\'][^>]*>\s*([\d,]+)',r'data-field=["\']price["\'][^>]*>\s*([\d,]+)',r'([\d]{2,3}(?:,\d{3}){1,3})']:
            m=re.search(p,t,re.I|re.S)
            if m:
                v=_num(m.group(1))
                if v is not None:return v
    except requests.RequestException:return None
    return None

def get_tgju_rates():
    return {"usd_toman":fetch_tgju_rate(TGJU_USD),"usdt_toman":fetch_tgju_rate(TGJU_USDT),"source":"tgju.org","timestamp":datetime.now().isoformat()}

CSV_COLUMNS=["Timestamp","Symbol","Status","Action","Price","Support","Resistance","Entry","SL","TP1","TP2","RR_TP1","RR_TP2","Confidence","Trend_4H","Trend_D1","RSI","MACD","Volume","Volume_Ratio","ATR_Pct","Liquidity","MarketCap","Setup_Level","Reason","Missing_Conditions","USD_Toman_TGJU","USDT_Toman_TGJU"]
def _status(level):return {"EXECUTABLE":"BUY","BEST_WATCH":"WATCH","NO_VALID_SETUP":"HOLD"}.get(level,"HOLD")
def generate_csv_report(results,portfolio_symbols=None,tgju_rates=None):
    rates=tgju_rates or get_tgju_rates(); out=io.StringIO(); w=csv.DictWriter(out,fieldnames=CSV_COLUMNS); w.writeheader()
    for r in sorted(results,key=lambda x:float(x.get("confidence",0) or 0),reverse=True):
        w.writerow({"Timestamp":datetime.now().isoformat(),"Symbol":r.get("symbol",r.get("coin","")),"Status":_status(r.get("setup_level",r.get("level",""))),"Action":r.get("action","NO TRADE"),"Price":r.get("price",""),"Support":r.get("support",""),"Resistance":r.get("resistance",""),"Entry":r.get("entry",""),"SL":r.get("stop_loss",r.get("sl","")),"TP1":r.get("tp1",""),"TP2":r.get("tp2",""),"RR_TP1":r.get("rr_tp1",r.get("rr","")),"RR_TP2":r.get("rr_tp2",""),"Confidence":r.get("confidence",0),"Trend_4H":r.get("h4_trend",r.get("trend","UNKNOWN")),"Trend_D1":r.get("d1_trend","UNKNOWN"),"RSI":r.get("rsi",""),"MACD":r.get("macd",""),"Volume":r.get("volume",""),"Volume_Ratio":r.get("volume_ratio",""),"ATR_Pct":r.get("atr_pct",""),"Liquidity":r.get("liquidity",""),"MarketCap":r.get("market_cap",""),"Setup_Level":r.get("setup_level",r.get("level","")),"Reason":r.get("reason",""),"Missing_Conditions":"; ".join(r.get("missing_conditions",[]) or []),"USD_Toman_TGJU":rates.get("usd_toman") if rates.get("usd_toman") is not None else "DATA_UNAVAILABLE","USDT_Toman_TGJU":rates.get("usdt_toman") if rates.get("usdt_toman") is not None else "DATA_UNAVAILABLE"})
    return out.getvalue()

def generate_institutional_csv(results,raw_data=None,tgju_rates=None):
    raw_data=raw_data or {}; rates=tgju_rates or get_tgju_rates(); fields=["timestamp","symbol","setup_level","action","entry","stop_loss","tp1","tp2","rr_tp1","rr_tp2","confidence","reason","source","data_timestamp","quality_score","price","rsi","funding_rate","oi_trend","volume","volume_ratio","market_cap","usd_toman_tgju","usdt_toman_tgju","required_conditions","missing_conditions"]
    out=io.StringIO(); w=csv.DictWriter(out,fieldnames=fields); w.writeheader()
    for r in results:
        s=r.get("symbol",r.get("coin","")); d=raw_data.get(s,{})
        w.writerow({"timestamp":datetime.now().isoformat(),"symbol":s,"setup_level":r.get("setup_level",r.get("level","")),"action":r.get("action","NO TRADE"),"entry":r.get("entry",""),"stop_loss":r.get("stop_loss",r.get("sl","")),"tp1":r.get("tp1",""),"tp2":r.get("tp2",""),"rr_tp1":r.get("rr_tp1",""),"rr_tp2":r.get("rr_tp2",""),"confidence":r.get("confidence",0),"reason":r.get("reason",""),"source":d.get("source","unknown"),"data_timestamp":d.get("timestamp",""),"quality_score":d.get("quality_score",""),"price":d.get("price",""),"rsi":d.get("rsi",""),"funding_rate":d.get("funding_rate",""),"oi_trend":d.get("oi_trend",""),"volume":d.get("volume",""),"volume_ratio":d.get("volume_ratio",""),"market_cap":d.get("market_cap",""),"usd_toman_tgju":rates.get("usd_toman") if rates.get("usd_toman") is not None else "DATA_UNAVAILABLE","usdt_toman_tgju":rates.get("usdt_toman") if rates.get("usdt_toman") is not None else "DATA_UNAVAILABLE","required_conditions":"|".join(r.get("required_conditions",[]) or []),"missing_conditions":"|".join(r.get("missing_conditions",[]) or [])})
    return out.getvalue()

def csv_filename(prefix="atlas_report"):return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
def send_csv_via_telegram(csv_content,filename,chat_id=None):
    if not TELEGRAM_TOKEN:raise RuntimeError("TELEGRAM_TOKEN is not configured")
    chat_id=chat_id or TELEGRAM_CHAT_ID
    if not chat_id:raise RuntimeError("TELEGRAM_CHAT_ID is not configured")
    r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",files={"document":(filename,csv_content.encode("utf-8-sig"),"text/csv")},data={"chat_id":chat_id},timeout=30); r.raise_for_status(); return r

def send_csv_report(results,portfolio_symbols=None,institutional=False):
    rates=get_tgju_rates(); c=generate_institutional_csv(results,tgju_rates=rates) if institutional else generate_csv_report(results,portfolio_symbols,rates); return send_csv_via_telegram(c,csv_filename("atlas_institutional" if institutional else "atlas_report"))
def best_setup_block(results):
    ex=[r for r in results if r.get("setup_level")=="EXECUTABLE"]; wa=[r for r in results if r.get("setup_level")=="BEST_WATCH"]
    if ex:
        r=max(ex,key=lambda x:float(x.get("confidence",0) or 0)); return f"🔥 BEST SETUP: {r.get('symbol')} — BUY\nEntry: {r.get('entry')} | SL: {r.get('stop_loss')} | TP1: {r.get('tp1')} | TP2: {r.get('tp2')} | R/R: {r.get('rr_tp1')}"
    if wa:
        r=max(wa,key=lambda x:float(x.get("confidence",0) or 0)); return f"🔥 BEST WATCH: {r.get('symbol')} — WAIT\nEntry reference: {r.get('entry','N/A')} | TP1: {r.get('tp1','N/A')} | TP2: {r.get('tp2','N/A')}\nشرایط باقی‌مانده: {'; '.join(r.get('missing_conditions',[]) or []) or 'تأیید بیشتر لازم است'}"
    return "⛔ NO VALID SETUP — در این اجرا ستاپ قابل اتکا وجود ندارد."
def build_report(results,title="ATLAS AI — MARKET 4H"):
    rates=get_tgju_rates(); usd=rates['usd_toman'] if rates['usd_toman'] is not None else 'DATA_UNAVAILABLE'; usdt=rates['usdt_toman'] if rates['usdt_toman'] is not None else 'DATA_UNAVAILABLE'; return "\n".join([f"🤖 {title}",f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",f"💵 USD/Toman (TGJU): {usd}",f"₮ USDT/Toman (TGJU): {usdt}","",best_setup_block(results),"",ReliableAnalyticalEngine.health_check(results)])
def split_telegram(text,limit=3900):return [text[i:i+limit] for i in range(0,len(text),limit)] or [""]
def send_report(text,results=None,portfolio_symbols=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:raise RuntimeError("Telegram credentials are not configured")
    for part in split_telegram(text):requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",data={"chat_id":TELEGRAM_CHAT_ID,"text":part},timeout=30).raise_for_status()
    if results:
        send_csv_report(results,portfolio_symbols,False); send_csv_report(results,portfolio_symbols,True)
def personal_report(*args,**kwargs):return build_report(*args,title="ATLAS AI — PERSONAL 4H",**kwargs)
if __name__=="__main__":print("ATLAS AI v12 loaded successfully.")
