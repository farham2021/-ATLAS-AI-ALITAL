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
        if None in tr:
            return None
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

def trend_from_rows(rows):
    c = closes(rows)
    s20, s50 = sma(c, 20), sma(c, 50)
    if not s20 or not s50:
        return "UNKNOWN"
    price = c[-1]
    if price > s20 > s50:
        return "BULLISH"
    if price < s20 < s50:
        return "BEARISH"
    return "MIXED"

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
    
    # تأثیر رژیم BTC
    if btc_regime and btc_regime.get("regime") == "RISK_ON":
        score += 20
    elif btc_regime and btc_regime.get("regime") == "RISK_OFF":
        score -= 20
    
    # تأثیر وسعت بازار
    if breadth and isinstance(breadth, dict):
        if breadth.get("score", 50) >= 65:
            score += 15
        elif breadth.get("score", 50) <= 35:
            score -= 15
    
    # تأثیر اخبار
    if news_impact == "HIGH":
        score -= 25
    elif news_impact == "NORMAL":
        score += 5
    
    score = max(0, min(100, score))
    
    # تعیین سطح
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
# 5. RISK REPORT (گزارش ریسک بازار) - اصلاح شده
# ============================================================

def generate_risk_report(btc_regime, breadth, market_quality, portfolio_risk=0):
    """تولید گزارش ریسک بازار"""
    lines = ["━━━━━━━━━━━━━━━━━━", "🛡️ گزارش ریسک بازار", "━━━━━━━━━━━━━━━━━━"]
    
    # رژیم BTC
    regime = btc_regime.get("regime", "UNKNOWN") if btc_regime else "UNKNOWN"
    regime_emoji = "🟢" if regime == "RISK_ON" else "🔴" if regime == "RISK_OFF" else "🟡"
    lines.append(f"{regime_emoji} رژیم بازار: {regime}")
    
    # کیفیت بازار - با بررسی وجود کلیدها
    if market_quality and isinstance(market_quality, dict):
        level = market_quality.get("level", "MEDIUM")
        score = market_quality.get("score", 50)
        emoji = market_quality.get("emoji", "🟡")
        lines.append(f"{emoji} کیفیت بازار: {level} ({score:.0f}%)")
    else:
        lines.append("🟡 کیفیت بازار: نامشخص")
    
    # وسعت بازار
    if breadth and isinstance(breadth, dict):
        breadth_score = breadth.get("score", 50)
        breadth_emoji = "🟢" if breadth_score >= 65 else "🔴" if breadth_score <= 35 else "🟡"
        lines.append(f"{breadth_emoji} وسعت بازار: {breadth_score:.1f}% صعودی")
    
    # ریسک پرتفوی
    if portfolio_risk and portfolio_risk > 0:
        risk_emoji = "🟢" if portfolio_risk <= 3 else "🟡" if portfolio_risk <= 6 else "🔴"
        lines.append(f"{risk_emoji} ریسک پرتفوی: {portfolio_risk:.1f}%")
    
    # وضعیت نهایی
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
    # Double Bottom (کف دوقلو) - ساده شده
    if len(c) >= 20:
        recent = c[-20:]
        min1 = min(recent[:10])
        min2 = min(recent[10:])
        if abs(min1 - min2) / max(min1, min2) < 0.03 and c[-1] > min2 * 1.02:
            patterns.append({"pattern": "DOUBLE_BOTTOM", "direction": "BULLISH", "message": "📊 الگوی کف دوقلو شناسایی شد"})
    # Double Top (سقف دوقلو)
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

def candle_is_closed(start_ms, timeframe, now_ms=None):
    if start_ms is None:
        return False
    now_ms = now_ms or int(time.time() * 1000)
    try:
        dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        if timeframe == "1M":
            if dt.month == 12:
                nxt = dt.replace(year=dt.year + 1, month=1, day=1)
            else:
                nxt = dt.replace(month=dt.month + 1, day=1)
            return int(nxt.timestamp() * 1000) <= now_ms
        if timeframe == "1w":
            nxt = dt + timedelta(days=7)
            return int(nxt.timestamp() * 1000) <= now_ms
        fixed = {
            "15m": 15 * 60 * 1000, "30m": 30 * 60 * 1000,
            "1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000,
            "1d": 24 * 60 * 60 * 1000,
        }.get(timeframe)
        if fixed is None:
            return False
        return start_ms + fixed <= now_ms
    except Exception:
        return False


# ============================================================
# ANALYZE COIN
# ============================================================

def analyze_coin(coin, weights, market_news=None, btc_regime=None, breadth=None):
    if is_stable(coin):
        return None
    try:
        rows, engine = best_ohlcv(coin, "4h", 250)
    except Exception:
        return None
    if len(rows) < 60:
        return None
    c = closes(rows)
    rsi_value = rsi(c)
    ml, ms, _ = macd(c)
    atrp = atr_pct(rows)
    vol_ratio = volume_ratio(rows)
    sup, res = support_resistance(rows)
    trend = trend_from_rows(rows)
    price = c[-1] if c else None
    if price is None:
        return None
    prev_price = c[-2] if len(c) > 1 else None
    
    # تشخیص الگو
    pattern = "NONE"
    pattern_dir = "NEUTRAL"
    if len(rows) >= 2:
        a, b = rows[-2], rows[-1]
        ao, ac = f(a[1]), f(a[4])
        bo, bh, bl, bc = f(b[1]), f(b[2]), f(b[3]), f(b[4])
        if bc > bo and ac < ao and bo <= ac and bc >= ao:
            pattern = "BULLISH ENGULFING"
            pattern_dir = "BULLISH"
        elif bc < bo and ac > ao and bo >= ac and bc <= ao:
            pattern = "BEARISH ENGULFING"
            pattern_dir = "BEARISH"
    
    # تشخیص الگوهای تکراری
    detected_patterns = detect_patterns(rows)
    
    direction = "NONE"
    if rsi_value and ml and ms:
        if rsi_value > 50 and ml > ms and trend == "BULLISH":
            direction = "LONG"
        elif rsi_value < 50 and ml < ms and trend == "BEARISH":
            direction = "SHORT"
    
    levels = None
    if direction in ("LONG", "SHORT"):
        atr_v = atr(rows)
        if atr_v and sup and res:
            if direction == "LONG":
                entry = price if price >= res else res * 1.002
                sl = entry - (atr_v * 1.5)
                tp1 = entry + (atr_v * 1.5)
                tp2 = entry + (atr_v * 3)
                levels = {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "atr": atr_v}
            else:
                entry = price if price <= sup else sup * 0.998
                sl = entry + (atr_v * 1.5)
                tp1 = entry - (atr_v * 1.5)
                tp2 = entry - (atr_v * 3)
                levels = {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "atr": atr_v}
    
    rr = None
    if levels:
        entry, sl, tp2 = levels['entry'], levels['sl'], levels['tp2']
        if entry != sl:
            rr = abs(entry - tp2) / abs(entry - sl)
    
    confidence = 50
    if direction in ("LONG", "SHORT"):
        if rsi_value:
            if (direction == "LONG" and 50 <= rsi_value <= 68) or (direction == "SHORT" and 32 <= rsi_value <= 50):
                confidence += 15
        if ml and ms:
            if (direction == "LONG" and ml > ms) or (direction == "SHORT" and ml < ms):
                confidence += 15
        if vol_ratio and vol_ratio >= 1.2:
            confidence += 10
        if pattern != "NONE":
            confidence += 10
        if trend in ("BULLISH", "BEARISH"):
            confidence += 10
    confidence = min(100, max(0, confidence))
    
    # فیلتر کیفیت بازار
    market_quality = get_market_quality(btc_regime or {}, breadth or {}, market_news.get("impact", "NORMAL") if market_news else "NORMAL")
    if market_quality.get("level") == "LOW" and direction in ("LONG", "SHORT"):
        confidence *= 0.7
    
    gate = "PASS"
    gate_reason = "All gates passed"
    
    if direction in ("LONG", "SHORT"):
        if direction == "LONG" and rsi_value and rsi_value > 75:
            gate = "BLOCK"
            gate_reason = "RSI اشباع خرید"
        elif direction == "SHORT" and rsi_value and rsi_value < 25:
            gate = "BLOCK"
            gate_reason = "RSI اشباع فروش"
    
    if direction in ("LONG", "SHORT"):
        if vol_ratio is None or vol_ratio < MIN_VOLUME_RATIO:
            gate = "BLOCK"
            gate_reason = "حجم تأیید نشد"
    
    if direction in ("LONG", "SHORT"):
        if not is_signal_fresh(coin, direction):
            gate = "BLOCK"
            gate_reason = "سیگنال تکراری"
    
    if levels and rr is not None and rr < MIN_EXECUTABLE_RR:
        gate = "BLOCK"
        gate_reason = f"R/R پایین ({rr:.2f})"
    
    if confidence < MIN_CONFIDENCE:
        gate = "BLOCK"
        gate_reason = f"اطمینان پایین ({confidence:.0f}%)"
    
    tf_confirmation = multi_timeframe_confirmation(coin, {})
    level_breaks = []
    if sup and res and prev_price:
        level_breaks = detect_level_breaks(price, sup, res, prev_price)
    
    sl_alert = None
    if levels and levels.get('sl'):
        sl_alert = check_stop_loss_alert(price, levels['sl'])
    
    action = "NO TRADE"
    if gate == "PASS" and tf_confirmation.get("confirmed", False):
        if direction == "LONG":
            action = "BUY CONFIRMATION"
        elif direction == "SHORT":
            action = "SELL CONFIRMATION"
    
    position_suggestion = None
    if levels and action in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
        position_suggestion = get_position_suggestion({
            "entry": levels.get('entry'),
            "sl": levels.get('sl')
        })
    
    entry_quality = 0
    if levels:
        entry_quality = entry_quality_score(
            levels.get('entry'), levels.get('sl'),
            vol_ratio, rsi_value, trend,
            "HIGH" if sup and res else "LOW"
        )
    
    exit_signal = None
    if levels and action in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
        exit_signal = generate_exit_signal(
            levels.get('entry'), price, direction,
            levels.get('tp1'), levels.get('tp2'), levels.get('sl')
        )
    
    # تحلیل حجم هوشمند
    volume_analysis = None
    if vol_ratio:
        avg_vol = sum([f(x[5]) for x in rows[-21:-1] if f(x[5]) is not None]) / 20 if len(rows) >= 21 else None
        current_vol = f(rows[-1][5]) if rows else None
        volume_analysis = smart_volume_analysis(vol_ratio, avg_vol, current_vol)
    
    session, session_label = get_current_session()
    
    return {
        "coin": coin,
        "price": price,
        "prev_price": prev_price,
        "change": None,
        "h4_trend": trend,
        "d1_trend": trend,
        "w1_trend": "UNKNOWN",
        "rsi": rsi_value,
        "macd": "BULLISH" if ml and ms and ml > ms else "BEARISH" if ml and ms and ml < ms else "UNKNOWN",
        "volume_ratio": vol_ratio,
        "atr_pct": atrp,
        "support": sup,
        "resistance": res,
        "direction": direction,
        "action": action,
        "confidence": int(confidence),
        "entry": levels['entry'] if levels else None,
        "sl": levels['sl'] if levels else None,
        "tp1": levels['tp1'] if levels else None,
        "tp2": levels['tp2'] if levels else None,
        "tp3": None,
        "tp4": None,
        "rr": rr,
        "gate": gate,
        "gate_reason": gate_reason,
        "reason": f"RSI: {rsi_value:.1f}, MACD: {'صعودی' if ml and ms and ml > ms else 'نزولی'}, حجم: {vol_ratio:.2f}x" if rsi_value and vol_ratio else "تحلیل پایه",
        "pattern": pattern,
        "pattern_dir": pattern_dir,
        "detected_patterns": detected_patterns,
        "sr_confidence": "HIGH" if sup and res else "LOW",
        "liquidity": "MEDIUM",
        "liquidity_score": 50,
        "quality": "MEDIUM",
        "overbought": rsi_value > 70 if rsi_value else False,
        "oversold": rsi_value < 30 if rsi_value else False,
        "snapshots": {"4h": {"rows": rows}},
        "level_breaks": level_breaks,
        "sl_alert": sl_alert,
        "position_suggestion": position_suggestion,
        "market_quality": market_quality,
        "tf_confirmation": tf_confirmation,
        "entry_quality": entry_quality,
        "exit_signal": exit_signal,
        "volume_analysis": volume_analysis,
        "session": session,
        "session_label": session_label,
        "graphical_price": graphical_price_display(price, prev_price),
        "improved": {
            "market_quality": market_quality.get("level"),
            "tf_confirmed": tf_confirmation.get("confirmed", False),
            "sl_alert": sl_alert is not None,
            "position_suggestion": position_suggestion is not None,
            "entry_quality": entry_quality,
            "exit_signal": exit_signal is not None,
            "patterns_found": len(detected_patterns),
            "session": session,
            "volume_alert": volume_analysis.get("alert", False) if volume_analysis else False
        }
    }


# ============================================================
# PARALLEL PROCESSING
# ============================================================

def analyze_coins_parallel(coins, weights, market_news=None, btc_regime=None, breadth=None):
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_coin = {
            executor.submit(analyze_coin, coin, weights, market_news, btc_regime, breadth): coin
            for coin in coins if not is_stable(coin)
        }
        for future in as_completed(future_to_coin):
            coin = future_to_coin[future]
            try:
                result = future.result(timeout=30)
                if result:
                    results.append(result)
                    print(f"✅ {coin}: {result.get('action', 'NO TRADE')} ({result.get('confidence', 0)}%)")
            except Exception as e:
                print(f"❌ {coin}: {e}")
    return results


# ============================================================
# CSV EXPORT
# ============================================================

CSV_COLUMNS = (
    "Group", "Symbol", "Status", "DecisionState", "Price", "Change24H",
    "Support", "Resistance", "Entry", "SL", "TP1", "TP2", "TP3", "TP4",
    "R/R", "Confidence", "H4Trend", "D1Trend", "W1Trend", "RSI", "MACD",
    "Volume", "VolumeRatio", "ATR_pct", "Liquidity", "Gate", "GateReason",
    "Direction", "RepeatSignal", "Reason", "ModelVersion", "EntryQuality", "Session"
)

def _csv_group(symbol, top10, dynamic30, personal_symbols):
    s = str(symbol or "").upper()
    if s in personal_symbols:
        return "PERSONAL_PORTFOLIO"
    if s in {str(x).upper() for x in (top10 or ATLAS_PRIORITY_TOP10)}:
        return "MARKET_TOP10"
    if s in {str(x).upper() for x in (dynamic30 or [])}:
        return "DYNAMIC_TOP30"
    return "ATLAS_RADAR"

def _csv_safe_plan(r):
    direction = r.get("direction")
    entry, sl, tp1, tp2 = (f(r.get(k)) for k in ("entry", "sl", "tp1", "tp2"))
    if None in (entry, sl, tp1, tp2):
        return None
    if direction == "LONG":
        if not (sl < entry < tp1 < tp2):
            return None
    else:
        if not (sl > entry > tp1 > tp2):
            return None
    rr = _rr_from_values(entry, sl, tp2)
    if rr is None or rr <= 0:
        return None
    return entry, sl, tp1, tp2

def _rr_from_values(entry, sl, tp):
    entry, sl, tp = f(entry), f(sl), f(tp)
    if None in (entry, sl, tp) or entry == sl:
        return None
    return abs(entry - tp) / abs(entry - sl)

def _csv_number(value, digits=8):
    v = f(value)
    if v is None:
        return ""
    return round(v, digits)

def generate_csv_report(results, top10, dynamic30):
    import csv, io
    personal_symbols = {str(x).upper() for x in ATLAS_PERSONAL_ASSETS}
    result_map = {str(r.get("coin") or "").upper(): dict(r) for r in (results or []) if r.get("coin")}
    
    ordered = []
    for sym in list(top10 or ATLAS_PRIORITY_TOP10) + list(dynamic30 or []) + list(ATLAS_PERSONAL_ASSETS):
        s = str(sym).upper()
        if s and s not in ordered:
            ordered.append(s)
    for metal in ATLAS_METALS:
        if metal not in ordered:
            ordered.append(metal)
    
    rows = []
    for sym in ordered:
        r = result_map.get(sym)
        if not r:
            continue
        plan = _csv_safe_plan(r)
        entry = sl = tp1 = tp2 = tp3 = tp4 = rr = ""
        if plan:
            entry, sl, tp1, tp2 = plan
            tp3, tp4 = f(r.get("tp3")), f(r.get("tp4"))
            rr = _rr_from_values(entry, sl, tp2)
        rows.append([
            _csv_group(sym, top10, dynamic30, personal_symbols),
            sym,
            str(r.get("action", "WAIT")),
            str(r.get("decision_state", "WAIT")),
            _csv_number(r.get("price")),
            _csv_number(r.get("change"), 4),
            _csv_number(r.get("support")),
            _csv_number(r.get("resistance")),
            _csv_number(entry),
            _csv_number(sl),
            _csv_number(tp1),
            _csv_number(tp2),
            _csv_number(tp3),
            _csv_number(tp4),
            _csv_number(rr, 3),
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
            _csv_number(r.get("entry_quality", 0), 2),
            r.get("session", ""),
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
# MAIN
# ============================================================

def main():
    try:
        print(f"🤖 {VERSION}")
        print("━━━━━━━━━━━━━━━━━━")
        telegram_preflight()
        init_sqlite()
        ensure_exchanges()
        
        universe = ["BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "LINK", "AVAX", "MATIC"]
        weights = {"rsi": 15, "macd": 15, "volume": 15, "higher_trend": 20, "candle_pattern": 15}
        
        print("📊 Analyzing coins in parallel...")
        results = analyze_coins_parallel(universe, weights)
        print(f"✅ Analyzed {len(results)} coins")
        
        btc_regime = {"regime": "RISK_ON"}
        breadth = {"score": 65, "state": "BULLISH"}
        market_news = {"impact": "NORMAL"}
        
        # 1. Voice Summary
        voice_summary = generate_voice_summary(results, btc_regime, breadth)
        print("\n" + voice_summary)
        
        # 2. Signal Ranking
        ranked = rank_signals(results, limit=5)
        if ranked:
            ranking_lines = ["\n🏆 TOP 5 SETUPS", "━━━━━━━━━━━━━━━━━━"]
            for i, r in enumerate(ranked, 1):
                direction = "🟢 BUY" if r.get("direction") == "LONG" else "🔴 SELL"
                ranking_lines.append(
                    f"{i}. {r['coin']} — {direction} — {r.get('confidence', 0)}% — R/R {r.get('rr', 0):.2f} — Score: {r.get('quality_score', 0):.0f}"
                )
            print("\n" + "\n".join(ranking_lines))
        
        # 3. Sentiment Analysis
        sentiment = analyze_sentiment([], fear_greed=None)
        print(f"\n😊 Sentiment: {sentiment['emoji']} {sentiment['level']} ({sentiment['score']:.0f}%)")
        
        # 4. Correlation Analysis
        if len(results) > 2:
            correlations = analyze_correlations(results)
            if correlations:
                corr_lines = ["\n🔗 TOP CORRELATIONS", "━━━━━━━━━━━━━━━━━━"]
                for c in correlations[:5]:
                    corr_lines.append(f"{c['symbol1']} ⇄ {c['symbol2']}: {c['correlation']:.2f} ({c['strength']})")
                print("\n" + "\n".join(corr_lines))
        
        # 5. Level Break Alerts
        all_breaks = []
        for r in results:
            if r.get('level_breaks'):
                all_breaks.extend(r['level_breaks'])
        if all_breaks:
            alert_lines = ["\n🚨 LEVEL BREAK ALERTS", "━━━━━━━━━━━━━━━━━━"]
            for alert in all_breaks:
                alert_lines.append(alert['message'])
            print("\n" + "\n".join(alert_lines))
        
        # 6. Risk Report
        market_quality = get_market_quality(btc_regime, breadth, market_news["impact"])
        risk_report = generate_risk_report(btc_regime, breadth, market_quality)
        print("\n" + risk_report)
        
        # 7. Position Sizing
        actionable = [r for r in results if r.get("action") in ("BUY CONFIRMATION", "SELL CONFIRMATION")]
        if actionable:
            pos_lines = ["\n📐 POSITION SIZING", "━━━━━━━━━━━━━━━━━━"]
            for r in actionable[:3]:
                pos = r.get('position_suggestion')
                if pos:
                    direction = "🟢 BUY" if r.get("direction") == "LONG" else "🔴 SELL"
                    pos_lines.append(
                        f"{r['coin']} {direction}: {pos['units']:.4f} units (${pos['amount']:,.0f}) — Risk: {pos['risk_percent']:.1f}%"
                    )
            print("\n" + "\n".join(pos_lines))
        
        # 8. Weekly Analysis
        weekly = generate_weekly_analysis(results)
        print("\n" + weekly)
        
        # 9. Graphical Price Display
        graph_lines = ["\n📈 GRAPHICAL PRICE DISPLAY", "━━━━━━━━━━━━━━━━━━"]
        for r in results[:5]:
            if r.get('graphical_price'):
                graph_lines.append(f"{r['coin']}: {r['graphical_price']}")
        print("\n" + "\n".join(graph_lines))
        
        # 10. Full Report
        report_lines = [
            "━━━━━━━━━━━━━━━━━━",
            f"📊 {VERSION} REPORT",
            "━━━━━━━━━━━━━━━━━━",
            "",
            voice_summary,
            "",
            "━━━━━━━━━━━━━━━━━━",
            "🏆 SIGNAL RANKING",
            "━━━━━━━━━━━━━━━━━━",
        ]
        if ranked:
            for i, r in enumerate(ranked, 1):
                direction = "🟢 BUY" if r.get("direction") == "LONG" else "🔴 SELL"
                report_lines.append(
                    f"{i}. {r['coin']} — {direction} — اطمینان: {r.get('confidence', 0)}% | R/R: {r.get('rr', 0):.2f}"
                )
                if r.get('entry') and r.get('sl') and r.get('tp2'):
                    report_lines.append(
                        f"   Entry: {fmt(r['entry'])} | SL: {fmt(r['sl'])} | TP2: {fmt(r['tp2'])}"
                    )
                if r.get('position_suggestion'):
                    pos = r['position_suggestion']
                    report_lines.append(
                        f"   💰 حجم: {pos['units']:.4f} واحد (${pos['amount']:,.0f})"
                    )
                if r.get('sl_alert'):
                    report_lines.append(f"   {r['sl_alert']['message']}")
                if r.get('exit_signal'):
                    report_lines.append(f"   {r['exit_signal']['message']}")
                if r.get('graphical_price'):
                    report_lines.append(f"   {r['graphical_price']}")
                report_lines.append("")
        else:
            report_lines.append("⚠️ هیچ سیگنال تأییدشده‌ای موجود نیست")
        
        if all_breaks:
            report_lines.append("━━━━━━━━━━━━━━━━━━")
            report_lines.append("🚨 LEVEL BREAK ALERTS")
            report_lines.append("━━━━━━━━━━━━━━━━━━")
            for alert in all_breaks[:5]:
                report_lines.append(alert['message'])
            report_lines.append("")
        
        if correlations:
            report_lines.append("━━━━━━━━━━━━━━━━━━")
            report_lines.append("🔗 CORRELATIONS")
            report_lines.append("━━━━━━━━━━━━━━━━━━")
            for c in correlations[:5]:
                report_lines.append(f"{c['symbol1']} ⇄ {c['symbol2']}: {c['correlation']:.2f} ({c['strength']})")
            report_lines.append("")
        
        report_lines.append(risk_report)
        report_lines.append("")
        report_lines.append(f"😊 Sentiment: {sentiment['emoji']} {sentiment['level']} ({sentiment['score']:.0f}%)")
        
        session, session_label = get_current_session()
        report_lines.append(f"🕐 SESSION: {session_label}")
        report_lines.append(f"📆 {shamsi(now_tehran())} {now_tehran().strftime('%H:%M')}")
        
        text = "\n".join(report_lines)
        parts, sent, errors = send_report(text)
        
        # 11. CSV Export
        csv_sent, csv_errors = send_csv_report(results, [], [])
        if csv_sent > 0:
            print(f"📊 CSV sent: {csv_sent} destinations")
        if csv_errors:
            print(f"⚠️ CSV errors: {csv_errors}")
        
        # 12. Voice Output
        if ENABLE_VOICE_REPORT and results:
            try:
                print("\n🎤 Generating audio report...")
                voice_text = "\n".join([
                    voice_summary,
                    "",
                    "سیگنال‌های برتر:",
                    *[f"{i+1}. {r['coin']} {'خرید' if r.get('direction')=='LONG' else 'فروش'} با اطمینان {r.get('confidence',0)} درصد" 
                      for i, r in enumerate(ranked[:3]) if r]
                ])
                audio_file = generate_audio_report(voice_text)
                if audio_file:
                    caption = f"🎤 گزارش صوتی اطلس | {shamsi(now_tehran())} {now_tehran().strftime('%H:%M')}"
                    result = send_audio_report(audio_file, caption)
                    if result:
                        print("✅ Audio report sent successfully")
                    else:
                        print("❌ Failed to send audio report")
                    try:
                        os.unlink(audio_file)
                    except:
                        pass
                else:
                    print("⚠️ Audio generation failed")
            except Exception as e:
                print(f"⚠️ Audio error: {e}")
        
        if errors:
            print(f"⚠️ Errors: {errors}")
        else:
            print(f"✅ Sent {sent} messages")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
