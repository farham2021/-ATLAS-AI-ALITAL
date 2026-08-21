# ============================================================
# ATLAS AI v10.1 — HARDENED DECISION ENGINE
# ============================================================
# v10.1 architecture hardening:
# - canonical CoinGecko IDs for /simple/price
# - weekly pivot defined defensively
# - Daily S/R primary with high-confidence H4 fallback for continuity
# - cached mandatory backtest gate
# - per-destination Telegram delivery state
# - relaxed H1 hard-gating while H4/D1 remain the primary trend filter
# - configurable volume threshold
# - zero-division and error observability hardening
# - fixed critical direction-before-trigger execution bug that caused Total scanned: 0
# - confirmation uses the latest fully CLOSED 4H candle, independent of exact cron minute
# - preserved the three fixed global-market report times and Telegram supergroup delivery
# - de-duplicated CoinGecko mover symbols
# - stronger final conclusion: best setup, entry/SL/TP and actionable ranking
# - unavailable asset count is explicitly reported for diagnostics
# v10.1 hardening: differentiated confidence, DXY fallback chain, 24H fallback,
# human-like overbought/oversold execution control, watch-quality ranking,
# and accurate attempted/successful asset accounting.
# v10.1 reporting hardening: fixed ATLAS Top-10 priority order, then Dynamic Top-30,
# then Static Radar; Telegram chunking now preserves radar section boundaries.
# Purpose:
#   Professional multi-timeframe market surveillance and signal engine.
#
# Design principles:
#   - ATLAS static radar is NEVER removed.
#   - Top-10 market-cap assets are refreshed every run.
#   - Next 30 dynamic assets are refreshed every run.
#   - Stablecoins are excluded from trading analysis.
#   - Crypto: 1H / 4H / 1D via CCXT exchange data.
#   - Macro/commodities: DXY, Gold, Silver, Copper, WTI, Brent via Yahoo
#     Finance chart API (or Alpha Vantage when configured).
#   - Signals require multi-factor confirmation.
#   - No signal is allowed against the higher-timeframe trend unless a
#     strong three-level divergence is detected.
#   - Incomplete candles are excluded.
#   - Telegram reports are split safely into multiple messages.
#   - The same report can be mirrored to a Telegram supergroup.
#   - Supabase is the primary persistence layer; SQLite is a local fallback.
#   - Signal outcomes are evaluated later from historical candles.
#   - Model weights are changed only after a mandatory backtest gate.
#   - Every self-modification is written to the changelog.
#
# IMPORTANT:
#   This is an analytical engine. It does not place orders.
#   No model can guarantee low-error signals or profits.
# ============================================================

import os
import re
import json
import math
import time
import sqlite3
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from statistics import mean, median

import ccxt


# ============================================================
# CONFIG
# ============================================================

VERSION = "ATLAS v10.1"
TIMEFRAMES = ("1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = "4h"
EVENT_TIMEFRAMES = ("30m", "1h", "4h", "1d", "1w", "1M")
EVENT_LOOKBACK_LIMITS = {"30m": 80, "1h": 120, "4h": 120, "1d": 120, "1w": 80, "1M": 60}
EVENT_DEDUP_ENABLED = os.environ.get("ATLAS_CANDLE_EVENT_DEDUP", "1").strip() != "0"
TEHRAN = ZoneInfo("Asia/Tehran")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_GROUP_CHAT_ID = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "").strip()

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://tmnfhsuwtqfpglckfxwg.supabase.co"
).strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
# For server-side GitHub Actions, SERVICE_ROLE is preferred.
# SUPABASE_ANON_KEY can be used only when RLS policies permit the writes.
if not SUPABASE_KEY:
    SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()

COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "").strip()
CRYPTOPANIC_TOKEN = os.environ.get("CRYPTOPANIC_TOKEN", "").strip()
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "").strip()

RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE_PCT", "1.5"))
MAX_PORTFOLIO_RISK = float(
    os.environ.get("MAX_PORTFOLIO_OPEN_RISK_PCT", "6.0")
)
MIN_CONFIDENCE = float(os.environ.get("ATLAS_MIN_CONFIDENCE", "60"))
MAX_LEVERAGE = float(os.environ.get("ATLAS_MAX_LEVERAGE", "10"))
BACKTEST_DAYS = int(os.environ.get("ATLAS_BACKTEST_DAYS", "180"))
SIGNAL_HORIZON_BARS = int(os.environ.get("ATLAS_SIGNAL_HORIZON_BARS", "36"))
MIN_BACKTEST_IMPROVEMENT = float(
    os.environ.get("ATLAS_BACKTEST_IMPROVEMENT", "10")
)
BACKTEST_REFRESH_HOURS = float(os.environ.get("ATLAS_BACKTEST_REFRESH_HOURS", "24"))
MIN_VOLUME_RATIO = float(os.environ.get("ATLAS_MIN_VOLUME_RATIO", "0.80"))
H4_FALLBACK_MIN_SCORE = float(os.environ.get("ATLAS_H4_FALLBACK_MIN_SCORE", "70"))
REQUEST_SLEEP_SECONDS = float(os.environ.get("ATLAS_REQUEST_SLEEP_SECONDS", "0.50"))

# v9 Decision Engine: a signal is not a trade merely because indicators align.
MIN_EXECUTABLE_RR = float(os.environ.get("ATLAS_MIN_EXECUTABLE_RR", "2.0"))
MIN_WATCH_CONFIDENCE = float(os.environ.get("ATLAS_MIN_WATCH_CONFIDENCE", "55"))
BTC_REGIME_CACHE_MINUTES = int(os.environ.get("ATLAS_BTC_REGIME_CACHE_MINUTES", "30"))
SIGNAL_MEMORY_HOURS = int(os.environ.get("ATLAS_SIGNAL_MEMORY_HOURS", "12"))
MARKET_BREADTH_MIN_SAMPLES = int(os.environ.get("ATLAS_MARKET_BREADTH_MIN_SAMPLES", "8"))

DB_FILE = os.environ.get("ATLAS_SQLITE_FILE", "atlas_v10.sqlite3")
CHANGELOG_FILE = os.environ.get("ATLAS_CHANGELOG", "changelog.txt")


# ============================================================
# ATLAS RADAR
# ============================================================

# These assets belong to the user's ATLAS radar and remain under
# surveillance even if they leave CoinGecko's current top ranks.
# Fixed priority radar requested for the first Telegram messages.
# This order is deliberate and MUST NOT be replaced by CoinGecko rank ordering.
ATLAS_PRIORITY_TOP10 = [
    "BTC", "ETH", "BNB", "XRP", "SOL",
    "TRX", "HYPE", "DOGE", "ADA", "POL",
]

ATLAS_STATIC = [
    "BTC", "ETH", "XRP", "SOL", "BNB", "TON", "ADA", "DOGE", "TRX", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR", "NEAR",
    "QNT", "GRT", "TAO", "ONDO", "UNI", "ETHFI", "ATOM", "FIL", "AAVE", "MKR",
    "APT", "ARB", "OP", "INJ", "TIA", "SEI", "PEPE", "FET", "ICP", "ETC",
    "HYPE", "POL",
]

STABLE_SYMBOLS = {
    "USDT", "USDC", "USDE", "USDS", "DAI", "FDUSD", "TUSD", "USDP",
    "PYUSD", "USDD", "FRAX", "LUSD", "GUSD", "USDG", "USDB", "EURC",
    "USDC.E", "USD0", "USD1",
}

# Canonical exchange aliases. Polygon migrated from MATIC to POL.
DISPLAY_SYMBOLS = {"POL": "MATIC"}
SYMBOL_ALIASES = {"MATIC": "POL", "POL": "POL"}


# Yahoo Finance symbols.
MACRO_SYMBOLS = {
    # Yahoo's canonical searchable ICE US Dollar Index symbol is DX-Y.NYB.
    # ^DXY remains a fallback because Yahoo chart availability can vary.
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
    """Gregorian -> Jalali without requiring an external package."""
    gy, gm, gd = dt.year, dt.month, dt.day
    gdm = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
        + (gy2 + 399) // 400 + gd
    )
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


def safe_mean(values, default=None):
    vals = [safe_float(v) for v in (values or [])]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else default


def safe_median(values, default=None):
    vals = [safe_float(v) for v in (values or [])]
    vals = [v for v in vals if v is not None]
    if not vals:
        return default
    vals.sort()
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


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


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def is_stable(symbol):
    s = (symbol or "").upper().replace("-", "")
    return s in {x.replace("-", "").upper() for x in STABLE_SYMBOLS}

def canonical_symbol(symbol):
    s = (symbol or "").upper().strip()
    return SYMBOL_ALIASES.get(s, s)

def display_symbol(symbol):
    s = (symbol or "").upper().strip()
    return DISPLAY_SYMBOLS.get(s, s)


def safe_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def http_get(url, timeout=15, headers=None):
    h = {
        "User-Agent": "ATLAS-AI/8.7",
        "Accept": "application/json,application/xml,text/xml,*/*",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        ctype = (r.headers.get("Content-Type") or "").lower()
        if raw.lstrip().startswith("<") or "xml" in ctype:
            return ET.fromstring(raw)
        return json.loads(raw)


def safe_http_get(url, timeout=15, headers=None, default=None):
    try:
        return http_get(url, timeout, headers)
    except ET.ParseError as e:
        append_changelog("HTTP_XML", None, None, f"XML parse failed: {url}: {e}")
        return default
    except Exception as e:
        append_changelog("HTTP", None, None, f"request failed: {url}: {e}")
        return default


# ============================================================
# SQLITE FALLBACK / LOCAL AUDIT
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
        """)


# ============================================================
# SUPABASE STORAGE
# ============================================================

class SupabaseStore:
    def __init__(self):
        self.enabled = bool(SUPABASE_URL and SUPABASE_KEY)
        self.headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def insert(self, table, row):
        if not self.enabled:
            return False
        try:
            url = f"{SUPABASE_URL}/rest/v1/{table}"
            req = urllib.request.Request(
                url,
                data=safe_json(row).encode(),
                headers=self.headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            if table != "atlas_changelog":
                try:
                    with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
                        fh.write(f"{now_utc().isoformat()} | SUPABASE | insert failed: {table}: {e}\n")
                except Exception:
                    pass
            return False

    def update(self, table, match, row):
        if not self.enabled:
            return False
        try:
            q = urllib.parse.urlencode(match)
            url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
            req = urllib.request.Request(
                url,
                data=safe_json(row).encode(),
                headers=self.headers,
                method="PATCH",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            if table != "atlas_changelog":
                try:
                    with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
                        fh.write(f"{now_utc().isoformat()} | SUPABASE | update failed: {table}: {e}\n")
                except Exception:
                    pass
            return False

    def select(self, table, params=None):
        if not self.enabled:
            return []
        try:
            q = urllib.parse.urlencode(params or {})
            url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception:
            return []


STORE = SupabaseStore()


def append_changelog(component, old, new, reason, evidence=None):
    ts = now_utc().isoformat()
    line = (
        f"{ts} | {VERSION} | {component} | "
        f"{old!r} -> {new!r} | {reason}"
    )
    if evidence:
        line += f" | {safe_json(evidence)}"
    try:
        with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    STORE.insert(
        "atlas_changelog",
        {
            "timestamp": ts,
            "model_version": VERSION,
            "component": component,
            "old_value": old if isinstance(old, (int, float)) else None,
            "new_value": new if isinstance(new, (int, float)) else None,
            "reason": reason,
            "evidence": evidence or {},
        },
    )


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
    for eid in ("binance", "xt", "lbank"):
        try:
            ex = make_exchange(eid)
            markets = ex.load_markets()
            if not markets:
                raise RuntimeError(f"{eid}: empty market catalog")
            EX[eid] = ex
            MARKETS[eid] = markets
        except Exception as e:
            EX.pop(eid, None)
            MARKETS.pop(eid, None)
            append_changelog("EXCHANGE_INIT", None, None, f"{eid}: {e}")


EX = {}
MARKETS = {}

def ensure_exchanges(force=False):
    """Initialize exchanges lazily; retry when an earlier network init failed."""
    if EX and MARKETS and not force:
        return True
    init_exchanges()
    return bool(EX)


def symbol_for(eid, coin):
    markets = MARKETS.get(eid, {})
    coin = canonical_symbol(coin)
    for s in (f"{coin}/USDT", f"{coin}/USDT:USDT"):
        if s in markets:
            return s
    # Last-resort legacy alias lookup for exchanges that still expose MATIC.
    if coin == "POL":
        for s in ("MATIC/USDT", "MATIC/USDT:MATIC", "MATIC/USDT:USDT"):
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
    """Return the next UTC candle boundary; monthly/weekly are calendar-aware."""
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
    """Keep only fully closed candles, including calendar-aware weekly/monthly candles."""
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
    """Detect a newly observed CLOSED candle without pretending REST is tick-level realtime."""
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


def best_ohlcv(coin, timeframe, limit=250):
    ensure_exchanges()
    for eid in ("binance", "xt", "lbank"):
        try:
            return exchange_ohlcv(eid, coin, timeframe, limit), eid.upper()
        except Exception:
            continue
    raise RuntimeError(f"{timeframe} DATA UNAVAILABLE: {coin}")


# ============================================================
# DYNAMIC MARKET UNIVERSE
# ============================================================

def gecko_top(limit=40):
    headers = {}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    url = "https://api.coingecko.com/api/v3/coins/markets?" + urllib.parse.urlencode({
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": str(limit),
        "page": "1",
        "sparkline": "false",
    })
    rows = safe_http_get(url, headers=headers, default=[])
    result = []
    for x in rows or []:
        s = (x.get("symbol") or "").upper()
        if s and not is_stable(s):
            result.append({
                "id": (x.get("id") or "").strip(),
                "symbol": s,
                "name": x.get("name"),
                "rank": x.get("market_cap_rank"),
                "market_cap": f(x.get("market_cap")),
            })
    return result


def binance_top(limit=40):
    ensure_exchanges()
    try:
        ex = EX.get("binance")
        if ex is None:
            return []
        rows = ex.fetch_tickers()
    except Exception:
        return []
    result = []
    for sym, x in rows.items():
        if not sym.endswith("/USDT") or ":USDT" in sym:
            continue
        coin = sym.split("/")[0].upper()
        if is_stable(coin):
            continue
        qv = f(x.get("quoteVolume"))
        if qv is None:
            continue
        result.append({"symbol": coin, "quote_volume": qv})
    result.sort(key=lambda x: x["quote_volume"], reverse=True)
    return result[:limit]


def build_universe():
    """
    Build the radar in a deterministic reporting order.

    Reporting contract:
      1) ATLAS_PRIORITY_TOP10, in the exact configured order.
      2) Dynamic Top-30 market-cap assets from CoinGecko, excluding priority assets.
      3) ATLAS_STATIC assets, excluding everything already present.

    The order is intentionally independent of confidence, liquidity or price.
    Those factors may rank setups inside the final conclusion, but they must
    never reorder the asset-report sequence.
    """
    cg = gecko_top(60)

    cg_symbols = []
    for x in cg:
        s = (x.get("symbol") or "").upper()
        if s and not is_stable(s) and s not in cg_symbols:
            cg_symbols.append(s)

    # Fixed user-priority universe. It is called Top-10 Priority rather than
    # "current market-cap Top 10" because MATIC/HYPE may not currently rank
    # inside CoinGecko's literal top ten.
    top10 = list(ATLAS_PRIORITY_TOP10)

    # Dynamic market-cap list: highest-ranked CoinGecko assets not already in
    # the fixed priority list. Fill from Binance only if CoinGecko is short.
    dynamic30 = [s for s in cg_symbols if s not in top10][:30]

    if len(dynamic30) < 30:
        for x in binance_top(80):
            s = (x.get("symbol") or "").upper()
            if s and not is_stable(s) and s not in top10 and s not in dynamic30:
                dynamic30.append(s)
            if len(dynamic30) >= 30:
                break

    dynamic30 = dynamic30[:30]

    # Static radar comes last and cannot displace priority/dynamic assets.
    static = [
        x for x in ATLAS_STATIC
        if not is_stable(x) and x not in top10 and x not in dynamic30
    ]

    universe = list(dict.fromkeys(top10 + dynamic30 + static))
    universe = [x for x in universe if not is_stable(x)]

    for symbol in universe:
        source = (
            "TOP10_PRIORITY" if symbol in top10
            else "DYNAMIC30" if symbol in dynamic30
            else "ATLAS_STATIC"
        )
        STORE.insert(
            "atlas_assets",
            {
                "symbol": symbol,
                "rank": next(
                    (x["rank"] for x in cg if x["symbol"] == symbol), None
                ),
                "source": source,
                "is_stablecoin": False,
                "active": True,
                "last_seen_at": now_utc().isoformat(),
            },
        )

    return universe, top10, dynamic30


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
    out = [None] * (n - 1) + [e]
    for x in values[n:]:
        e = (x - e) * a + e
        out.append(e)
    return out

def macd(values):
    """Efficient MACD: one EMA12/EMA26 pass, then one signal EMA9 pass."""
    if len(values) < 40:
        return None, None, None
    e12 = ema_series(values, 12)
    e26 = ema_series(values, 26)
    line = [e12[i] - e26[i] for i in range(len(values)) if e12[i] is not None and e26[i] is not None]
    if len(line) < 9:
        return None, None, None
    signal_series = ema_series(line, 9)
    signal = signal_series[-1]
    if signal is None:
        return None, None, None
    hist = line[-1] - signal
    return line[-1], signal, hist


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
    """Legacy fallback S/R from a candle set.

    The primary ATLAS S/R engine is ``daily_key_levels`` below. This
    function remains as a safe fallback when Daily data is unavailable.
    """
    lows = [f(x[3]) for x in rows[-30:] if f(x[3]) is not None]
    highs = [f(x[2]) for x in rows[-30:] if f(x[2]) is not None]
    if not lows or not highs:
        return None, None
    return min(lows), max(highs)


def _cluster_levels(values, tolerance=0.012):
    """Cluster nearby prices so repeated touches form one S/R zone."""
    vals = sorted(v for v in values if v is not None and v > 0)
    if not vals:
        return []
    clusters = [[vals[0]]]
    for v in vals[1:]:
        center = sum(clusters[-1]) / len(clusters[-1])
        if abs(v - center) / center <= tolerance:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [
        {
            "level": sum(c) / len(c),
            "touches": len(c),
            "spread": (max(c) - min(c)) / max(sum(c) / len(c), 1e-12) * 100,
        }
        for c in clusters
    ]


def daily_key_levels(daily_rows, current_price=None):
    """Reliable Daily-only support/resistance; never silently falls back to H4."""
    valid = []
    for r in (daily_rows or []):
        if not isinstance(r, (list, tuple)) or len(r) < 6:
            continue
        vals = [f(r[i]) for i in (0,1,2,3,4,5)]
        if all(v is not None for v in vals[:5]):
            valid.append([int(vals[0]), vals[1], vals[2], vals[3], vals[4], vals[5] or 0.0])
    if len(valid) < 60:
        return {"support":None,"resistance":None,"support_score":0,"resistance_score":0,
                "support_touches":0,"resistance_touches":0,"confidence":"LOW","method":"INSUFFICIENT_DAILY_DATA"}

    rows = valid[-180:]
    price = f(current_price) or f(rows[-1][4])
    if price is None or price <= 0:
        return {"support":None,"resistance":None,"support_score":0,"resistance_score":0,
                "support_touches":0,"resistance_touches":0,"confidence":"LOW","method":"INVALID_DAILY_PRICE"}

    highs=[r[2] for r in rows]; lows=[r[3] for r in rows]; vols=[r[5] for r in rows]
    atr_d=atr(rows,14)
    if atr_d is None or atr_d <= 0:
        return {"support":None,"resistance":None,"support_score":0,"resistance_score":0,
                "support_touches":0,"resistance_touches":0,"confidence":"LOW","method":"INVALID_DAILY_ATR"}

    swing_highs=[]; swing_lows=[]
    for i in range(2,len(rows)-2):
        h,l=highs[i],lows[i]
        if h is not None and h >= max(highs[i-2:i]) and h >= max(highs[i+1:i+3]): swing_highs.append(h)
        if l is not None and l <= min(lows[i-2:i]) and l <= min(lows[i+1:i+3]): swing_lows.append(l)
    for n in (20,60,120):
        chunk=rows[-n:]
        swing_highs.append(max(r[2] for r in chunk))
        swing_lows.append(min(r[3] for r in chunk))

    sup_clusters=_cluster_levels([x for x in swing_lows if x < price],0.015)
    res_clusters=_cluster_levels([x for x in swing_highs if x > price],0.015)
    valid_vols=[v for v in vols[-21:-1] if v is not None and v>0]
    avg_vol=safe_mean(valid_vols) if len(valid_vols)>=10 else None

    def score_zone(zone,side):
        level=zone["level"]; touches=zone["touches"]; score=35+min(25,(touches-1)*8)
        distances=[]; rejection=0; vol_hits=0
        for i,r in enumerate(rows):
            o,h,l,c,v=r[1],r[2],r[3],r[4],r[5]
            if None in (h,l,c): continue
            if h >= level >= l: distances.append(len(rows)-1-i)
            body=max(abs(c-o),1e-12) if o is not None else 1e-12
            rng=max(h-l,1e-12)
            if side=="support" and l<=level*1.006 and c>level and (c-l)/rng>0.55: rejection+=1
            if side=="resistance" and h>=level*0.994 and c<level and (h-c)/rng>0.55: rejection+=1
            if avg_vol and v is not None and v>=avg_vol*1.2:
                if side=="support" and l<=level*1.006 and c>level: vol_hits+=1
                if side=="resistance" and h>=level*0.994 and c<level: vol_hits+=1
        if distances:
            score += max(0,15-min(distances)*0.35)
        dist_pct=abs(level-price)/price*100; atrp=atr_d/price*100
        if dist_pct<=max(atrp*4,8): score+=10
        elif dist_pct<=max(atrp*8,15): score+=5
        score += min(15,rejection*3)+min(10,vol_hits*2)
        return int(clamp(round(score),0,100))

    def best(clusters,side):
        ranked=[(score_zone(z,side),z) for z in clusters]
        if not ranked:return None
        ranked.sort(key=lambda q:(q[0],-abs(q[1]["level"]-price)/price),reverse=True)
        score,z=ranked[0]
        return {"level":z["level"],"score":score,"touches":z["touches"]}

    sup=best(sup_clusters,"support"); res=best(res_clusters,"resistance")
    if sup and sup["score"]<55:sup=None
    if res and res["score"]<55:res=None
    min_score=min(sup["score"] if sup else 0,res["score"] if res else 0)
    confidence="HIGH" if min_score>=80 else "MEDIUM" if min_score>=65 else "LOW"
    return {"support":sup["level"] if sup else None,"resistance":res["level"] if res else None,
            "support_score":sup["score"] if sup else 0,"resistance_score":res["score"] if res else 0,
            "support_touches":sup["touches"] if sup else 0,"resistance_touches":res["touches"] if res else 0,
            "confidence":confidence,"method":"DAILY_SWING_CLUSTER_REJECTION_VOLUME"}


# ============================================================
# CANDLE PATTERNS
# ============================================================

def candle_pattern(rows):
    if len(rows) < 3:
        return "NONE", "NONE"

    a, b = rows[-2], rows[-1]
    ao, ac = f(a[1]), f(a[4])
    bo, bh, bl, bc = f(b[1]), f(b[2]), f(b[3]), f(b[4])

    ar = abs(ac - ao)
    br = abs(bc - bo)
    upper = bh - max(bo, bc)
    lower = min(bo, bc) - bl
    total = max(bh - bl, 1e-12)

    # Doji
    if br / total <= 0.10:
        return "DOJI", "NEUTRAL"

    # Engulfing
    if bc > bo and ac < ao and bo <= ac and bc >= ao and br > ar:
        return "BULLISH ENGULFING", "BULLISH"
    if bc < bo and ac > ao and bo >= ac and bc <= ao and br > ar:
        return "BEARISH ENGULFING", "BEARISH"

    # Hammer / Shooting Star
    if lower >= 2.2 * max(br, total * 0.02) and upper <= br:
        return "HAMMER", "BULLISH"
    if upper >= 2.2 * max(br, total * 0.02) and lower <= br:
        return "SHOOTING STAR", "BEARISH"

    # Pin bars
    if lower / total >= 0.60 and bc >= bo:
        return "BULLISH PIN BAR", "BULLISH"
    if upper / total >= 0.60 and bc <= bo:
        return "BEARISH PIN BAR", "BEARISH"

    return "NONE", "NEUTRAL"


# ============================================================
# DIVERGENCE
# ============================================================

def local_extrema(values, window=3):
    vals=[safe_float(v) for v in (values or [])]
    lows,highs=[],[]
    for i in range(window,len(vals)-window):
        if vals[i] is None: continue
        chunk=[v for v in vals[i-window:i+window+1] if v is not None]
        if len(chunk)<window+1: continue
        if vals[i]==min(chunk): lows.append(i)
        if vals[i]==max(chunk): highs.append(i)
    return lows,highs


def divergence_3_level(values, indicator):
    """Strong 3-level divergence proxy."""
    if len(values) != len(indicator) or len(values) < 40:
        return None
    lows, highs = local_extrema(values, 2)
    if len(lows) >= 3:
        idx = lows[-3:]
        p = [values[i] for i in idx]
        r = [indicator[i] for i in idx]
        if p[0] > p[1] > p[2] and r[0] < r[1] < r[2]:
            return "BULLISH_3_LEVEL"
    if len(highs) >= 3:
        idx = highs[-3:]
        p = [values[i] for i in idx]
        r = [indicator[i] for i in idx]
        if p[0] < p[1] < p[2] and r[0] > r[1] > r[2]:
            return "BEARISH_3_LEVEL"
    return None


# ============================================================
# MULTI-TIMEFRAME ANALYSIS
# ============================================================

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


def tf_snapshot(coin):
    out = {}
    for tf in TIMEFRAMES:
        try:
            limit = 250 if tf in ("1h", "4h", "1d") else 120 if tf == "1w" else 60
            rows, engine = best_ohlcv(coin, tf, limit)
            c = closes(rows)
            if len(c) < 20:
                raise RuntimeError(f"{tf}: insufficient closed candles")
            r = rsi(c)
            ml, ms, hist = macd(c)
            s20, s50 = sma(c, 20), sma(c, 50)
            out[tf] = {
                "rows": rows,
                "engine": engine,
                "trend": trend_from_rows(rows),
                "rsi": r,
                "macd": "BULLISH" if ml is not None and ms is not None and ml > ms
                else "BEARISH" if ml is not None and ms is not None else "UNKNOWN",
                "sma20": s20,
                "sma50": s50,
                "price": c[-1],
                "event": candle_event(coin, tf, rows),
            }
        except Exception as e:
            out[tf] = {"error": str(e), "trend": "UNKNOWN", "event": {"status":"ERROR","closed_ts":None,"timeframe":tf}}
    # 30m is kept separate because it is used as the execution/momentum confirmation.
    try:
        rows, engine = best_ohlcv(coin, "30m", EVENT_LOOKBACK_LIMITS["30m"])
        out["30m"] = {"rows": rows, "engine": engine, "event": candle_event(coin, "30m", rows)}
    except Exception as e:
        out["30m"] = {"error": str(e), "event": {"status":"ERROR","closed_ts":None,"timeframe":"30m"}}
    return out


# ============================================================
# 30-MINUTE MOMENTUM
# ============================================================

def momentum_30m(coin):
    try:
        rows,_=best_ohlcv(coin,"30m",60)
        rows=strip_incomplete(rows,"30m")
        c=[x for x in closes(rows) if x is not None]
        if len(c)<6:return "UNKNOWN",False
        base = c[-4]
        if base is None or base == 0:
            return "UNKNOWN", False
        short=(c[-1]/base-1)*100
        if short>0.20:return "BULLISH",False
        if short<-0.20:return "BEARISH",False
        return "NEUTRAL",False
    except Exception as e:
        append_changelog("MOMENTUM_30M",None,None,f"{coin}: {e}")
        return "UNKNOWN",False


# ============================================================
# NEWS
# ============================================================

RSS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://www.theblock.co/rss.xml",
]


def news_feed():
    items = []
    for url in RSS:
        root = safe_http_get(url, timeout=10, default=None)
        if root is None or not hasattr(root, "findall"):
            continue
        for x in root.findall(".//item")[:8]:
            title = (x.findtext("title") or "").strip()
            link = (x.findtext("link") or "").strip()
            if title:
                items.append({"title": title, "url": link, "source": url})

    if CRYPTOPANIC_TOKEN:
        url = "https://cryptopanic.com/api/developer/v2/posts/?" + urllib.parse.urlencode({
            "auth_token": CRYPTOPANIC_TOKEN,
            "public": "true",
            "kind": "news",
            "regions": "en",
            "limit": "15",
        })
        d = safe_http_get(url, default={})
        for x in d.get("results", []) if isinstance(d, dict) else []:
            items.append({
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "source": "CryptoPanic",
            })

    if NEWSAPI_KEY:
        url = "https://newsapi.org/v2/everything?" + urllib.parse.urlencode({
            "q": "crypto bitcoin ethereum regulation Federal Reserve",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": NEWSAPI_KEY,
        })
        d = safe_http_get(url, default={})
        for x in d.get("articles", []) if isinstance(d, dict) else []:
            items.append({
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "source": x.get("source", {}).get("name", "NewsAPI"),
            })

    score = 0
    high = False
    for item in items:
        t = item["title"].lower()
        score += sum(1 for w in NEWS_POSITIVE if w in t)
        score -= sum(1 for w in NEWS_NEGATIVE if w in t)
        if any(w in t for w in HIGH_IMPACT_WORDS):
            high = True

    bias = (
        "NEGATIVE" if score <= -3
        else "POSITIVE" if score >= 3
        else "MIXED/LIMITED"
    )
    impact = "HIGH" if high else "NORMAL"

    return {
        "bias": bias,
        "impact": impact,
        "items": items[:12],
    }


# ============================================================
# MACRO: DXY / METALS / OIL
# ============================================================

def yahoo_chart(symbol, interval="1h", range_="5d"):
    url=("https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol)+"?"+urllib.parse.urlencode({"interval":interval,"range":range_,"events":"history"}))
    d=safe_http_get(url,timeout=15,default={})
    if not isinstance(d,dict): return []
    chart=d.get("chart")
    if not isinstance(chart,dict): return []
    results=chart.get("result")
    if not isinstance(results,list) or not results: return []
    result=results[0] or {}
    indicators=result.get("indicators") or {}
    quotes=indicators.get("quote") or []
    if not quotes or not isinstance(quotes[0],dict): return []
    quote=quotes[0]; timestamps=result.get("timestamp") or []
    rows=[]
    for i,ts in enumerate(timestamps):
        try:
            o=f((quote.get("open") or [None]*len(timestamps))[i]); h=f((quote.get("high") or [None]*len(timestamps))[i])
            l=f((quote.get("low") or [None]*len(timestamps))[i]); c=f((quote.get("close") or [None]*len(timestamps))[i])
            v=f((quote.get("volume") or [None]*len(timestamps))[i])
            if None not in (o,h,l,c): rows.append([int(ts)*1000,o,h,l,c,v or 0.0])
        except (IndexError,TypeError,ValueError): continue
    return strip_incomplete(rows,interval)


def macro_snapshot():
    out = {}
    for name, symbols in MACRO_SYMBOLS.items():
        candidates = symbols if isinstance(symbols, (tuple, list)) else (symbols,)
        value = None
        for symbol in candidates:
            try:
                rows = yahoo_chart(symbol, "1h", "5d")
                c = closes(rows)
                if c:
                    value = c[-1]
                    break
            except Exception as e:
                append_changelog("MACRO", None, None, f"{name}/{symbol}: {e}")
        out[name] = value
    return out


# ============================================================
# LIQUIDITY
# ============================================================

def asset_liquidity(coin, ticker_sources):
    volumes = []
    for x in ticker_sources:
        qv = f(x.get("quoteVolume"))
        if qv and qv > 0:
            volumes.append(qv)

    if not volumes:
        return 0.0, "LOW"

    v = sum(volumes)
    # Logarithmic score, deliberately conservative.
    score = clamp((math.log10(v + 1) / 10) * 100, 0, 100)

    label = "HIGH" if score >= 70 else "MEDIUM" if score >= 45 else "LOW"
    return score, label


def market_liquidity_index(results):
    scores = [f(x.get("liquidity_score")) for x in results]
    scores = [x for x in scores if x is not None]
    return round(safe_mean(scores, 0.0), 1)


# ============================================================
# PRICE CONSENSUS
# ============================================================

def price_consensus(coin):
    vals = []
    sources = []
    errors = []

    for eid in EX:
        try:
            x = exchange_ticker(eid, coin)
            if x["price"] is not None:
                vals.append(x["price"])
                sources.append(x)
        except Exception as e:
            errors.append(str(e))

    # CoinGecko validation
    try:
        headers = {}
        if COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
        rows = gecko_top(50)
        x = next(
            (z for z in rows if (z.get("symbol") or "").upper() == coin),
            None,
        )
        # CoinGecko /simple/price requires the canonical CoinGecko ID, not symbol.
        gecko_id = (x or {}).get("id")
        if gecko_id:
            url = "https://api.coingecko.com/api/v3/simple/price?" + urllib.parse.urlencode({
                "ids": gecko_id,
                "vs_currencies": "usd",
            })
            d = safe_http_get(url, headers=headers, default={})
            p = f((d.get(gecko_id) or {}).get("usd")) if isinstance(d, dict) else None
            if p is not None:
                vals.append(p)
                sources.append({"source": "CoinGecko", "price": p, "id": gecko_id})
    except Exception:
        pass

    if not vals:
        raise RuntimeError("NO PRICE DATA")

    med = safe_median(vals)
    spreads = [abs(x - med) / med * 100 for x in vals if med]
    sp = max(spreads) if spreads else 0

    quality = (
        "HIGH" if len(vals) >= 4 and sp <= 1.5
        else "MEDIUM" if len(vals) >= 3 and sp <= 3
        else "LOW"
    )
    if errors:
        append_changelog("PRICE_CONSENSUS", coin, None, "; ".join(errors[:8]), {"error_count": len(errors), "sources_ok": [x.get("source") for x in sources]})
    return med, sources, quality, sp, errors


# ============================================================
# SIGNAL SCORING
# ============================================================

def indicator_alignment(tf4):
    c = tf4["rows"]
    vals = closes(c)
    rr = tf4["rsi"]
    ml, ms, hist = macd(vals)

    bullish = 0
    bearish = 0
    reasons = []
    overbought = False
    oversold = False

    if rr is not None:
        if 52 <= rr <= 68:
            bullish += 1
            reasons.append("RSI صعودی/متعادل")
        elif rr < 45:
            bearish += 1
            oversold = True
            reasons.append("RSI ضعیف / اشباع فروش")
        elif rr > 75:
            overbought = True
            reasons.append("RSI بالای 75؛ اشباع خرید — بدون امتیاز صعودی")

    if ml is not None and ms is not None:
        if ml > ms:
            bullish += 1
            reasons.append("MACD صعودی")
        elif ml < ms:
            bearish += 1
            reasons.append("MACD نزولی")

    if tf4["sma20"] and tf4["sma50"]:
        if vals[-1] > tf4["sma20"] > tf4["sma50"]:
            bullish += 1
            reasons.append("SMA20/50 صعودی")
        elif vals[-1] < tf4["sma20"] < tf4["sma50"]:
            bearish += 1
            reasons.append("SMA20/50 نزولی")

    direction = (
        "BULLISH" if bullish >= 2 and bullish > bearish
        else "BEARISH" if bearish >= 2 and bearish > bullish
        else "MIXED"
    )
    return direction, bullish, bearish, reasons, overbought, oversold


def rsi_series(values, n=14):
    """Wilder RSI series using the same method as rsi(), without O(n^2) slicing."""
    if len(values) <= n:
        return []
    gains = []
    losses = []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    out = [None] * n
    out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    for i in range(n, len(gains)):
        ag = ((n - 1) * ag + gains[i]) / n
        al = ((n - 1) * al + losses[i]) / n
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out

def strong_divergence(rows):
    vals = closes(rows)
    rsis = rsi_series(vals, 14)
    if not rsis or len(rsis) != len(vals):
        return None
    p = [v for v, r in zip(vals, rsis) if r is not None]
    r = [r for r in rsis if r is not None]
    if len(r) < 40:
        return None
    return divergence_3_level(p, r)


def weekly_pivot(rows):
    """Return a simple pivot from the latest completed 7-day window of 4H candles."""
    if not rows or len(rows) < 42:
        return None
    recent = rows[-42:]
    highs = [f(x[2]) for x in recent if len(x) >= 5 and f(x[2]) is not None]
    lows = [f(x[3]) for x in recent if len(x) >= 5 and f(x[3]) is not None]
    closes_ = [f(x[4]) for x in recent if len(x) >= 5 and f(x[4]) is not None]
    if not highs or not lows or not closes_:
        return None
    return (max(highs) + min(lows) + closes_[-1]) / 3.0


def calculate_levels(rows, direction, daily_levels=None):
    price = f(rows[-1][4]) if rows else None
    sup = daily_levels.get("support") if daily_levels else None
    res = daily_levels.get("resistance") if daily_levels else None
    if sup is None or res is None:
        return None
    pivot = weekly_pivot(rows)
    a = atr(rows)

    if not price or not a:
        return None

    if direction == "LONG":
        # Correct geometry: resistance must be above price when it is used
        # as a breakout reference. If historical resistance is below price,
        # it is treated as already broken, and the next target uses ATR.
        resistance = max(res, price)
        entry = price if price >= res else res * 1.002
        sl = min(sup * 0.995, entry - 1.5 * a)
        risk = max(entry - sl, entry * 0.005)
        tp1 = max(entry + 2 * risk, resistance + 1.0 * a)
        tp2 = max(entry + 3 * risk, tp1 + risk)
    else:
        support = min(sup, price)
        entry = price if price <= sup else sup * 0.998
        sl = max(res * 1.005, entry + 1.5 * a)
        risk = max(sl - entry, entry * 0.005)
        tp1 = min(entry - 2 * risk, support - 1.0 * a)
        tp2 = min(entry - 3 * risk, tp1 - risk)

    # Sanity checks prevent the previous v7 price/resistance contradiction.
    if direction == "LONG":
        if not (sl < entry < tp1 <= tp2):
            return None
    else:
        if not (sl > entry > tp1 >= tp2):
            return None

    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "atr": a,
        "support": sup,
        "resistance": res,
        "pivot": pivot,
    }


def suggested_leverage(atr_percent):
    if not atr_percent or atr_percent <= 0:
        return 1.0
    lev = (1 / (atr_percent / 100)) * 0.5
    return round(clamp(lev, 1, MAX_LEVERAGE), 1)


def candle_trigger_state(rows, direction, support=None, resistance=None):
    """Classify the latest CLOSED 4H candle; no prediction of an unfinished candle."""
    if not rows or len(rows) < 3:
        return {"state":"UNKNOWN","close_location":None,"range_pct":None,"near_extreme":False}
    r=rows[-1]
    o,h,l,c=map(f,r[1:5])
    if None in (h,l,c) or h <= l or c <= 0:
        return {"state":"UNKNOWN","close_location":None,"range_pct":None,"near_extreme":False}
    loc=(c-l)/(h-l)
    range_pct=(h-l)/c*100
    prev=rows[-2]
    ph,pl,pc=f(prev[2]),f(prev[3]),f(prev[4])
    state="NEUTRAL_CLOSE"
    if direction=="LONG":
        if resistance is not None and c>resistance and pc is not None and pc<=resistance:
            state="BREAKOUT_CLOSED"
        elif loc>=0.80:
            state="BULLISH_CLOSE"
        elif l < (support or -math.inf) and c > (support or math.inf):
            state="SUPPORT_RECLAIM"
    elif direction=="SHORT":
        if support is not None and c<support and pc is not None and pc>=support:
            state="BREAKDOWN_CLOSED"
        elif loc<=0.20:
            state="BEARISH_CLOSE"
        elif h > (resistance or math.inf) and c < (resistance or -math.inf):
            state="RESISTANCE_REJECT"
    return {"state":state,"close_location":round(loc,3),"range_pct":round(range_pct,3),"near_extreme":loc>=0.85 or loc<=0.15}


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

    # Daily S/R is authoritative for the report. H4 remains the execution
    # timeframe, but Daily structure determines the key levels.
    daily_levels = daily_key_levels(tfd.get("rows", []), price)
    h4_levels = h4_fallback_levels(tf4.get("rows", []), price)
    sr_fallback = False
    effective_levels = daily_levels
    if (not effective_levels or effective_levels.get("confidence") == "LOW") and h4_levels and h4_levels.get("confidence") != "LOW":
        effective_levels = h4_levels
        sr_fallback = True

    mom30, _ = momentum_30m(coin)

    # Direction must be resolved BEFORE any trigger calculation uses it.
    # v8.6.1 accidentally evaluated candle_trigger_state(..., direction, ...)
    # before direction was assigned, causing every asset analysis to raise
    # UnboundLocalError and leaving the report with Total scanned: 0.

    # --------------------------------------------------------
    # v10.0 CONFIDENCE — component-level, not binary.
    # The six learned weights now produce different scores for different
    # quality setups instead of clustering many assets at exactly 65%.
    # --------------------------------------------------------
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

    # RSI is graded. Extreme overbought/oversold never earns full confirmation.
    rsi_points = 0.0
    # Direction is selected immediately below; use the raw indicator direction
    # here so the score remains deterministic before gate evaluation.
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

    # --------------------------------------------------------
    # Direction selection
    # --------------------------------------------------------
    direction = "NONE"
    # H4 + D1 remain the primary trend filter. H1 is confirmation, not a
    # mandatory hard gate; this prevents the model from going silent merely
    # because a lower timeframe is temporarily counter-trend.
    if ind_dir == "BULLISH" and h4 == "BULLISH" and d1 == "BULLISH":
        direction = "LONG"
    elif ind_dir == "BEARISH" and h4 == "BEARISH" and d1 == "BEARISH":
        direction = "SHORT"

    # Strong three-level divergence is the only exception to
    # the normal higher-timeframe rule.
    if divergence == "BULLISH_3_LEVEL" and h4 != "BULLISH":
        direction = "LONG"
        confidence = max(confidence, 65)
    elif divergence == "BEARISH_3_LEVEL" and h4 != "BEARISH":
        direction = "SHORT"
        confidence = max(confidence, 65)

    # If a 3-level divergence overrides the raw indicator direction, recompute
    # directional RSI/MACD contributions so confidence matches the final signal.
    if direction in ("LONG", "SHORT"):
        rsi_points = 0.0
        macd_points = 0.0
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
        if ml is not None and ms is not None:
            if direction == "LONG" and ml > ms: macd_points = weights["macd"]
            elif direction == "SHORT" and ml < ms: macd_points = weights["macd"]
        old_ind = score_components["indicators"]
        confidence += (rsi_points + macd_points) - old_ind
        score_components["rsi"] = round(rsi_points, 2)
        score_components["macd"] = round(macd_points, 2)
        score_components["indicators"] = round(rsi_points + macd_points, 2)

    # Weekly/monthly are regime filters, not entry triggers. A direct
    # monthly contradiction blocks the setup; a weekly contradiction
    # requires an unusually strong confidence score.
    regime_conflict = False

    # Candle trigger is calculated only after direction has been resolved.
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

    # --------------------------------------------------------
    # Hard gates
    # --------------------------------------------------------
    gate = "PASS"
    warning = None
    gate_blocks = []

    # Evaluate every mandatory blocker independently. This avoids the old
    # elif-chain problem where only the first failure was reported.
    if regime_conflict:
        gate_blocks.append("Monthly regime contradicts signal")
    if quality == "LOW" or (spread_pct is not None and spread_pct > 3):
        gate_blocks.append("Data quality/conflict")
    if vol_ratio is None or vol_ratio <= MIN_VOLUME_RATIO:
        gate_blocks.append("Volume confirmation missing")
    if confidence < MIN_CONFIDENCE:
        gate_blocks.append("Confidence below threshold")
    if direction == "NONE":
        gate_blocks.append("Higher-timeframe alignment missing")
    if ((direction == "LONG" and w1 == "BEARISH") or (direction == "SHORT" and w1 == "BULLISH")) and confidence < max(MIN_CONFIDENCE + 15, 75):
        gate_blocks.append("Weekly regime conflict; stronger confirmation required")

    if market_news["impact"] == "HIGH":
        warning = "نوسان بالا"
        if ((market_news["bias"] == "NEGATIVE" and direction == "LONG") or
            (market_news["bias"] == "POSITIVE" and direction == "SHORT")):
            gate_blocks.append("High-impact news contradicts signal")

    if direction == "LONG" and mom30 == "BEARISH":
        warning = "شتاب مخالف"
        gate_blocks.append("30m momentum strongly opposes long")
    if direction == "SHORT" and mom30 == "BULLISH":
        warning = "شتاب مخالف"
        gate_blocks.append("30m momentum strongly opposes short")

    if gate_blocks:
        gate = "BLOCK"
        gate_reason = " | ".join(gate_blocks)
    else:
        gate_reason = "All mandatory gates passed"

    levels = None
    leverage = 1.0
    action = "NO TRADE"

    if gate == "PASS":
        if not effective_levels or effective_levels.get("confidence") == "LOW":
            gate = "BLOCK"
            gate_reason = "Reliable Daily/H4 S/R not confirmed"
        elif sr_fallback and confidence < max(MIN_CONFIDENCE + 10, H4_FALLBACK_MIN_SCORE):
            gate = "BLOCK"
            gate_reason = "H4 S/R fallback requires elevated confidence"
        else:
            levels = calculate_levels(tf4["rows"], direction, effective_levels)
            if levels is None:
                gate = "BLOCK"
                gate_reason = "Invalid price geometry"
            else:
                leverage = suggested_leverage(atrp)
                four_h_event = snapshots.get("4h", {}).get("event", {})
                trigger_ok_long = trigger["state"] in ("BREAKOUT_CLOSED", "SUPPORT_RECLAIM", "BULLISH_CLOSE") and direction == "LONG"
                trigger_ok_short = trigger["state"] in ("BREAKDOWN_CLOSED", "RESISTANCE_REJECT", "BEARISH_CLOSE") and direction == "SHORT"
                # The latest fully CLOSED 4H candle is authoritative.
                # We do not require the GitHub run itself to occur inside the
                # small NEW_CLOSED event window; this keeps the three fixed
                # daily report times from going silent when a run is delayed.
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

    return {
        "coin": coin,
        "price": price,
        "change": change_24h,
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
        "price_errors": errors[:8],
        "engine": tf4.get("engine"),
        "snapshots": snapshots,
    }


# ============================================================
# v9 DECISION ENGINE — REGIME / BREADTH / RISK / MEMORY
# ============================================================

def _trend_bias_from_rows(rows):
    try:
        c = closes(rows)
        if len(c) < 60:
            return "UNKNOWN", None, None, None
        rr = rsi(c)
        ml, ms, _ = macd(c)
        s20, s50 = sma(c, 20), sma(c, 50)
        if None in (rr, ml, ms, s20, s50):
            return "UNKNOWN", rr, ml, ms
        bull = c[-1] > s20 > s50 and ml > ms
        bear = c[-1] < s20 < s50 and ml < ms
        if bull and rr >= 52:
            return "BULLISH", rr, ml, ms
        if bear and rr <= 48:
            return "BEARISH", rr, ml, ms
        return "MIXED", rr, ml, ms
    except Exception:
        return "UNKNOWN", None, None, None


def btc_market_regime(force=False):
    """Classify BTC as RISK_ON / NEUTRAL / RISK_OFF using closed 4H/1D data.

    This is deliberately a regime filter, not a trading trigger. It is cached
    in-process so a report does not repeatedly hammer the exchange.
    """
    global _BTC_REGIME_CACHE
    now = time.time()
    if not force and _BTC_REGIME_CACHE:
        if now - _BTC_REGIME_CACHE.get("ts", 0) < BTC_REGIME_CACHE_MINUTES * 60:
            return dict(_BTC_REGIME_CACHE)
    out = {
        "regime": "UNKNOWN", "h4": "UNKNOWN", "d1": "UNKNOWN",
        "rsi4": None, "rsi1": None, "volume_ratio": None,
        "reason": "BTC data unavailable", "ts": now,
    }
    try:
        r4, _ = best_ohlcv("BTC", "4h", 180)
        r1, _ = best_ohlcv("BTC", "1d", 180)
        h4, rsi4, _, _ = _trend_bias_from_rows(r4)
        d1, rsi1, _, _ = _trend_bias_from_rows(r1)
        _, vr = volume_state(r4)
        out.update({"h4": h4, "d1": d1, "rsi4": rsi4, "rsi1": rsi1, "volume_ratio": vr})
        if h4 == "BULLISH" and d1 == "BULLISH":
            out["regime"] = "RISK_ON"
            out["reason"] = "BTC 4H + 1D bullish"
        elif h4 == "BEARISH" and d1 == "BEARISH":
            out["regime"] = "RISK_OFF"
            out["reason"] = "BTC 4H + 1D bearish"
        else:
            out["regime"] = "NEUTRAL"
            out["reason"] = "BTC higher timeframes mixed"
    except Exception as e:
        append_changelog("BTC_REGIME", None, None, str(e), {"traceback": traceback.format_exc()})
    _BTC_REGIME_CACHE = dict(out)
    return out


_BTC_REGIME_CACHE = {}


def market_breadth(results):
    # Breadth sample = only assets with a genuine H4/D1 directional agreement.
    # MIXED is excluded from both numerator and denominator.
    aligned = [
        r for r in results
        if r.get("h4_trend") == r.get("d1_trend")
        and r.get("h4_trend") in ("BULLISH", "BEARISH")
    ]
    if not aligned:
        return {"score": 50.0, "bullish": 0, "bearish": 0, "samples": 0, "state": "UNKNOWN"}
    bullish = sum(1 for r in aligned if r["h4_trend"] == "BULLISH")
    bearish = sum(1 for r in aligned if r["h4_trend"] == "BEARISH")
    score = bullish / max(bullish + bearish, 1) * 100
    if len(aligned) < MARKET_BREADTH_MIN_SAMPLES:
        state = "LOW_SAMPLE"
    elif score >= 65:
        state = "BULLISH"
    elif score <= 35:
        state = "BEARISH"
    else:
        state = "MIXED"
    return {"score": round(score, 1), "bullish": bullish, "bearish": bearish, "samples": len(aligned), "state": state}


def decision_rr(result):
    entry, sl, tp2 = f(result.get("entry")), f(result.get("sl")), f(result.get("tp2"))
    if None in (entry, sl, tp2) or entry <= 0:
        return None
    risk = abs(entry - sl)
    reward = abs(tp2 - entry)
    if risk <= 0:
        return None
    return reward / risk


def _near_opposing_level(result):
    entry = f(result.get("entry"))
    if entry is None or entry <= 0:
        return False
    direction = result.get("direction")
    if direction == "LONG":
        res = f(result.get("resistance"))
        if res is not None and res > entry:
            return (res - entry) / entry < 0.015
    if direction == "SHORT":
        sup = f(result.get("support"))
        if sup is not None and sup < entry:
            return (entry - sup) / entry < 0.015
    return False


def _load_signal_memory(coin):
    init_sqlite()
    with sqlite_conn() as c:
        row = c.execute("select * from signal_memory where coin=?", (coin,)).fetchone()
    return dict(row) if row else None


def _save_signal_memory(result, state):
    init_sqlite()
    with sqlite_conn() as c:
        c.execute("""insert into signal_memory
            (coin,direction,action,confidence,signal_candle_ts,entry,sl,tp1,tp2,last_seen_at,decision_state)
            values(?,?,?,?,?,?,?,?,?,?,?)
            on conflict(coin) do update set
            direction=excluded.direction, action=excluded.action,
            confidence=excluded.confidence, signal_candle_ts=excluded.signal_candle_ts,
            entry=excluded.entry, sl=excluded.sl, tp1=excluded.tp1, tp2=excluded.tp2,
            last_seen_at=excluded.last_seen_at, decision_state=excluded.decision_state""",
            (result["coin"], result.get("direction"), result.get("action"), result.get("confidence"),
             result.get("signal_candle_ts"), result.get("entry"), result.get("sl"), result.get("tp1"),
             result.get("tp2"), now_utc().isoformat(), state))


def setup_quality_score(r):
    """Human-like entry quality score; informational but also used by the execution gate."""
    score = 50.0
    trigger = (r.get("candle_trigger") or {}).get("state")
    if trigger in ("BREAKOUT_CLOSED", "SUPPORT_RECLAIM", "BREAKDOWN_CLOSED", "RESISTANCE_REJECT"):
        score += 15
    elif trigger == "BULLISH_CLOSE" or trigger == "BEARISH_CLOSE":
        score += 8
    if r.get("h4_trend") == r.get("d1_trend") and r.get("h4_trend") in ("BULLISH", "BEARISH"):
        score += 10
    if r.get("overbought") or r.get("oversold"):
        score -= 15
    vr = f(r.get("volume_ratio"))
    if vr is not None:
        score += 10 if vr >= 1.35 else 5 if vr >= 1.0 else -5 if vr < 0.8 else 0
    sr = r.get("sr_confidence")
    score += 10 if sr == "HIGH" else 5 if sr == "MEDIUM" else 0
    direction = r.get("direction")
    w1 = r.get("w1_trend")
    if direction == "LONG" and w1 == "BEARISH":
        score -= 10
    elif direction == "SHORT" and w1 == "BULLISH":
        score -= 10
    return int(clamp(round(score), 0, 100))


def risk_quality_score(r, rr=None):
    """Risk quality combines reward/risk, liquidity, data quality and structure."""
    score = 40.0
    rr = f(rr)
    if rr is not None:
        score += 25 if rr >= 3 else 20 if rr >= 2.5 else 15 if rr >= 2 else 0 if rr >= 1.5 else -20
    liq = f(r.get("liquidity_score")) or 0
    score += 15 if liq >= 70 else 8 if liq >= 45 else -8
    q = r.get("quality")
    score += 15 if q == "HIGH" else 8 if q == "MEDIUM" else -10
    spread = f(r.get("spread"))
    score += 10 if spread is not None and spread <= 1 else 5 if spread is not None and spread <= 3 else -20
    if _near_opposing_level(r):
        score -= 20
    return int(clamp(round(score), 0, 100))


def apply_decision_engine(results, btc_regime, breadth):
    """Turn raw confirmations into human-like decisions.

    A setup must be technically aligned AND tradable. Poor R/R, adverse BTC
    regime, nearby opposing structure, or an unchanged signal are downgraded
    to WATCH rather than being presented as fresh executable trades.
    """
    for r in results:
        raw = r.get("action", "NO TRADE")
        rr = decision_rr(r)
        r["rr"] = round(rr, 2) if rr is not None else None
        r["setup_score"] = int(r.get("confidence", 0))
        r["entry_quality"] = setup_quality_score(r)
        r["risk_quality"] = risk_quality_score(r, rr)
        state = "NO TRADE"
        reasons = []
        direction = r.get("direction")
        regime = btc_regime.get("regime", "UNKNOWN")

        if raw in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            state = raw

            if r.get("entry_quality", 0) < 70:
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append(f"Entry quality {r.get('entry_quality', 0)}/100 < 70")
            if r.get("risk_quality", 0) < 70:
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append(f"Risk quality {r.get('risk_quality', 0)}/100 < 70")

            # Human-like risk control: do not chase extreme momentum.
            # A genuine closed-candle breakout/reclaim may still execute,
            # but an extreme RSI without structural confirmation becomes WATCH.
            trigger_state = (r.get("candle_trigger") or {}).get("state")
            if direction == "LONG" and r.get("overbought"):
                if not (trigger_state in ("BREAKOUT_CLOSED", "SUPPORT_RECLAIM") and r.get("confidence", 0) >= 75 and (r.get("volume_ratio") or 0) >= 1.35):
                    state = "BULLISH WATCH"
                    reasons.append("RSI اشباع خرید؛ ورود تعقیبی ممنوع، منتظر Pullback/Retest")
            elif direction == "SHORT" and r.get("oversold"):
                if not (trigger_state in ("BREAKDOWN_CLOSED", "RESISTANCE_REJECT") and r.get("confidence", 0) >= 75 and (r.get("volume_ratio") or 0) >= 1.35):
                    state = "BEARISH WATCH"
                    reasons.append("RSI اشباع فروش؛ ورود تعقیبی ممنوع، منتظر Pullback/Retest")

            if rr is None or rr < MIN_EXECUTABLE_RR:
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append(f"R/R زیر {MIN_EXECUTABLE_RR:.1f}")
            if _near_opposing_level(r):
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append("مقاومت/حمایت مقابل بسیار نزدیک")
            if regime == "RISK_OFF" and direction == "LONG":
                state = "BULLISH WATCH"
                reasons.append("BTC regime ریسک‌گریز")
            elif regime == "RISK_ON" and direction == "SHORT":
                state = "BEARISH WATCH"
                reasons.append("BTC regime ریسک‌پذیر")
            if breadth["state"] == "BEARISH" and direction == "LONG":
                state = "BULLISH WATCH"
                reasons.append("Market breadth مخالف LONG")
            elif breadth["state"] == "BULLISH" and direction == "SHORT":
                state = "BEARISH WATCH"
                reasons.append("Market breadth مخالف SHORT")

            mem = _load_signal_memory(r["coin"])
            same_candle = bool(mem and mem.get("signal_candle_ts") == r.get("signal_candle_ts") and mem.get("direction") == direction)
            recent_same = False
            if mem and mem.get("last_seen_at"):
                try:
                    age = (now_utc() - datetime.fromisoformat(mem["last_seen_at"].replace("Z", "+00:00"))).total_seconds() / 3600
                    recent_same = age < SIGNAL_MEMORY_HOURS and mem.get("direction") == direction
                except Exception:
                    pass
            if same_candle or recent_same:
                r["repeat_signal"] = True
                if state == raw:
                    state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append("سیگنال تکراری؛ تغییر معنادار مشاهده نشد")
            else:
                r["repeat_signal"] = False

        elif raw in ("BULLISH WATCH", "BEARISH WATCH"):
            state = raw
        else:
            # Do not discard useful directional information merely because a
            # hard gate blocked execution. A WATCH is informational, never an
            # entry order, and requires the independent watch threshold.
            if direction in ("LONG", "SHORT") and r.get("confidence", 0) >= MIN_WATCH_CONFIDENCE:
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                if r.get("gate_reason"):
                    reasons.append(r["gate_reason"])
            else:
                state = "NO TRADE"

        r["decision_state"] = state
        r["decision_reasons"] = reasons
        if state != raw:
            r["original_action"] = raw
        if state in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            _save_signal_memory(r, state)
        elif raw in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
            _save_signal_memory(r, state)
        STORE.insert("atlas_decision_events", {
            "timestamp": now_utc().isoformat(), "coin": r["coin"], "state": state,
            "confidence": r.get("confidence"), "rr": r.get("rr"),
            "btc_regime": regime, "breadth": breadth.get("score"),
            "reason": " | ".join(reasons) or "decision passed",
        })
    return results


def atlas_decision_board(results, btc_regime, breadth):
    buys = [r for r in results if r.get("decision_state") == "BUY CONFIRMATION" and not r.get("repeat_signal")]
    sells = [r for r in results if r.get("decision_state") == "SELL CONFIRMATION" and not r.get("repeat_signal")]
    bw = [r for r in results if r.get("decision_state") == "BULLISH WATCH"]
    sw = [r for r in results if r.get("decision_state") == "BEARISH WATCH"]
    buys.sort(key=lambda r: (r.get("confidence", 0), r.get("rr") or 0), reverse=True)
    sells.sort(key=lambda r: (r.get("confidence", 0), r.get("rr") or 0), reverse=True)
    bw.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    sw.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    best = buys[0] if buys else (sells[0] if sells else None)
    lines = [
        "━━━━━━━━━━━━━━━━━━",
        f"🎯 {VERSION} DECISION BOARD",
        f"BTC REGIME: {btc_regime.get('regime','UNKNOWN')} | {btc_regime.get('reason','')}",
        f"MARKET BREADTH: {breadth.get('state')} | {breadth.get('score'):.1f}% bullish | N={breadth.get('samples',0)}",
    ]
    def compact(title, rows, icon):
        lines.append(f"{icon} {title}")
        if not rows:
            lines.append("— ندارد")
            return
        for r in rows[:5]:
            rr = f" | R/R {r['rr']:.2f}" if r.get("rr") else ""
            lines.append(f"{r['coin']} — {r['confidence']}%{rr}")
    compact("EXECUTABLE BUY", buys, "🟢")
    compact("EXECUTABLE SELL / REDUCE", sells, "🔴")
    compact("WATCH — صعود", bw, "📈")
    compact("WATCH — ریزش", sw, "📉")
    if best:
        lines.extend([
            "🔥 BEST SETUP",
            f"{best['coin']} | {best['decision_state']} | Confidence {best['confidence']}% | R/R {best.get('rr') or 0:.2f}",
            f"Entry {fmt(best.get('entry'))} | SL {fmt(best.get('sl'))} | TP1 {fmt(best.get('tp1'))} | TP2 {fmt(best.get('tp2'))}",
            f"Trend H4/D1: {best.get('h4_trend')} / {best.get('d1_trend')} | S/R: {best.get('sr_confidence')}",
        ])
    else:
        lines.append("⚪ BEST SETUP: هیچ معامله‌ای با کیفیت کافی پیدا نشد")
    lines.append("Rule: تحلیل خوب ≠ معامله خوب؛ R/R، regime، ساختار و تکراری‌بودن سیگنال همزمان بررسی شده‌اند.")
    return "\n".join(lines)


# ============================================================
# SELF-HEALING WEIGHTS
# ============================================================

DEFAULT_WEIGHTS = {
    "candle_pattern": 20.0,
    "rsi": 15.0,
    "macd": 15.0,
    "volume": 15.0,
    "higher_trend": 20.0,
    "news_clear": 15.0,
}


def get_weights():
    weights = DEFAULT_WEIGHTS.copy()
    # Carry the latest learned weights forward across v8.x versions.
    rows = STORE.select(
        "atlas_model_weights",
        {"select": "feature,weight,model_version,updated_at", "order": "updated_at.desc", "limit": "200"},
    )
    seen=set()
    for r in rows:
        feature=r.get("feature")
        w=f(r.get("weight"))
        if feature in weights and feature not in seen and w is not None:
            weights[feature]=clamp(w,5,30); seen.add(feature)
    init_sqlite()
    with sqlite_conn() as c:
        local=c.execute("select feature,weight from model_weights").fetchall()
        for r in local:
            if r["feature"] in weights and r["feature"] not in seen and f(r["weight"]) is not None:
                weights[r["feature"]]=clamp(f(r["weight"]),5,30)
        for feature,weight in weights.items():
            c.execute("insert or ignore into model_weights(feature,weight,baseline_weight,updated_at) values(?,?,?,?)",
                      (feature,weight,DEFAULT_WEIGHTS[feature],now_utc().isoformat()))
    return weights


def update_weight(feature, factor, reason, evidence):
    if feature not in DEFAULT_WEIGHTS:
        return
    evidence=evidence or {}
    old=DEFAULT_WEIGHTS.get(feature,15.0)
    rows=STORE.select("atlas_model_weights", {"select":"feature,weight,updated_at","feature":f"eq.{feature}","order":"updated_at.desc","limit":"1"})
    if rows:
        old=f(rows[0].get("weight")) or old
    else:
        init_sqlite()
        with sqlite_conn() as c:
            r=c.execute("select weight from model_weights where feature=?",(feature,)).fetchone()
            if r and f(r[0]) is not None: old=f(r[0])
    new=clamp(old*factor,5,30)
    payload={"model_version":VERSION,"feature":feature,"weight":new,"baseline_weight":DEFAULT_WEIGHTS[feature],"samples":evidence.get("samples",0),"wins":evidence.get("wins",0),"losses":evidence.get("losses",0),"reason":reason,"updated_at":now_utc().isoformat()}
    STORE.insert("atlas_model_weights",payload)
    init_sqlite()
    with sqlite_conn() as c:
        c.execute("insert into model_weights(feature,weight,baseline_weight,samples,wins,losses,updated_at,reason) values(?,?,?,?,?,?,?,?) on conflict(feature) do update set weight=excluded.weight,samples=excluded.samples,wins=excluded.wins,losses=excluded.losses,updated_at=excluded.updated_at,reason=excluded.reason",
                  (feature,new,DEFAULT_WEIGHTS[feature],evidence.get("samples",0),evidence.get("wins",0),evidence.get("losses",0),payload["updated_at"],reason))
    append_changelog(feature,old,new,reason,evidence)


def self_diagnostic():
    """Adapt weights only after the backtest gate, using durable local signal IDs."""
    init_sqlite()
    with sqlite_conn() as c:
        rows=c.execute("""
            select s.id,s.coin,s.direction,s.outcome,s.notes
            from signal_outcomes s
            left join self_healing_processed p on p.signal_id=s.id
            where s.status='CLOSED' and p.signal_id is null
            order by s.id asc
        """).fetchall()
    if len(rows)<3:return
    batch=rows[:(len(rows)//3)*3]
    for start_i in range(0,len(batch),3):
        recent=batch[start_i:start_i+3]
        losses=sum(1 for r in recent if r["outcome"]=="SL")
        error_pct=losses/3*100
        if error_pct>5:
            counts={}
            for r in recent:
                text=(r["notes"] or "").lower()
                for token in ("rsi","macd","volume","sma","hammer","engulfing"):
                    if token in text: counts[token]=counts.get(token,0)+1
            feature=max(counts,key=counts.get) if counts else "rsi"
            mapped={"rsi":"rsi","macd":"macd","volume":"volume","sma":"higher_trend","hammer":"candle_pattern","engulfing":"candle_pattern"}
            feature=mapped.get(feature,"rsi")
            update_weight(feature,0.80,"خطای پیش‌بینی > 5% پس از batch جدید؛ وزن 20% کاهش یافت",
                          {"samples":3,"wins":3-losses,"losses":losses,"error_pct":error_pct,"signal_ids":[r["id"] for r in recent]})
        with sqlite_conn() as c:
            c.executemany("insert or ignore into self_healing_processed(signal_id,processed_at) values(?,?)",[(r["id"],now_utc().isoformat()) for r in recent])


# ============================================================
# BACKTEST ENGINE
# ============================================================

def backtest_coin(coin, days=180):
    try:
        rows, engine = best_ohlcv(coin, "4h", 1200)
    except Exception:
        return None

    cutoff = int((time.time() - days * 86400) * 1000)
    rows = [x for x in rows if x[0] >= cutoff]
    if len(rows) < 150:
        return None

    trades = []
    equity = 1.0
    peak = equity
    max_dd = 0.0

    for i in range(80, len(rows) - SIGNAL_HORIZON_BARS, 4):
        window = rows[:i]
        c = closes(window)
        rr = rsi(c)
        ml, ms, _ = macd(c)
        s20, s50 = sma(c, 20), sma(c, 50)

        if None in (rr, ml, ms, s20, s50):
            continue

        bullish = c[-1] > s20 > s50 and ml > ms and rr > 50
        bearish = c[-1] < s20 < s50 and ml < ms and rr < 50

        vol, vr = volume_state(window)
        if vr is None or vr <= MIN_VOLUME_RATIO:
            continue

        direction = "LONG" if bullish else "SHORT" if bearish else None
        if not direction:
            continue

        a = atr(window)
        if not a:
            continue

        entry = c[-1]
        sl = entry - 1.5 * a if direction == "LONG" else entry + 1.5 * a
        tp = entry + 3 * a if direction == "LONG" else entry - 3 * a

        outcome = None
        pnl = None
        for future in rows[i:i + SIGNAL_HORIZON_BARS]:
            hi, lo = f(future[2]), f(future[3])
            if direction == "LONG":
                if lo <= sl:
                    outcome, pnl = "SL", -1.5
                    break
                if hi >= tp:
                    outcome, pnl = "TP", 3.0
                    break
            else:
                if hi >= sl:
                    outcome, pnl = "SL", -1.5
                    break
                if lo <= tp:
                    outcome, pnl = "TP", 3.0
                    break

        if outcome:
            trades.append(pnl)
            equity *= 1 + pnl / 100
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100)

    if not trades:
        return None

    wins = sum(1 for x in trades if x > 0)
    losses = len(trades) - wins
    avg_profit = safe_mean([x for x in trades if x > 0], 0.0)
    avg_loss = abs(safe_mean([x for x in trades if x < 0], 0.0)) if losses else 0
    gross_profit = sum(x for x in trades if x > 0)
    gross_loss = abs(sum(x for x in trades if x < 0))

    return {
        "coin": coin,
        "engine": engine,
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(trades) * 100,
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "max_drawdown": max_dd,
        "profit_factor": gross_profit / gross_loss if gross_loss else 99,
        "trades_raw": trades,
    }


def _cached_backtest_gate():
    """Return a recent cached gate result, or None when refresh is due."""
    try:
        cutoff = now_utc() - timedelta(hours=BACKTEST_REFRESH_HOURS)
        with sqlite_conn() as c:
            row = c.execute(
                "select timestamp, passed, details from backtest_gate_cache where id=1"
            ).fetchone()
        if not row or not row[0]:
            return None
        ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        if ts < cutoff:
            return None
        details = row[2]
        try:
            details = json.loads(details) if isinstance(details, str) else (details or {})
        except Exception:
            details = {}
        return bool(row[1]), {"cached": True, **details}
    except Exception as e:
        append_changelog("BACKTEST_CACHE", None, None, str(e), {"traceback": traceback.format_exc()})
        return None


def _save_backtest_gate(passed, details):
    try:
        with sqlite_conn() as c:
            c.execute(
                "insert or replace into backtest_gate_cache(id,timestamp,passed,details) values(1,?,?,?)",
                (now_utc().isoformat(), int(bool(passed)), safe_json(details)),
            )
    except Exception as e:
        append_changelog("BACKTEST_CACHE", None, None, f"cache write failed: {e}", {"traceback": traceback.format_exc()})


def h4_fallback_levels(rows, current_price=None):
    """Conservative H4 fallback used only when Daily S/R is unavailable.

    It is deliberately weaker than Daily S/R and therefore requires a higher
    confidence threshold before it can produce a confirmation signal.
    """
    if not rows or len(rows) < 80:
        return None
    price = f(current_price) or f(rows[-1][4])
    if price is None or price <= 0:
        return None
    window = rows[-80:]
    lows = [f(x[3]) for x in window if f(x[3]) is not None and f(x[3]) < price]
    highs = [f(x[2]) for x in window if f(x[2]) is not None and f(x[2]) > price]
    if not lows or not highs:
        return None
    sup = max(lows)
    res = min(highs)
    a = atr(window)
    if not a or a <= 0:
        return None
    sup_dist = abs(price - sup) / a
    res_dist = abs(res - price) / a
    score_s = 80 if sup_dist <= 3 else 72 if sup_dist <= 6 else 60
    score_r = 80 if res_dist <= 3 else 72 if res_dist <= 6 else 60
    conf = "HIGH" if min(score_s, score_r) >= 80 else "MEDIUM" if min(score_s, score_r) >= 65 else "LOW"
    return {
        "support": sup, "resistance": res,
        "support_score": score_s, "resistance_score": score_r,
        "support_touches": 0, "resistance_touches": 0,
        "confidence": conf, "method": "H4_RANGE_FALLBACK"
    }


def mandatory_backtest_gate(universe):
    """Run a compact portfolio backtest before any weight change.

    The gate is mandatory, but the expensive calculation is cached for a
    configurable period (default 24h) so a 4H scheduler does not rerun the
    full backtest on every execution.
    """
    cached = _cached_backtest_gate()
    if cached is not None:
        return cached

    samples = []
    for coin in universe[:20]:
        r = backtest_coin(coin, BACKTEST_DAYS)
        if r:
            samples.append(r)

    if not samples:
        append_changelog(
            "BACKTEST",
            None,
            None,
            "Backtest unavailable; self-modification frozen",
        )
        result = {"reason": "no backtest data"}
        _save_backtest_gate(False, result)
        return False, result

    win_rate = safe_mean([x.get("win_rate") for x in samples], 0.0)
    pf = safe_mean([x.get("profit_factor") for x in samples], 0.0)
    dd = max((safe_float(x.get("max_drawdown"), 0.0) or 0.0) for x in samples)

    # If no baseline exists, establish it without changing the model.
    old = STORE.select(
        "atlas_backtests",
        {
            "select": "profit_factor,win_rate",
            "model_version": f"eq.{VERSION}",
            "limit": "1",
            "order": "timestamp.desc",
        },
    )

    if not old:
        for r in samples:
            STORE.insert(
                "atlas_backtests",
                {
                    "model_version": VERSION,
                    "coin": r["coin"],
                    "timeframe": "4h",
                    "period_days": BACKTEST_DAYS,
                    "trades": r["trades"],
                    "wins": r["wins"],
                    "losses": r["losses"],
                    "win_rate": r["win_rate"],
                    "avg_profit": r["avg_profit"],
                    "avg_loss": r["avg_loss"],
                    "max_drawdown": r["max_drawdown"],
                    "profit_factor": r["profit_factor"],
                    "passed": True,
                    "details": {"baseline": True},
                },
            )
        append_changelog(
            "BACKTEST",
            None,
            pf,
            "Baseline established; no automatic model change allowed yet",
            {"win_rate": win_rate, "profit_factor": pf, "max_drawdown": dd},
        )
        result = {
            "win_rate": win_rate,
            "profit_factor": pf,
            "max_drawdown": dd,
            "improvement": 0,
        }
        _save_backtest_gate(True, result)
        return True, result

    baseline_pf = f(old[0].get("profit_factor")) or 0
    baseline_wr = f(old[0].get("win_rate")) or 0

    improvement_pf = (
        (pf - baseline_pf) / baseline_pf * 100 if baseline_pf else 0
    )
    improvement_wr = (
        (win_rate - baseline_wr) / baseline_wr * 100 if baseline_wr else 0
    )

    passed = (
        improvement_pf >= MIN_BACKTEST_IMPROVEMENT
        or improvement_wr >= MIN_BACKTEST_IMPROVEMENT
    )

    for r in samples:
        STORE.insert(
            "atlas_backtests",
            {
                "model_version": VERSION,
                "coin": r["coin"],
                "timeframe": "4h",
                "period_days": BACKTEST_DAYS,
                "trades": r["trades"],
                "wins": r["wins"],
                "losses": r["losses"],
                "win_rate": r["win_rate"],
                "avg_profit": r["avg_profit"],
                "avg_loss": r["avg_loss"],
                "max_drawdown": r["max_drawdown"],
                "profit_factor": r["profit_factor"],
                "baseline_profit_factor": baseline_pf,
                "baseline_win_rate": baseline_wr,
                "improvement_pct": max(improvement_pf, improvement_wr),
                "passed": passed,
                "details": {"self_healing_gate": True},
            },
        )

    append_changelog(
        "BACKTEST_GATE",
        baseline_pf,
        pf,
        "Mandatory pre-change backtest",
        {
            "baseline_win_rate": baseline_wr,
            "new_win_rate": win_rate,
            "improvement_pf_pct": improvement_pf,
            "improvement_wr_pct": improvement_wr,
            "passed": passed,
        },
    )

    result = {
        "win_rate": win_rate,
        "profit_factor": pf,
        "max_drawdown": dd,
        "improvement": max(improvement_pf, improvement_wr),
    }
    _save_backtest_gate(passed, result)
    return passed, result


# ============================================================
# SIGNAL OUTCOME TRACKING
# ============================================================

def store_signal(result):
    if result["action"] not in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
        return None

    row = {
        "timestamp": now_utc().isoformat(),
        "run_type": "SNIPER",
        "coin": result["coin"],
        "timeframe": "4h",
        "action": result["action"],
        "direction": result["direction"],
        "score": int(result["confidence"]),
        "confidence": result["confidence"],
        "price": result["price"],
        "change_24h": result["change"],
        "trend": result["trend"],
        "rsi": result["rsi"],
        "macd": result["macd"],
        "volume": result["volume"],
        "support": result["support"],
        "resistance": result["resistance"],
        "entry": result["entry"],
        "sl": result["sl"],
        "tp1": result["tp1"],
        "tp2": result["tp2"],
        "data_quality": result["quality"],
        "spread_pct": result["spread"],
        "exchanges": ",".join(result["sources"]),
        "alignment": result["h4_trend"] + "/" + result["d1_trend"],
        "gate": result["gate"],
        "gate_reason": result["gate_reason"],
        "raw_action": result["action"],
        "notes": result["reason"],
        "candle_pattern": result["pattern"],
        "h1_trend": result["h1_trend"],
        "h4_trend": result["h4_trend"],
        "d1_trend": result["d1_trend"],
        "w1_trend": result.get("w1_trend"),
        "m1_trend": result.get("m1_trend"),
        "candle_trigger": result.get("candle_trigger", {}),
        "candle_events": result.get("candle_events", {}),
        "liquidity_score": result["liquidity_score"],
        "volume_ratio": result["volume_ratio"],
        "atr_pct": result["atr_pct"],
        "pivot_weekly": result["pivot"],
        "momentum_30m": result["momentum_30m"],
        "news_impact": result["news_impact"],
        "volatility_warning": bool(result["warning"]),
        "reason": result["reason"],
        "leverage": result["leverage"],
        "confidence_breakdown": result.get("score_components", {}),
        "model_version": VERSION,
    }
    STORE.insert("atlas_signals", row)

    init_sqlite()
    with sqlite_conn() as c:
        c.execute(
            """
            insert into signal_outcomes
            (coin,direction,entry,sl,tp1,tp2,issued_at,notes)
            values(?,?,?,?,?,?,?,?)
            """,
            (
                result["coin"], result["direction"], result["entry"],
                result["sl"], result["tp1"], result["tp2"],
                now_utc().isoformat(), result["reason"],
            ),
        )


def evaluate_open_outcomes():
    init_sqlite()
    with sqlite_conn() as c:
        open_rows=c.execute("select * from signal_outcomes where status='OPEN' order by id asc limit 100").fetchall()
    for row in open_rows:
        try:
            candles,_=best_ohlcv(row["coin"],"4h",100)
            issued=datetime.fromisoformat(row["issued_at"].replace("Z","+00:00"))
            after=[x for x in candles if x[0]/1000>issued.timestamp()]
            outcome=None; exit_price=None; bars=0
            entry=f(row["entry"]); sl=f(row["sl"]); tp1=f(row["tp1"]); tp2=f(row["tp2"])
            if None in (entry,sl,tp1): continue
            for bars,x in enumerate(after[:SIGNAL_HORIZON_BARS],1):
                hi,lo=f(x[2]),f(x[3])
                if hi is None or lo is None: continue
                if row["direction"]=="LONG":
                    if lo<=sl:
                        outcome,exit_price="SL",sl; break
                    if tp2 is not None and hi>=tp2:
                        outcome,exit_price="TP2",tp2; break
                    if hi>=tp1:
                        outcome,exit_price="TP1",tp1; break
                else:
                    if hi>=sl:
                        outcome,exit_price="SL",sl; break
                    if tp2 is not None and lo<=tp2:
                        outcome,exit_price="TP2",tp2; break
                    if lo<=tp1:
                        outcome,exit_price="TP1",tp1; break
            if outcome is None and after and len(after)>=SIGNAL_HORIZON_BARS:
                last=after[SIGNAL_HORIZON_BARS-1]; exit_price=f(last[4])
                if exit_price is not None:
                    outcome="TIMEOUT"; bars=SIGNAL_HORIZON_BARS
            if not outcome or exit_price is None: continue
            pnl=((exit_price-entry)/entry*100) if row["direction"]=="LONG" else ((entry-exit_price)/entry*100)
            with sqlite_conn() as c:
                c.execute("update signal_outcomes set status='CLOSED',outcome=?,exit_price=?,exit_at=?,pnl_pct=?,bars_to_exit=? where id=?",(outcome,exit_price,now_utc().isoformat(),pnl,bars,row["id"]))
            STORE.insert("atlas_signal_outcomes",{"coin":row["coin"],"direction":row["direction"],"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"issued_at":row["issued_at"],"status":"CLOSED","outcome":outcome,"exit_price":exit_price,"exit_at":now_utc().isoformat(),"pnl_pct":pnl,"bars_to_exit":bars,"notes":row["notes"]})
        except Exception as e:
            append_changelog("OUTCOME_EVAL",None,None,f"{row['coin']}: {e}",{"traceback":traceback.format_exc()})


# ============================================================
# TELEGRAM
# ============================================================

def telegram_api_get_me():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN missing")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
        headers={"User-Agent": "ATLAS-AI/8.7"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getMe failed: {data}")
    return data.get("result") or {}


def telegram_send_one(chat_id, text):
    if not TELEGRAM_TOKEN or not chat_id:
        raise RuntimeError("Telegram secrets missing")

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
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {data}")
    return data


def telegram_preflight():
    """Validate Telegram credentials before the expensive market run."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing from GitHub Secrets")
    if not TELEGRAM_CHAT_ID and not TELEGRAM_GROUP_CHAT_ID:
        raise RuntimeError("No Telegram destination configured: TELEGRAM_CHAT_ID / TELEGRAM_GROUP_CHAT_ID")
    me = telegram_api_get_me()
    append_changelog(
        "TELEGRAM_PREFLIGHT", None, None,
        f"Telegram API reachable as @{me.get('username') or me.get('first_name') or 'bot'}"
    )
    return me


def split_telegram(text, max_chars=3900):
    """Split without destroying asset blocks."""
    if len(text) <= max_chars:
        return [text]

    parts = []
    current = ""

    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                parts.append(current)
            if len(block) <= max_chars:
                current = block
            else:
                # Hard split only as last resort.
                for i in range(0, len(block), max_chars):
                    parts.append(block[i:i + max_chars])
                current = ""

    if current:
        parts.append(current)

    return parts


def send_report(text):
    """Deliver once per configured destination, with independent retry state."""
    import hashlib
    parts = split_telegram(text)
    report_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    init_sqlite()
    destinations = []
    for destination in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        if destination and destination not in destinations:
            destinations.append(destination)
    if not destinations:
        msg = "No Telegram destination configured"
        append_changelog("TELEGRAM", None, None, msg)
        return len(parts), 0, [msg]

    sent = 0
    errors = []
    for destination in destinations:
        with sqlite_conn() as c:
            already = c.execute(
                "select 1 from telegram_sent_reports where report_hash=? and destination=?",
                (report_hash, destination),
            ).fetchone()
        if already:
            continue

        destination_ok = True
        for i, part in enumerate(parts, 1):
            try:
                telegram_send_one(destination, part)
                sent += 1
                time.sleep(0.7)
            except Exception as e:
                destination_ok = False
                err = f"Telegram destination {destination}, part {i}: {e}"
                errors.append(err)
                append_changelog("TELEGRAM", None, None, err, {"traceback": traceback.format_exc()})
                break
        if destination_ok:
            with sqlite_conn() as c:
                c.execute(
                    "insert or ignore into telegram_sent_reports(report_hash,destination,sent_at) values(?,?,?)",
                    (report_hash, destination, now_utc().isoformat()),
                )
    return len(parts), sent, errors


# ============================================================
# REPORT FORMAT
# ============================================================

def action_emoji(action):
    if action == "BUY CONFIRMATION":
        return "🟢 BUY CONFIRMATION"
    if action == "SELL CONFIRMATION":
        return "🔴 SELL CONFIRMATION"
    if action == "BULLISH WATCH":
        return "🟢 BULLISH WATCH"
    if action == "BEARISH WATCH":
        return "🔴 BEARISH WATCH"
    return "⛔ NO TRADE"


def asset_block(r):
    """Compact decision-focused asset report.

    Signal calculations still use the full MTF dataset; Telegram only shows
    fields that materially affect a trading decision. This keeps the report
    readable without weakening the engine.
    """
    action = r.get("action", "NO TRADE")
    lines = [
        f"🔹 {display_symbol(r['coin'])}",
        f"Price: {fmt(r['price'])} | 24H: {pct(r['change'])}",
        f"H4/D1/W1: {r['h4_trend']} / {r['d1_trend']} / {r.get('w1_trend','UNKNOWN')}",
        f"RSI: {r['rsi']:.1f}" if r.get('rsi') is not None else "RSI: N/A",
        f"MACD: {'🟢' if r['macd']=='BULLISH' else '🔴' if r['macd']=='BEARISH' else '🟡'} {r['macd']}",
        f"Pattern: {r['pattern']}" + (" ✅" if r.get("pattern_valid") else ""),
        f"Volume: {r['volume']} | {r['volume_ratio']:.2f}x" if r.get('volume_ratio') is not None else f"Volume: {r['volume']} | N/A",
        f"Liquidity: {r['liquidity']} | ATR: {r['atr_pct']:.2f}%" if r.get('atr_pct') is not None else f"Liquidity: {r['liquidity']} | ATR: N/A",
        f"4H Trigger: {(r.get('candle_trigger') or {}).get('state','UNKNOWN')}",
        f"Daily S/R: {fmt(r.get('support'))} ↔ {fmt(r.get('resistance'))} | {r.get('sr_confidence','LOW')}",
        f"Scores: Setup {r.get('setup_score', r.get('confidence',0))}/100 | Entry {r.get('entry_quality',0)}/100 | Risk {r.get('risk_quality',0)}/100",
        f"🎯 ACTION: {action_emoji(action)}",
    ]

    if action in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
        lines += [
            f"R/R: 1:{r.get('rr', 0):.2f} | Entry: {fmt(r.get('entry'))} | SL: {fmt(r.get('sl'))}",
            f"TP1: {fmt(r.get('tp1'))} | TP2: {fmt(r.get('tp2'))}",
            f"Reason: {r.get('reason') or 'تأیید چندعاملی کافی است'}",
        ]
    elif r.get("decision_reasons"):
        lines.append("Decision: " + " | ".join(r["decision_reasons"][:3]))
        lines.append(f"Confidence: {r.get('confidence',0)}% | Data: {r.get('quality','UNKNOWN')}")
    else:
        lines.append(f"Confidence: {r.get('confidence',0)}% | Data: {r.get('quality','UNKNOWN')}")
        lines.append(f"Reason: {r.get('reason') or 'تأیید چندعاملی کافی نیست'}")

    if r.get("warning"):
        lines.append(f"⚠️ {r['warning']}")
    if f(r.get("spread")) is not None and r["spread"] > 3:
        lines.append(f"⚠️ DATA CONFLICT: {r['spread']:.2f}%")
    if r.get("price_errors"):
        lines.append(f"⚠️ PRICE SOURCES FAILED: {len(r['price_errors'])}")
    return "\n".join(lines)


# ============================================================
# MARKET INTELLIGENCE — GLOBAL / SENTIMENT / DOMINANCE / MOVERS
# ============================================================

def coingecko_headers():
    if COINGECKO_API_KEY:
        return {"x-cg-demo-api-key": COINGECKO_API_KEY}
    return {}


def global_market_intelligence():
    """Fetch one compact daily market snapshot from CoinGecko + F&G.

    Uses /global for aggregate market regime and /coins/markets for the
    top-300 universe so gainers/losers are calculated locally rather than
    depending on the paid top_gainers_losers endpoint.
    """
    out = {
        "market_cap": None, "volume_24h": None, "market_change_24h": None,
        "volume_change_24h": None, "btc_dominance": None,
        "eth_dominance": None, "stablecoin_dominance": None,
        "altcoin_dominance": None, "fear_greed": None,
        "fear_greed_label": None, "fear_greed_ts": None,
        "top_gainers": [], "top_losers": [], "heatmap": [],
        "source": "CoinGecko + Alternative.me + optional CoinGlass",
    }

    global_data = safe_http_get(
        "https://api.coingecko.com/api/v3/global",
        headers=coingecko_headers(), default={}
    )
    if isinstance(global_data, dict):
        d = global_data.get("data") or {}
        cap = d.get("total_market_cap") or {}
        vol = d.get("total_volume") or {}
        dom = d.get("market_cap_percentage") or {}
        out["market_cap"] = f(cap.get("usd"))
        out["volume_24h"] = f(vol.get("usd"))
        out["market_change_24h"] = f(d.get("market_cap_change_percentage_24h_usd"))
        out["volume_change_24h"] = f(d.get("volume_change_percentage_24h_usd"))
        out["btc_dominance"] = f(dom.get("btc"))
        out["eth_dominance"] = f(dom.get("eth"))
        # Stablecoin dominance is approximated from the principal stablecoins
        # exposed by CoinGecko. This avoids double-counting non-stable assets.
        stable_ids = ("usdt", "usdc", "usde", "dai", "fdusd", "usds", "usdd")
        stable_dom = sum(f(dom.get(k), 0) or 0 for k in stable_ids)
        out["stablecoin_dominance"] = stable_dom if stable_dom > 0 else None
        btc = out["btc_dominance"] or 0
        stable = out["stablecoin_dominance"] or 0
        out["altcoin_dominance"] = max(0.0, 100.0 - btc - stable)

    # Top 300 market-cap snapshot. Two calls are enough because CoinGecko
    # supports up to 250 records per page on the markets endpoint.
    markets = []
    for page, per_page in ((1, 250), (2, 50)):
        url = "https://api.coingecko.com/api/v3/coins/markets?" + urllib.parse.urlencode({
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": str(per_page), "page": str(page), "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        })
        rows = safe_http_get(url, headers=coingecko_headers(), default=[])
        if isinstance(rows, list):
            markets.extend(rows)
        if len(markets) >= 300:
            break
        time.sleep(0.15)

    clean = []
    for x in markets[:300]:
        if not isinstance(x, dict):
            continue
        sym = (x.get("symbol") or "").upper()
        if not sym or is_stable(sym):
            continue
        ch = f(x.get("price_change_percentage_24h"))
        price = f(x.get("current_price"))
        vol = f(x.get("total_volume"))
        rank = x.get("market_cap_rank")
        if ch is None or price is None:
            continue
        clean.append({
            "symbol": sym, "name": x.get("name") or sym,
            "rank": rank, "price": price, "volume": vol,
            "change_24h": ch, "high_24h": f(x.get("high_24h")),
            "low_24h": f(x.get("low_24h")),
            "change_1h": f(x.get("price_change_percentage_1h_in_currency")),
            "change_7d": f(x.get("price_change_percentage_7d_in_currency")),
        })
    # CoinGecko can expose duplicate symbols (same ticker used by different assets).
    # Keep the highest-ranked occurrence so the report is not misleading.
    unique = {}
    for item in sorted(clean, key=lambda x: (x.get("rank") or 999999)):
        unique.setdefault(item["symbol"], item)
    clean = list(unique.values())
    clean.sort(key=lambda x: x["change_24h"], reverse=True)
    out["top_gainers"] = clean[:7]
    out["top_losers"] = list(reversed(clean[-7:])) if clean else []

    fg = safe_http_get("https://api.alternative.me/fng/?limit=1", default={})
    if isinstance(fg, dict):
        try:
            item = (fg.get("data") or [])[0]
            out["fear_greed"] = int(item.get("value"))
            out["fear_greed_label"] = item.get("value_classification")
            out["fear_greed_ts"] = item.get("timestamp")
        except (IndexError, TypeError, ValueError):
            pass

    out["heatmap"] = liquidation_heatmap_summary(("BTC", "ETH"))
    return out


def liquidation_heatmap_summary(symbols=("BTC", "ETH")):
    """Optional CoinGlass heatmap summary.

    CoinGlass currently requires an API key for API access. Therefore the
    module is deliberately non-blocking: without a key it returns an empty
    list and never prevents the core ATLAS report from running.
    """
    if not COINGLASS_API_KEY:
        return []
    headers = {"CG-API-KEY": COINGLASS_API_KEY, "accept": "application/json"}
    result = []
    for symbol in symbols:
        url = "https://open-api-v4.coinglass.com/api/futures/liquidation/aggregated-heatmap/model1?" + urllib.parse.urlencode({
            "symbol": symbol, "range": "24h"
        })
        d = safe_http_get(url, timeout=15, headers=headers, default={})
        if not isinstance(d, dict) or d.get("code") not in (None, "0", 0):
            continue
        data = d.get("data") or {}
        y_axis = data.get("y_axis") or []
        cells = data.get("liquidation_leverage_data") or []
        price = None
        candles = data.get("price_candlesticks") or []
        if candles and isinstance(candles[-1], (list, tuple)) and len(candles[-1]) >= 5:
            price = f(candles[-1][4])
        levels = []
        for cell in cells:
            if not isinstance(cell, (list, tuple)) or len(cell) < 3:
                continue
            yi, intensity = safe_float(cell[1]), safe_float(cell[2])
            if yi is None or intensity is None:
                continue
            yi = int(yi)
            if 0 <= yi < len(y_axis):
                lvl = f(y_axis[yi])
                if lvl and lvl > 0:
                    levels.append((lvl, intensity))
        above = sorted([x for x in levels if price is not None and x[0] > price], key=lambda z: z[1], reverse=True)
        below = sorted([x for x in levels if price is not None and x[0] < price], key=lambda z: z[1], reverse=True)
        result.append({
            "symbol": symbol, "price": price,
            "above": above[:3], "below": below[:3],
        })
    return result


def market_intelligence_block(mi):
    lines = ["━━━━━━━━━━━━━━━━━━", "🌐 GLOBAL MARKET PULSE"]
    if mi.get("market_cap") is not None:
        lines.append(f"Total Market Cap: ${mi['market_cap']/1e12:.2f}T")
    if mi.get("volume_24h") is not None:
        lines.append(f"24H Market Volume: ${mi['volume_24h']/1e9:.2f}B")
    if mi.get("market_change_24h") is not None:
        lines.append(f"Market Cap 24H: {pct(mi['market_change_24h'])}")
    if mi.get("volume_change_24h") is not None:
        lines.append(f"Volume 24H Change: {pct(mi['volume_change_24h'])}")
    if mi.get("fear_greed") is not None:
        lines.append(f"😨 Fear & Greed: {mi['fear_greed']} — {mi.get('fear_greed_label','N/A')} (Alternative.me)")
    dom = []
    if mi.get("btc_dominance") is not None: dom.append(f"BTC {mi['btc_dominance']:.2f}%")
    if mi.get("eth_dominance") is not None: dom.append(f"ETH {mi['eth_dominance']:.2f}%")
    if mi.get("altcoin_dominance") is not None: dom.append(f"ALT* {mi['altcoin_dominance']:.2f}%")
    if dom: lines.append("Dominance: " + " | ".join(dom))
    if mi.get("stablecoin_dominance") is not None:
        lines.append(f"Stablecoin dominance: {mi['stablecoin_dominance']:.2f}%")

    gainers = mi.get("top_gainers") or []
    losers = mi.get("top_losers") or []
    if gainers:
        lines.append("🚀 TOP GAINERS — Top 300: " + " | ".join(f"{x['symbol']} {pct(x['change_24h'])}" for x in gainers[:5]))
    if losers:
        lines.append("🔻 TOP LOSERS — Top 300: " + " | ".join(f"{x['symbol']} {pct(x['change_24h'])}" for x in losers[:5]))

    hm = mi.get("heatmap") or []
    if hm:
        lines.append("🔥 LIQUIDATION HEATMAP — CoinGlass")
        for x in hm:
            above = x.get("above") or []
            below = x.get("below") or []
            a = fmt(above[0][0]) if above else "N/A"
            b = fmt(below[0][0]) if below else "N/A"
            lines.append(f"{x['symbol']}: price {fmt(x.get('price'))} | strongest above {a} | strongest below {b}")
    else:
        lines.append("🔥 Liquidation Heatmap: N/A (COINGLASS_API_KEY not configured or endpoint unavailable)")
    lines.append("* ALT* = total crypto dominance excluding BTC and principal stablecoins; ETH is included in ALT*, so dominance lines are not additive.")
    return "\n".join(lines)


def market_summary(results, macro, news):
    tradable = [
        x for x in results
        if x["action"] in ("BUY CONFIRMATION", "SELL CONFIRMATION")
    ]
    bullish = sum(1 for x in results if x["h4_trend"] == "BULLISH")
    bearish = sum(1 for x in results if x["h4_trend"] == "BEARISH")

    if bullish > bearish * 1.25:
        regime = "تمایل غالب صعودی"
    elif bearish > bullish * 1.25:
        regime = "تمایل غالب نزولی"
    else:
        regime = "بازار دوطرفه / خنثی"

    dxy = macro.get("DXY")
    fg = safe_http_get(
        "https://api.alternative.me/fng/?limit=1",
        default={},
    )
    fg_value = None
    fg_label = ""
    try:
        fg_value = int(fg["data"][0]["value"])
        fg_label = fg["data"][0]["value_classification"]
    except Exception:
        pass

    lines = [
        "━━━━━━━━━━━━━━━━━━",
        "🧠 ATLAS MARKET INTELLIGENCE",
        f"Bias: {regime}",
        f"4H Bullish: {bullish} | 4H Bearish: {bearish}",
        f"Actionable setups: {len(tradable)}",
        f"DXY: {fmt(dxy)} | USD liquidity proxy" if dxy is not None else "DXY: N/A | USD liquidity proxy unavailable",
        f"Fear & Greed: {fg_value} — {fg_label}" if fg_value is not None else "Fear & Greed: N/A",
        f"News: {news['bias']} / Impact: {news['impact']}",
    ]

    if macro.get("GOLD"):
        lines.append(f"Gold: {fmt(macro['GOLD'])}")
    if macro.get("SILVER"):
        lines.append(f"Silver: {fmt(macro['SILVER'])}")
    if macro.get("COPPER"):
        lines.append(f"Copper: {fmt(macro['COPPER'])}")
    if macro.get("WTI"):
        lines.append(f"WTI: {fmt(macro['WTI'])}")
    if macro.get("BRENT"):
        lines.append(f"Brent: {fmt(macro['BRENT'])}")

    if tradable:
        lines.append("")
        lines.append("🏆 BEST SETUPS")
        for i, x in enumerate(
            sorted(
                tradable,
                key=lambda z: (z["confidence"], z["liquidity_score"]),
                reverse=True,
            )[:8],
            1,
        ):
            lines.append(
                f"{i}. {x['coin']} — {x['direction']} — "
                f"{x['confidence']}% — {x['liquidity']}"
            )
    else:
        lines += [
            "",
            "⛔ هیچ ستاپی با تمام شروط ATLAS تأیید نشد.",
            "عدم قطعیت بالا - سیگنال صادر نشد",
        ]

    lines += [
        "",
        "📌 جمع‌بندی:",
        "ATLAS فقط زمانی سیگنال معاملاتی می‌دهد که روند H4 و D1، "
        "اندیکاتورها، حجم و ساختار قیمت هم‌جهت باشند.",
        "سیگنال خلاف روند تایم‌فریم بالاتر بدون واگرایی 3 سطحی حذف می‌شود.",
        "خبر پرریسک یا داده متناقض می‌تواند سیگنال را متوقف کند.",
        "استیبل‌کوین‌ها از چرخه سیگنال‌دهی حذف شده‌اند.",
        "",
        "تنظیمات بر اساس داده‌ی محدود اخیر انجام شده و ممکن است در آینده عملکرد متفاوتی داشته باشد.",
    ]
    return "\n".join(lines)


def atlas_conclusion(results):
    threshold = MIN_CONFIDENCE
    actionable = [x for x in results if x.get("decision_state") in ("BUY CONFIRMATION", "SELL CONFIRMATION") and x.get("confidence", 0) >= threshold and not x.get("repeat_signal")]
    buys = sorted([x for x in actionable if x.get("decision_state") == "BUY CONFIRMATION"], key=lambda z: (z.get("confidence", 0), z.get("rr") or 0, z.get("liquidity_score", 0)), reverse=True)
    sells = sorted([x for x in actionable if x.get("decision_state") == "SELL CONFIRMATION"], key=lambda z: (z.get("confidence", 0), z.get("rr") or 0, z.get("liquidity_score", 0)), reverse=True)
    rise = sorted([x for x in results if x.get("decision_state") == "BULLISH WATCH" and x.get("confidence", 0) >= MIN_WATCH_CONFIDENCE], key=lambda z: (z.get("confidence", 0), z.get("entry_quality", 0), z.get("liquidity_score", 0)), reverse=True)
    fall = sorted([x for x in results if x.get("decision_state") == "BEARISH WATCH" and x.get("confidence", 0) >= MIN_WATCH_CONFIDENCE], key=lambda z: (z.get("confidence", 0), z.get("entry_quality", 0), z.get("liquidity_score", 0)), reverse=True)

    label = lambda x: display_symbol(x.get("coin"))
    lines = ["━━━━━━━━━━━━━━━━━━", f"🎯 {VERSION} FINAL CONCLUSION"]
    lines.append("🟢 BUY / ACCUMULATE: " + (", ".join(f"{label(x)} ({x['confidence']}%)" for x in buys[:5]) if buys else "هیچ خریدی با تأیید کامل صادر نشد."))
    lines.append("🔴 SELL / REDUCE: " + (", ".join(f"{label(x)} ({x['confidence']}%)" for x in sells[:5]) if sells else "هیچ فروش تأییدشده‌ای صادر نشد."))
    lines.append("📈 RISE WATCH: " + (", ".join(f"{label(x)} ({x['confidence']}%)" for x in rise[:5]) if rise else "ندارد"))
    lines.append("📉 FALL WATCH: " + (", ".join(f"{label(x)} ({x['confidence']}%)" for x in fall[:5]) if fall else "ندارد"))

    best = buys[0] if buys else (sells[0] if sells else None)
    best_side = "BUY" if buys else "SELL"
    if buys and sells and sells[0].get("confidence", 0) > buys[0].get("confidence", 0):
        best, best_side = sells[0], "SELL"
    if best:
        lines += [
            f"⭐ BEST SETUP: {label(best)} — {best_side} — {best['confidence']}%",
            f"   H4/D1: {best.get('h4_trend')} / {best.get('d1_trend')} | S/R: {best.get('sr_confidence','LOW')} | Volume: {best.get('volume_ratio'):.2f}x" if best.get('volume_ratio') is not None else f"   H4/D1: {best.get('h4_trend')} / {best.get('d1_trend')} | S/R: {best.get('sr_confidence','LOW')} | Volume: N/A",
            f"   Entry: {fmt(best.get('entry'))} | SL: {fmt(best.get('sl'))} | TP1: {fmt(best.get('tp1'))} | TP2: {fmt(best.get('tp2'))}",
        ]
    elif rise or fall:
        watch = rise[0] if rise else fall[0]
        side = "BULLISH WATCH" if rise else "BEARISH WATCH"
        lines += [
            f"⭐ BEST WATCH: {label(watch)} — {side} — {watch['confidence']}%",
            f"   Trigger: {(watch.get('candle_trigger') or {}).get('state','UNKNOWN')} | RSI: {watch.get('rsi'):.1f}" if watch.get('rsi') is not None else f"   Trigger: {(watch.get('candle_trigger') or {}).get('state','UNKNOWN')} | RSI: N/A",
            f"   S/R: {watch.get('sr_confidence','LOW')} | Volume: {watch.get('volume_ratio'):.2f}x" if watch.get('volume_ratio') is not None else f"   S/R: {watch.get('sr_confidence','LOW')} | Volume: N/A",
            "   تصمیم: هنوز ورود اجرایی نیست؛ منتظر تأیید ساختار/پولبک هستیم.",
        ]
    else:
        lines.append("⭐ BEST SETUP: NONE — بازار در این اجرا ستاپ کم‌ریسک و تأییدشده نداد.")

    new_events = 0
    for r in results:
        ev = r.get("candle_events", {})
        new_events += sum(1 for x in ev.values() if isinstance(x, dict) and x.get("status") == "NEW_CLOSED")
    lines.append(f"Threshold: {threshold:.0f}% | Watch threshold: {MIN_WATCH_CONFIDENCE:.0f}% | Closed-candle events observed: {new_events}")
    lines.append("🛡️ تصمیم ATLAS: BUY/SELL فقط پس از Gate + R/R + regime + ساختار؛ WATCH جهت معتبر ولی هنوز غیرقابل‌اجراست.")
    return "\n".join(lines)


def _ordered_report_results(results, top10, dynamic30):
    """Return results in the contractual Telegram radar order."""
    by_coin = {}
    for r in results:
        coin = (r.get("coin") or "").upper()
        if coin and coin not in by_coin:
            by_coin[coin] = r

    ordered = []
    seen = set()

    for group in (top10, dynamic30, ATLAS_STATIC):
        for coin in group:
            coin = coin.upper()
            if coin in by_coin and coin not in seen:
                ordered.append(by_coin[coin])
                seen.add(coin)

    # Defensive tail: anything introduced by a future data source but not
    # assigned to one of the three groups still appears at the end.
    for r in results:
        coin = (r.get("coin") or "").upper()
        if coin and coin not in seen:
            ordered.append(r)
            seen.add(coin)

    return ordered


def _report_section_header(title, count, available=None, subtitle=None):
    lines = ["━━━━━━━━━━━━━━━━━━", title, f"Assets listed: {count} | Available: {available if available is not None else count}"]
    if subtitle:
        lines.append(subtitle)
    return "\n".join(lines)


def build_report(results, top10, dynamic30, macro, news, market_info, unavailable=0,
                 btc_regime=None, breadth=None):
    # CRITICAL: report order is a product requirement, not a performance rank.
    # Never sort the full result set by confidence here.
    results = _ordered_report_results(results, top10, dynamic30)

    liq = market_liquidity_index(results)
    dt = now_tehran()

    priority_success = [r for r in results if r.get("coin") in set(top10)]
    dynamic_success = [r for r in results if r.get("coin") in set(dynamic30)]
    static_success = [
        r for r in results
        if r.get("coin") not in set(top10) and r.get("coin") not in set(dynamic30)
    ]

    header = [
        f"🤖 {VERSION} — SNIPER",
        "━━━━━━━━━━━━━━━━━━",
        f"{shamsi(dt)}  {dt.strftime('%H:%M')} 🇮🇷",
        "Timeframe: 30M / 1H / 4H / 1D / 1W / 1M",
        "",
        f"💧 MARKET LIQUIDITY INDEX: {liq:.1f}/100",
        f"🧭 DXY: {fmt(macro.get('DXY'))} | USD liquidity proxy",
        f"📰 NEWS: {news['bias']} | {news['impact']}",
        "",
        "📡 RADAR ORDER",
        "1️⃣ ATLAS TOP 10 PRIORITY → 2️⃣ DYNAMIC TOP 30 → 3️⃣ ATLAS STATIC RADAR",
        f"Priority Top 10: {len(top10)} | Available: {len(priority_success)}",
        f"Dynamic Top 30: {len(dynamic30)} | Available: {len(dynamic_success)} | refreshed now",
        f"ATLAS Static Radar: {len(ATLAS_STATIC)} | Available: {len(static_success)}",
        f"Total scanned: {len(results)}",
        f"Unavailable/failed: {unavailable}",
        "",
    ]

    blocks = []

    # These explicit section headers guarantee that Telegram chunking can
    # never silently mix Dynamic-30 before the Priority-10 assets.
    blocks.append(_report_section_header(
        "1️⃣ ATLAS TOP 10 PRIORITY",
        len(top10), len(priority_success),
        "BTC → ETH → BNB → XRP → SOL → TRX → HYPE → DOGE → ADA → MATIC",
    ))
    blocks.extend(asset_block(x) for x in priority_success)

    blocks.append(_report_section_header(
        "2️⃣ DYNAMIC TOP 30",
        len(dynamic30), len(dynamic_success),
        "Current CoinGecko market-cap ranking, refreshed every run; membership may change daily.",
    ))
    blocks.extend(asset_block(x) for x in dynamic_success)

    blocks.append(_report_section_header(
        "3️⃣ ATLAS STATIC RADAR",
        len(static_success), len(static_success),
        "Persistent surveillance assets not already present in sections 1 or 2.",
    ))
    blocks.extend(asset_block(x) for x in static_success)

    footer = [
        "━━━━━━━━━━━━━━━━━━",
        "🛡️ ATLAS DATA ENGINE",
        f"Assets attempted: {len(results) + unavailable}",
        f"Successful: {len(results)} | Unavailable: {unavailable}",
        f"Success rate: {(len(results) / max(len(results) + unavailable, 1) * 100):.1f}%",
        "Only CLOSED candles used for signals; incomplete candles excluded",
        "Stablecoins excluded",
        "Data conflict >3% = NO TRADE",
        f"Risk/trade: {RISK_PER_TRADE:.2f}%",
        f"Max portfolio open risk: {MAX_PORTFOLIO_RISK:.2f}%",
        "No automatic orders.",
        "",
        "🎯 ATLAS v10.1 HARDENED DECISION ENGINE + SELF-HEALING + CLOSED-CANDLE ENGINE: ACTIVE",
        "",
        "⚠️ این گزارش تحلیلی است و سیگنال قطعی یا تضمین سود نیست. "
        "ATLAS در شرایط ابهام به‌جای حدس، معامله را متوقف می‌کند.",
    ]

    return "\n\n".join([
        "\n".join(header),
        "\n\n".join(blocks),
        market_intelligence_block(market_info),
        market_summary(results, macro, news),
        atlas_conclusion(results),
        atlas_decision_board(
            results,
            btc_regime or {"regime": "UNKNOWN", "reason": ""},
            breadth or {"state": "UNKNOWN", "score": 50.0, "samples": 0},
        ),
        "\n".join(footer),
    ])


# ============================================================
# CONTEXT PERSISTENCE
# ============================================================

def save_context(macro, news, liquidity, market_info=None):
    STORE.insert(
        "atlas_market_context",
        {
            "timestamp": now_utc().isoformat(),
            "timeframe": "4h",
            "fear_greed": (market_info or {}).get("fear_greed"),
            "fear_greed_label": (market_info or {}).get("fear_greed_label"),
            "btc_dominance": (market_info or {}).get("btc_dominance"),
            "btc_funding": None,
            "btc_open_interest": None,
            "news_bias": news["bias"],
            "news_items": news["items"],
            "dxy": macro.get("DXY"),
            "liquidity_score": liquidity,
            "gold": macro.get("GOLD"),
            "silver": macro.get("SILVER"),
            "copper": macro.get("COPPER"),
            "wti": macro.get("WTI"),
            "brent": macro.get("BRENT"),
            "market_summary": news["bias"],
            "eth_dominance": (market_info or {}).get("eth_dominance"),
            "altcoin_dominance": (market_info or {}).get("altcoin_dominance"),
            "stablecoin_dominance": (market_info or {}).get("stablecoin_dominance"),
            "global_market_cap": (market_info or {}).get("market_cap"),
            "global_volume_24h": (market_info or {}).get("volume_24h"),
            "global_market_change_24h": (market_info or {}).get("market_change_24h"),
            "global_volume_change_24h": (market_info or {}).get("volume_change_24h"),
        },
    )


def save_run(results, parts, macro, news, unavailable=0):
    STORE.insert(
        "atlas_runs",
        {
            "timestamp": now_utc().isoformat(),
            "model_version": VERSION,
            "assets_scanned": len(results) + unavailable,
            "successful": len(results),
            "unavailable": unavailable,
            "signals_sent": sum(
                1 for x in results
                if x["action"] in ("BUY CONFIRMATION", "SELL CONFIRMATION")
            ),
            "telegram_parts": parts,
            "market_liquidity": market_liquidity_index(results),
            "dxy": macro.get("DXY"),
            "news_bias": news["bias"],
            "notes": "v10 human-like decision engine: regime + breadth + entry/risk quality + R/R + signal memory + closed-candle MTF",
        },
    )


# ============================================================
# MAIN
# ============================================================

def report():
    init_sqlite()
    evaluate_open_outcomes()
    universe, top10, dynamic30 = build_universe()

    # Governance: backtest MUST pass before self-healing can change weights.
    backtest_ok, bt = mandatory_backtest_gate(universe)
    if backtest_ok:
        self_diagnostic()
    else:
        append_changelog("SELF_HEALING", None, None,
                         "Model adaptation frozen because mandatory backtest gate failed", bt)

    weights = get_weights()
    news = news_feed()
    macro = macro_snapshot()
    market_info = global_market_intelligence()
    results = []
    unavailable = 0
    for coin in universe:
        try:
            r = analyze_coin(coin, news, weights)
            if r:
                results.append(r)
        except Exception as e:
            unavailable += 1
            append_changelog("ASSET_ERROR", None, None, f"{coin}: {e}", {"traceback": traceback.format_exc()})
        time.sleep(REQUEST_SLEEP_SECONDS)

    # v9: market regime and breadth are calculated after the raw radar scan,
    # then the decision engine converts technical confirmations into actual
    # trade candidates. The existing 4-hour cadence is intentionally unchanged.
    btc_regime = btc_market_regime()
    breadth = market_breadth(results)
    results = apply_decision_engine(results, btc_regime, breadth)

    for r in results:
        # Only genuinely executable decisions become open trade signals.
        r["action"] = r.get("decision_state", r.get("action"))
        store_signal(r)
    text = build_report(results, top10, dynamic30, macro, news, market_info, unavailable, btc_regime, breadth)
    return text, results, macro, news, market_info, unavailable


def main():
    try:
        # Fail early and visibly if Telegram itself is unavailable.
        telegram_preflight()

        text, results, macro, news, market_info, unavailable = report()
        parts, sent, errors = send_report(text)

        save_context(
            macro,
            news,
            market_liquidity_index(results),
            market_info,
        )
        save_run(results, parts, macro, news, unavailable)

        print(text)
        print("")
        print(
            f"{VERSION} sent: {sent} Telegram messages "
            f"across {parts} report parts; errors={len(errors)}"
        )

        if errors or sent == 0:
            raise RuntimeError(
                "Telegram delivery failed: " + "; ".join(errors or ["0 messages sent"])
            )
        return 0

    except Exception as e:
        tb = traceback.format_exc()
        append_changelog("FATAL", None, None, str(e), {"traceback": tb})
        print(f"{VERSION} ERROR: {e}")

        # If Telegram credentials are valid, send a compact diagnostic instead
        # of silently marking the GitHub Action successful.
        try:
            if TELEGRAM_TOKEN and (TELEGRAM_CHAT_ID or TELEGRAM_GROUP_CHAT_ID):
                alert = (
                    f"🚨 {VERSION} FAILED\n"
                    f"Reason: {str(e)[:900]}\n\n"
                    "Check the GitHub Actions log and changelog.txt."
                )
                for destination in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
                    if destination:
                        try:
                            telegram_send_one(destination, alert)
                        except Exception as te:
                            print(f"Telegram error alert failed for {destination}: {te}")
        except Exception:
            pass
        # IMPORTANT: return non-zero so GitHub Actions shows the real failure.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
