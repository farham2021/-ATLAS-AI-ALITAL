#!/usr/bin/env python3
"""ATLAS AI v12 reliable analytical engine."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import math

@dataclass
class SetupResult:
    symbol: str
    level: str
    action: str
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    rr_tp1: Optional[float] = None
    rr_tp2: Optional[float] = None
    confidence: float = 0.0
    required_conditions: List[str] = field(default_factory=list)
    missing_conditions: List[str] = field(default_factory=list)
    reason: str = ""
    timestamp: str = ""
    def to_dict(self): return asdict(self)

class DataValidator:
    WEIGHTS={"tgju":.95,"kraken":.95,"okx":.90,"coingecko":.90,"coinglass":.90,"tradingview":.85,"unknown":.30}
    def validate(self,value,source="unknown",timestamp=None):
        now=datetime.now(timezone.utc).timestamp(); ts=timestamp or now
        try: age=max(0,now-float(ts))
        except (TypeError,ValueError): age=float("inf")
        freshness=1 if age<=60 else .9 if age<=300 else .7 if age<=3600 else .4
        quality=freshness*self.WEIGHTS.get(str(source).lower(),.3)
        valid=value not in (None,"","DATA_UNAVAILABLE")
        if isinstance(value,(int,float)) and not math.isfinite(float(value)): valid=False
        return {"value":value,"source":source,"timestamp":ts,"age_seconds":age,"quality_score":round(quality,3),"valid":valid}

class ReliableAnalyticalEngine:
    def __init__(self,min_executable_rr=1.5,min_watch_rr=1.0):
        self.validator=DataValidator(); self.min_executable_rr=min_executable_rr; self.min_watch_rr=min_watch_rr
    @staticmethod
    def num(d,k):
        try:
            v=float(d.get(k)); return v if math.isfinite(v) else None
        except (TypeError,ValueError): return None
    def levels(self,d):
        p=self.num(d,"price")
        if p is None or p<=0:return None,None
        s=[]; r=[]
        for k in ("support","sma_200","low_30d"):
            v=self.num(d,k)
            if v is not None and v<p:s.append(v)
        for v in d.get("supports",[]) or []:
            try:
                v=float(v)
                if v<p:s.append(v)
            except: pass
        for k in ("resistance","sma_50","high_30d"):
            v=self.num(d,k)
            if v is not None and v>p:r.append(v)
        for v in d.get("resistances",[]) or []:
            try:
                v=float(v)
                if v>p:r.append(v)
            except: pass
        return (max(s) if s else None),(min(r) if r else None)
    def analyze_coin(self,symbol,d):
        now=datetime.now(timezone.utc).isoformat(); p=self.num(d,"price")
        if p is None:return SetupResult(symbol,"NO_VALID_SETUP","NO TRADE",reason="قیمت معتبر در دسترس نیست",timestamp=now)
        s,r=self.levels(d)
        if s is None or r is None:return SetupResult(symbol,"NO_VALID_SETUP","NO TRADE",reason="حمایت/مقاومت معتبر برای R/R وجود ندارد",timestamp=now)
        risk=p-s
        if risk<=0:return SetupResult(symbol,"NO_VALID_SETUP","NO TRADE",reason="ریسک نامعتبر",timestamp=now)
        tp2=r+.30*(r-p); rr1=(r-p)/risk; rr2=(tp2-p)/risk
        trend=str(d.get("trend","neutral")).lower(); rsi=self.num(d,"rsi"); funding=self.num(d,"funding_rate"); vr=self.num(d,"volume_ratio"); sc=int(d.get("support_count",0) or 0)
        cond=[]; miss=[]
        (cond if trend in ("bullish","strong_bullish") else miss).append("روند صعودی")
        (cond if max(rr1,rr2)>=self.min_executable_rr else miss).append(f"R/R حداقل {self.min_executable_rr:.1f}")
        (cond if rsi is None or rsi<70 else miss).append("RSI زیر 70")
        (cond if funding is None or funding<.0005 else miss).append("Funding کنترل‌شده")
        (cond if vr is None or vr<=2.5 else miss).append("حجم بدون Spike خطرناک")
        (cond if sc>=2 else miss).append("حداقل دو تأیید حمایت")
        executable=max(rr1,rr2)>=self.min_executable_rr and trend in ("bullish","strong_bullish") and len(cond)>=5
        watch=max(rr1,rr2)>=self.min_watch_rr and trend in ("bullish","strong_bullish","neutral") and (rsi is None or rsi<75)
        if executable: level,action,conf,reason="EXECUTABLE","BUY CONFIRMATION",.85,"هم‌گرایی روند، R/R و شرایط ریسک تأیید شده است."
        elif watch: level,action,conf,reason="BEST_WATCH","WAIT",.55,"بهترین کاندید پایش؛ هنوز یک یا چند شرط ورود قطعی کم است."
        else: level,action,conf,reason="NO_VALID_SETUP","NO TRADE",0,"شرایط کافی برای ستاپ معتبر وجود ندارد."
        return SetupResult(symbol,level,action,p,s,r,tp2,rr1,rr2,conf,cond,miss,reason,now)
    @staticmethod
    def health_check(results):
        ok=sum(1 for r in results if r.get("price") not in (None,"","DATA_UNAVAILABLE")); return f"📊 Health: {ok}/{len(results)} assets analyzed successfully"
    @staticmethod
    def volume_spike_warning(r):
        try:
            vr=float(r.get("volume_ratio")); return f"⚠️ حجم غیرعادی: {vr:.2f}x میانگین" if vr>2.5 else None
        except: return None
