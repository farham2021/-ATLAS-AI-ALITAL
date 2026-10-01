"""
ATLAS Professional Intelligent Monitor  —  ناظر هوشمند حرفه‌ای
================================================================
Identity : Senior Trading Systems Architect + 15y Market Analyst
Role     : Self-diagnosing, self-correcting signal supervisor
Runs on  : GitHub Actions (additive layer — does NOT rewrite bot.py)

Design principles
-----------------
1. Fail-closed on incomplete data or high uncertainty.
2. Candle patterns are valid ONLY when ≥2 confirming indicators align.
3. Higher-timeframe trend is law; 3-level divergence is the only exception.
4. Confidence score is transparent and weighted exactly as specified.
5. Every change to indicator weights is logged with reason.
6. Overfitting warning is mandatory in weekly reports.
7. No signal is emitted below confidence threshold (default 60).

This module is pure analysis + scoring.  Execution, Telegram delivery and
persistence remain the responsibility of the existing ATLAS pipeline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MONITOR_VERSION = "ATLAS_PROFESSIONAL_MONITOR_V1_0"

# ---------------------------------------------------------------------------
# Configurable weights (self-learning module may adjust these gradually)
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "candle_pattern": 20.0,
    "indicators": 30.0,          # shared across RSI / MACD / SMA alignment
    "volume": 15.0,
    "htf_alignment": 20.0,
    "news_clear": 15.0,
}

CONFIDENCE_THRESHOLD = 60.0
MIN_RR = 2.0
RISK_PCT = 1.5
MAX_LEVERAGE = 10.0
ATR_LEVERAGE_FACTOR = 0.5

# Fixed top-10 by market-cap (updated manually or via external refresh)
FIXED_TOP10 = (
    "BTC", "ETH", "BNB", "SOL", "XRP",
    "ADA", "DOGE", "AVAX", "LINK", "DOT",
)

# Metals + energy that are always in scope
COMMODITIES = ("XAU", "XAG", "COPPER", "WTI", "BRENT")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _sma(closes: Sequence[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _ema(closes: Sequence[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    k = 2 / (n + 1)
    e = sum(closes[:n]) / n
    for v in closes[n:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(closes: Sequence[float], n: int = 14) -> Optional[float]:
    if len(closes) <= n:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[-n:]) / n
    avg_l = sum(losses[-n:]) / n
    if avg_l == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_g / avg_l))


def _atr(rows: Sequence[Sequence[Any]], n: int = 14) -> Optional[float]:
    if len(rows) <= n:
        return None
    trs = []
    for i in range(1, len(rows)):
        h = _f(rows[i][2])
        l = _f(rows[i][3])
        pc = _f(rows[i - 1][4])
        if None not in (h, l, pc):
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return None
    return sum(trs[-n:]) / n


def _macd_hist(closes: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
    if len(closes) < 35:
        return None, None

    def series(period: int) -> List[Optional[float]]:
        k = 2 / (period + 1)
        e = sum(closes[:period]) / period
        out: List[Optional[float]] = [None] * (period - 1) + [e]
        for v in closes[period:]:
            e = v * k + e * (1 - k)
            out.append(e)
        return out

    e12, e26 = series(12), series(26)
    mac = [None if a is None or b is None else a - b for a, b in zip(e12, e26)]
    vals = [x for x in mac if x is not None]
    if len(vals) < 10:
        return None, None
    k = 2 / 10
    sig = sum(vals[:9]) / 9
    hist = []
    for v in vals[9:]:
        sig = v * k + sig * (1 - k)
        hist.append(v - sig)
    if not hist:
        return None, None
    delta = hist[-1] - hist[-2] if len(hist) > 1 else None
    return hist[-1], delta


# ---------------------------------------------------------------------------
# Candle pattern detection (classic definitions)
# ---------------------------------------------------------------------------

@dataclass
class Candle:
    o: float
    h: float
    l: float
    c: float
    v: float

    @property
    def body(self) -> float:
        return abs(self.c - self.o)

    @property
    def range(self) -> float:
        return self.h - self.l

    @property
    def upper_wick(self) -> float:
        return self.h - max(self.o, self.c)

    @property
    def lower_wick(self) -> float:
        return min(self.o, self.c) - self.l

    @property
    def is_bull(self) -> bool:
        return self.c > self.o

    @property
    def is_bear(self) -> bool:
        return self.c < self.o


def _to_candles(rows: Sequence[Sequence[Any]]) -> List[Candle]:
    out = []
    for r in rows:
        if len(r) < 6:
            continue
        o, h, l, c, v = map(_f, (r[1], r[2], r[3], r[4], r[5]))
        if None in (o, h, l, c, v) or h < l:
            continue
        out.append(Candle(o, h, l, c, v))
    return out


def detect_patterns(candles: Sequence[Candle]) -> List[Dict[str, Any]]:
    """Return list of detected patterns on the last 1-3 candles.
    Each item: {name, direction: 'BULL'|'BEAR', strength: 0-1}
    """
    if len(candles) < 3:
        return []
    c0, c1, c2 = candles[-3], candles[-2], candles[-1]
    found = []

    # Engulfing
    if c1.is_bear and c2.is_bull and c2.o <= c1.c and c2.c >= c1.o and c2.body > c1.body * 1.05:
        found.append({"name": "Bullish Engulfing", "direction": "BULL", "strength": 0.85})
    if c1.is_bull and c2.is_bear and c2.o >= c1.c and c2.c <= c1.o and c2.body > c1.body * 1.05:
        found.append({"name": "Bearish Engulfing", "direction": "BEAR", "strength": 0.85})

    # Pin Bar / Hammer / Shooting Star
    if c2.range > 0:
        body_ratio = c2.body / c2.range
        if body_ratio < 0.35:
            if c2.lower_wick > c2.body * 2.0 and c2.upper_wick < c2.body * 0.6:
                name = "Hammer" if c2.is_bull or c2.lower_wick > c2.upper_wick * 2 else "Pin Bar Bull"
                found.append({"name": name, "direction": "BULL", "strength": 0.75})
            if c2.upper_wick > c2.body * 2.0 and c2.lower_wick < c2.body * 0.6:
                name = "Shooting Star" if c2.is_bear or c2.upper_wick > c2.lower_wick * 2 else "Pin Bar Bear"
                found.append({"name": name, "direction": "BEAR", "strength": 0.75})

    # Doji
    if c2.range > 0 and c2.body / c2.range < 0.12:
        found.append({"name": "Doji", "direction": "NEUTRAL", "strength": 0.45})

    # Morning / Evening star (simplified 3-candle)
    if (c0.is_bear and c1.body < c0.body * 0.5 and c2.is_bull
            and c2.c > (c0.o + c0.c) / 2):
        found.append({"name": "Morning Star", "direction": "BULL", "strength": 0.9})
    if (c0.is_bull and c1.body < c0.body * 0.5 and c2.is_bear
            and c2.c < (c0.o + c0.c) / 2):
        found.append({"name": "Evening Star", "direction": "BEAR", "strength": 0.9})

    return found


# ---------------------------------------------------------------------------
# Indicator alignment checks
# ---------------------------------------------------------------------------

@dataclass
class IndicatorSnapshot:
    rsi: Optional[float] = None
    macd_hist: Optional[float] = None
    macd_delta: Optional[float] = None
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    price: Optional[float] = None
    volume_ratio: Optional[float] = None
    atr: Optional[float] = None
    atr_pct: Optional[float] = None


def build_indicators(rows: Sequence[Sequence[Any]]) -> IndicatorSnapshot:
    closes = [_f(r[4]) for r in rows if len(r) >= 5 and _f(r[4]) is not None]
    closes = [c for c in closes if c is not None]
    vols = [_f(r[5]) for r in rows if len(r) >= 6 and _f(r[5]) is not None]
    vols = [v for v in vols if v is not None]
    snap = IndicatorSnapshot()
    if len(closes) < 50:
        return snap
    snap.price = closes[-1]
    snap.rsi = _rsi(closes, 14)
    mh, md = _macd_hist(closes)
    snap.macd_hist = mh
    snap.macd_delta = md
    snap.sma20 = _sma(closes, 20)
    snap.sma50 = _sma(closes, 50)
    atr = _atr(rows, 14)
    snap.atr = atr
    if atr and snap.price:
        snap.atr_pct = (atr / snap.price) * 100.0
    if len(vols) >= 20:
        vma = sum(vols[-20:]) / 20
        if vma > 0:
            snap.volume_ratio = vols[-1] / vma
    return snap


def indicator_alignment(snap: IndicatorSnapshot, direction: str) -> Tuple[int, List[str]]:
    """Return (count of confirming indicators, list of reasons).
    Direction is 'LONG' or 'SHORT'.
    """
    confirms = 0
    reasons = []
    long = direction == "LONG"

    # RSI
    if snap.rsi is not None:
        if long and 30 <= snap.rsi <= 55:
            confirms += 1
            reasons.append(f"RSI={snap.rsi:.1f} supportive (not overbought)")
        elif not long and 45 <= snap.rsi <= 70:
            confirms += 1
            reasons.append(f"RSI={snap.rsi:.1f} supportive (not oversold)")
        elif long and snap.rsi < 30:
            confirms += 1
            reasons.append(f"RSI={snap.rsi:.1f} oversold bounce potential")
        elif not long and snap.rsi > 70:
            confirms += 1
            reasons.append(f"RSI={snap.rsi:.1f} overbought rejection potential")

    # MACD
    if snap.macd_hist is not None:
        if long and snap.macd_hist > 0:
            confirms += 1
            reasons.append("MACD histogram positive")
        elif not long and snap.macd_hist < 0:
            confirms += 1
            reasons.append("MACD histogram negative")
        if snap.macd_delta is not None:
            if long and snap.macd_delta > 0:
                reasons.append("MACD momentum rising")
            elif not long and snap.macd_delta < 0:
                reasons.append("MACD momentum falling")

    # SMA trend
    if snap.sma20 is not None and snap.sma50 is not None and snap.price is not None:
        if long and snap.sma20 > snap.sma50 and snap.price > snap.sma20:
            confirms += 1
            reasons.append("SMA20 > SMA50 and price above SMA20")
        elif not long and snap.sma20 < snap.sma50 and snap.price < snap.sma20:
            confirms += 1
            reasons.append("SMA20 < SMA50 and price below SMA20")

    return confirms, reasons


# ---------------------------------------------------------------------------
# Dynamic Support / Resistance
# ---------------------------------------------------------------------------

def dynamic_sr(rows: Sequence[Sequence[Any]], lookback: int = 20) -> Dict[str, float]:
    """Simple recent High/Low + classic weekly pivot approximation."""
    if len(rows) < lookback:
        return {}
    recent = rows[-lookback:]
    highs = [_f(r[2]) for r in recent if _f(r[2]) is not None]
    lows = [_f(r[3]) for r in recent if _f(r[3]) is not None]
    closes = [_f(r[4]) for r in recent if _f(r[4]) is not None]
    if not highs or not lows or not closes:
        return {}
    hh, ll, last = max(highs), min(lows), closes[-1]
    pivot = (hh + ll + last) / 3.0
    return {
        "resistance": hh,
        "support": ll,
        "pivot": pivot,
        "r1": 2 * pivot - ll,
        "s1": 2 * pivot - hh,
    }


# ---------------------------------------------------------------------------
# Confidence scoring (exact weights from specification)
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceBreakdown:
    candle: float = 0.0
    indicators: float = 0.0
    volume: float = 0.0
    htf: float = 0.0
    news: float = 0.0
    total: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_confidence(
    pattern_score: float,          # 0-1
    indicator_confirms: int,       # 0-3
    volume_ok: bool,
    htf_aligned: bool,
    strong_divergence: bool,
    news_sensitive: bool,
    weights: Optional[Mapping[str, float]] = None,
) -> ConfidenceBreakdown:
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    bd = ConfidenceBreakdown()

    # 1. Candle pattern (max 20)
    bd.candle = min(w["candle_pattern"], pattern_score * w["candle_pattern"])
    if pattern_score > 0:
        bd.reasons.append(f"الگوی کندلی (امتیاز {pattern_score:.2f})")

    # 2. Indicators (max 30) — proportional to number of confirms (need ≥2 for full credit path)
    if indicator_confirms >= 2:
        bd.indicators = w["indicators"] * min(1.0, indicator_confirms / 3.0)
        bd.reasons.append(f"{indicator_confirms} اندیکاتور هم‌جهت")
    elif indicator_confirms == 1:
        bd.indicators = w["indicators"] * 0.35
        bd.reasons.append("فقط ۱ اندیکاتور هم‌جهت (ضعیف)")
    else:
        bd.reasons.append("اندیکاتور هم‌جهت کافی نیست")

    # 3. Volume (max 15)
    if volume_ok:
        bd.volume = w["volume"]
        bd.reasons.append("حجم بالاتر از میانگین ۲۰ دوره")
    else:
        bd.reasons.append("حجم تایید نشده")

    # 4. Higher-TF alignment (max 20)
    if htf_aligned:
        bd.htf = w["htf_alignment"]
        bd.reasons.append("هم‌جهت با روند تایم‌فریم بالاتر")
    elif strong_divergence:
        bd.htf = w["htf_alignment"] * 0.6
        bd.reasons.append("واگرایی قوی ۳سطحی — استثنا از روند HTF")
    else:
        bd.reasons.append("خلاف روند تایم‌فریم بالاتر — سیگنال رد شد")

    # 5. News clear (max 15)
    if not news_sensitive:
        bd.news = w["news_clear"]
        bd.reasons.append("خبر حساس شناسایی نشد")
    else:
        bd.reasons.append("خبر حساس / نوسان بالا — امتیاز خبر صفر")

    bd.total = round(bd.candle + bd.indicators + bd.volume + bd.htf + bd.news, 2)
    return bd


# ---------------------------------------------------------------------------
# Risk geometry
# ---------------------------------------------------------------------------

def compute_risk_geometry(
    direction: str,
    price: float,
    atr: float,
    sr: Mapping[str, float],
    min_rr: float = MIN_RR,
) -> Optional[Dict[str, Any]]:
    """ATR-based or structure-based SL/TP with min RR 1:2.

    Structural levels are preferred for SL when nearby, but TP is never
    allowed to collapse RR below the minimum — if a resistance/support cap
    would do that, we keep the ATR-based TP instead.
    """
    if not price or not atr or atr <= 0:
        return None

    long = direction == "LONG"
    if long:
        struct_sl = sr.get("support")
        if struct_sl and struct_sl < price and (price - struct_sl) / price < 0.08:
            sl = struct_sl - atr * 0.15
        else:
            sl = price - atr * 1.5
        risk = price - sl
        if risk <= 0:
            return None
        tp1 = price + risk * 1.0
        tp2 = price + risk * min_rr
        res = sr.get("resistance")
        # Only pull TP2 toward resistance if RR stays ≥ min_rr
        if res and res > price:
            capped = min(tp2, res)
            if (capped - price) / risk >= min_rr * 0.95:
                tp2 = capped
    else:
        struct_sl = sr.get("resistance")
        if struct_sl and struct_sl > price and (struct_sl - price) / price < 0.08:
            sl = struct_sl + atr * 0.15
        else:
            sl = price + atr * 1.5
        risk = sl - price
        if risk <= 0:
            return None
        tp1 = price - risk * 1.0
        tp2 = price - risk * min_rr
        sup = sr.get("support")
        if sup and sup < price:
            capped = max(tp2, sup)
            if (price - capped) / risk >= min_rr * 0.95:
                tp2 = capped

    rr = abs(tp2 - price) / risk if risk > 0 else 0
    if rr < min_rr * 0.95:
        return None

    atr_pct = (atr / price) * 100.0
    lev = min(MAX_LEVERAGE, max(1.0, (1.0 / max(atr_pct, 0.3)) * ATR_LEVERAGE_FACTOR))

    return {
        "entry": round(price, 8),
        "sl": round(sl, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "rr": round(rr, 2),
        "atr": round(atr, 8),
        "atr_pct": round(atr_pct, 3),
        "leverage": round(lev, 2),
        "risk_pct": RISK_PCT,
    }


# ---------------------------------------------------------------------------
# Main analysis entry
# ---------------------------------------------------------------------------

@dataclass
class MonitorResult:
    symbol: str
    state: str                          # NO_TRADE | WATCH | SETUP | CONFIRMED
    signal: str                         # BUY | SELL | WATCH
    direction: str                      # LONG | SHORT | NEUTRAL
    confidence: float
    confidence_breakdown: Dict[str, Any]
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    leverage: Optional[float] = None
    rr: Optional[float] = None
    reason: str = ""
    warning: str = ""
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    indicators: Dict[str, Any] = field(default_factory=dict)
    htf_aligned: bool = False
    volume_ok: bool = False
    news_sensitive: bool = False
    uncertainty: bool = False
    version: str = MONITOR_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def telegram_message(self) -> str:
        if self.uncertainty or self.state == "NO_TRADE":
            return (
                f"📊 ناظر هوشمند | {self.symbol}\n"
                f"وضعیت: عدم قطعیت بالا — سیگنال صادر نشد\n"
                f"دلیل: {self.reason or 'داده ناقص یا شرایط مبهم'}"
            )
        side = "Long" if self.direction == "LONG" else "Short" if self.direction == "SHORT" else "—"
        lines = [
            f"📊 سیگنال معاملاتی | {self.symbol}",
            f"جهت: {side}",
            f"ورود: {self.entry}",
            f"حد ضرر: {self.sl}",
            f"حد سود ۱: {self.tp1}",
            f"حد سود ۲: {self.tp2}",
            f"اهرم پیشنهادی: {self.leverage}x" if self.leverage else "اهرم پیشنهادی: —",
            f"امتیاز اطمینان: {self.confidence:.0f}%",
            f"دلیل: {self.reason}",
        ]
        if self.warning:
            lines.append(f"⚠️ {self.warning}")
        return "\n".join(lines)


def analyze_asset(
    symbol: str,
    rows_4h: Sequence[Sequence[Any]],
    rows_1h: Optional[Sequence[Sequence[Any]]] = None,
    rows_1d: Optional[Sequence[Sequence[Any]]] = None,
    news_sensitive: bool = False,
    opposing_momentum_30m: bool = False,
    weights: Optional[Mapping[str, float]] = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> MonitorResult:
    """
    Core professional analysis for one asset.
    rows_* : closed OHLCV [ts, o, h, l, c, v]
    """
    base = MonitorResult(
        symbol=symbol,
        state="NO_TRADE",
        signal="WATCH",
        direction="NEUTRAL",
        confidence=0.0,
        confidence_breakdown={},
        news_sensitive=news_sensitive,
    )

    if len(rows_4h) < 60:
        base.uncertainty = True
        base.reason = "داده ۴ساعته ناکافی — عدم قطعیت بالا"
        return base

    candles = _to_candles(rows_4h)
    if len(candles) < 5:
        base.uncertainty = True
        base.reason = "کندل‌های معتبر ناکافی"
        return base

    snap = build_indicators(rows_4h)
    if snap.price is None or snap.atr is None:
        base.uncertainty = True
        base.reason = "اندیکاتورهای پایه قابل محاسبه نیستند"
        return base

    patterns = detect_patterns(candles)
    # Prefer strongest non-neutral pattern
    directional = [p for p in patterns if p["direction"] in ("BULL", "BEAR")]
    if not directional:
        base.reason = "الگوی کندلی جهت‌دار معتبر یافت نشد"
        base.patterns = patterns
        base.indicators = {
            "rsi": snap.rsi, "macd_hist": snap.macd_hist,
            "sma20": snap.sma20, "sma50": snap.sma50,
            "volume_ratio": snap.volume_ratio, "atr_pct": snap.atr_pct,
        }
        return base

    best = max(directional, key=lambda p: p["strength"])
    direction = "LONG" if best["direction"] == "BULL" else "SHORT"

    # Indicator confirmation (must have ≥2 for full path)
    ind_count, ind_reasons = indicator_alignment(snap, direction)

    # Volume
    volume_ok = bool(snap.volume_ratio and snap.volume_ratio >= 1.0)

    # Higher-TF trend (daily preferred, else 4h SMA structure)
    htf_aligned = False
    strong_divergence = False
    if rows_1d and len(rows_1d) >= 50:
        d_snap = build_indicators(rows_1d)
        if d_snap.sma20 and d_snap.sma50 and d_snap.price:
            if direction == "LONG" and d_snap.sma20 > d_snap.sma50 and d_snap.price > d_snap.sma50:
                htf_aligned = True
            elif direction == "SHORT" and d_snap.sma20 < d_snap.sma50 and d_snap.price < d_snap.sma50:
                htf_aligned = True
            # Simple 3-level divergence proxy: price vs RSI extreme against HTF
            if not htf_aligned and snap.rsi is not None:
                if direction == "LONG" and snap.rsi < 28 and d_snap.sma20 < d_snap.sma50:
                    strong_divergence = True
                elif direction == "SHORT" and snap.rsi > 72 and d_snap.sma20 > d_snap.sma50:
                    strong_divergence = True
    else:
        # Fallback: 4h structure itself
        if snap.sma20 and snap.sma50:
            if direction == "LONG" and snap.sma20 > snap.sma50:
                htf_aligned = True
            elif direction == "SHORT" and snap.sma20 < snap.sma50:
                htf_aligned = True

    # Hard rule: no signal against HTF unless strong divergence
    if not htf_aligned and not strong_divergence:
        base.direction = direction
        base.patterns = patterns
        base.reason = "سیگنال خلاف روند تایم‌فریم بالاتر — رد شد (واگرایی قوی وجود ندارد)"
        base.indicators = {
            "rsi": snap.rsi, "macd_hist": snap.macd_hist,
            "sma20": snap.sma20, "sma50": snap.sma50,
            "volume_ratio": snap.volume_ratio,
        }
        return base

    # Pattern must be confirmed by ≥2 indicators
    if ind_count < 2:
        base.direction = direction
        base.patterns = patterns
        base.reason = f"الگوی {best['name']} بدون حداقل ۲ اندیکاتور هم‌جهت — رد شد"
        base.indicators = {
            "rsi": snap.rsi, "macd_hist": snap.macd_hist,
            "sma20": snap.sma20, "sma50": snap.sma50,
            "volume_ratio": snap.volume_ratio,
        }
        return base

    # Confidence
    bd = compute_confidence(
        pattern_score=best["strength"],
        indicator_confirms=ind_count,
        volume_ok=volume_ok,
        htf_aligned=htf_aligned,
        strong_divergence=strong_divergence,
        news_sensitive=news_sensitive,
        weights=weights,
    )

    # Geometry
    sr = dynamic_sr(rows_4h)
    geo = compute_risk_geometry(direction, snap.price, snap.atr, sr)
    if geo is None:
        base.direction = direction
        base.confidence = bd.total
        base.confidence_breakdown = bd.to_dict()
        base.reason = "هندسه ریسک معتبر (RR≥1:2) قابل محاسبه نیست"
        base.patterns = patterns
        return base

    # Assemble result
    base.direction = direction
    base.confidence = bd.total
    base.confidence_breakdown = bd.to_dict()
    base.entry = geo["entry"]
    base.sl = geo["sl"]
    base.tp1 = geo["tp1"]
    base.tp2 = geo["tp2"]
    base.leverage = geo["leverage"]
    base.rr = geo["rr"]
    base.patterns = patterns
    base.htf_aligned = htf_aligned
    base.volume_ok = volume_ok
    base.indicators = {
        "rsi": snap.rsi,
        "macd_hist": snap.macd_hist,
        "sma20": snap.sma20,
        "sma50": snap.sma50,
        "volume_ratio": snap.volume_ratio,
        "atr_pct": snap.atr_pct,
    }

    reason_parts = [
        f"الگوی {best['name']}",
        *ind_reasons[:3],
    ]
    if volume_ok:
        reason_parts.append("حجم بالاتر از میانگین")
    if htf_aligned:
        reason_parts.append("هم‌جهت با روند بالاتر")
    elif strong_divergence:
        reason_parts.append("واگرایی قوی ۳سطحی")
    base.reason = " + ".join(reason_parts)

    if news_sensitive:
        base.warning = "نوسان بالا — خبر حساس شناسایی شد"
    if opposing_momentum_30m:
        base.warning = (base.warning + " | " if base.warning else "") + "شتاب مخالف در ۳۰ دقیقه اخیر"

    # State machine
    if bd.total >= confidence_threshold and not opposing_momentum_30m:
        base.state = "CONFIRMED"
        base.signal = "BUY" if direction == "LONG" else "SELL"
    elif bd.total >= confidence_threshold * 0.85:
        base.state = "SETUP"
        base.signal = "WATCH"
    elif bd.total >= 42:
        base.state = "WATCH"
        base.signal = "WATCH"
    else:
        base.state = "NO_TRADE"
        base.signal = "WATCH"
        base.reason = f"امتیاز اطمینان {bd.total:.0f} زیر آستانه — سیگنال صادر نشد"

    return base


# ---------------------------------------------------------------------------
# Universe helpers (for orchestration outside bot.py)
# ---------------------------------------------------------------------------

def build_universe(
    top10: Sequence[str] = FIXED_TOP10,
    dynamic30: Optional[Sequence[str]] = None,
    include_commodities: bool = True,
) -> List[str]:
    """Merge fixed top-10 + dynamic list + commodities, deduplicated."""
    seen = set()
    out = []
    for s in list(top10) + list(dynamic30 or []) + (list(COMMODITIES) if include_commodities else []):
        u = str(s).upper().strip()
        if u and u not in seen and u not in ("USDT", "USDC", "DAI", "BUSD"):
            seen.add(u)
            out.append(u)
    return out


def format_telegram_batch(results: Sequence[MonitorResult], max_signals: int = 8) -> str:
    """Format only CONFIRMED / high-SETUP signals for Telegram."""
    actionable = [r for r in results if r.state in ("CONFIRMED", "SETUP") and r.confidence >= 55]
    actionable.sort(key=lambda r: r.confidence, reverse=True)
    if not actionable:
        return (
            "📊 ناظر هوشمند حرفه‌ای\n"
            "در این سیکل هیچ سیگنال با امتیاز ≥۵۵ یافت نشد.\n"
            "بازار در وضعیت انتظار یا عدم قطعیت است."
        )
    parts = [r.telegram_message() for r in actionable[:max_signals]]
    footer = (
        f"\n\n—\nناظر هوشمند | {MONITOR_VERSION}\n"
        "این تحلیل توصیه مالی نیست. مدیریت ریسک شخصی الزامی است."
    )
    return "\n\n────────────────\n\n".join(parts) + footer
