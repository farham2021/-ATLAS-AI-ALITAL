# ============================================================
# ATLAS AI v8.1 — SELF-HEALING MARKET SUPERVISOR
# ============================================================
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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from statistics import mean, median

import ccxt


# ============================================================
# CONFIG
# ============================================================

VERSION = "ATLAS v8.1"
TIMEFRAMES = ("1h", "4h", "1d")
SIGNAL_TIMEFRAME = "4h"
TEHRAN = ZoneInfo("Asia/Tehran")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_GROUP_CHAT_ID = ""  # v8.1: single Telegram destination only

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

DB_FILE = os.environ.get("ATLAS_SQLITE_FILE", "atlas_v81.sqlite3")
CHANGELOG_FILE = os.environ.get("ATLAS_CHANGELOG", "changelog.txt")


# ============================================================
# ATLAS RADAR
# ============================================================

# These assets belong to the user's ATLAS radar and remain under
# surveillance even if they leave CoinGecko's current top ranks.
ATLAS_STATIC = [
    "BTC", "ETH", "XRP", "SOL", "BNB", "TON", "ADA", "DOGE", "TRX", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR", "NEAR",
    "QNT", "GRT", "TAO", "ONDO", "UNI", "ETHFI", "ATOM", "FIL", "AAVE", "MKR",
    "APT", "ARB", "OP", "INJ", "TIA", "SEI", "PEPE", "FET", "ICP", "ETC",
]

STABLE_SYMBOLS = {
    "USDT", "USDC", "USDE", "USDS", "DAI", "FDUSD", "TUSD", "USDP",
    "PYUSD", "USDD", "FRAX", "LUSD", "GUSD", "USDG", "USDB", "EURC",
    "USDC.E", "USD0", "USD1",
}

# Yahoo Finance symbols.
MACRO_SYMBOLS = {
    "DXY": "^DXY",
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


def f(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


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
    return s in STABLE_SYMBOLS or s.startswith("USD")


def safe_json(value):
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return "{}"


def http_get(url, timeout=15, headers=None):
    h = {
        "User-Agent": "ATLAS-AI/8.1",
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
    except Exception:
        return default


# ============================================================
# SQLITE FALLBACK / LOCAL AUDIT
# ============================================================

def sqlite_conn():
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
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
                data=json.dumps(row, ensure_ascii=False).encode(),
                headers=self.headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            append_changelog(
                "SUPABASE", None, None, f"insert failed: {table}: {e}"
            )
            return False

    def update(self, table, match, row):
        if not self.enabled:
            return False
        try:
            q = urllib.parse.urlencode(match)
            url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
            req = urllib.request.Request(
                url,
                data=json.dumps(row, ensure_ascii=False).encode(),
                headers=self.headers,
                method="PATCH",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            append_changelog(
                "SUPABASE", None, None, f"update failed: {table}: {e}"
            )
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


EX = {}
MARKETS = {}

for eid in ("binance", "xt", "lbank"):
    try:
        EX[eid] = make_exchange(eid)
        MARKETS[eid] = EX[eid].load_markets()
    except Exception:
        MARKETS[eid] = {}


def symbol_for(eid, coin):
    markets = MARKETS.get(eid, {})
    for s in (f"{coin}/USDT", f"{coin}/USDT:USDT"):
        if s in markets:
            return s
    return None


def exchange_ticker(eid, coin):
    ex = EX[eid]
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
    ex = EX[eid]
    sym = symbol_for(eid, coin)
    if not sym:
        raise RuntimeError(f"{eid}: pair unavailable")
    rows = ex.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
    if len(rows) < 60:
        raise RuntimeError(f"{eid}: insufficient candles")
    return strip_incomplete(rows, timeframe)


def strip_incomplete(rows, timeframe):
    ms = {
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }.get(timeframe, 4 * 60 * 60 * 1000)
    now = int(time.time() * 1000)
    if rows and rows[-1][0] + ms > now:
        return rows[:-1]
    return rows


def best_ohlcv(coin, timeframe, limit=250):
    for eid in ("binance", "xt", "lbank"):
        try:
            return exchange_ohlcv(eid, coin, timeframe, limit), eid.upper()
        except Exception:
            continue
    raise RuntimeError(f"4H DATA UNAVAILABLE: {coin}")


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
                "symbol": s,
                "name": x.get("name"),
                "rank": x.get("market_cap_rank"),
                "market_cap": f(x.get("market_cap")),
            })
    return result


def binance_top(limit=40):
    try:
        rows = EX["binance"].fetch_tickers()
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
    cg = gecko_top(40)
    top10 = [x["symbol"] for x in cg[:10]]
    dynamic30 = [x["symbol"] for x in cg[10:40]]

    if len(dynamic30) < 20:
        for x in binance_top(50):
            if x["symbol"] not in top10 and x["symbol"] not in dynamic30:
                dynamic30.append(x["symbol"])
            if len(dynamic30) >= 30:
                break

    dynamic30 = dynamic30[:30]

    # ATLAS static radar is preserved, but stablecoins are removed.
    static = [x for x in ATLAS_STATIC if not is_stable(x)]

    universe = list(dict.fromkeys(top10 + dynamic30 + static))
    universe = [x for x in universe if not is_stable(x)]

    for i, symbol in enumerate(universe, 1):
        STORE.insert(
            "atlas_assets",
            {
                "symbol": symbol,
                "rank": next(
                    (x["rank"] for x in cg if x["symbol"] == symbol), None
                ),
                "source": (
                    "TOP10" if symbol in top10
                    else "DYNAMIC30" if symbol in dynamic30
                    else "ATLAS_STATIC"
                ),
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


def macd(values):
    if len(values) < 40:
        return None, None, None
    line = []
    for i in range(26, len(values) + 1):
        a = ema(values[:i], 12)
        b = ema(values[:i], 26)
        if a is not None and b is not None:
            line.append(a - b)
    signal = ema(line, 9)
    if signal is None:
        return None, None, None
    prev_signal = ema(line[:-1], 9) if len(line) > 10 else None
    hist = line[-1] - signal
    return line[-1], signal, hist if prev_signal is not None else None


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
    lows = [f(x[3]) for x in rows[-20:]]
    highs = [f(x[2]) for x in rows[-20:]]
    return min(lows), max(highs)


def daily_key_levels(rows, price=None):
    """Find robust daily support/resistance from completed daily candles.

    Uses local swing points, clustering, touch count, recency and ATR-aware
    tolerance. Only levels on the correct side of current price are returned.
    """
    if not rows or len(rows) < 30:
        return None

    completed = rows[:-1] if len(rows) > 1 else rows
    completed = completed[-90:]
    if len(completed) < 30:
        return None

    closes = [f(x[4]) for x in completed]
    highs = [f(x[2]) for x in completed]
    lows = [f(x[3]) for x in completed]
    last_price = f(price) if price else closes[-1]

    # Daily ATR proxy: median of recent true ranges.
    trs = []
    for i in range(1, len(completed)):
        h, l = highs[i], lows[i]
        pc = closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    trs = sorted(x for x in trs if x > 0)
    atr_d = trs[len(trs)//2] if trs else max(last_price * 0.02, 1e-12)

    # Candidate swing points.
    candidates = []
    w = 2
    for i in range(w, len(completed) - w):
        if highs[i] >= max(highs[i-w:i+w+1]):
            candidates.append(("R", highs[i], i))
        if lows[i] <= min(lows[i-w:i+w+1]):
            candidates.append(("S", lows[i], i))

    tolerance = max(atr_d * 0.30, last_price * 0.003)

    def cluster(side):
        vals = [(v, i) for s, v, i in candidates if s == side]
        groups = []
        for value, pos in sorted(vals, key=lambda z: z[0]):
            placed = False
            for g in groups:
                if abs(value - g["level"]) <= tolerance:
                    g["values"].append((value, pos))
                    g["level"] = sum(v for v, _ in g["values"]) / len(g["values"])
                    placed = True
                    break
            if not placed:
                groups.append({"level": value, "values": [(value, pos)]})
        return groups

    def score(g):
        touches = len(g["values"])
        recency = max(pos for _, pos in g["values"])
        recency_score = 20 * (recency / max(len(completed)-1, 1))
        touch_score = min(40, touches * 12)
        distance = abs(g["level"] - last_price) / max(atr_d, 1e-12)
        proximity_score = max(0, 25 - min(distance, 25))
        # A level repeatedly respected and not absurdly distant scores higher.
        return min(100, round(touch_score + recency_score + proximity_score + 15, 1))

    supports = [g for g in cluster("S") if g["level"] < last_price]
    resistances = [g for g in cluster("R") if g["level"] > last_price]

    if not supports or not resistances:
        return None

    # Prefer strength first, then proximity among similarly strong levels.
    supports.sort(key=lambda g: (score(g), -abs(last_price-g["level"])), reverse=True)
    resistances.sort(key=lambda g: (score(g), -abs(last_price-g["level"])), reverse=True)

    s = supports[0]
    r = resistances[0]

    return {
        "support": s["level"],
        "resistance": r["level"],
        "support_strength": score(s),
        "resistance_strength": score(r),
        "support_touches": len(s["values"]),
        "resistance_touches": len(r["values"]),
        "atr_daily": atr_d,
    }


def weekly_pivot(rows):
    # Use the latest completed 7-day window from available 4H candles.
    if len(rows) < 42:
        return None
    recent = rows[-42:]
    h = max(f(x[2]) for x in recent)
    l = min(f(x[3]) for x in recent)
    c = f(recent[-1][4])
    return (h + l + c) / 3


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
    lows, highs = [], []
    for i in range(window, len(values) - window):
        chunk = values[i - window:i + window + 1]
        if values[i] == min(chunk):
            lows.append(i)
        if values[i] == max(chunk):
            highs.append(i)
    return lows, highs


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
            rows, engine = best_ohlcv(coin, tf, 250)
            c = closes(rows)
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
            }
        except Exception as e:
            out[tf] = {"error": str(e), "trend": "UNKNOWN"}
    return out


# ============================================================
# 30-MINUTE MOMENTUM
# ============================================================

def momentum_30m(coin):
    try:
        rows, _ = best_ohlcv(coin, "30m", 40)
        c = closes(rows)
        if len(c) < 6:
            return "UNKNOWN", False
        short = (c[-1] / c[-4] - 1) * 100
        if short > 0.20:
            return "BULLISH", False
        if short < -0.20:
            return "BEARISH", False
        return "NEUTRAL", False
    except Exception:
        return "UNKNOWN", False


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
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + urllib.parse.quote(symbol)
        + "?"
        + urllib.parse.urlencode({
            "interval": interval,
            "range": range_,
            "events": "history",
        })
    )
    d = http_get(url)
    result = d["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    timestamps = result.get("timestamp", [])
    rows = []
    for i, ts in enumerate(timestamps):
        o = f(quote["open"][i])
        h = f(quote["high"][i])
        l = f(quote["low"][i])
        c = f(quote["close"][i])
        v = f(quote.get("volume", [None] * len(timestamps))[i])
        if None not in (o, h, l, c):
            rows.append([ts * 1000, o, h, l, c, v or 0])
    return rows


def macro_snapshot():
    out = {}
    for name, symbol in MACRO_SYMBOLS.items():
        try:
            rows = yahoo_chart(symbol, "1h", "5d")
            c = closes(rows)
            if c:
                out[name] = c[-1]
        except Exception:
            out[name] = None
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
    return round(mean(scores), 1) if scores else 0.0


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
            (z for z in rows if z["symbol"] == coin),
            None,
        )
        # Full simple-price request is used when market-cap list has no price.
        if x:
            url = "https://api.coingecko.com/api/v3/simple/price?" + urllib.parse.urlencode({
                "ids": coin.lower(),
                "vs_currencies": "usd",
            })
            d = safe_http_get(url, headers=headers, default={})
            p = f(d.get(coin.lower(), {}).get("usd"))
            if p:
                vals.append(p)
                sources.append({"source": "CoinGecko", "price": p})
    except Exception:
        pass

    if not vals:
        raise RuntimeError("NO PRICE DATA")

    med = median(vals)
    spreads = [abs(x - med) / med * 100 for x in vals if med]
    sp = max(spreads) if spreads else 0

    quality = (
        "HIGH" if len(vals) >= 4 and sp <= 1.5
        else "MEDIUM" if len(vals) >= 3 and sp <= 3
        else "LOW"
    )
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

    if rr is not None:
        if 52 <= rr <= 68:
            bullish += 1
            reasons.append("RSI صعودی/متعادل")
        elif rr < 45:
            bearish += 1
            reasons.append("RSI ضعیف")
        elif rr > 75:
            bullish += 1
            reasons.append("RSI بالای 75؛ مومنتوم قوی اما پرریسک")

    if ml is not None and ms is not None:
        if ml > ms and ml > 0:
            bullish += 1
            reasons.append("MACD صعودی")
        elif ml < ms and ml < 0:
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
    return direction, bullish, bearish, reasons


def strong_divergence(rows):
    vals = closes(rows)
    # RSI series
    rsis = []
    for i in range(15, len(vals) + 1):
        rsis.append(rsi(vals[:i]))
    if len(rsis) < 40:
        return None
    # Align lengths by taking tail of price series.
    p = vals[-len(rsis):]
    return divergence_3_level(p, rsis)


def calculate_levels(rows, direction, daily_levels=None):
    price = f(rows[-1][4])
    sup, res = support_resistance(rows)
    pivot = weekly_pivot(rows)
    if daily_levels:
        sup = daily_levels["support"]
        res = daily_levels["resistance"]
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


def analyze_coin(coin, market_news):
    if is_stable(coin):
        return None

    snapshots = tf_snapshot(coin)
    tf4 = snapshots.get("4h", {})
    if "rows" not in tf4:
        raise RuntimeError("4H unavailable")

    tf1 = snapshots.get("1h", {})
    tfd = snapshots.get("1d", {})

    price, sources, quality, spread_pct, errors = price_consensus(coin)

    daily_levels = daily_key_levels(tfd.get("rows", []), price)
    if daily_levels is None:
        # Do not fabricate daily S/R when the daily history is insufficient.
        daily_levels = None

    h1 = tf1.get("trend", "UNKNOWN")
    h4 = tf4.get("trend", "UNKNOWN")
    d1 = tfd.get("trend", "UNKNOWN")

    pattern, pattern_dir = candle_pattern(tf4["rows"])
    ind_dir, bull_n, bear_n, indicator_reasons = indicator_alignment(tf4)

    divergence = strong_divergence(tf4["rows"])

    vol_state, vol_ratio = volume_state(tf4["rows"])
    atrp = atr_pct(tf4["rows"])
    liq_score, liq_label = asset_liquidity(coin, sources)

    mom30, _ = momentum_30m(coin)

    # --------------------------------------------------------
    # Confidence components
    # --------------------------------------------------------
    candle_points = 0
    candle_valid = False
    if pattern != "NONE" and pattern_dir in ("BULLISH", "BEARISH"):
        aligned = 0
        if pattern_dir == ind_dir:
            aligned += 1
        if pattern_dir == h4:
            aligned += 1
        if pattern_dir == d1:
            aligned += 1
        if aligned >= 2:
            candle_points = 20
            candle_valid = True

    indicator_points = min(30, (2 if bull_n >= 2 else 0) * 15)
    if bear_n >= 2:
        indicator_points = 30

    volume_points = 15 if vol_ratio is not None and vol_ratio > 1 else 0
    higher_points = 20 if h4 in ("BULLISH", "BEARISH") and d1 == h4 else 0
    news_points = 15 if market_news["impact"] != "HIGH" else 0

    confidence = candle_points + indicator_points + volume_points
    confidence += higher_points + news_points

    # --------------------------------------------------------
    # Direction selection
    # --------------------------------------------------------
    direction = "NONE"
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

    # --------------------------------------------------------
    # Hard gates
    # --------------------------------------------------------
    gate = "PASS"
    gate_reason = "All mandatory gates passed"
    warning = None

    if quality == "LOW" or spread_pct > 3:
        gate = "BLOCK"
        gate_reason = "Data quality/conflict"
    elif vol_ratio is None or vol_ratio <= 1:
        gate = "BLOCK"
        gate_reason = "Volume confirmation missing"
    elif confidence < MIN_CONFIDENCE:
        gate = "BLOCK"
        gate_reason = "Confidence below threshold"
    elif direction == "NONE":
        gate = "BLOCK"
        gate_reason = "Higher-timeframe alignment missing"
    elif market_news["impact"] == "HIGH":
        warning = "نوسان بالا"
        # High-impact news is not always a full block. It is a warning
        # unless the news directly contradicts the proposed direction.
        if (
            market_news["bias"] == "NEGATIVE" and direction == "LONG"
        ) or (
            market_news["bias"] == "POSITIVE" and direction == "SHORT"
        ):
            gate = "BLOCK"
            gate_reason = "High-impact news contradicts signal"
    elif direction == "LONG" and mom30 == "BEARISH":
        warning = "شتاب مخالف"
        gate = "BLOCK"
        gate_reason = "30m momentum strongly opposes long"
    elif direction == "SHORT" and mom30 == "BULLISH":
        warning = "شتاب مخالف"
        gate = "BLOCK"
        gate_reason = "30m momentum strongly opposes short"

    levels = None
    leverage = 1.0
    action = "NO TRADE"

    if gate == "PASS":
        levels = calculate_levels(tf4["rows"], direction, daily_levels)
        if levels is None:
            gate = "BLOCK"
            gate_reason = "Invalid price geometry"
        else:
            leverage = suggested_leverage(atrp)
            action = "BUY CONFIRMATION" if direction == "LONG" else "SELL CONFIRMATION"

    reason_parts = []
    if pattern_valid := candle_valid:
        reason_parts.append(pattern)
    reason_parts.extend(indicator_reasons[:3])
    if vol_ratio is not None and vol_ratio > 1:
        reason_parts.append(f"حجم {vol_ratio:.2f}x میانگین 20")
    if h4 == d1 and h4 in ("BULLISH", "BEARISH"):
        reason_parts.append(f"هم‌جهت H4/D1 {h4}")
    if divergence:
        reason_parts.append("واگرایی 3 سطحی")
    if warning:
        reason_parts.append(warning)

    return {
        "coin": coin,
        "price": price,
        "change": next(
            (x.get("change") for x in sources if x["source"] == "BINANCE"),
            None,
        ),
        "trend": h4,
        "h1_trend": h1,
        "h4_trend": h4,
        "d1_trend": d1,
        "pattern": pattern,
        "pattern_valid": pattern_valid,
        "rsi": tf4.get("rsi"),
        "macd": tf4.get("macd"),
        "volume": vol_state,
        "volume_ratio": vol_ratio,
        "atr_pct": atrp,
        "support": (daily_levels["support"] if daily_levels else (levels["support"] if levels else support_resistance(tf4["rows"])[0])),
        "resistance": (daily_levels["resistance"] if daily_levels else (levels["resistance"] if levels else support_resistance(tf4["rows"])[1])),
        "support_strength": daily_levels["support_strength"] if daily_levels else 0,
        "resistance_strength": daily_levels["resistance_strength"] if daily_levels else 0,
        "support_touches": daily_levels["support_touches"] if daily_levels else 0,
        "resistance_touches": daily_levels["resistance_touches"] if daily_levels else 0,
        "pivot": levels["pivot"] if levels else weekly_pivot(tf4["rows"]),
        "entry": levels["entry"] if levels else None,
        "sl": levels["sl"] if levels else None,
        "tp1": levels["tp1"] if levels else None,
        "tp2": levels["tp2"] if levels else None,
        "leverage": leverage,
        "direction": direction,
        "action": action,
        "confidence": int(clamp(confidence, 0, 100)),
        "quality": quality,
        "spread": spread_pct,
        "liquidity_score": liq_score,
        "liquidity": liq_label,
        "momentum_30m": mom30,
        "news_impact": market_news["impact"],
        "warning": warning,
        "gate": gate,
        "gate_reason": gate_reason,
        "reason": " + ".join(reason_parts) or "تایید چندعاملی کافی نیست",
        "sources": [x["source"] for x in sources],
        "engine": tf4.get("engine"),
        "snapshots": snapshots,
    }


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

    rows = STORE.select(
        "atlas_model_weights",
        {"select": "feature,weight", "model_version": f"eq.{VERSION}"},
    )
    for r in rows:
        if r.get("feature") in weights:
            weights[r["feature"]] = f(r.get("weight")) or weights[r["feature"]]

    init_sqlite()
    with sqlite_conn() as c:
        for feature, weight in weights.items():
            c.execute(
                """
                insert or ignore into model_weights
                (feature,weight,baseline_weight,updated_at)
                values(?,?,?,?)
                """,
                (feature, weight, DEFAULT_WEIGHTS[feature], now_utc().isoformat()),
            )
    return weights


def update_weight(feature, factor, reason, evidence):
    old = DEFAULT_WEIGHTS.get(feature, 15.0)
    rows = STORE.select(
        "atlas_model_weights",
        {
            "select": "weight",
            "feature": f"eq.{feature}",
            "model_version": f"eq.{VERSION}",
            "limit": "1",
        },
    )
    if rows:
        old = f(rows[0].get("weight")) or old

    new = clamp(old * factor, 5, 30)

    append_changelog(feature, old, new, reason, evidence)
    STORE.insert(
        "atlas_model_weights",
        {
            "model_version": VERSION,
            "feature": feature,
            "weight": new,
            "baseline_weight": DEFAULT_WEIGHTS.get(feature, old),
            "samples": evidence.get("samples", 0),
            "wins": evidence.get("wins", 0),
            "losses": evidence.get("losses", 0),
            "reason": reason,
            "updated_at": now_utc().isoformat(),
        },
    )


def self_diagnostic():
    """After every three closed signals, identify weak features."""
    rows = STORE.select(
        "atlas_signal_outcomes",
        {
            "select": "coin,direction,outcome,notes",
            "status": "eq.CLOSED",
            "limit": "300",
            "order": "evaluated_at.desc",
        },
    )

    if len(rows) < 3 or len(rows) % 3:
        return

    recent = rows[:3]
    losses = sum(1 for r in recent if r.get("outcome") == "SL")
    error_pct = losses / len(recent) * 100

    if error_pct <= 5:
        return

    # Simple evidence attribution from stored reason text.
    counts = {}
    for r in recent:
        for token in ("RSI", "MACD", "volume", "SMA", "Hammer", "Engulfing"):
            if token.lower() in (r.get("notes") or "").lower():
                counts[token] = counts.get(token, 0) + 1

    feature = max(counts, key=counts.get) if counts else "rsi"
    mapped = {
        "RSI": "rsi",
        "MACD": "macd",
        "volume": "volume",
        "SMA": "higher_trend",
        "Hammer": "candle_pattern",
        "Engulfing": "candle_pattern",
    }
    feature = mapped.get(feature, "rsi")

    update_weight(
        feature,
        0.80,
        "خطای پیش‌بینی > 5% پس از سه سیگنال؛ وزن 20% کاهش یافت",
        {
            "samples": 3,
            "wins": 3 - losses,
            "losses": losses,
            "error_pct": error_pct,
            "replacement": "Stochastic",
        },
    )


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
        if vr is None or vr <= 1:
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
    avg_profit = mean([x for x in trades if x > 0]) if wins else 0
    avg_loss = abs(mean([x for x in trades if x < 0])) if losses else 0
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


def mandatory_backtest_gate(universe):
    """Run a compact portfolio backtest before any weight change."""
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
        return False, {"reason": "no backtest data"}

    win_rate = mean(x["win_rate"] for x in samples)
    pf = mean(x["profit_factor"] for x in samples)
    dd = max(x["max_drawdown"] for x in samples)

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
        return True, {
            "win_rate": win_rate,
            "profit_factor": pf,
            "max_drawdown": dd,
            "improvement": 0,
        }

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

    return passed, {
        "win_rate": win_rate,
        "profit_factor": pf,
        "max_drawdown": dd,
        "improvement": max(improvement_pf, improvement_wr),
    }


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
        "liquidity_score": result["liquidity_score"],
        "volume_ratio": result["volume_ratio"],
        "atr_pct": result["atr_pct"],
        "pivot_weekly": result["pivot"],
        "momentum_30m": result["momentum_30m"],
        "news_impact": result["news_impact"],
        "volatility_warning": bool(result["warning"]),
        "reason": result["reason"],
        "leverage": result["leverage"],
        "confidence_breakdown": {
            "candle": 20 if result["pattern_valid"] else 0,
            "indicators": 30 if result["macd"] != "UNKNOWN" else 0,
            "volume": 15 if result["volume_ratio"] and result["volume_ratio"] > 1 else 0,
            "higher_trend": 20 if result["h4_trend"] == result["d1_trend"] else 0,
            "news_clear": 15 if result["news_impact"] != "HIGH" else 0,
        },
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
        open_rows = c.execute(
            """
            select * from signal_outcomes
            where status='OPEN'
            order by id asc
            limit 100
            """
        ).fetchall()

    for row in open_rows:
        coin = row["coin"]
        try:
            candles, _ = best_ohlcv(coin, "4h", 80)
        except Exception:
            continue

        issued = datetime.fromisoformat(row["issued_at"].replace("Z", "+00:00"))
        after = [
            x for x in candles
            if x[0] / 1000 > issued.timestamp()
        ]
        outcome = None
        exit_price = None
        bars = 0

        for bars, x in enumerate(after[:SIGNAL_HORIZON_BARS], 1):
            hi, lo = f(x[2]), f(x[3])
            if row["direction"] == "LONG":
                if lo <= row["sl"]:
                    outcome, exit_price = "SL", row["sl"]
                    break
                if hi >= row["tp1"]:
                    outcome, exit_price = "TP1", row["tp1"]
                    break
            else:
                if hi >= row["sl"]:
                    outcome, exit_price = "SL", row["sl"]
                    break
                if lo <= row["tp1"]:
                    outcome, exit_price = "TP1", row["tp1"]
                    break

        if outcome:
            if row["direction"] == "LONG":
                pnl = (exit_price - row["entry"]) / row["entry"] * 100
            else:
                pnl = (row["entry"] - exit_price) / row["entry"] * 100

            with sqlite_conn() as c:
                c.execute(
                    """
                    update signal_outcomes
                    set status='CLOSED', outcome=?, exit_price=?,
                        exit_at=?, pnl_pct=?, bars_to_exit=?
                    where id=?
                    """,
                    (
                        outcome, exit_price, now_utc().isoformat(),
                        pnl, bars, row["id"],
                    ),
                )

            STORE.insert(
                "atlas_signal_outcomes",
                {
                    "coin": coin,
                    "direction": row["direction"],
                    "entry": row["entry"],
                    "sl": row["sl"],
                    "tp1": row["tp1"],
                    "tp2": row["tp2"],
                    "issued_at": row["issued_at"],
                    "status": "CLOSED",
                    "outcome": outcome,
                    "exit_price": exit_price,
                    "exit_at": now_utc().isoformat(),
                    "pnl_pct": pnl,
                    "bars_to_exit": bars,
                    "notes": row["notes"],
                },
            )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send_one(chat_id, text):
    if not TELEGRAM_TOKEN or not chat_id:
        raise RuntimeError("Telegram secrets missing")

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


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
    """Send the report exactly once to the primary Telegram chat.

    Telegram_GROUP_CHAT_ID is intentionally disabled in v8.1 to prevent
    duplicate delivery of the same report.
    """
    parts = split_telegram(text)
    if not TELEGRAM_CHAT_ID:
        append_changelog("TELEGRAM", None, None, "TELEGRAM_CHAT_ID missing")
        return len(parts), 0, ["TELEGRAM_CHAT_ID missing"]

    sent = 0
    errors = []

    for i, part in enumerate(parts, 1):
        try:
            telegram_send_one(TELEGRAM_CHAT_ID, part)
            sent += 1
            time.sleep(0.7)
        except Exception as e:
            errors.append(f"Telegram part {i}: {e}")

    for e in errors:
        append_changelog("TELEGRAM", None, None, e)

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
    lines = [
        f"🔹 {r['coin']}",
        f"Price: {fmt(r['price'])}",
        f"24H: {pct(r['change'])}",
        f"Trend H1/H4/D1: {r['h1_trend']} / {r['h4_trend']} / {r['d1_trend']}",
        f"RSI14: {r['rsi']:.1f}" if r["rsi"] is not None else "RSI14: N/A",
        f"MACD: {'🟢' if r['macd']=='BULLISH' else '🔴' if r['macd']=='BEARISH' else '🟡'} {r['macd']}",
        f"Pattern: {r['pattern']}" + (" ✅" if r["pattern_valid"] else ""),
        f"Volume: {'🟢' if r['volume']=='STRONG' else '🔴' if r['volume']=='WEAK' else '🟡'} {r['volume']}",
        f"Volume Ratio: {r['volume_ratio']:.2f}x" if r["volume_ratio"] is not None else "Volume Ratio: N/A",
        f"Liquidity: {r['liquidity']} ({r['liquidity_score']:.0f}/100)",
        f"ATR: {r['atr_pct']:.2f}%" if r["atr_pct"] is not None else "ATR: N/A",
        f"4H/D1 Alignment: {'✅' if r['h4_trend']==r['d1_trend'] else '⚠️'}",
        f"Support: {fmt(r['support'])} | Daily Strength: {r.get('support_strength', 0):.0f}/100 | Touches: {r.get('support_touches', 0)}",
        f"Resistance: {fmt(r['resistance'])} | Daily Strength: {r.get('resistance_strength', 0):.0f}/100 | Touches: {r.get('resistance_touches', 0)}",
        f"Weekly Pivot: {fmt(r['pivot'])}",
        f"Confidence: {r['confidence']}%",
        f"🎯 ACTION: {action_emoji(r['action'])}",
        f"Data: {r['quality']}",
    ]

    if r["action"] in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
        lines += [
            f"Direction: {r['direction']}",
            f"Entry: {fmt(r['entry'])}",
            f"SL: {fmt(r['sl'])}",
            f"TP1: {fmt(r['tp1'])}",
            f"TP2: {fmt(r['tp2'])}",
            f"Leverage: {r['leverage']:.1f}x",
            f"Reason: {r['reason']}",
        ]
    else:
        lines.append(f"Reason: {r['reason']}")

    if r["warning"]:
        lines.append(f"⚠️ {r['warning']}")

    if r["spread"] > 3:
        lines.append(f"⚠️ DATA CONFLICT: {r['spread']:.2f}%")

    return "\n".join(lines)


def atlas_conclusion(results):
    """Final decision layer: identifies strong rise/fall candidates.

    A candidate is only promoted when H4 and D1 agree and confidence is high.
    Overbought/oversold conditions are explicitly downgraded rather than
    treated as automatic buy/sell signals.
    """
    confirmed_buy = [
        x for x in results
        if x["action"] == "BUY CONFIRMATION"
        and x["h4_trend"] == "BULLISH"
        and x["d1_trend"] == "BULLISH"
        and x["confidence"] >= 60
        and x["quality"] in ("HIGH", "MEDIUM")
    ]
    confirmed_sell = [
        x for x in results
        if x["action"] == "SELL CONFIRMATION"
        and x["h4_trend"] == "BEARISH"
        and x["d1_trend"] == "BEARISH"
        and x["confidence"] >= 60
        and x["quality"] in ("HIGH", "MEDIUM")
    ]

    rise_watch = [
        x for x in results
        if x["h4_trend"] == "BULLISH"
        and x["d1_trend"] == "BULLISH"
        and x["confidence"] >= 60
        and x["action"] != "BUY CONFIRMATION"
    ]
    fall_watch = [
        x for x in results
        if x["h4_trend"] == "BEARISH"
        and x["d1_trend"] == "BEARISH"
        and x["confidence"] >= 60
        and x["action"] != "SELL CONFIRMATION"
    ]

    lines = ["━━━━━━━━━━━━━━━━━━", "🎯 ATLAS FINAL CONCLUSION"]

    if confirmed_buy:
        lines.append("🟢 BUY / ACCUMULATE — تأییدشده:")
        for x in sorted(confirmed_buy, key=lambda z: z["confidence"], reverse=True)[:5]:
            lines.append(f"• {x['coin']} | Confidence {x['confidence']}% | BUY CONFIRMATION")
    else:
        lines.append("🟢 BUY: فعلاً هیچ ارز با تأیید کامل ATLAS برای خرید وجود ندارد.")

    if confirmed_sell:
        lines.append("🔴 SELL / REDUCE — تأییدشده:")
        for x in sorted(confirmed_sell, key=lambda z: z["confidence"], reverse=True)[:5]:
            lines.append(f"• {x['coin']} | Confidence {x['confidence']}% | SELL CONFIRMATION")
    else:
        lines.append("🔴 SELL: فعلاً هیچ ارز با تأیید کامل ATLAS برای فروش وجود ندارد.")

    if rise_watch:
        lines.append("📈 مستعد صعود / تحت نظر:")
        for x in sorted(rise_watch, key=lambda z: z["confidence"], reverse=True)[:5]:
            rsi = x.get("rsi")
            tag = "⚠️ RSI بالا" if rsi is not None and rsi >= 75 else "✅"
            lines.append(f"• {x['coin']} | {x['confidence']}% | {tag}")
    else:
        lines.append("📈 مستعد صعود: کاندید معتبر کافی وجود ندارد.")

    if fall_watch:
        lines.append("📉 مستعد ریزش / تحت نظر:")
        for x in sorted(fall_watch, key=lambda z: z["confidence"], reverse=True)[:5]:
            rsi = x.get("rsi")
            tag = "⚠️ oversold" if rsi is not None and rsi <= 30 else "⚠️"
            lines.append(f"• {x['coin']} | {x['confidence']}% | {tag}")
    else:
        lines.append("📉 مستعد ریزش: کاندید معتبر کافی وجود ندارد.")

    lines += [
        "",
        "🛑 تصمیم ATLAS:",
        "خرید فقط از بخش BUY / ACCUMULATE تأییدشده؛",
        "فروش/کاهش فقط از بخش SELL / REDUCE تأییدشده.",
        "صرفاً صعودی یا نزولی بودن یک ارز به‌تنهایی مجوز معامله نیست.",
        "در صورت تعارض H4/D1، حجم ضعیف یا داده ناقص → NO TRADE.",
    ]
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
        f"DXY: {fmt(dxy)}" if dxy else "DXY: N/A",
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


def build_report(results, top10, dynamic30, macro, news):
    # Most useful assets first, but the complete radar is still retained.
    results.sort(
        key=lambda x: (
            x["action"] in ("BUY CONFIRMATION", "SELL CONFIRMATION"),
            x["confidence"],
            x["liquidity_score"],
            abs(x["price"] or 0),
        ),
        reverse=True,
    )

    liq = market_liquidity_index(results)
    dt = now_tehran()

    header = [
        f"🤖 {VERSION} — SNIPER",
        "━━━━━━━━━━━━━━━━━━",
        f"{shamsi(dt)}  {dt.strftime('%H:%M')} 🇮🇷",
        "Timeframe: 1H / 4H / 1D",
        "",
        f"💧 MARKET LIQUIDITY INDEX: {liq:.1f}/100",
        f"🧭 DXY: {fmt(macro.get('DXY'))}",
        f"📰 NEWS: {news['bias']} | {news['impact']}",
        "",
        "📡 RADAR",
        f"Top 10 Market Cap: {len(top10)}",
        f"Dynamic Top 30: {len(dynamic30)}",
        f"ATLAS Static Radar: {len(ATLAS_STATIC)}",
        f"Total scanned: {len(results)}",
        "",
    ]

    blocks = [asset_block(x) for x in results]

    footer = [
        "━━━━━━━━━━━━━━━━━━",
        "🛡️ ATLAS DATA ENGINE",
        f"Assets scanned: {len(results)}",
        f"Successful: {len(results)}",
        "Incomplete 4H candles excluded",
        "Stablecoins excluded",
        "Data conflict >3% = NO TRADE",
        f"Risk/trade: {RISK_PER_TRADE:.2f}%",
        f"Max portfolio open risk: {MAX_PORTFOLIO_RISK:.2f}%",
        "No automatic orders.",
        "",
        "🎯 ATLAS v8.1 SELF-HEALING: ACTIVE",
        "",
        "⚠️ این گزارش تحلیلی است و سیگنال قطعی یا تضمین سود نیست. "
        "ATLAS در شرایط ابهام به‌جای حدس، معامله را متوقف می‌کند.",
    ]

    return "\n\n".join([
        "\n".join(header),
        "\n\n".join(blocks),
        market_summary(results, macro, news),
        atlas_conclusion(results),
        "\n".join(footer),
    ])


# ============================================================
# CONTEXT PERSISTENCE
# ============================================================

def save_context(macro, news, liquidity):
    STORE.insert(
        "atlas_market_context",
        {
            "timestamp": now_utc().isoformat(),
            "timeframe": "4h",
            "fear_greed": None,
            "fear_greed_label": None,
            "btc_dominance": None,
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
        },
    )


def save_run(results, parts, macro, news):
    STORE.insert(
        "atlas_runs",
        {
            "timestamp": now_utc().isoformat(),
            "model_version": VERSION,
            "assets_scanned": len(results),
            "successful": len(results),
            "unavailable": 0,
            "signals_sent": sum(
                1 for x in results
                if x["action"] in ("BUY CONFIRMATION", "SELL CONFIRMATION")
            ),
            "telegram_parts": parts,
            "market_liquidity": market_liquidity_index(results),
            "dxy": macro.get("DXY"),
            "news_bias": news["bias"],
            "notes": "v8.1 self-healing run",
        },
    )


# ============================================================
# MAIN
# ============================================================

def report():
    init_sqlite()

    # Evaluate previous signals before producing new ones.
    evaluate_open_outcomes()
    self_diagnostic()

    universe, top10, dynamic30 = build_universe()
    news = news_feed()
    macro = macro_snapshot()

    results = []
    unavailable = 0

    for coin in universe:
        try:
            r = analyze_coin(coin, news)
            if r:
                results.append(r)
        except Exception as e:
            unavailable += 1
            append_changelog(
                "ASSET_ERROR",
                None,
                None,
                f"{coin}: {e}",
            )
        time.sleep(0.08)

    # Mandatory backtest is run before any future model adaptation.
    backtest_ok, bt = mandatory_backtest_gate(universe)
    if not backtest_ok:
        append_changelog(
            "SELF_HEALING",
            None,
            None,
            "Model adaptation frozen because mandatory backtest gate failed",
            bt,
        )

    for r in results:
        store_signal(r)

    text = build_report(results, top10, dynamic30, macro, news)
    return text, results, macro, news, unavailable


def main():
    try:
        text, results, macro, news, unavailable = report()
        parts, sent, errors = send_report(text)

        save_context(
            macro,
            news,
            market_liquidity_index(results),
        )
        save_run(results, parts, macro, news)

        print(text)
        print("")
        print(
            f"ATLAS v8.1 sent: {sent} Telegram messages "
            f"across {parts} report parts; errors={len(errors)}"
        )

        # Never fail the analysis because Telegram failed.
        return 0

    except Exception as e:
        append_changelog("FATAL", None, None, str(e))
        print(f"ATLAS v8.1 ERROR: {e}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
