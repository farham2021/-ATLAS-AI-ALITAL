"""ATLAS early-risk scan for crypto + Iran multi-asset snapshots.

The scanner uses closed 4h/1d candles and fresh Supabase snapshots. It does not
place trades or promise a 24-48h forecast. All new alerts are independently
deduped and recorded in the existing market-guard event ledger before Telegram.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from atlas_crossmarket_risk import (
    corroborating_context,
    crypto_context,
    market_risks,
    news_context,
    request_json,
)

UTC = dt.timezone.utc
TEHRAN = ZoneInfo("Asia/Tehran")
VERSION = "ATLAS_EARLY_RISK_V2"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID", "").strip()
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
CMC_API_KEY = os.getenv("CMC_API_KEY", "").strip()
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()
RISK_MODE = os.getenv("ATLAS_EARLY_RISK_MODE", "SHADOW").strip().upper()
ALERT_COOLDOWN_HOURS = max(1, int(os.getenv("ATLAS_RISK_ALERT_COOLDOWN_HOURS", "6")))
MAX_ALERTS_PER_CYCLE = max(1, min(20, int(os.getenv("ATLAS_RISK_ALERT_MAX_PER_CYCLE", "10"))))

PERSONAL_ASSETS = (
    "BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "DOGE", "ADA", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR",
    "NEAR", "ONDO", "TAO", "ZEC",
)
STABLECOINS = {
    "USDT", "USDC", "USDE", "USDS", "DAI", "FDUSD", "TUSD", "USDP",
    "PYUSD", "USDD", "FRAX", "LUSD", "GUSD", "USDG", "USDB", "EURC",
    "USD1", "RLUSD", "USTB", "USYC", "BUIDL", "USDY", "USDF", "BFUSD",
}
EXCHANGE_SPECS = (
    ("lbank", "lbank"), ("xt", "xt"), ("okx", "okx"),
    ("bybit", "bybit"), ("kucoin", "kucoin"), ("gateio", "gate"),
    ("bitget", "bitget"), ("mexc", "mexc"), ("kraken", "kraken"),
)
DATA_SYMBOL_ALIASES = {"MATIC": "POL", "RNDR": "RENDER"}
ACTION_RANK = {"NONE": 0, "WATCH": 1, "REDUCE": 2, "SELL": 3,
               "HIGH": 2, "CRITICAL": 3}


def _now():
    return dt.datetime.now(UTC)


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def timeframe_ms(timeframe):
    return {"4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000}.get(timeframe)


def expected_closed_open_ms(timeframe, now_ms=None):
    interval = timeframe_ms(timeframe)
    if interval is None:
        raise ValueError("unsupported timeframe")
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    return (now_ms // interval) * interval - interval


def normalize_ohlcv(rows, timeframe, now_ms=None):
    """Validate OHLCV and discard every candle that has not closed yet."""
    interval = timeframe_ms(timeframe)
    if interval is None:
        return []
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    parsed = {}
    for row in rows or []:
        try:
            if isinstance(row, dict):
                stamp = row.get("timestamp", row.get("ts", row.get("time")))
                values = [row[k] for k in ("open", "high", "low", "close", "volume")]
            else:
                stamp, *values = row[:6]
            stamp = int(float(stamp))
            if stamp < 10**12:
                stamp *= 1000
            opened, high, low, close, volume = map(float, values)
            if not all(math.isfinite(x) for x in (opened, high, low, close, volume)):
                continue
            if min(opened, high, low, close) <= 0 or volume < 0:
                continue
            if high < max(opened, close) or low > min(opened, close) or high < low:
                continue
            if stamp + interval > now_ms:
                continue
            parsed[stamp] = (stamp, opened, high, low, close, volume)
        except (TypeError, ValueError, KeyError, IndexError, OverflowError):
            continue
    return [parsed[key] for key in sorted(parsed)]


def score(rows4, rowsd, now_ms=None, providers=None, rank=None, context_flags=None):
    """Score a downside setup from closed candles only; confidence is evidence strength."""
    rows4 = normalize_ohlcv(rows4, "4h", now_ms)
    rowsd = normalize_ohlcv(rowsd, "1d", now_ms)
    if len(rows4) < 55 or len(rowsd) < 55:
        raise ValueError("insufficient closed candles")
    expected4 = expected_closed_open_ms("4h", now_ms)
    expectedd = expected_closed_open_ms("1d", now_ms)
    if rows4[-1][0] != expected4 or rowsd[-1][0] != expectedd:
        raise ValueError("stale closed-candle boundary")

    closes4 = [bar[4] for bar in rows4]
    volumes4 = [bar[5] for bar in rows4]
    lows4 = [bar[3] for bar in rows4]
    closesd = [bar[4] for bar in rowsd]
    last = closes4[-1]
    ma20_4 = sum(closes4[-20:]) / 20
    ma50_4 = sum(closes4[-50:]) / 50
    ma20_d = sum(closesd[-20:]) / 20
    support = min(lows4[-13:-1])
    volume_ratio = volumes4[-1] / max(sum(volumes4[-21:-1]) / 20, 1e-12)
    change24 = (last / closes4[-7] - 1) * 100
    technical = []
    if last < ma20_4:
        technical.append("قیمت بسته‌شدهٔ ۴ساعته زیر میانگین ۲۰")
    if ma20_4 < ma50_4:
        technical.append("میانگین ۲۰ زیر میانگین ۵۰ در ۴ساعته")
    if closesd[-1] < ma20_d:
        technical.append("بسته‌شدن روزانه زیر میانگین ۲۰")
    support_break = last < support
    if support_break:
        technical.append("شکست حمایت ۱۲ کندل بسته‌شده")
    selling_volume = volume_ratio >= 1.6 and closes4[-1] < closes4[-2]
    if selling_volume:
        technical.append("افزایش حجم روی کندل نزولی")
    momentum_loss = change24 <= -4.0
    if momentum_loss:
        technical.append("افت بیش از ۴٪ در شش کندل ۴ساعته")

    context = list(context_flags or [])[:2]
    tech_n = len(technical)
    if tech_n >= 5 and support_break and closesd[-1] < ma20_d and selling_volume and momentum_loss:
        decision = "SELL"
    elif (
        tech_n >= 4 and momentum_loss and (support_break or closesd[-1] < ma20_d)
    ) or (tech_n >= 3 and support_break and momentum_loss and context):
        decision = "REDUCE"
    elif support_break or momentum_loss or (tech_n >= 1 and context):
        decision = "WATCH"
    else:
        decision = "NONE"
    evidence_count = min(5, tech_n) + min(2, len(context))
    confidence = min(92, 50 + evidence_count * 7) if decision != "NONE" else 0
    return {
        "symbol": None, "asset_group": "کریپتو", "decision": decision,
        "confidence": confidence, "evidence_is_probability": False,
        "price": last, "price_unit": "USDT", "change_pct": round(change24, 3), "volume_ratio": round(volume_ratio, 3),
        "support": support, "technical_flags": technical, "context_flags": context,
        "flags": technical + context, "technical_count": tech_n,
        "last_closed_4h_ms": rows4[-1][0], "last_closed_1d_ms": rowsd[-1][0],
        "providers": providers or {}, "rank": rank,
    }


def stablecoin_risk(asset, now=None, max_age_minutes=30):
    """Depeg check from a current CG/CMC quote; no candle claim is made."""
    price = _num(asset.get("current_price"))
    if price is None or price <= 0:
        return None
    try:
        updated = dt.datetime.fromisoformat(str(asset.get("updated_at") or "").replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
    except ValueError:
        return None
    now = now or _now()
    age = (now.astimezone(UTC) - updated.astimezone(UTC)).total_seconds()
    if age < -300 or age > max_age_minutes * 60:
        return None
    deviation = (price - 1.0) * 100
    absolute = abs(deviation)
    if absolute < 0.5:
        return None
    decision = "SELL" if absolute >= 2.0 else "REDUCE" if absolute >= 1.0 else "WATCH"
    return {
        "symbol": asset["symbol"], "asset_group": "رمزارز پایدار",
        "decision": decision, "confidence": min(90, 60 + int(absolute * 8)),
        "evidence_is_probability": False, "price": price, "change_pct": _num(asset.get("change_24h")),
        "flags": [f"انحراف قیمت از ۱ دلار: {deviation:+.2f}%"],
        "timestamp": asset.get("updated_at"), "provider": asset.get("provider"),
        "reference_level": 1.0, "rank": asset.get("rank"),
    }


def fetch_universe():
    """Get a current Top-100 universe from CoinGecko, falling back to CMC."""
    rows = []
    provider = None
    cg_headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
    try:
        query = urllib.parse.urlencode({
            "vs_currency": "usd", "order": "market_cap_desc", "per_page": "100", "page": "1",
            "sparkline": "false", "price_change_percentage": "24h",
        })
        raw = request_json("https://api.coingecko.com/api/v3/coins/markets?" + query, cg_headers, timeout=18)
        if not isinstance(raw, list) or len(raw) < 80:
            raise RuntimeError("CoinGecko returned fewer than 80 market assets")
        for item in raw:
            symbol = str(item.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            rows.append({
                "symbol": symbol, "rank": _num(item.get("market_cap_rank")),
                "current_price": _num(item.get("current_price")),
                "change_24h": _num(item.get("price_change_percentage_24h")),
                "provider": "CoinGecko", "updated_at": item.get("last_updated"),
            })
        provider = "CoinGecko"
    except Exception as cg_error:
        if not CMC_API_KEY:
            raise RuntimeError("CoinGecko unavailable and CMC_API_KEY is not configured") from cg_error
        query = urllib.parse.urlencode({"limit": "100", "convert": "USD"})
        raw = request_json(
            "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest?" + query,
            {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}, timeout=18,
        )
        for item in raw.get("data", []):
            symbol = str(item.get("symbol") or "").upper().strip()
            quote = ((item.get("quote") or {}).get("USD") or {})
            if symbol:
                rows.append({
                    "symbol": symbol, "rank": _num(item.get("cmc_rank")),
                    "current_price": _num(quote.get("price")),
                    "change_24h": _num(quote.get("percent_change_24h")),
                    "provider": "CoinMarketCap", "updated_at": quote.get("last_updated"),
                })
        if len(rows) < 80:
            raise RuntimeError("CoinMarketCap returned fewer than 80 market assets")
        provider = "CoinMarketCap"

    # Keep the highest-ranked row for duplicate tickers; add the personal list
    # even if an asset falls outside the dynamic Top 100.
    by_symbol = {}
    for item in rows:
        current = by_symbol.get(item["symbol"])
        if current is None or (item.get("rank") or 10**9) < (current.get("rank") or 10**9):
            by_symbol[item["symbol"]] = item
    for symbol in PERSONAL_ASSETS:
        by_symbol.setdefault(symbol, {
            "symbol": symbol, "rank": None, "current_price": None, "change_24h": None,
            "provider": provider, "updated_at": None, "personal": True,
        })
    universe = sorted(by_symbol.values(), key=lambda x: (x.get("rank") or 10**9, x["symbol"]))
    return universe, provider


class CCXTMarketData:
    """Fault-tolerant CCXT spot feed, sharing the existing ATLAS venue order."""
    def __init__(self):
        try:
            import ccxt
        except ImportError as exc:
            raise RuntimeError("ccxt is not installed") from exc
        self.exchanges = {}
        self.markets = {}
        self.locks = {}
        self.status = {}
        for public_id, native_id in EXCHANGE_SPECS:
            try:
                cls = getattr(ccxt, native_id, None)
                if cls is None:
                    self.status[public_id] = "UNSUPPORTED"
                    continue
                exchange = cls({"enableRateLimit": True, "timeout": 15000, "options": {"defaultType": "spot"}})
                markets = exchange.load_markets()
                if not markets:
                    self.status[public_id] = "EMPTY_MARKETS"
                    continue
                self.exchanges[public_id] = exchange
                self.markets[public_id] = markets
                self.locks[public_id] = threading.Lock()
                self.status[public_id] = f"OK:{len(markets)}"
            except Exception as exc:
                self.status[public_id] = "ERROR:" + type(exc).__name__

    def _pair(self, venue, coin):
        aliases = [coin, DATA_SYMBOL_ALIASES.get(coin, coin)]
        markets = self.markets.get(venue, {})
        for market in markets.values():
            if not isinstance(market, dict) or market.get("quote") != "USDT":
                continue
            if str(market.get("base") or "").upper() in aliases and market.get("active", True) is not False:
                return market.get("symbol")
        for alias in aliases:
            for pair in (f"{alias}/USDT", f"{alias}/USDT:USDT"):
                if pair in markets:
                    return pair
        return None

    def fetch(self, coin, timeframe, now_ms=None):
        failures = []
        for venue in self.exchanges:
            pair = self._pair(venue, coin)
            if not pair:
                continue
            try:
                with self.locks[venue]:
                    raw = self.exchanges[venue].fetch_ohlcv(pair, timeframe=timeframe, limit=90)
                candles = normalize_ohlcv(raw, timeframe, now_ms)
                if len(candles) < 55:
                    failures.append(venue + ":short")
                    continue
                if candles[-1][0] != expected_closed_open_ms(timeframe, now_ms):
                    failures.append(venue + ":stale")
                    continue
                return candles, venue.upper()
            except Exception as exc:
                failures.append(venue + ":" + type(exc).__name__)
        raise RuntimeError("no fresh closed-candle source (" + ",".join(failures[:6]) + ")")


def scan_crypto(universe, market_data, context_flags=None, now_ms=None, workers=4):
    candidates = []
    errors = []
    seen = len(universe)

    def analyze(asset):
        symbol = asset["symbol"]
        if symbol in STABLECOINS:
            return stablecoin_risk(asset), None
        bars4, provider4 = market_data.fetch(symbol, "4h", now_ms)
        barsd, providerd = market_data.fetch(symbol, "1d", now_ms)
        result = score(
            bars4, barsd, now_ms, providers={"4h": provider4, "1d": providerd},
            rank=asset.get("rank"), context_flags=context_flags,
        )
        result["symbol"] = symbol
        result["timestamp"] = dt.datetime.fromtimestamp(result["last_closed_4h_ms"] / 1000, UTC).isoformat()
        result["chart_url"] = "https://www.tradingview.com/chart/?symbol=" + urllib.parse.quote(
            f"{provider4}:{DATA_SYMBOL_ALIASES.get(symbol, symbol)}USDT"
        )
        return (result if result["decision"] != "NONE" else None), None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(6, workers))) as pool:
        future_map = {pool.submit(analyze, asset): asset["symbol"] for asset in universe}
        for future in concurrent.futures.as_completed(future_map):
            symbol = future_map[future]
            try:
                candidate, _ = future.result()
                if candidate:
                    candidates.append(candidate)
            except Exception as exc:
                errors.append({"symbol": symbol, "reason": str(exc)[:220]})
    candidates.sort(key=lambda x: (ACTION_RANK.get(x["decision"], 0), x.get("confidence", 0)), reverse=True)
    coverage = {"requested": seen, "available": seen - len(errors), "unavailable": len(errors), "alerts": len(candidates)}
    return candidates, errors, coverage


def risk_event_key(candidate):
    candle = candidate.get("last_closed_4h_ms") or candidate.get("timestamp")
    digest = hashlib.sha256(
        f"{VERSION}|{candidate.get('asset_group')}|{candidate.get('symbol')}|{candidate.get('decision')}|{candle}".encode()
    ).hexdigest()[:32]
    return "EARLY_RISK:" + digest


def should_notify(candidate, previous_state, now=None, cooldown_hours=ALERT_COOLDOWN_HOURS):
    if not candidate or candidate.get("decision") not in {"WATCH", "REDUCE", "SELL"}:
        return False
    if not previous_state:
        return True
    old = ACTION_RANK.get(str(previous_state.get("level") or "").upper(), 0)
    new = ACTION_RANK.get(str(candidate.get("decision") or "").upper(), 0)
    if new > old:
        return True
    stamp = previous_state.get("notified_at")
    try:
        previous = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return True
    now = now or _now()
    return (now - previous.astimezone(UTC)).total_seconds() >= cooldown_hours * 3600


def format_alert(candidate):
    stamp = candidate.get("timestamp") or _now().isoformat()
    parsed = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    local = parsed.astimezone(TEHRAN).strftime("%Y-%m-%d %H:%M")
    action = candidate["decision"]
    action_fa = {"WATCH": "پایش", "REDUCE": "کاهش ریسک", "SELL": "خروج تأییدشده"}[action]
    lines = [f"{action} | {candidate.get('symbol')} | {candidate.get('asset_group', 'کریپتو')}", f"اقدام: {action_fa}"]
    if candidate.get("price") is not None:
        unit = candidate.get("price_unit") or (candidate.get("details") or {}).get("unit") or ""
        lines.append(f"آخرین قیمت معتبر: {candidate['price']} {unit}".rstrip())
    if candidate.get("change_pct") is not None:
        period = "۲۴ساعته" if candidate.get("asset_group") in ("فلزات جهانی", "سهم تهران", "صندوق", "طلا و سکه ایران") else "حدود ۲۴ساعت"
        lines.append(f"تغییر مرجع {period}: {candidate['change_pct']:+.2f}%")
    if candidate.get("volume_ratio") is not None:
        lines.append(f"نسبت حجم به میانگین: {candidate['volume_ratio']:.2f}×")
    lines.append("شواهد: " + "؛ ".join(candidate.get("flags") or []))
    lines.append(f"قدرت شواهد: {candidate.get('confidence', 0)}٪ (احتمال موفقیت نیست)")
    if candidate.get("providers"):
        lines.append("منابع کندل: " + ", ".join(f"{tf}={src}" for tf, src in candidate["providers"].items()))
    elif candidate.get("provider"):
        lines.append("منبع: " + str(candidate["provider"]))
    lines.append("زمان داده: " + local + " تهران")
    if candidate.get("chart_url"):
        lines.append("نمودار: " + candidate["chart_url"])
    lines.append("هشدار مبتنی بر دادهٔ مشاهده‌شده است؛ پیش‌بینی قطعی یا تضمین بازهٔ ۲۴–۴۸ساعته نیست.")
    return "\n".join(lines)


class SupabaseStore:
    def __init__(self, url=SUPABASE_URL, key=SUPABASE_KEY):
        if not url.startswith("https://") or not key:
            raise RuntimeError("Supabase credentials unavailable")
        self.url, self.key = url.rstrip("/"), key

    def request(self, method, path, payload=None, prefer=None):
        headers = {"apikey": self.key, "Authorization": "Bearer " + self.key,
                   "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        req = urllib.request.Request(self.url + "/rest/v1/" + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def rows(self, table, limit):
        query = urllib.parse.urlencode({"select": "*", "order": "captured_at.desc", "limit": str(limit)})
        return self.request("GET", table + "?" + query) or []

    def state(self, symbol):
        query = urllib.parse.urlencode({"symbol": "eq." + symbol, "select": "symbol,level,notified_at", "limit": "1"})
        rows = self.request("GET", "atlas_risk_alert_state?" + query) or []
        return rows[0] if rows else None

    def event(self, event_key):
        query = urllib.parse.urlencode({"event_key": "eq." + event_key, "select": "event_key,telegram_sent,details", "limit": "1"})
        rows = self.request("GET", "atlas_market_guard_events?" + query) or []
        return rows[0] if rows else None

    def upsert_event(self, row):
        query = urllib.parse.urlencode({"on_conflict": "event_key"})
        return self.request("POST", "atlas_market_guard_events?" + query, row,
                            "resolution=merge-duplicates,return=minimal")

    def update_event(self, event_key, telegram_sent, details):
        query = urllib.parse.urlencode({"event_key": "eq." + event_key})
        self.request("PATCH", "atlas_market_guard_events?" + query,
                     {"telegram_sent": bool(telegram_sent), "details": details}, "return=minimal")

    def update_state(self, symbol, level, notified_at):
        query = urllib.parse.urlencode({"on_conflict": "symbol"})
        return self.request("POST", "atlas_risk_alert_state?" + query,
                            {"symbol": symbol, "level": level, "notified_at": notified_at},
                            "resolution=merge-duplicates,return=minimal")

    def heartbeat(self, run_key, status, now):
        query = urllib.parse.urlencode({"on_conflict": "run_key"})
        local_date = now.astimezone(TEHRAN).date().isoformat()
        lease_until = (now + dt.timedelta(minutes=45)).isoformat() if status == "RUNNING" else None
        row = {"run_key": run_key, "cycle": "EARLY_RISK", "tehran_date": local_date,
               "source": "atlas_early_risk", "status": status,
               "lease_until": lease_until, "lease_token": None,
               "completed_at": now.isoformat() if status in {"DONE", "ERROR"} else None}
        return self.request("POST", "atlas_scheduler_runs?" + query, row,
                            "resolution=merge-duplicates,return=minimal")

    def candidates_from_tables(self, now=None):
        now = now or _now()
        tables = (
            ("atlas_tse_snapshots", 1000, 36),
            ("atlas_fund_snapshots", 1000, 36),
            ("atlas_market_snapshots", 500, 8),
            ("atlas_iran_fx_snapshots", 200, 12),
        )
        findings = []
        errors = []
        for table, limit, max_age in tables:
            try:
                findings.extend(market_risks(table, max_age=max_age, rows=self.rows(table, limit), now=now))
            except Exception as exc:
                errors.append({"table": table, "reason": type(exc).__name__ + ": " + str(exc)[:180]})
        return findings, errors


def _telegram_call(method, payload, token=TELEGRAM_TOKEN, timeout=20):
    if not token:
        raise RuntimeError("Telegram token missing")
    url = "https://api.telegram.org/bot" + token + "/" + method
    body = urllib.parse.urlencode(payload).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.load(response)
            if result.get("ok"):
                return result.get("result") or {}
            error_code = int(result.get("error_code") or 0)
            if error_code == 429 and attempt < 2:
                time.sleep(min(5, int((result.get("parameters") or {}).get("retry_after", 1))))
                continue
            raise RuntimeError("Telegram rejected request (HTTP " + str(error_code) + ")")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body_text)
            except ValueError:
                parsed = {}
            if exc.code == 429 and attempt < 2:
                time.sleep(min(5, int((parsed.get("parameters") or {}).get("retry_after", 1))))
                continue
            if exc.code >= 500 or exc.code == 429:
                raise TimeoutError("Telegram upstream unavailable") from exc
            raise RuntimeError("Telegram rejected request (HTTP " + str(exc.code) + ")") from exc
        except (TimeoutError, ConnectionError, urllib.error.URLError) as exc:
            if method == "sendMessage":
                # A timed-out POST may already have reached Telegram. Retrying
                # here can create a duplicate message; leave the event UNKNOWN.
                raise TimeoutError("Telegram delivery outcome is unknown") from exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise TimeoutError("Telegram delivery outcome is unknown") from exc
    raise TimeoutError("Telegram delivery outcome is unknown")


def telegram_preflight(token=TELEGRAM_TOKEN, group=TELEGRAM_GROUP_CHAT_ID):
    if not token or not group:
        raise RuntimeError("Telegram group credentials unavailable")
    bot = _telegram_call("getMe", {}, token=token)
    chat = _telegram_call("getChat", {"chat_id": group}, token=token)
    member = _telegram_call("getChatMember", {"chat_id": group, "user_id": bot.get("id")}, token=token)
    status = str(member.get("status") or "").lower()
    if status in {"left", "kicked"}:
        raise RuntimeError("Telegram bot is not a member of the configured group")
    if status == "restricted" and member.get("can_send_messages") is False:
        raise RuntimeError("Telegram bot cannot send messages in the configured group")
    return {"bot_id": bot.get("id"), "username": bot.get("username"),
            "chat_id": (chat.get("id") if isinstance(chat, dict) else group),
            "membership_status": status, "send_permission_checked": True}


def _make_event(candidate, now, delivery_status="PENDING"):
    key = risk_event_key(candidate)
    details = {
        "engine_version": VERSION, "decision": candidate["decision"],
        "asset_group": candidate.get("asset_group"), "evidence_confidence_pct": candidate.get("confidence"),
        "confidence_is_probability": False, "flags": candidate.get("flags") or [],
        "technical_flags": candidate.get("technical_flags") or [],
        "context_flags": candidate.get("context_flags") or [],
        "providers": candidate.get("providers") or candidate.get("provider"),
        "rank": candidate.get("rank"), "change_pct": candidate.get("change_pct"),
        "volume_ratio": candidate.get("volume_ratio"), "support": candidate.get("support"),
        "reference_level": candidate.get("reference_level"), "observed_at": candidate.get("timestamp"),
        "delivery": {"status": delivery_status, "attempted_at": now.isoformat()},
    }
    return {
        "captured_at": now.isoformat(), "event_type": "EARLY_RISK",
        "symbol": str(candidate.get("symbol") or "UNKNOWN"), "price": _num(candidate.get("price")),
        "pct_1h": None, "reference_price": None,
        "reference_level": _num(candidate.get("support", candidate.get("reference_level"))),
        "telegram_sent": False, "event_key": key, "source_event_key": None,
        "details": details, "model_version": VERSION,
    }


def deliver_candidates(candidates, store, send, token=TELEGRAM_TOKEN,
                       group=TELEGRAM_GROUP_CHAT_ID, now=None, max_alerts=MAX_ALERTS_PER_CYCLE):
    """Audit-first delivery. Definite errors may retry; ambiguous sends do not."""
    now = now or _now()
    ordered = sorted(candidates or [], key=lambda x: ACTION_RANK.get(x.get("decision"), 0), reverse=True)
    queue = []
    skipped = 0
    for candidate in ordered:
        symbol = candidate.get("symbol") or "UNKNOWN"
        state = store.state(symbol)
        if not should_notify(candidate, state, now):
            skipped += 1
            continue
        row = _make_event(candidate, now)
        prior_event = store.event(row["event_key"])
        if prior_event:
            prior_status = str(((prior_event.get("details") or {}).get("delivery") or {}).get("status") or "").upper()
            if prior_event.get("telegram_sent") or prior_status in {"SENT", "ATTEMPTING", "UNKNOWN"}:
                skipped += 1
                continue
        store.upsert_event(row)  # If this fails, send is deliberately not attempted.
        queue.append((candidate, row))
        if len(queue) >= max_alerts:
            break
    if not queue:
        return {"queued": 0, "sent": 0, "skipped": skipped, "errors": []}

    if not token or not group:
        errors = ["Telegram group credentials unavailable"]
        for _, row in queue:
            details = row["details"]
            details["delivery"] = {"status": "BLOCKED", "attempted_at": now.isoformat(), "error": errors[0]}
            store.update_event(row["event_key"], False, details)
        return {"queued": len(queue), "sent": 0, "skipped": skipped, "errors": errors}

    try:
        preflight = telegram_preflight(token, group)
    except Exception as exc:
        for _, row in queue:
            details = row["details"]
            details["delivery"] = {"status": "ERROR", "attempted_at": now.isoformat(),
                                   "error": "preflight_" + type(exc).__name__}
            store.update_event(row["event_key"], False, details)
        return {"queued": len(queue), "sent": 0, "skipped": skipped,
                "errors": ["PREFLIGHT:" + type(exc).__name__]}

    sent = 0
    errors = []
    # Keep comfortably below Telegram's 4096-character message limit and retain
    # an event-level delivery result for every batch.
    batches = [queue[i:i + 5] for i in range(0, len(queue), 5)]
    for batch in batches:
        message = "🚨 ATLAS | هشدارهای پایش زودهنگام\nزمان پایش: " + now.astimezone(TEHRAN).strftime("%Y-%m-%d %H:%M") + " تهران\n\n"
        message += "\n\n".join(format_alert(candidate) for candidate, _ in batch)
        for _, row in batch:
            details = row["details"]
            details["delivery"] = {"status": "ATTEMPTING", "attempted_at": now.isoformat(),
                                   "bot_username": preflight.get("username")}
            store.update_event(row["event_key"], False, details)
        try:
            result = send(message, group)
            message_id = result.get("message_id") if isinstance(result, dict) else result
            delivered_at = _now().isoformat()
            for candidate, row in batch:
                details = row["details"]
                details["delivery"] = {"status": "SENT", "attempted_at": now.isoformat(),
                                       "sent_at": delivered_at, "message_id": message_id,
                                       "bot_username": preflight.get("username")}
                store.update_event(row["event_key"], True, details)
                store.update_state(candidate["symbol"], candidate["decision"], delivered_at)
            sent += len(batch)
        except Exception as exc:
            ambiguous = isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError))
            status = "UNKNOWN" if ambiguous else "ERROR"
            for _, row in batch:
                details = row["details"]
                details["delivery"] = {"status": status, "attempted_at": now.isoformat(),
                                       "error": type(exc).__name__}
                store.update_event(row["event_key"], False, details)
            errors.append(status + ":" + type(exc).__name__)
    return {"queued": len(queue), "sent": sent, "skipped": skipped, "errors": errors}


def _read_tables(store, now):
    return store.candidates_from_tables(now)


def _emit_shadow(candidates, errors, coverage, contexts):
    print(json.dumps({
        "mode": "SHADOW", "engine": VERSION, "checked_at": _now().isoformat(),
        "crypto_coverage": coverage, "crypto_alerts": candidates,
        "cross_market_context": contexts, "source_errors": errors,
        "telegram_sent": False, "database_alert_writes": False,
    }, ensure_ascii=False, indent=2))


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
    store = SupabaseStore()
    now = _now()
    run_id = os.getenv("GITHUB_RUN_ID", str(int(now.timestamp())))
    run_key = "EARLY_RISK:" + now.strftime("%Y-%m-%d:%H%M") + ":" + run_id
    store.heartbeat(run_key, "RUNNING", now)
    source_errors = []
    crypto_alerts = []
    coverage = {"requested": 0, "available": 0, "unavailable": 0, "alerts": 0}
    contexts = {}
    market_alerts = []
    try:
        try:
            universe, universe_provider = fetch_universe()
            contexts["universe_provider"] = universe_provider
            try:
                contexts["global"] = crypto_context()
            except Exception as exc:
                contexts["global"] = {"status": "UNAVAILABLE", "provider": "CoinGecko"}
                source_errors.append({"source": "CoinGecko global", "reason": type(exc).__name__})
            try:
                contexts["news"] = news_context()
            except Exception as exc:
                contexts["news"] = {"status": "UNAVAILABLE", "provider": "NewsAPI", "headlines": [], "risk_sources": 0}
                source_errors.append({"source": "NewsAPI", "reason": type(exc).__name__})
            context_flags = corroborating_context(contexts.get("global"), contexts.get("news"))
            try:
                market_data = CCXTMarketData()
                crypto_alerts, crypto_errors, coverage = scan_crypto(universe, market_data, context_flags)
                source_errors.extend({"source": "OHLCV", **x} for x in crypto_errors)
                contexts["ohlcv_providers"] = market_data.status
            except Exception as exc:
                source_errors.append({"source": "OHLCV", "reason": type(exc).__name__ + ": " + str(exc)[:180]})
        except Exception as exc:
            source_errors.append({"source": "crypto_universe", "reason": type(exc).__name__ + ": " + str(exc)[:180]})
        market_alerts, table_errors = _read_tables(store, now)
        source_errors.extend(table_errors)
        candidates = (crypto_alerts + market_alerts)
        candidates.sort(key=lambda x: ACTION_RANK.get(x.get("decision"), 0), reverse=True)
        if RISK_MODE == "SHADOW":
            try:
                preflight = telegram_preflight()
                contexts["telegram_preflight"] = {
                    "status": "OK", "bot_username": preflight.get("username"),
                    "chat_id": preflight.get("chat_id"),
                    "membership_status": preflight.get("membership_status"),
                    "send_permission_checked": preflight.get("send_permission_checked"),
                    "messages_sent": False,
                }
            except Exception as exc:
                contexts["telegram_preflight"] = {
                    "status": "UNAVAILABLE", "reason": type(exc).__name__, "messages_sent": False,
                }
                source_errors.append({"source": "Telegram preflight", "reason": type(exc).__name__})
            _emit_shadow(candidates, source_errors, coverage, contexts)
            critical_failure = (
                any(item.get("source") == "crypto_universe" for item in source_errors)
                or (coverage["requested"] > 0 and coverage["available"] == 0)
            )
            if critical_failure:
                print("::error::ATLAS shadow scan has no usable crypto market coverage")
            store.heartbeat(run_key, "ERROR" if critical_failure else "DONE", _now())
            return 2 if critical_failure else 0

        result = deliver_candidates(
            candidates, store,
            lambda message, chat: _telegram_call("sendMessage", {"chat_id": chat, "text": message}, TELEGRAM_TOKEN),
            now=now,
        )
        print(json.dumps({
            "mode": "LIVE", "engine": VERSION, "checked_at": now.isoformat(),
            "crypto_coverage": coverage, "crypto_candidates": len(crypto_alerts),
            "cross_market_candidates": len(market_alerts), "delivery": result,
            "source_errors": source_errors,
        }, ensure_ascii=False))
        store.heartbeat(run_key, "DONE", _now())
        no_crypto_universe = any(x.get("source") == "crypto_universe" for x in source_errors)
        return 2 if result["errors"] or no_crypto_universe or (coverage["requested"] and coverage["available"] == 0) else 0
    except Exception as exc:
        try:
            store.heartbeat(run_key, "ERROR", _now())
        except Exception:
            pass
        print("::error::ATLAS early-risk cycle failed: " + type(exc).__name__ + ": " + str(exc)[:240])
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
