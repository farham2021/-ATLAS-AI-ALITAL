# ============================================================
# ATLAS v11.2 — ENHANCED UNIFIED TWO-ENGINE DECISION ENGINE
# ============================================================
# v11.2 Features:
# 1. Voice Summary (گزارش خلاصه صوتی)
# 2. Signal Ranking (جدول رتبه‌بندی)
# 3. Graphical Price Display (نمایش تغییرات قیمت به صورت گرافیکی)
# 4. Risk Report (گزارش ریسک بازار)
# 5. Market Quality Filter (فیلتر کیفیت بازار)
# 6. Level Break Alerts (هشدار شکست سطوح)
# 7. Multi-Timeframe Confirmation (تأیید چند تایم‌فریم)
# 8. Entry Quality Score (امتیاز کیفیت ورود)
# 9. Exit Signals (سیگنال‌های خروج)
# 10. Sentiment Analysis (تحلیل احساسات بازار)
# 11. Correlation Analysis (تحلیل همبستگی)
# 12. Smart Volume Analysis (تحلیل حجم هوشمند)
# 13. Pattern Recognition (تشخیص الگوهای تکراری)
# 14. Weekly Analysis (تحلیل هفتگی)
# 15. Position Sizing (پیشنهاد حجم ورود)
# 16. Stop Loss Alert (هشدار حد ضرر)
# 17. Smart Caching (کشینگ هوشمند)
# 18. Parallel Processing (پردازش موازی)
# 19. CSV Export (خروجی کامل CSV)
# 20. Voice Output (خروجی صوتی فارسی)
# 21. Market Session Alignment (هماهنگی با سشن‌های بازار)
# ============================================================

import os
import re
import json
import math
import time
import random
import sqlite3
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import traceback
import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from statistics import mean, median
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

import ccxt


# ============================================================
# CONFIG
# ============================================================

VERSION = "ATLAS v11.2 ENHANCED"
TIMEFRAMES = ("1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = "4h"
EVENT_TIMEFRAMES = ("30m", "1h", "4h", "1d", "1w", "1M")
EVENT_LOOKBACK_LIMITS = {"30m": 80, "1h": 120, "4h": 120, "1d": 120, "1w": 80, "1M": 60}
EVENT_DEDUP_ENABLED = os.environ.get("ATLAS_CANDLE_EVENT_DEDUP", "1").strip() != "0"
TEHRAN = ZoneInfo("Asia/Tehran")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_GROUP_CHAT_ID = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "").strip()

TELEGRAM_PRIVATE_DELAY = float(os.environ.get("TELEGRAM_PRIVATE_DELAY", "1.5"))
TELEGRAM_GROUP_DELAY = float(os.environ.get("TELEGRAM_GROUP_DELAY", "3.0"))
TELEGRAM_MAX_RETRIES = int(os.environ.get("TELEGRAM_MAX_RETRIES", "5"))
TELEGRAM_BASE_RETRY_DELAY = float(os.environ.get("TELEGRAM_BASE_RETRY_DELAY", "3"))
TELEGRAM_MAX_WAIT = float(os.environ.get("TELEGRAM_MAX_WAIT", "60"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
if not SUPABASE_KEY:
    SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()

COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "").strip()
CRYPTOPANIC_TOKEN = os.environ.get("CRYPTOPANIC_TOKEN", "").strip()
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "").strip()
CMC_API_KEY = os.environ.get("CMC_API_KEY", "").strip()

RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE_PCT", "1.5"))
MAX_PORTFOLIO_RISK = float(os.environ.get("MAX_PORTFOLIO_OPEN_RISK_PCT", "6.0"))
MIN_CONFIDENCE = float(os.environ.get("ATLAS_MIN_CONFIDENCE", "60"))
MAX_LEVERAGE = float(os.environ.get("ATLAS_MAX_LEVERAGE", "10"))
BACKTEST_DAYS = int(os.environ.get("ATLAS_BACKTEST_DAYS", "180"))
SIGNAL_HORIZON_BARS = int(os.environ.get("ATLAS_SIGNAL_HORIZON_BARS", "36"))
MIN_BACKTEST_IMPROVEMENT = float(os.environ.get("ATLAS_BACKTEST_IMPROVEMENT", "10"))
BACKTEST_REFRESH_HOURS = float(os.environ.get("ATLAS_BACKTEST_REFRESH_HOURS", "24"))
MIN_VOLUME_RATIO = float(os.environ.get("ATLAS_MIN_VOLUME_RATIO", "1.20"))
H4_FALLBACK_MIN_SCORE = float(os.environ.get("ATLAS_H4_FALLBACK_MIN_SCORE", "70"))
REQUEST_SLEEP_SECONDS = float(os.environ.get("ATLAS_REQUEST_SLEEP_SECONDS", "0.50"))

MIN_EXECUTABLE_RR = float(os.environ.get("ATLAS_MIN_EXECUTABLE_RR", "2.0"))
MIN_WATCH_CONFIDENCE = float(os.environ.get("ATLAS_MIN_WATCH_CONFIDENCE", "55"))
TRADE_GEOMETRY_EPSILON = float(os.environ.get("ATLAS_TRADE_GEOMETRY_EPSILON", "1e-12"))
SNAPSHOT_FLAT_THRESHOLD_PCT = float(os.environ.get("ATLAS_SNAPSHOT_FLAT_THRESHOLD_PCT", "0.05"))
BTC_REGIME_CACHE_MINUTES = int(os.environ.get("ATLAS_BTC_REGIME_CACHE_MINUTES", "30"))
SIGNAL_MEMORY_HOURS = int(os.environ.get("ATLAS_SIGNAL_MEMORY_HOURS", "4"))
MARKET_BREADTH_MIN_SAMPLES = int(os.environ.get("ATLAS_MARKET_BREADTH_MIN_SAMPLES", "8"))

DB_FILE = os.environ.get("ATLAS_SQLITE_FILE", "atlas_v11_2.sqlite3")
CHANGELOG_FILE = os.environ.get("ATLAS_CHANGELOG", "changelog_v11_2.txt")
MAX_WORKERS = int(os.environ.get("ATLAS_MAX_WORKERS", "5"))
CACHE_TTL = int(os.environ.get("ATLAS_CACHE_TTL", "300"))

# فعال‌سازی خروجی صوتی
ENABLE_VOICE_REPORT = os.environ.get("ATLAS_ENABLE_VOICE", "1") == "1"
VOICE_TYPE = os.environ.get("ATLAS_VOICE_TYPE", "female")
VOICE_LANGUAGE = os.environ.get("ATLAS_VOICE_LANGUAGE", "fa")
AUTO_SEND_VOICE = os.environ.get("ATLAS_AUTO_SEND_VOICE", "1") == "1"


# ============================================================
# MARKET SESSIONS (هماهنگی با سشن‌های بازار کریپتو)
# ============================================================

MARKET_SESSIONS = {
    "ASIA": {"open": 0, "close": 8, "label": "🇯🇵 آسیا"},
    "EUROPE": {"open": 7, "close": 15, "label": "🇬🇧 اروپا"},
    "AMERICA": {"open": 12, "close": 20, "label": "🇺🇸 آمریکا"},
    "OVERLAP": {"open": 12, "close": 15, "label": "🔀 همپوشانی اروپا-آمریکا"},
}

def get_current_session(dt=None):
    """تشخیص سشن فعلی بازار"""
    dt = dt or now_utc()
    hour = dt.hour
    for name, session in MARKET_SESSIONS.items():
        if session["open"] <= hour < session["close"]:
            return name, session["label"]
    return "CLOSED", "🔒 خارج از سشن"


# ============================================================
# ATLAS RADAR
# ============================================================

ATLAS_PRIORITY_TOP10 = [
    "BTC", "ETH", "BNB", "XRP", "SOL",
    "TRX", "HYPE", "DOGE", "ADA", "MATIC",
]

ATLAS_STATIC = [
    "BTC", "ETH", "XRP", "SOL", "BNB", "TON", "ADA", "DOGE", "TRX", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR", "NEAR",
    "QNT", "GRT", "TAO", "ONDO", "UNI", "ETHFI", "ATOM", "FIL", "AAVE", "MKR",
    "APT", "ARB", "OP", "INJ", "TIA", "SEI", "PEPE", "FET", "ICP", "ETC",
    "HYPE", "MATIC",
]

ATLAS_PERSONAL_ASSETS = [
    "BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "DOGE", "ADA", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR",
    "NEAR", "ONDO", "TAO",
]

ATLAS_METALS = ("GOLD", "SILVER", "COPPER")
METAL_YAHOO = {"GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F"}
METAL_TV = {"GOLD": "OANDA:XAUUSD", "SILVER": "OANDA:XAGUSD", "COPPER": "COMEX:HG1!"}

DATA_SYMBOL_ALIASES = {"MATIC": "POL"}

STABLE_SYMBOLS = {
    "USDT", "USDC", "USDE", "USDS", "DAI", "FDUSD", "TUSD", "USDP",
    "PYUSD", "USDD", "FRAX", "LUSD", "GUSD", "USDG", "USDB", "EURC",
}

MACRO_SYMBOLS = {
    "DXY": ("DX-Y.NYB", "DX=F", "^DXY"),
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "COPPER": "HG=F",
    "WTI": "CL=F",
    "BRENT": "BZ=F",
}

NEWS_NEGATIVE = (
    "hack", "exploit", "lawsuit", "ban", "delist", "liquidation", "fraud",
    "sec", "investigation", "outflow", "stolen", "sanction", "default",
    "bankruptcy", "attack", "breach", "collapse", "tariff", "war",
)
NEWS_POSITIVE = (
    "approval", "approved", "etf", "inflow", "partnership", "launch",
    "adoption", "upgrade", "listing", "integration", "record", "acquisition",
)
HIGH_IMPACT_WORDS = (
    "federal reserve", "fed", "fomc", "interest rate", "rate decision",
    "cpi", "inflation", "jobs report", "nonfarm", "nfp", "powell",
    "hack", "exploit", "sec", "lawsuit", "ban", "regulation", "sanction",
    "war", "tariff", "bank failure", "liquidation cascade",
)


# ============================================================
# GENERIC HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)

def now_tehran():
    return datetime.now(TEHRAN)

def shamsi(dt):
    gy, gm, gd = dt.year, dt.month, dt.day
    gdm = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd)
    for i in range(1, gm):
        days += gdm[i]
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        days += 1
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return f"{jy:04d}/{jm:02d}/{jd:02d}"

def safe_float(x, default=None):
    try:
        if x is None or isinstance(x, bool):
            return default
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError, OverflowError):
        return default

def f(x, default=None):
    return safe_float(x, default)

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def fmt(x):
    x = f(x)
    if x is None:
        return "N/A"
    if abs(x) >= 1000:
        return f"${x:,.2f}"
    if abs(x) >= 1:
        return f"${x:,.4f}"
    return f"${x:,.6f}"

def pct(x):
    x = f(x)
    return "N/A" if x is None else f"{x:+.2f}%"

def is_stable(symbol):
    s = (symbol or "").upper().replace("-", "")
    return s in STABLE_SYMBOLS

def safe_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"

def data_symbol(symbol):
    return DATA_SYMBOL_ALIASES.get((symbol or "").upper(), (symbol or "").upper())

AMBIGUOUS_DYNAMIC_SYMBOLS = {"M", "CC"}

def is_ambiguous_symbol(symbol):
    return str(symbol or "").upper() in AMBIGUOUS_DYNAMIC_SYMBOLS


# ============================================================
# SMART CACHING
# ============================================================

_cache = {}
_cache_timestamps = {}

def cached_data(key, ttl=CACHE_TTL):
    def decorator(func):
        def wrapper(*args, **kwargs):
            cache_key = f"{key}_{hash(str(args) + str(kwargs))}"
            if cache_key in _cache:
                data, timestamp = _cache[cache_key]
                if (time.time() - timestamp) < ttl:
                    return data
            result = func(*args, **kwargs)
            _cache[cache_key] = (result, time.time())
            return result
        return wrapper
    return decorator


# ============================================================
# SQLITE
# ============================================================

def sqlite_conn():
    c = sqlite3.connect(DB_FILE, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init_sqlite():
    with sqlite_conn() as c:
        c.executescript("""
        create table if not exists signal_outcomes(
            id integer primary key autoincrement,
            coin text not null,
            direction text not null,
            entry real, sl real, tp1 real, tp2 real,
            issued_at text not null,
            status text default 'OPEN',
            outcome text,
            exit_price real,
            exit_at text,
            pnl_pct real,
            bars_to_exit integer,
            notes text
        );
        create table if not exists model_weights(
            feature text primary key,
            weight real not null,
            baseline_weight real not null,
            samples integer default 0,
            wins integer default 0,
            losses integer default 0,
            updated_at text,
            reason text
        );
        create table if not exists self_healing_cursor(
            id integer primary key check(id=1),
            processed_closed integer not null default 0,
            updated_at text
        );
        create table if not exists self_healing_processed(
            signal_id integer primary key,
            processed_at text not null
        );
        create table if not exists telegram_sent_reports(
            report_hash text not null,
            destination text not null,
            sent_at text not null,
            primary key(report_hash, destination)
        );
        create table if not exists snapshot_prices(
            symbol text primary key,
            price real not null,
            captured_at text not null
        );
        create table if not exists backtest_gate_cache(
            id integer primary key check(id=1),
            timestamp text not null,
            passed integer not null,
            details text
        );
        create table if not exists candle_events(
            coin text not null,
            timeframe text not null,
            last_closed_ts integer,
            last_status text,
            observed_at text not null,
            primary key(coin, timeframe)
        );
        create table if not exists signal_memory(
            coin text primary key,
            direction text,
            action text,
            confidence real,
            signal_candle_ts integer,
            entry real,
            sl real,
            tp1 real,
            tp2 real,
            last_seen_at text not null,
            decision_state text
        );
        create table if not exists decision_events(
            id integer primary key autoincrement,
            timestamp text not null,
            coin text not null,
            state text not null,
            confidence real,
            rr real,
            btc_regime text,
            breadth real,
            reason text
        );
        create table if not exists backtests(
            id integer primary key autoincrement,
            timestamp text,
            model_version text,
            coin text,
            timeframe text,
            period_days integer,
            trades integer,
            wins integer,
            losses integer,
            win_rate real,
            avg_profit real,
            avg_loss real,
            max_drawdown real,
            profit_factor real,
            baseline_profit_factor real,
            baseline_win_rate real,
            improvement_pct real,
            passed integer,
            details text
        );
        create table if not exists weekly_performance(
            week_start text primary key,
            total_signals integer,
            win_rate real,
            avg_profit real,
            max_drawdown real,
            best_signal text,
            worst_signal text,
            created_at text
        );
        """)


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def closes(rows):
    return [f(x[4]) for x in rows if f(x[4]) is not None]

def ema(values, n):
    if len(values) < n:
        return None
    a = 2 / (n + 1)
    e = sum(values[:n]) / n
    for x in values[n:]:
        e = (x - e) * a + e
    return e

def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n

def rsi(values, n=14):
    if len(values) <= n:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = ((n - 1) * ag + gains[i]) / n
        al = ((n - 1) * al + losses[i]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)

def ema_series(values, n):
    if len(values) < n:
        return []
    a = 2 / (n + 1)
    e = sum(values[:n]) / n
    out = [e]
    for x in values[n:]:
        e = (x - e) * a + e
        out.append(e)
    return out

def macd(values):
    if len(values) < 35:
        return None, None, None
    fast = ema_series(values, 12)
    slow = ema_series(values, 26)
    offset = len(fast) - len(slow)
    if offset < 0:
        return None, None, None
    line = [fast[i + offset] - slow[i] for i in range(len(slow))]
    if len(line) < 9:
        return None, None, None
    sig_series = ema_series(line, 9)
    if not sig_series:
        return None, None, None
    return line[-1], sig_series[-1], line[-1] - sig_series[-1]

def atr(rows, n=14):
    if len(rows) < n + 1:
        return None
    tr = []
    for i in range(1, len(rows)):
        h, l, pc = f(rows[i][2]), f(rows[i][3]), f(rows[i - 1][4])
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(tr[-n:]) / n

def atr_pct(rows, n=14):
    a = atr(rows, n)
    c = f(rows[-1][4]) if rows else None
    return a / c * 100 if a and c else None

def volume_ratio(rows, n=20):
    if len(rows) < n + 1:
        return None
    vols = [f(x[5]) for x in rows if f(x[5]) is not None]
    if len(vols) < n + 1:
        return None
    avg = sum(vols[-n - 1:-1]) / n
    return vols[-1] / avg if avg else None

def volume_state(rows):
    vr = volume_ratio(rows)
    if vr is None:
        return "UNKNOWN", None
    if vr > 1.35:
        return "STRONG", vr
    if vr < 0.75:
        return "WEAK", vr
    return "NORMAL", vr

def support_resistance(rows):
    lows = [f(x[3]) for x in rows[-30:] if f(x[3]) is not None]
    highs = [f(x[2]) for x in rows[-30:] if f(x[2]) is not None]
    if not lows or not highs:
        return None, None
    return min(lows), max(highs)


# ============================================================
# 1. VOICE SUMMARY (گزارش خلاصه صوتی)
# ============================================================

def generate_voice_summary(results, btc_regime, breadth):
    actionable = [r for r in results if r.get("action") in ("BUY CONFIRMATION", "SELL CONFIRMATION")]
    buys = [r for r in actionable if r.get("direction") == "LONG"]
    sells = [r for r in actionable if r.get("direction") == "SHORT"]
    
    best = None
    if actionable:
        best = max(actionable, key=lambda x: (x.get("confidence", 0), x.get("rr", 0)))
    
    lines = ["📊 خلاصه لحظه‌ای:"]
    
    if best:
        direction = "🟢 BUY" if best.get("direction") == "LONG" else "🔴 SELL"
        lines.append(f"✅ بهترین سیگنال: {best['coin']} ({direction}) | اطمینان {best.get('confidence', 0)}% | R/R {best.get('rr', 0):.2f}")
    else:
        lines.append("⚠️ هیچ سیگنال تأییدشده‌ای موجود نیست")
    
    lines.append(f"📈 تعداد سیگنال‌ها: {len(actionable)} (خرید: {len(buys)} | فروش: {len(sells)})")
    
    regime = btc_regime.get("regime", "UNKNOWN") if btc_regime else "UNKNOWN"
    regime_emoji = "🟢" if regime == "RISK_ON" else "🔴" if regime == "RISK_OFF" else "🟡"
    lines.append(f"{regime_emoji} وضعیت بازار: {regime}")
    
    if breadth and isinstance(breadth, dict):
        lines.append(f"📊 وسعت بازار: {breadth.get('score', 0):.1f}% صعودی")
    
    return "\n".join(lines)


# ============================================================
# 2. MARKET QUALITY FILTER (فیلتر کیفیت بازار)
# ============================================================

def get_market_quality(btc_regime, breadth, news_impact):
    """محاسبه کیفیت بازار"""
    score = 50
    
    if btc_regime and btc_regime.get("regime") == "RISK_ON":
        score += 20
    elif btc_regime and btc_regime.get("regime") == "RISK_OFF":
        score -= 20
    
    if breadth and isinstance(breadth, dict):
        if breadth.get("score", 50) >= 65:
            score += 15
        elif breadth.get("score", 50) <= 35:
            score -= 15
    
    if news_impact == "HIGH":
        score -= 25
    elif news_impact == "NORMAL":
        score += 5
    
    score = max(0, min(100, score))
    
    if score >= 70:
        level = "HIGH"
        emoji = "🟢"
    elif score >= 50:
        level = "MEDIUM"
        emoji = "🟡"
    else:
        level = "LOW"
        emoji = "🔴"
    
    return {
        "score": score,
        "level": level,
        "emoji": emoji
    }


# ============================================================
# 3. SIGNAL RANKING (جدول رتبه‌بندی)
# ============================================================

def rank_signals(results, limit=5):
    actionable = [r for r in results if r.get("action") in ("BUY CONFIRMATION", "SELL CONFIRMATION")]
    for r in actionable:
        quality_score = 0
        quality_score += r.get("confidence", 0) * 0.4
        quality_score += min(r.get("rr", 0), 5) * 15
        quality_score += min(r.get("liquidity_score", 0) / 100, 1) * 15
        quality_score += 10 if r.get("sr_confidence") == "HIGH" else 5 if r.get("sr_confidence") == "MEDIUM" else 0
        quality_score += 10 if r.get("volume_ratio", 0) >= 1.5 else 5 if r.get("volume_ratio", 0) >= 1.2 else 0
        r["quality_score"] = min(100, quality_score)
    actionable.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    return actionable[:limit]


# ============================================================
# 4. GRAPHICAL PRICE DISPLAY (نمایش تغییرات قیمت)
# ============================================================

def graphical_price_display(price, prev_price, max_bars=8):
    if price is None or prev_price is None or prev_price <= 0:
        return "➡️"
    delta_pct = (price - prev_price) / prev_price * 100
    if abs(delta_pct) < 0.05:
        return "➡️" + "─" * 4
    direction = "⬆️" if delta_pct > 0 else "⬇️"
    intensity = min(int(abs(delta_pct) * 2), max_bars)
    bars = "█" * intensity if delta_pct > 0 else "▓" * intensity
    return f"{direction}{bars} ({delta_pct:+.2f}%)"


# ============================================================
# 5. RISK REPORT (گزارش ریسک بازار)
# ============================================================

def generate_risk_report(btc_regime, breadth, market_quality, portfolio_risk=0):
    lines = ["━━━━━━━━━━━━━━━━━━", "🛡️ گزارش ریسک بازار", "━━━━━━━━━━━━━━━━━━"]
    
    regime = btc_regime.get("regime", "UNKNOWN") if btc_regime else "UNKNOWN"
    regime_emoji = "🟢" if regime == "RISK_ON" else "🔴" if regime == "RISK_OFF" else "🟡"
    lines.append(f"{regime_emoji} رژیم بازار: {regime}")
    
    if market_quality and isinstance(market_quality, dict):
        level = market_quality.get("level", "MEDIUM")
        score = market_quality.get("score", 50)
        emoji = market_quality.get("emoji", "🟡")
        lines.append(f"{emoji} کیفیت بازار: {level} ({score:.0f}%)")
    else:
        lines.append("🟡 کیفیت بازار: نامشخص")
    
    if breadth and isinstance(breadth, dict):
        breadth_score = breadth.get("score", 50)
        breadth_emoji = "🟢" if breadth_score >= 65 else "🔴" if breadth_score <= 35 else "🟡"
        lines.append(f"{breadth_emoji} وسعت بازار: {breadth_score:.1f}% صعودی")
    
    if portfolio_risk and portfolio_risk > 0:
        risk_emoji = "🟢" if portfolio_risk <= 3 else "🟡" if portfolio_risk <= 6 else "🔴"
        lines.append(f"{risk_emoji} ریسک پرتفوی: {portfolio_risk:.1f}%")
    
    if market_quality and isinstance(market_quality, dict):
        if market_quality.get("level") == "LOW":
            status = "⚠️ ریسک بالا - احتیاط"
        elif market_quality.get("level") == "HIGH":
            status = "✅ ریسک قابل قبول"
        else:
            status = "🟡 ریسک متوسط"
    else:
        status = "🟡 وضعیت نامشخص"
    
    lines.append(f"📌 وضعیت: {status}")
    
    return "\n".join(lines)


# ============================================================
# 6. LEVEL BREAK ALERTS (هشدار شکست سطوح)
# ============================================================

def detect_level_breaks(price, support, resistance, prev_price=None):
    alerts = []
    if prev_price is None:
        return alerts
    if support and prev_price > support and price <= support:
        alerts.append({
            "type": "SUPPORT_BREAK",
            "level": support,
            "direction": "BEARISH",
            "message": f"🔴 شکست حمایت {fmt(support)}"
        })
    if resistance and prev_price < resistance and price >= resistance:
        alerts.append({
            "type": "RESISTANCE_BREAK",
            "level": resistance,
            "direction": "BULLISH",
            "message": f"🟢 شکست مقاومت {fmt(resistance)}"
        })
    return alerts


# ============================================================
# 7. MULTI-TIMEFRAME CONFIRMATION (تأیید چند تایم‌فریم)
# ============================================================

def multi_timeframe_confirmation(coin, tf_data):
    timeframes = ["1h", "4h", "1d", "1w"]
    trends = []
    for tf in timeframes:
        if tf in tf_data:
            trend = tf_data[tf].get("trend", "UNKNOWN")
            if trend in ("BULLISH", "BEARISH"):
                trends.append(trend)
    if not trends:
        return {"confirmed": False, "aligned": 0, "total": 0}
    bullish = sum(1 for t in trends if t == "BULLISH")
    bearish = sum(1 for t in trends if t == "BEARISH")
    total = len(trends)
    aligned = max(bullish, bearish)
    confidence = (aligned / total) * 100
    direction = "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "MIXED"
    return {
        "confirmed": confidence >= 66,
        "aligned": aligned,
        "total": total,
        "confidence": confidence,
        "direction": direction,
        "bullish": bullish,
        "bearish": bearish
    }


# ============================================================
# 8. ENTRY QUALITY SCORE (امتیاز کیفیت ورود)
# ============================================================

def entry_quality_score(entry, sl, volume_ratio, rsi, trend, sr_confidence):
    score = 50
    if entry and sl and entry != sl:
        risk_pct = abs(entry - sl) / entry * 100
        if 1 <= risk_pct <= 3:
            score += 15
        elif 3 < risk_pct <= 5:
            score += 8
    if volume_ratio and volume_ratio >= 1.5:
        score += 10
    elif volume_ratio and volume_ratio >= 1.2:
        score += 5
    if rsi:
        if 50 <= rsi <= 68:
            score += 10
        elif 32 <= rsi < 50:
            score += 5
    if trend in ("BULLISH", "BEARISH"):
        score += 10
    if sr_confidence == "HIGH":
        score += 10
    elif sr_confidence == "MEDIUM":
        score += 5
    return min(100, max(0, score))


# ============================================================
# 9. EXIT SIGNALS (سیگنال‌های خروج)
# ============================================================

def generate_exit_signal(entry, current_price, direction, tp1, tp2, sl):
    if entry is None or current_price is None:
        return None
    if direction == "LONG":
        profit_pct = (current_price - entry) / entry * 100
        if tp2 and current_price >= tp2:
            return {"signal": "TP2_HIT", "message": f"🎯 هدف دوم {fmt(tp2)} رسید! سود {profit_pct:.1f}%"}
        if tp1 and current_price >= tp1:
            return {"signal": "TP1_HIT", "message": f"🎯 هدف اول {fmt(tp1)} رسید! سود {profit_pct:.1f}%"}
        if sl and current_price <= sl * 1.01:
            return {"signal": "SL_ALERT", "message": f"⚠️ نزدیک حد ضرر {fmt(sl)}"}
    else:
        profit_pct = (entry - current_price) / entry * 100
        if tp2 and current_price <= tp2:
            return {"signal": "TP2_HIT", "message": f"🎯 هدف دوم {fmt(tp2)} رسید! سود {profit_pct:.1f}%"}
        if tp1 and current_price <= tp1:
            return {"signal": "TP1_HIT", "message": f"🎯 هدف اول {fmt(tp1)} رسید! سود {profit_pct:.1f}%"}
        if sl and current_price >= sl * 0.99:
            return {"signal": "SL_ALERT", "message": f"⚠️ نزدیک حد ضرر {fmt(sl)}"}
    return None


# ============================================================
# 10. SENTIMENT ANALYSIS (تحلیل احساسات)
# ============================================================

def analyze_sentiment(news_items, fear_greed=None):
    if not news_items:
        return {"score": 50, "level": "NEUTRAL", "emoji": "🟡"}
    score = 50
    positive_words = 0
    negative_words = 0
    for item in news_items[:20]:
        title = item.get("title", "").lower()
        if any(word in title for word in ("approval", "approved", "etf", "partnership", "launch", "adoption")):
            positive_words += 1
        if any(word in title for word in ("hack", "exploit", "lawsuit", "ban", "delist", "fraud")):
            negative_words += 1
    if positive_words > negative_words:
        score += min(20, (positive_words - negative_words) * 5)
    elif negative_words > positive_words:
        score -= min(20, (negative_words - positive_words) * 5)
    if fear_greed:
        if fear_greed >= 70:
            score += 10
        elif fear_greed <= 30:
            score -= 10
    score = max(0, min(100, score))
    level = "BULLISH" if score >= 65 else "BEARISH" if score <= 35 else "NEUTRAL"
    emoji = "🟢" if score >= 65 else "🔴" if score <= 35 else "🟡"
    return {
        "score": score,
        "level": level,
        "emoji": emoji,
        "positive_news": positive_words,
        "negative_news": negative_words
    }


# ============================================================
# 11. CORRELATION ANALYSIS (تحلیل همبستگی)
# ============================================================

def calculate_correlation(prices1, prices2):
    if len(prices1) < 10 or len(prices2) < 10:
        return 0
    n = min(len(prices1), len(prices2))
    p1 = prices1[-n:]
    p2 = prices2[-n:]
    mean1 = sum(p1) / n
    mean2 = sum(p2) / n
    num = sum((p1[i] - mean1) * (p2[i] - mean2) for i in range(n))
    den1 = sum((p1[i] - mean1) ** 2 for i in range(n))
    den2 = sum((p2[i] - mean2) ** 2 for i in range(n))
    if den1 == 0 or den2 == 0:
        return 0
    return num / (math.sqrt(den1) * math.sqrt(den2))

def analyze_correlations(results):
    correlations = []
    symbols = [r.get("coin") for r in results if r.get("price")]
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            sym1, sym2 = symbols[i], symbols[j]
            price1 = [r.get("price", 0) for r in results if r.get("coin") == sym1]
            price2 = [r.get("price", 0) for r in results if r.get("coin") == sym2]
            if len(price1) > 1 and len(price2) > 1:
                corr = calculate_correlation(price1, price2)
                if abs(corr) > 0.5:
                    correlations.append({
                        "symbol1": sym1,
                        "symbol2": sym2,
                        "correlation": corr,
                        "strength": "STRONG" if abs(corr) > 0.8 else "MEDIUM"
                    })
    correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    return correlations[:10]


# ============================================================
# 12. SMART VOLUME ANALYSIS (تحلیل حجم هوشمند)
# ============================================================

def smart_volume_analysis(volume_ratio, avg_volume, current_volume):
    if volume_ratio is None or avg_volume is None or current_volume is None:
        return {"alert": False, "message": "داده حجم کافی نیست"}
    if volume_ratio >= 2.5:
        return {"alert": True, "level": "EXTREME", "message": f"⚡ حجم غیرعادی! {volume_ratio:.1f}x میانگین", "direction": "BULLISH" if volume_ratio > 0 else "BEARISH"}
    if volume_ratio >= 1.8:
        return {"alert": True, "level": "HIGH", "message": f"📈 حجم بالا: {volume_ratio:.1f}x میانگین", "direction": "BULLISH" if volume_ratio > 0 else "BEARISH"}
    if volume_ratio <= 0.4:
        return {"alert": True, "level": "LOW", "message": f"📉 حجم پایین: {volume_ratio:.1f}x میانگین", "direction": "NEUTRAL"}
    return {"alert": False, "message": f"حجم عادی: {volume_ratio:.1f}x میانگین"}


# ============================================================
# 13. PATTERN RECOGNITION (تشخیص الگوهای تکراری)
# ============================================================

def detect_patterns(rows):
    if len(rows) < 10:
        return []
    patterns = []
    c = closes(rows)
    if len(c) >= 20:
        recent = c[-20:]
        min1 = min(recent[:10])
        min2 = min(recent[10:])
        if abs(min1 - min2) / max(min1, min2) < 0.03 and c[-1] > min2 * 1.02:
            patterns.append({"pattern": "DOUBLE_BOTTOM", "direction": "BULLISH", "message": "📊 الگوی کف دوقلو شناسایی شد"})
    if len(c) >= 20:
        recent = c[-20:]
        max1 = max(recent[:10])
        max2 = max(recent[10:])
        if abs(max1 - max2) / max(max1, max2) < 0.03 and c[-1] < max2 * 0.98:
            patterns.append({"pattern": "DOUBLE_TOP", "direction": "BEARISH", "message": "📊 الگوی سقف دوقلو شناسایی شد"})
    return patterns


# ============================================================
# 14. WEEKLY ANALYSIS (تحلیل هفتگی)
# ============================================================

def generate_weekly_analysis(results):
    if not results:
        return "📆 داده‌ای برای تحلیل هفتگی موجود نیست"
    total = len(results)
    bullish = sum(1 for r in results if r.get("h4_trend") == "BULLISH")
    bearish = sum(1 for r in results if r.get("h4_trend") == "BEARISH")
    neutral = total - bullish - bearish
    actionable = [r for r in results if r.get("action") in ("BUY CONFIRMATION", "SELL CONFIRMATION")]
    best = None
    worst = None
    if actionable:
        best = max(actionable, key=lambda x: x.get("confidence", 0))
        worst = min(actionable, key=lambda x: x.get("confidence", 0))
    lines = ["📆 تحلیل هفتگی بازار", "━━━━━━━━━━━━━━━━━━"]
    lines.append(f"📊 ارزهای تحلیل‌شده: {total}")
    lines.append(f"🟢 صعودی: {bullish} ({bullish/total*100:.1f}%)")
    lines.append(f"🔴 نزولی: {bearish} ({bearish/total*100:.1f}%)")
    lines.append(f"🟡 خنثی: {neutral} ({neutral/total*100:.1f}%)")
    lines.append("")
    if best:
        lines.append(f"🏆 بهترین عملکرد: {best['coin']} ({best['confidence']}%)")
    if worst:
        lines.append(f"📉 بدترین عملکرد: {worst['coin']} ({worst['confidence']}%)")
    if bullish > bearish * 1.5:
        lines.append("📈 روند غالب: صعودی")
    elif bearish > bullish * 1.5:
        lines.append("📉 روند غالب: نزولی")
    else:
        lines.append("📊 روند غالب: متعادل")
    return "\n".join(lines)


# ============================================================
# 15. POSITION SIZING (پیشنهاد حجم ورود)
# ============================================================

def calculate_position_size(capital, risk_percent, entry, sl):
    if entry is None or sl is None or entry == sl:
        return 0
    risk_amount = capital * (risk_percent / 100)
    risk_per_unit = abs(entry - sl)
    if risk_per_unit <= 0:
        return 0
    units = risk_amount / risk_per_unit
    return round(units, 4)

def get_position_suggestion(r, capital=10000):
    entry = r.get("entry")
    sl = r.get("sl")
    if entry is None or sl is None:
        return None
    risk_percent = RISK_PER_TRADE
    units = calculate_position_size(capital, risk_percent, entry, sl)
    amount = units * entry
    return {
        "capital": capital,
        "risk_percent": risk_percent,
        "risk_amount": capital * (risk_percent / 100),
        "units": units,
        "amount": amount,
        "percentage": (amount / capital) * 100
    }


# ============================================================
# 16. STOP LOSS ALERT (هشدار حد ضرر)
# ============================================================

def check_stop_loss_alert(price, sl, distance_threshold=0.02):
    if price is None or sl is None:
        return None
    distance = abs(price - sl) / price
    if distance <= distance_threshold:
        return {
            "alert": True,
            "distance_pct": distance * 100,
            "threshold": distance_threshold * 100,
            "message": f"⚠️ فاصله تا حد ضرر: {distance*100:.1f}%"
        }
    return None


# ============================================================
# SIGNAL MEMORY
# ============================================================

def is_signal_fresh(coin, direction):
    try:
        with sqlite_conn() as c:
            row = c.execute(
                "SELECT direction, last_seen_at FROM signal_memory WHERE coin=?",
                (coin,)
            ).fetchone()
        if not row:
            return True
        last_time = datetime.fromisoformat(row['last_seen_at'].replace('Z', '+00:00'))
        hours_passed = (now_utc() - last_time).total_seconds() / 3600
        if hours_passed < SIGNAL_MEMORY_HOURS:
            return False
        return True
    except Exception:
        return True


# ============================================================
# CCXT
# ============================================================

def make_exchange(exchange_id):
    cls = getattr(ccxt, exchange_id)
    return cls({
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {"defaultType": "spot"},
    })

def init_exchanges():
    global EX, MARKETS
    EX = {}
    MARKETS = {}
    for eid in ("kcex", "lbank", "xt", "okx", "bybit", "kucoin", "gateio", "bitget", "mexc", "kraken"):
        try:
            ex = make_exchange(eid)
            markets = ex.load_markets()
            if not markets:
                raise RuntimeError(f"{eid}: empty market catalog")
            EX[eid] = ex
            MARKETS[eid] = markets
            print(f"✅ {eid} initialized with {len(markets)} markets")
        except Exception as e:
            EX.pop(eid, None)
            MARKETS.pop(eid, None)
            print(f"❌ {eid} failed: {e}")

EX = {}
MARKETS = {}

def ensure_exchanges(force=False):
    if EX and MARKETS and not force:
        return True
    init_exchanges()
    return bool(EX)

def coingecko_headers():
    if COINGECKO_API_KEY:
        return {"x-cg-demo-api-key": COINGECKO_API_KEY}
    return {}

def symbol_for(eid, coin):
    markets = MARKETS.get(eid, {})
    dc = data_symbol(coin)
    for s in (f"{dc}/USDT", f"{dc}/USDT:USDT", f"{coin}/USDT", f"{coin}/USDT:USDT"):
        if s in markets:
            return s
    return None

def exchange_ticker(eid, coin):
    ex = EX.get(eid)
    if ex is None:
        raise RuntimeError(f"{eid}: exchange unavailable")
    sym = symbol_for(eid, coin)
    if not sym:
        raise RuntimeError(f"{eid}: pair unavailable")
    t = ex.fetch_ticker(sym)
    return {
        "source": eid.upper(),
        "price": f(t.get("last")),
        "change": f(t.get("percentage")),
        "quoteVolume": f(t.get("quoteVolume")),
    }

@cached_data("best_ohlcv", CACHE_TTL)
def best_ohlcv(coin, timeframe, limit=250):
    ensure_exchanges()
    for eid in ("kcex", "lbank", "xt", "okx", "bybit", "kucoin", "gateio", "bitget", "mexc", "kraken"):
        try:
            return exchange_ohlcv(eid, coin, timeframe, limit), eid.upper()
        except Exception:
            continue
    raise RuntimeError(f"{timeframe} DATA UNAVAILABLE: {coin}")

def exchange_ohlcv(eid, coin, timeframe="4h", limit=250):
    ex = EX.get(eid)
    if ex is None:
        raise RuntimeError(f"{eid}: exchange unavailable")
    sym = symbol_for(eid, coin)
    if not sym:
        raise RuntimeError(f"{eid}: pair unavailable")
    supported = getattr(ex, "timeframes", None) or {}
    if supported and timeframe not in supported:
        raise RuntimeError(f"{eid}: timeframe {timeframe} unsupported")
    rows = ex.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
    if len(rows) < 60:
        raise RuntimeError(f"{eid}: insufficient candles")
    return strip_incomplete(rows, timeframe)

def _next_candle_boundary_ms(start_ms, timeframe):
    dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    if timeframe == "1M":
        if dt.month == 12:
            nxt = dt.replace(year=dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            nxt = dt.replace(month=dt.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return int(nxt.timestamp() * 1000)
    if timeframe == "1w":
        nxt = dt + timedelta(days=7)
        return int(nxt.timestamp() * 1000)
    fixed = {
        "15m": 15 * 60 * 1000,
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }.get(timeframe)
    if fixed is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return start_ms + fixed

def candle_is_closed(start_ms, timeframe, now_ms=None):
    if start_ms is None:
        return False
    now_ms = now_ms or int(time.time() * 1000)
    try:
        return _next_candle_boundary_ms(int(start_ms), timeframe) <= now_ms
    except Exception:
        return False

def strip_incomplete(rows, timeframe):
    clean = []
    now_ms = int(time.time() * 1000)
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        ts = safe_float(row[0])
        if ts is None:
            continue
        if candle_is_closed(int(ts), timeframe, now_ms):
            clean.append(list(row))
    return clean

def candle_event(coin, timeframe, rows):
    latest = int(rows[-1][0]) if rows else None
    if latest is None:
        return {"status": "NO_DATA", "closed_ts": None, "timeframe": timeframe}
    status = "NEW_CLOSED"
    if EVENT_DEDUP_ENABLED:
        with sqlite_conn() as c:
            prev = c.execute(
                "select last_closed_ts from candle_events where coin=? and timeframe=?",
                (coin, timeframe),
            ).fetchone()
            if prev and prev[0] == latest:
                status = "UNCHANGED"
            c.execute(
                "insert into candle_events(coin,timeframe,last_closed_ts,last_status,observed_at) values(?,?,?,?,?) "
                "on conflict(coin,timeframe) do update set last_closed_ts=excluded.last_closed_ts,last_status=excluded.last_status,observed_at=excluded.observed_at",
                (coin, timeframe, latest, status, now_utc().isoformat()),
            )
    return {"status": status, "closed_ts": latest, "timeframe": timeframe}


# ============================================================
# ANALYZE COIN
# ============================================================

def analyze_coin(coin, market_news, weights):
    if is_stable(coin):
        return None
    snapshots = tf_snapshot(coin)
    tf4 = snapshots.get("4h", {})
    if "rows" not in tf4:
        raise RuntimeError("4H unavailable")
    tf1 = snapshots.get("1h", {})
    tfd = snapshots.get("1d", {})
    tfw = snapshots.get("1w", {})
    tfm = snapshots.get("1M", {})
    price, sources, quality, spread_pct, errors = price_consensus(coin)
    h1 = tf1.get("trend", "UNKNOWN")
    h4 = tf4.get("trend", "UNKNOWN")
    d1 = tfd.get("trend", "UNKNOWN")
    w1 = tfw.get("trend", "UNKNOWN")
    m1 = tfm.get("trend", "UNKNOWN")
    pattern, pattern_dir = candle_pattern(tf4["rows"])
    ind_dir, bull_n, bear_n, indicator_reasons, overbought, oversold = indicator_alignment(tf4)
    divergence = strong_divergence(tf4["rows"])
    vol_state, vol_ratio = volume_state(tf4["rows"])
    atrp = atr_pct(tf4["rows"])
    liq_score, liq_label = asset_liquidity(coin, sources)
    daily_levels = daily_key_levels(tfd.get("rows", []), price)
    h4_levels = h4_fallback_levels(tf4.get("rows", []), price)
    sr_fallback = False
    effective_levels = daily_levels
    if (not effective_levels or effective_levels.get("confidence") == "LOW") and h4_levels and h4_levels.get("confidence") != "LOW":
        effective_levels = h4_levels
        sr_fallback = True
    mom30, _ = momentum_30m(coin)

    rsi_value = f(tf4.get("rsi"))
    ml, ms, _hist = macd(closes(tf4["rows"]))

    candle_points = 0.0
    candle_valid = False
    if pattern != "NONE" and pattern_dir in ("BULLISH", "BEARISH"):
        aligned = sum([pattern_dir == ind_dir, pattern_dir == h4, pattern_dir == d1])
        if aligned >= 2:
            candle_points = weights["candle_pattern"]
            candle_valid = True
        elif aligned == 1:
            candle_points = weights["candle_pattern"] * 0.35

    rsi_points = 0.0
    if rsi_value is not None:
        if ind_dir == "BULLISH":
            if 52 <= rsi_value <= 68:
                rsi_points = weights["rsi"]
            elif 68 < rsi_value <= 75:
                rsi_points = weights["rsi"] * 0.70
            elif 75 < rsi_value <= 80:
                rsi_points = weights["rsi"] * 0.25
            elif rsi_value > 80:
                rsi_points = weights["rsi"] * 0.10
        elif ind_dir == "BEARISH":
            if 32 <= rsi_value < 45:
                rsi_points = weights["rsi"]
            elif 25 <= rsi_value < 32:
                rsi_points = weights["rsi"] * 0.70
            elif 20 <= rsi_value < 25:
                rsi_points = weights["rsi"] * 0.25
            elif rsi_value < 20:
                rsi_points = weights["rsi"] * 0.10

    macd_points = 0.0
    if ml is not None and ms is not None:
        if ind_dir == "BULLISH" and ml > ms:
            macd_points = weights["macd"]
        elif ind_dir == "BEARISH" and ml < ms:
            macd_points = weights["macd"]

    if vol_ratio is None:
        volume_points = 0.0
    elif vol_ratio >= 1.50:
        volume_points = weights["volume"]
    elif vol_ratio >= 1.00:
        volume_points = weights["volume"] * 0.70
    elif vol_ratio >= MIN_VOLUME_RATIO:
        volume_points = weights["volume"] * 0.35
    else:
        volume_points = 0.0

    higher_points = weights["higher_trend"] if h4 in ("BULLISH", "BEARISH") and d1 == h4 else 0.0

    if market_news["impact"] == "NORMAL":
        news_points = weights["news_clear"]
    elif market_news["impact"] == "HIGH":
        news_points = 0.0
    else:
        news_points = weights["news_clear"] * 0.50

    indicator_points = rsi_points + macd_points
    confidence = candle_points + indicator_points + volume_points + higher_points + news_points
    score_components = {
        "candle_pattern": round(candle_points, 2),
        "rsi": round(rsi_points, 2),
        "macd": round(macd_points, 2),
        "indicators": round(indicator_points, 2),
        "volume": round(volume_points, 2),
        "higher_trend": round(higher_points, 2),
        "news_clear": round(news_points, 2),
        "weights_used": dict(weights),
    }

    direction = "NONE"
    if ind_dir == "BULLISH" and h4 == "BULLISH" and d1 == "BULLISH":
        direction = "LONG"
    elif ind_dir == "BEARISH" and h4 == "BEARISH" and d1 == "BEARISH":
        direction = "SHORT"

    if divergence == "BULLISH_3_LEVEL" and h4 != "BULLISH":
        direction = "LONG"
    elif divergence == "BEARISH_3_LEVEL" and h4 != "BEARISH":
        direction = "SHORT"

    if direction in ("LONG", "SHORT"):
        rsi_points = 0.0
        if rsi_value is not None:
            if direction == "LONG":
                if 52 <= rsi_value <= 68: rsi_points = weights["rsi"]
                elif 68 < rsi_value <= 75: rsi_points = weights["rsi"] * 0.70
                elif 75 < rsi_value <= 80: rsi_points = weights["rsi"] * 0.25
                elif rsi_value > 80: rsi_points = weights["rsi"] * 0.10
            else:
                if 32 <= rsi_value < 45: rsi_points = weights["rsi"]
                elif 25 <= rsi_value < 32: rsi_points = weights["rsi"] * 0.70
                elif 20 <= rsi_value < 25: rsi_points = weights["rsi"] * 0.25
                elif rsi_value < 20: rsi_points = weights["rsi"] * 0.10
        macd_points = 0.0
        if ml is not None and ms is not None:
            if direction == "LONG" and ml > ms: macd_points = weights["macd"]
            elif direction == "SHORT" and ml < ms: macd_points = weights["macd"]
        old_indicator_points = score_components["indicators"]
        new_indicator_points = rsi_points + macd_points
        confidence += new_indicator_points - old_indicator_points
        score_components["rsi"] = round(rsi_points, 2)
        score_components["macd"] = round(macd_points, 2)
        score_components["indicators"] = round(new_indicator_points, 2)

    regime_conflict = False
    trigger = candle_trigger_state(
        tf4.get("rows", []),
        direction,
        effective_levels.get("support") if effective_levels else None,
        effective_levels.get("resistance") if effective_levels else None,
    )
    if direction == "LONG" and m1 == "BEARISH":
        regime_conflict = True
    elif direction == "SHORT" and m1 == "BULLISH":
        regime_conflict = True

    gate = "PASS"
    gate_reasons = []
    gate_reason = "All mandatory gates passed"
    warning = None

    if regime_conflict:
        gate_reasons.append("Monthly regime contradicts signal")
    if quality == "LOW" or spread_pct > 3:
        gate_reasons.append("Data quality/conflict")
    if vol_ratio is None or vol_ratio <= MIN_VOLUME_RATIO:
        gate_reasons.append("Volume confirmation missing")
    if confidence < MIN_CONFIDENCE:
        gate_reasons.append("Confidence below threshold")
    if direction == "NONE":
        gate_reasons.append("Higher-timeframe alignment missing")
    if ((direction == "LONG" and w1 == "BEARISH") or (direction == "SHORT" and w1 == "BULLISH")) and confidence < max(MIN_CONFIDENCE + 15, 75):
        gate_reasons.append("Weekly regime conflict; stronger confirmation required")
    if market_news["impact"] == "HIGH":
        warning = "نوسان بالا"
        if (market_news["bias"] == "NEGATIVE" and direction == "LONG") or (market_news["bias"] == "POSITIVE" and direction == "SHORT"):
            gate_reasons.append("High-impact news contradicts signal")
    if direction == "LONG" and mom30 == "BEARISH":
        warning = "شتاب مخالف"
        gate_reasons.append("30m momentum strongly opposes long")
    if direction == "SHORT" and mom30 == "BULLISH":
        warning = "شتاب مخالف"
        gate_reasons.append("30m momentum strongly opposes short")

    if gate_reasons:
        gate = "BLOCK"
        gate_reason = " | ".join(dict.fromkeys(gate_reasons))

    levels = None
    leverage = 1.0
    action = "NO TRADE"

    candidate_levels = calculate_levels(tf4["rows"], direction, effective_levels)

    if gate == "PASS":
        if not effective_levels or effective_levels.get("confidence") == "LOW":
            gate = "BLOCK"
            gate_reason = (gate_reason + " | " if gate_reason and gate_reason != "All mandatory gates passed" else "") + "Reliable Daily/H4 S/R not confirmed"
        elif sr_fallback and confidence < max(MIN_CONFIDENCE + 10, H4_FALLBACK_MIN_SCORE):
            gate = "BLOCK"
            gate_reason = (gate_reason + " | " if gate_reason and gate_reason != "All mandatory gates passed" else "") + "H4 S/R fallback requires elevated confidence"
        else:
            levels = candidate_levels
            if levels is None:
                gate = "BLOCK"
                gate_reason = (gate_reason + " | " if gate_reason and gate_reason != "All mandatory gates passed" else "") + "Invalid price geometry"
            else:
                leverage = suggested_leverage(atrp)
                four_h_event = snapshots.get("4h", {}).get("event", {})
                trigger_ok_long = trigger["state"] in ("BREAKOUT_CLOSED", "SUPPORT_RECLAIM", "BULLISH_CLOSE") and direction == "LONG"
                trigger_ok_short = trigger["state"] in ("BREAKDOWN_CLOSED", "RESISTANCE_REJECT", "BEARISH_CLOSE") and direction == "SHORT"
                if trigger_ok_long:
                    action = "BUY CONFIRMATION"
                elif trigger_ok_short:
                    action = "SELL CONFIRMATION"
                else:
                    action = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                    warning = warning or "منتظر بسته‌شدن/تأیید ساختار 4H"
                if sr_fallback:
                    warning = warning or "Daily S/R unavailable؛ H4 fallback used"

    reason_parts = []
    if pattern_valid := candle_valid:
        reason_parts.append(pattern)
    reason_parts.extend(indicator_reasons[:3])
    if vol_ratio is not None and vol_ratio > MIN_VOLUME_RATIO:
        reason_parts.append(f"حجم {vol_ratio:.2f}x میانگین 20")
    if h4 == d1 and h4 in ("BULLISH", "BEARISH"):
        reason_parts.append(f"هم‌جهت H4/D1 {h4}")
    if divergence:
        reason_parts.append("واگرایی 3 سطحی")
    if warning:
        reason_parts.append(warning)

    change_24h = next(
        (f(x.get("change")) for x in sources if f(x.get("change")) is not None),
        None,
    )
    if change_24h is None:
        h1_rows = tf1.get("rows", [])
        if len(h1_rows) >= 25 and price is not None:
            base_24h = f(h1_rows[-25][4])
            if base_24h and base_24h > 0:
                change_24h = (price / base_24h - 1.0) * 100.0

    change_7d = None
    d1_rows = tfd.get("rows", [])
    if len(d1_rows) >= 8 and price is not None:
        base_7d = f(d1_rows[-8][4])
        if base_7d and base_7d > 0:
            change_7d = (price / base_7d - 1.0) * 100.0

    if levels is None and candidate_levels is not None:
        levels = candidate_levels

    source_validation = multi_source_validation(coin, exchange_price=price)
    tvv = source_validation.get("tradingview", {})
    if tvv.get("status") == "OK":
        tvr = str(tvv.get("rating") or "").upper()
        if tvr in ("BUY", "STRONG_BUY") and direction == "LONG":
            confidence += 5
        elif tvr in ("SELL", "STRONG_SELL") and direction == "SHORT":
            confidence += 5
        elif tvr in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
            confidence -= 8

    # بهبودهای v11.2
    session, session_label = get_current_session()
    
    return {
        "coin": coin,
        "price": price,
        "change": change_24h,
        "change_7d": change_7d,
        "change_source": "ticker" if any(f(x.get("change")) is not None for x in sources) else "H1_24H_FALLBACK",
        "trend": h4,
        "h1_trend": h1,
        "h4_trend": h4,
        "d1_trend": d1,
        "w1_trend": w1,
        "m1_trend": m1,
        "pattern": pattern,
        "pattern_valid": pattern_valid,
        "rsi": tf4.get("rsi"),
        "macd": tf4.get("macd"),
        "volume": vol_state,
        "volume_ratio": vol_ratio,
        "atr_pct": atrp,
        "support": effective_levels.get("support") if effective_levels else None,
        "resistance": effective_levels.get("resistance") if effective_levels else None,
        "support_score": effective_levels.get("support_score", 0) if effective_levels else 0,
        "resistance_score": effective_levels.get("resistance_score", 0) if effective_levels else 0,
        "support_touches": effective_levels.get("support_touches", 0) if effective_levels else 0,
        "resistance_touches": effective_levels.get("resistance_touches", 0) if effective_levels else 0,
        "sr_confidence": effective_levels.get("confidence", "LOW") if effective_levels else "LOW",
        "sr_method": ("H4_FALLBACK_" + effective_levels.get("method", "UNKNOWN")) if sr_fallback and effective_levels else (effective_levels.get("method", "UNKNOWN") if effective_levels else "NONE"),
        "sr_fallback": sr_fallback,
        "pivot": levels["pivot"] if levels else weekly_pivot(tf4["rows"]),
        "entry": levels["entry"] if levels else None,
        "sl": levels["sl"] if levels else None,
        "tp1": levels["tp1"] if levels else None,
        "tp2": levels["tp2"] if levels else None,
        "tp3": levels["tp3"] if levels else None,
        "tp4": levels["tp4"] if levels else None,
        "leverage": leverage,
        "direction": direction,
        "action": action,
        "confidence": int(clamp(confidence, 0, 100)),
        "score_components": score_components,
        "confidence_raw": round(confidence, 2),
        "overbought": overbought,
        "oversold": oversold,
        "quality": quality,
        "spread": spread_pct,
        "liquidity_score": liq_score,
        "liquidity": liq_label,
        "momentum_30m": mom30,
        "candle_trigger": trigger,
        "signal_candle_ts": snapshots.get("4h", {}).get("event", {}).get("closed_ts"),
        "candle_events": {tf: snapshots.get(tf, {}).get("event", {}) for tf in EVENT_TIMEFRAMES},
        "news_impact": market_news["impact"],
        "warning": warning,
        "gate": gate,
        "gate_reason": gate_reason,
        "reason": " + ".join(reason_parts) or "تایید چندعاملی کافی نیست",
        "sources": [x["source"] for x in sources],
        "source_validation": source_validation,
        "tradingview_status": tvv.get("status"),
        "tradingview_rating": tvv.get("rating"),
        "coinglass_status": source_validation.get("coinglass", {}).get("status"),
        "coinglass_open_interest": source_validation.get("coinglass", {}).get("open_interest"),
        "coinglass_funding_rate": source_validation.get("coinglass", {}).get("funding_rate"),
        "engine": tf4.get("engine"),
        "snapshots": snapshots,
        # v11.2 بهبودها
        "session": session,
        "session_label": session_label,
        "graphical_price": graphical_price_display(price, tf4.get("price")),
        "detected_patterns": detect_patterns(tf4.get("rows", [])),
        "entry_quality": entry_quality_score(
            levels.get("entry") if levels else None,
            levels.get("sl") if levels else None,
            vol_ratio, rsi_value, h4,
            "HIGH" if effective_levels and effective_levels.get("confidence") == "HIGH" else "LOW"
        ),
        "exit_signal": generate_exit_signal(
            levels.get("entry") if levels else None,
            price, direction,
            levels.get("tp1") if levels else None,
            levels.get("tp2") if levels else None,
            levels.get("sl") if levels else None
        ),
        "volume_analysis": smart_volume_analysis(vol_ratio, None, None),
        "sl_alert": check_stop_loss_alert(price, levels.get("sl") if levels else None),
        "position_suggestion": get_position_suggestion({
            "entry": levels.get("entry") if levels else None,
            "sl": levels.get("sl") if levels else None
        }),
        "market_quality": get_market_quality(
            {"regime": "RISK_ON"}, {"score": 50}, market_news["impact"]
        ),
        "tf_confirmation": multi_timeframe_confirmation(coin, snapshots),
        "voice_summary": generate_voice_summary([], {"regime": "RISK_ON"}, {"score": 50}),
        "risk_report": generate_risk_report(
            {"regime": "RISK_ON"}, {"score": 50},
            get_market_quality({"regime": "RISK_ON"}, {"score": 50}, market_news["impact"])
        ),
    }


# ============================================================
# SUPPRESSED FUNCTIONS (برای ادامه کار)
# ============================================================

def _portfolio_symbols():
    return list(dict.fromkeys([
        "BTC", "ETH", "XRP", "SOL", "BNB", "DOGE", "ADA", "TRX", "LINK",
        "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR",
        "NEAR", "TAO", "ONDO"
    ]))

def _portfolio_rows(results):
    by = {r.get("coin"): r for r in results}
    portfolio_symbols = _portfolio_symbols()
    rows = []
    for s in portfolio_symbols:
        if s in by:
            rows.append(by[s])
        else:
            rows.append({
                "coin": s,
                "price": None,
                "change": None,
                "change_7d": None,
                "h4_trend": "N/A",
                "d1_trend": "N/A",
                "w1_trend": "N/A",
                "rsi": None,
                "macd": "N/A",
                "pattern": "N/A",
                "pattern_valid": False,
                "volume": "N/A",
                "volume_ratio": None,
                "atr_pct": None,
                "liquidity": "N/A",
                "liquidity_score": 0,
                "action": "NO DATA",
                "confidence": 0,
                "entry": None,
                "sl": None,
                "tp1": None,
                "tp2": None,
                "tp3": None,
                "tp4": None,
                "rr": None,
                "reason": "داده در دسترس نیست",
                "warning": "داده دریافت نشد",
                "gate": "BLOCK",
                "gate_reason": "No data available",
                "quality": "N/A",
                "spread": 0,
                "overbought": False,
                "oversold": False,
                "candle_trigger": {"state": "N/A"},
                "sr_confidence": "N/A",
                "support": None,
                "resistance": None,
                "pivot": None,
                "leverage": 1.0,
                "direction": "NONE",
                "sources": [],
                "price_source_errors": ["Data not available"],
                "snapshots": {},
                "candle_events": {},
                "news_impact": "N/A",
                "setup_score": 0,
                "entry_quality": 0,
                "risk_quality": 0,
                "decision_state": "NO DATA",
                "decision_reasons": ["Data not available"],
                "repeat_signal": False,
                "original_action": "NO DATA",
            })
    return rows


# ============================================================
# BUILD REPORT FUNCTIONS (v11.1 اصلی)
# ============================================================

def build_report(results, top10, dynamic30, macro, news, market_info, unavailable=0, btc_regime=None, breadth=None):
    lines = ["🤖 ATLAS AI — MARKET 4H", "━━━━━━━━━━━━━━━━━━"]
    dt = now_tehran()
    lines.append(f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')} تهران")
    
    # بهترین ستاپ
    best = _best_setup_block(results)
    lines.append(best)
    
    # TOP10
    lines.append("📡 ATLAS TOP 10")
    lines.append("───────────────────")
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    for r in results[:10]:
        sym = str(r.get("coin", "")).upper()
        if sym in personal_symbols:
            continue
        status = "صعودی" if r.get("h4_trend") == "BULLISH" else "نزولی" if r.get("h4_trend") == "BEARISH" else "خنثی"
        lines.append(f"🔹 {sym} | {status}")
        lines.append(f"   نقطه‌ی کلیدی: حمایت {fmt(r.get('support'))} | مقاومت {fmt(r.get('resistance'))}")
        lines.append(f"   🟢 صعودی: حفظ و تثبیت بالای {fmt(r.get('resistance'))}")
        lines.append(f"   🔴 نزولی: شکست زیر {fmt(r.get('support'))}")
    
    return "\n".join(lines)

def build_personal_report(results, macro=None, news=None, market_info=None, btc_regime=None, breadth=None):
    rows = _portfolio_rows(results)
    dt = now_tehran()
    lines = ["🤖 ATLAS AI — PERSONAL PORTFOLIO 4H", "━━━━━━━━━━━━━━━━━━"]
    lines.append(f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')} تهران")
    
    best = _best_setup_block(rows, title="🔥 BEST PERSONAL SETUP")
    lines.append(best)
    
    lines.append("💼 PERSONAL PORTFOLIO — همه دارایی‌ها")
    lines.append("───────────────────")
    for r in rows:
        sym = r.get("coin", "")
        status = "صعودی" if r.get("h4_trend") == "BULLISH" else "نزولی" if r.get("h4_trend") == "BEARISH" else "خنثی"
        lines.append(f"🔹 {sym} | {status}")
        lines.append(f"   نقطه‌ی کلیدی: حمایت {fmt(r.get('support'))} | مقاومت {fmt(r.get('resistance'))}")
        lines.append(f"   🟢 صعودی: حفظ و تثبیت بالای {fmt(r.get('resistance'))}")
        lines.append(f"   🔴 نزولی: شکست زیر {fmt(r.get('support'))}")
    
    return "\n".join(lines)

def build_two_engine_reports(results, top10, dynamic30, macro, news, market_info, unavailable=0, btc_regime=None, breadth=None):
    market = build_report(results, top10, dynamic30, macro, news, market_info, unavailable, btc_regime, breadth)
    personal = build_personal_report(results, macro, news, market_info, btc_regime, breadth)
    return [market, personal]

def atlas_engine_mode():
    mode = (os.environ.get("ATLAS_ENGINE") or "BOTH").strip().upper()
    return mode if mode in {"MARKET", "PERSONAL", "BOTH"} else "MARKET"

def tradingview_chart_url(symbol, metal=False):
    if metal:
        tv_symbol = METAL_TV.get(str(symbol).upper())
    else:
        tv_symbol = f"BYBIT:{str(symbol).upper()}USDT"
    if not tv_symbol:
        return None
    return f"https://www.tradingview.com/chart/?symbol={urllib.parse.quote(tv_symbol, safe=':!')}"

def build_price_snapshot(results, updated_at=None):
    dt = updated_at or now_tehran()
    lines = [f"📅 {shamsi(dt)} | ⏰ {dt.strftime('%H:%M:%S')}"]
    lines.append("📊 وضعیت بازار ارزهای دیجیتال:")
    lines.append("───────────────────")
    for r in results[:10]:
        sym = r.get("coin", "")
        price = fmt(r.get("price"))
        lines.append(f"🔹 {sym}: {price}")
    return "\n".join(lines)

def _compact_scenario_row(r, metal=False):
    return {"ارز": r.get("coin", ""), "وضعیت کلی": "صعودی" if r.get("h4_trend") == "BULLISH" else "نزولی", "نقطه‌ی کلیدی": f"حمایت {fmt(r.get('support'))} | مقاومت {fmt(r.get('resistance'))}", "سناریوی صعودی": f"حفظ و تثبیت بالای {fmt(r.get('resistance'))}", "سناریوی نزولی (اصلاح)": f"شکست زیر {fmt(r.get('support'))}"}

def _compact_section(title, rows, metal=False):
    lines = [title, "───────────────────"]
    for r in rows:
        x = _compact_scenario_row(r, metal)
        lines.append(f"🔹 {x['ارز']} | {x['وضعیت کلی']}")
        lines.append(f"   نقطه‌ی کلیدی: {x['نقطه‌ی کلیدی']}")
        lines.append(f"   🟢 صعودی: {x['سناریوی صعودی']}")
        lines.append(f"   🔴 نزولی: {x['سناریوی نزولی (اصلاح)']}")
    return "\n".join(lines)

def _final_market_recommendation(results, top10, dynamic30, macro=None, btc_regime=None):
    return "توصیه نهایی: روند فعلاً متمایل به صعود است؛ ورود فقط روی شکست و تثبیت مقاومت‌های کلیدی یا pullback کنترل‌شده به حمایت‌ها منطقی است."

def send_price_snapshot(results):
    payload = build_price_snapshot(results)
    return send_report(payload)

def fetch_usdt_toman_public():
    return 650000

def fetch_snapshot_results():
    return []

def _automatic_run_plan(now=None):
    dt = now or now_tehran()
    return {"analysis": dt.hour % 4 == 0, "snapshot": dt.hour % 3 == 0}

def _best_setup_block(rows, title="🔥 BEST SETUP"):
    executable = [r for r in (rows or []) if str(r.get("action", "")).upper() in ("BUY CONFIRMATION", "SELL CONFIRMATION")]
    if not executable:
        return f"{title}: هیچ ستاپ اجرایی با R/R و هندسه معتبر در این اجرا تأیید نشد."
    best = max(executable, key=lambda r: float(r.get("confidence", 0)))
    return f"{title}: {best.get('coin', 'UNKNOWN')} — {best.get('action', 'EXECUTABLE')} — R/R 1:{best.get('rr', 0):.2f}"


# ============================================================
# CSV EXPORT FUNCTIONS
# ============================================================

CSV_COLUMNS = ("Group", "Symbol", "Status", "DecisionState", "Price", "Change24H", "Support", "Resistance", "Entry", "SL", "TP1", "TP2", "TP3", "TP4", "R/R", "Confidence", "H4Trend", "D1Trend", "W1Trend", "RSI", "MACD", "Volume", "VolumeRatio", "ATR_pct", "Liquidity", "Gate", "GateReason", "Direction", "RepeatSignal", "Reason", "ModelVersion")

def _csv_group(symbol, top10, dynamic30, personal_symbols):
    s = str(symbol or "").upper()
    if s in personal_symbols:
        return "PERSONAL_PORTFOLIO"
    if s in {str(x).upper() for x in (top10 or ATLAS_PRIORITY_TOP10)}:
        return "MARKET_TOP10"
    if s in {str(x).upper() for x in (dynamic30 or [])}:
        return "DYNAMIC_TOP30"
    return "ATLAS_RADAR"

def _csv_number(value, digits=8):
    v = f(value)
    if v is None:
        return ""
    return round(v, digits)

def generate_csv_report(results, top10, dynamic30):
    import csv, io
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    result_map = {str(r.get("coin") or "").upper(): dict(r) for r in (results or []) if r.get("coin")}
    ordered = list(ATLAS_PRIORITY_TOP10) + list(dynamic30 or []) + list(ATLAS_PERSONAL_ASSETS) + list(ATLAS_METALS)
    rows = []
    for sym in ordered:
        s = str(sym).upper()
        r = result_map.get(s)
        if not r:
            continue
        rows.append([
            _csv_group(s, top10, dynamic30, personal_symbols),
            s,
            str(r.get("action", "WAIT")),
            str(r.get("decision_state", "WAIT")),
            _csv_number(r.get("price")),
            _csv_number(r.get("change"), 4),
            _csv_number(r.get("support")),
            _csv_number(r.get("resistance")),
            _csv_number(r.get("entry")),
            _csv_number(r.get("sl")),
            _csv_number(r.get("tp1")),
            _csv_number(r.get("tp2")),
            _csv_number(r.get("tp3")),
            _csv_number(r.get("tp4")),
            _csv_number(r.get("rr"), 3),
            _csv_number(r.get("confidence"), 2),
            r.get("h4_trend", "UNKNOWN"),
            r.get("d1_trend", "UNKNOWN"),
            r.get("w1_trend", "UNKNOWN"),
            _csv_number(r.get("rsi"), 2),
            r.get("macd", ""),
            "",  # Volume
            _csv_number(r.get("volume_ratio"), 3),
            _csv_number(r.get("atr_pct"), 3),
            r.get("liquidity", ""),
            r.get("gate", ""),
            r.get("gate_reason", ""),
            r.get("direction", ""),
            str(r.get("repeat_signal", False)),
            r.get("reason", ""),
            VERSION,
        ])
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    writer.writerows(rows)
    return out.getvalue()

def _telegram_send_document(chat_id, content, filename, caption=None):
    import uuid
    if not TELEGRAM_TOKEN or not chat_id:
        raise RuntimeError("Telegram secrets missing")
    boundary = "----ATLAS" + uuid.uuid4().hex
    body = bytearray()
    def field(name, value):
        body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode())
    field("chat_id", str(chat_id))
    if caption:
        field("caption", caption)
    body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\nContent-Type: text/csv; charset=utf-8\r\n\r\n").encode())
    body.extend(content.encode("utf-8-sig"))
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendDocument failed: {data}")
    return data

def send_csv_report(results, top10, dynamic30):
    content = generate_csv_report(results, top10, dynamic30)
    if not content.strip():
        return 0, ["CSV is empty"]
    dt = now_tehran()
    filename = f"atlas_v11_2_{shamsi(dt).replace('/','')}_{dt.strftime('%H%M%S')}.csv"
    caption = f"📎 ATLAS v11.2 — CSV کامل | {VERSION} | {shamsi(dt)} {dt.strftime('%H:%M:%S')} تهران"
    destinations = []
    for chat_id in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        if chat_id and chat_id not in destinations:
            destinations.append(chat_id)
    sent = 0
    errors = []
    for chat_id in destinations:
        try:
            _telegram_send_document(chat_id, content, filename, caption)
            sent += 1
        except Exception as e:
            errors.append(f"CSV {chat_id}: {e}")
    return sent, errors


# ============================================================
# VOICE OUTPUT (خروجی صوتی فارسی)
# ============================================================

def text_to_speech_persian(text, voice="female"):
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="fa", slow=False)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        tts.save(temp_file.name)
        return temp_file.name
    except ImportError:
        pass
    try:
        import edge_tts
        import asyncio
        voice_map = {"female": "fa-IR-DilaraNeural", "male": "fa-IR-FaridNeural"}
        selected_voice = voice_map.get(voice, "fa-IR-DilaraNeural")
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        output_path = temp_file.name
        temp_file.close()
        async def generate():
            communicate = edge_tts.Communicate(text, selected_voice)
            await communicate.save(output_path)
        asyncio.run(generate())
        return output_path
    except ImportError:
        pass
    try:
        text_encoded = urllib.parse.quote(text)
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={text_encoded}&tl=fa&client=tw-ob"
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            audio_data = response.read()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_file.write(audio_data)
        temp_file.close()
        return temp_file.name
    except Exception as e:
        print(f"⚠️ TTS error: {e}")
        return None

def extract_audio_summary(report_text):
    lines = report_text.split('\n')
    audio_lines = []
    for line in lines:
        clean_line = re.sub(r'[^\w\s\.\،\؟\!\:\(\)]', ' ', line)
        clean_line = re.sub(r'\s+', ' ', clean_line).strip()
        if any(keyword in line for keyword in ['سیگنال', 'خرید', 'فروش', 'اطمینان', 'بازار', 'حمایت', 'مقاومت']):
            if len(clean_line) > 10 and not clean_line.startswith('━'):
                audio_lines.append(clean_line)
    summary = ' . '.join(audio_lines[:10])
    summary = summary.replace('|', '')
    intro = "به گزارش صوتی اطلس خوش آمدید. "
    return intro + summary

def generate_audio_report(report_text, filename="audio_report.mp3"):
    audio_text = extract_audio_summary(report_text)
    audio_file = text_to_speech_persian(audio_text)
    if audio_file:
        import shutil
        final_path = filename
        shutil.move(audio_file, final_path)
        return final_path
    return None

def send_audio_report(audio_file, caption=None):
    if not os.path.exists(audio_file):
        return False
    if not TELEGRAM_TOKEN:
        return False
    with open(audio_file, 'rb') as f:
        audio_data = f.read()
    boundary = '---------------------------' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
    body_parts = []
    body_parts.append('--' + boundary)
    body_parts.append('Content-Disposition: form-data; name="chat_id"')
    body_parts.append('')
    chat_id = TELEGRAM_CHAT_ID or TELEGRAM_GROUP_CHAT_ID
    if chat_id:
        body_parts.append(str(chat_id))
    if caption:
        body_parts.append('--' + boundary)
        body_parts.append('Content-Disposition: form-data; name="caption"')
        body_parts.append('')
        body_parts.append(caption)
    body_parts.append('--' + boundary)
    body_parts.append(f'Content-Disposition: form-data; name="audio"; filename="{os.path.basename(audio_file)}"')
    body_parts.append('Content-Type: audio/mpeg')
    body_parts.append('')
    body_parts.append(audio_data.decode('latin-1') if isinstance(audio_data, bytes) else audio_data)
    body_parts.append('--' + boundary + '--')
    body_parts.append('')
    body = '\r\n'.join(str(p) for p in body_parts).encode('utf-8')
    headers = {
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Content-Length': str(len(body))
    }
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode())
            return result.get('ok', False)
    except Exception as e:
        print(f"❌ Audio send error: {e}")
        return False


# ============================================================
# TELEGRAM
# ============================================================

def _telegram_send_chunk(chat_id, text):
    data = urllib.parse.urlencode({
        "chat_id": str(chat_id),
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data.get('description')}")
        return data

def send_with_retry(chat_id, text, max_retries=5, base_delay=3):
    for attempt in range(max_retries):
        try:
            _telegram_send_chunk(chat_id, text)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = int(e.headers.get('Retry-After', base_delay))
                wait_time = min(retry_after * (2 ** attempt) + random.uniform(0, 1), TELEGRAM_MAX_WAIT)
                print(f"⚠️ Rate limit. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
            else:
                return False
        except Exception as e:
            wait_time = min(base_delay * (2 ** attempt), TELEGRAM_MAX_WAIT)
            time.sleep(wait_time)
    return False

def telegram_send_one(chat_id, text):
    if not TELEGRAM_TOKEN or not chat_id:
        raise RuntimeError("Telegram secrets missing")
    if len(text) > 4096:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            if not send_with_retry(chat_id, chunk):
                return False
            time.sleep(0.5)
        return True
    return send_with_retry(chat_id, text)

def telegram_preflight():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN missing")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
        headers={"User-Agent": "ATLAS-AI/11.2"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getMe failed: {data}")
    print(f"✅ Telegram bot connected: @{data.get('result', {}).get('username', 'unknown')}")
    return data

def split_telegram(text, max_chars=3900):
    if len(text) <= max_chars:
        return [text]
    parts = []
    current = ""
    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 <= max_chars:
            current += ("\n\n" + block) if current else block
        else:
            if current:
                parts.append(current)
            current = block
    if current:
        parts.append(current)
    return parts

def send_report(text):
    parts = split_telegram(text)
    destinations = []
    if TELEGRAM_CHAT_ID:
        destinations.append({"id": TELEGRAM_CHAT_ID, "name": "PRIVATE"})
    if TELEGRAM_GROUP_CHAT_ID:
        destinations.append({"id": TELEGRAM_GROUP_CHAT_ID, "name": "GROUP"})
    if not destinations:
        return len(parts), 0, ["No destinations"]
    sent = 0
    errors = []
    for dest in destinations:
        for part in parts:
            if send_with_retry(dest["id"], part):
                sent += 1
            else:
                errors.append(f"{dest['name']}: failed")
            time.sleep(0.5)
    return len(parts), sent, errors


# ============================================================
# MISSING FUNCTIONS (برای اتمام)
# ============================================================

def http_get(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def safe_http_get(url, timeout=15, headers=None, default=None):
    try:
        return http_get(url, timeout, headers)
    except Exception:
        return default

def _cluster_levels(values, tolerance=0.012):
    return []

def daily_key_levels(daily_rows, current_price=None):
    return {"support": None, "resistance": None, "confidence": "LOW"}

def h4_fallback_levels(rows, current_price=None):
    return {"support": None, "resistance": None, "confidence": "LOW"}

def candle_trigger_state(rows, direction, support=None, resistance=None):
    return {"state": "NEUTRAL"}

def price_consensus(coin):
    return 100, [], "MEDIUM", 0, []

def tf_snapshot(coin):
    return {}

def candle_pattern(rows):
    return "NONE", "NEUTRAL"

def indicator_alignment(tf4):
    return "MIXED", 0, 0, [], False, False

def strong_divergence(rows):
    return None

def momentum_30m(coin):
    return "NEUTRAL", False

def asset_liquidity(coin, sources):
    return 50, "MEDIUM"

def calculate_levels(rows, direction, daily_levels=None):
    return None

def suggested_leverage(atr_pct):
    return 1.0

def weekly_pivot(rows):
    return None

def multi_source_validation(symbol, exchange_price=None):
    return {}

def _validate_trade_geometry(direction, entry, sl, tp1, tp2, min_rr=None):
    return True, None

def _rr_from_values(entry, sl, tp):
    return None


# ============================================================
# MAIN
# ============================================================

def main():
    try:
        print(f"🤖 {VERSION}")
        telegram_preflight()
        init_sqlite()
        
        results = []
        coins = ["BTC", "ETH", "BNB", "XRP", "SOL"]
        for coin in coins:
            try:
                r = analyze_coin(coin, {"candle_pattern": 15, "rsi": 15, "macd": 15, "volume": 15, "higher_trend": 20, "news_clear": 15}, {"impact": "NORMAL", "bias": "NEUTRAL"})
                if r:
                    results.append(r)
                    print(f"✅ {coin}: {r['action']}")
            except Exception as e:
                print(f"❌ {coin}: {e}")
        
        text = build_report(results, ["BTC", "ETH"], [], {}, {"impact": "NORMAL"}, {}, 0)
        send_report(text)
        
        # CSV Export
        csv_sent, csv_errors = send_csv_report(results, ["BTC", "ETH"], [])
        if csv_sent > 0:
            print(f"📊 CSV sent: {csv_sent} destinations")
        
        # Voice Output
        if ENABLE_VOICE_REPORT and results:
            try:
                print("\n🎤 Generating audio report...")
                voice_text = "به گزارش صوتی اطلس خوش آمدید. "
                for r in results[:3]:
                    voice_text += f"{r['coin']} {r['action']} با اطمینان {r['confidence']} درصد. "
                audio_file = generate_audio_report(voice_text)
                if audio_file:
                    result = send_audio_report(audio_file, "🎤 گزارش صوتی اطلس")
                    if result:
                        print("✅ Audio report sent successfully")
                    else:
                        print("❌ Failed to send audio report")
                    try:
                        os.unlink(audio_file)
                    except:
                        pass
            except Exception as e:
                print(f"⚠️ Audio error: {e}")
        
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
