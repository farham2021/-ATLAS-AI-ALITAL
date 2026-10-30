"""Read-only cross-market evidence helpers for the ATLAS early-risk runner.

This module never sends Telegram messages and never writes to Supabase. It only
normalizes already-persisted Iran market snapshots and fetches optional macro and
news context. A headline or one macro statistic cannot by itself produce SELL.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request

UTC = dt.timezone.utc


def request_json(url: str, headers=None, timeout=18):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ATLAS-RiskSentinel/2", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _time(value):
    try:
        result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=UTC)
        return result.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _number(value):
    try:
        result = float(value)
        return result if result == result and abs(result) < 1e20 else None
    except (TypeError, ValueError):
        return None


def _flow(payload):
    direction = str(
        payload.get("real_flow_direction")
        or payload.get("market_real_flow_direction")
        or ""
    ).upper()
    if direction in {"OUTFLOW", "INFLOW", "FLAT"}:
        return direction
    raw = _number(
        payload.get("real_money_flow", payload.get("market_real_net_volume", payload.get("real_net_volume")))
    )
    if raw is None:
        return "UNKNOWN"
    return "OUTFLOW" if raw < 0 else "INFLOW" if raw > 0 else "FLAT"


def _change_pct(row, payload):
    direct = _number(payload.get("pct", payload.get("change_pct")))
    if direct is not None:
        return direct
    raw = payload.get("raw")
    if isinstance(raw, dict):
        direct = _number(raw.get("change_percent"))
        if direct is not None:
            return direct
        change = _number(raw.get("change"))
        old = _number(raw.get("value"))
        if change is not None and old not in (None, 0):
            return change / old * 100.0
    # Navasan snapshots retain price_raw and absolute change in the raw record.
    change = _number(payload.get("change"))
    price_raw = _number(payload.get("price_raw"))
    if change is not None and price_raw not in (None, 0):
        return change / price_raw * 100.0
    return None


def _severity(flags, change_pct, *, outflow=False, buyer_power=None, group=""):
    """Conservative, rule-based evidence ladder. Confidence is not probability."""
    if group == "TSE_MARKET":
        breadth = next((_number(x.split(":", 1)[1]) for x in flags if x.startswith("breadth_pct:")), None)
        count = len(flags)
        if count >= 2 and breadth is not None and breadth <= 20 and outflow:
            return "REDUCE", 78
        if count >= 2:
            return "WATCH", 66
        return "NONE", 0
    if change_pct is None:
        return "NONE", 0
    if group in {"TSE", "FUND"}:
        if change_pct <= -7.0 and outflow and buyer_power is not None and buyer_power < 0.5:
            return "SELL", 86
        if change_pct <= -4.0 and outflow:
            return "REDUCE", 76
        if change_pct <= -2.0 and outflow:
            return "WATCH", 64
        return "NONE", 0
    if group in {"METAL", "FX"}:
        if change_pct <= -8.0:
            return "SELL", 82
        if change_pct <= -5.0:
            return "REDUCE", 74
        if change_pct <= -3.0:
            return "WATCH", 62
    return "NONE", 0


def market_risks(table, max_age=32, rows=None, now=None):
    """Return validated WATCH/REDUCE/SELL candidates from existing snapshots.

    `breadth` is normalized because providers have written both 0..1 and 0..100
    representations over time. BRSAPI uses market_real_net_volume and
    market_real_flow_direction; TSETMC uses real_money_flow.
    """
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    groups = {}
    for row in rows or []:
        symbol = str(row.get("symbol") or "").strip()
        timestamp = _time(row.get("captured_at"))
        if not symbol or not timestamp or (now - timestamp).total_seconds() > max_age * 3600:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        groups.setdefault(symbol, []).append((timestamp, row, payload))
    for history in groups.values():
        history.sort(key=lambda entry: entry[0], reverse=True)

    output = []
    if table in {"atlas_tse_snapshots", "atlas_fund_snapshots"}:
        summary = groups.get("TSE_MARKET", []) if table == "atlas_tse_snapshots" else []
        if summary:
            stamp, row, payload = summary[0]
            breadth = _number(payload.get("breadth"))
            if breadth is not None and 0 <= breadth <= 1:
                breadth *= 100
            flow = _flow(payload)
            flags = []
            if breadth is not None and breadth < 35:
                flags.append(f"breadth_pct:{breadth:.2f}")
            if flow == "OUTFLOW":
                flags.append("خروج پول حقیقی بازار")
            if breadth is not None and breadth < 20:
                flags.append("پهنای بازار بسیار ضعیف")
            decision, confidence = _severity(flags, None, outflow=flow == "OUTFLOW", group="TSE_MARKET")
            if decision != "NONE":
                output.append({
                    "symbol": "TSE_MARKET", "asset_group": "بورس تهران", "decision": decision,
                    "confidence": confidence, "change_pct": None, "price": _number(row.get("price")),
                    "timestamp": stamp.isoformat(), "provider": payload.get("provider", "TSE snapshot"),
                    "flags": [x.split(":", 1)[0] if x.startswith("breadth_pct:") else x for x in flags],
                    "details": {"breadth_pct": breadth, "flow": flow, "advance": payload.get("advance"), "decline": payload.get("decline")},
                    "chart_url": "https://www.tradingview.com/markets/stocks-iran/market-movers-all-stocks/",
                })

        # Individual shares and ETFs are evaluated from the actual daily change
        # and real-investor flow fields captured by BRSAPI/TSETMC.
        for symbol, history in groups.items():
            if symbol == "TSE_MARKET":
                continue
            stamp, row, payload = history[0]
            pct = _change_pct(row, payload)
            flow = _flow(payload)
            bp = _number(payload.get("real_buyer_power", payload.get("market_real_buyer_power")))
            group = "FUND" if row.get("fund_type") or payload.get("is_fund_hint") or payload.get("fund_type") else "TSE"
            flags = []
            if pct is not None and pct <= -2:
                flags.append(f"افت روزانه {pct:.2f}%")
            if flow == "OUTFLOW":
                flags.append("خروج پول حقیقی")
            if bp is not None and bp < 0.7:
                flags.append(f"قدرت خریدار ضعیف ({bp:.2f})")
            decision, confidence = _severity(flags, pct, outflow=flow == "OUTFLOW", buyer_power=bp, group=group)
            if decision != "NONE":
                output.append({
                    "symbol": symbol, "asset_group": "صندوق" if group == "FUND" else "سهم تهران",
                    "decision": decision, "confidence": confidence, "change_pct": pct,
                    "price": _number(row.get("price")), "timestamp": stamp.isoformat(),
                    "provider": payload.get("provider", "TSE snapshot"), "flags": flags,
                    "details": {"flow": flow, "buyer_power": bp, "trade_value": payload.get("trade_value")},
                    "chart_url": "https://www.tradingview.com/markets/stocks-iran/market-movers-all-stocks/",
                })

    elif table == "atlas_market_snapshots":
        for symbol, history in groups.items():
            if symbol in {"SILVER999_FAIR"}:  # Derived from XAG and FX; avoid double-counting XAG.
                continue
            stamp, row, payload = history[0]
            pct = _change_pct(row, payload)
            # Yahoo copper snapshots omit a 24h percentage; compute only from a
            # prior real snapshot of the same symbol and unit.
            if pct is None and len(history) > 1:
                previous = _number(history[1][1].get("price"))
                current = _number(row.get("price"))
                if previous and current and previous > 0:
                    pct = (current / previous - 1) * 100
            if pct is None:
                continue
            decision, confidence = _severity([f"change_pct:{pct:.2f}"], pct, group="METAL")
            if decision != "NONE":
                output.append({
                    "symbol": symbol, "asset_group": "فلزات جهانی", "decision": decision,
                    "confidence": confidence, "change_pct": pct, "price": _number(row.get("price")),
                    "timestamp": stamp.isoformat(), "provider": payload.get("provider", "market snapshot"),
                    "flags": [f"افت قیمت {pct:.2f}%"], "details": {"unit": payload.get("unit"), "proxy": payload.get("proxy", False)},
                    "chart_url": "https://www.tradingview.com/chart/?symbol=" + urllib.parse.quote(str(symbol)),
                })

    elif table == "atlas_iran_fx_snapshots":
        for symbol, history in groups.items():
            if symbol not in {"GOLD18", "COIN_EMAMI", "USD_IRR", "USDT_IRR"}:
                continue
            stamp, row, payload = history[0]
            pct = _change_pct(row, payload)
            if pct is None:
                continue
            # FX is treated as macro context; a falling IRR-denominated quote is
            # a watch on purchasing power, not an automatic instruction to sell.
            group = "FX" if symbol in {"USD_IRR", "USDT_IRR"} else "METAL"
            decision, confidence = _severity([f"change_pct:{pct:.2f}"], pct, group=group)
            if decision != "NONE":
                output.append({
                    "symbol": symbol, "asset_group": "دلار/تتر ایران" if group == "FX" else "طلا و سکه ایران",
                    "decision": "WATCH" if group == "FX" else decision, "confidence": min(confidence or 60, 68) if group == "FX" else confidence,
                    "change_pct": pct, "price": _number(row.get("price")), "timestamp": stamp.isoformat(),
                    "provider": payload.get("provider", "FX snapshot"),
                    "flags": [f"تغییر مرجع {pct:.2f}%"], "details": {"unit": payload.get("unit_canonical", payload.get("unit_raw"))},
                    "chart_url": "https://www.tradingview.com/chart/?symbol=" + urllib.parse.quote(str(symbol)),
                })
    return output


def crypto_context():
    key = os.getenv("COINGECKO_API_KEY", "").strip()
    headers = {"x-cg-demo-api-key": key} if key else {}
    data = request_json("https://api.coingecko.com/api/v3/global", headers).get("data", {})
    return {
        "provider": "CoinGecko", "status": "OK",
        "market_cap_24h_pct": _number(data.get("market_cap_change_percentage_24h_usd")),
        "btc_dominance_pct": _number((data.get("market_cap_percentage") or {}).get("btc")),
        "captured_at": dt.datetime.now(UTC).isoformat(),
    }


def news_context():
    """Optional news context; never a standalone alert trigger."""
    key = os.getenv("NEWSAPI_KEY", "").strip()
    if not key:
        return {"status": "UNCONFIGURED", "provider": "NewsAPI", "headlines": [], "risk_sources": 0}
    since = (dt.datetime.now(UTC) - dt.timedelta(hours=12)).isoformat(timespec="seconds").replace("+00:00", "Z")
    params = urllib.parse.urlencode({
        "q": "(bitcoin OR cryptocurrency OR crypto) AND (hack OR exploit OR SEC OR regulation OR liquidation OR bankruptcy OR outage OR ban)",
        "language": "en", "sortBy": "publishedAt", "pageSize": 20, "from": since, "apiKey": key,
    })
    data = request_json("https://newsapi.org/v2/everything?" + params)
    headlines = []
    risk_sources = set()
    for article in data.get("articles", []):
        title = str(article.get("title") or "").strip()
        source = str((article.get("source") or {}).get("name") or "").strip()
        if not title:
            continue
        headlines.append({"title": title[:240], "source": source, "published_at": article.get("publishedAt"), "url": article.get("url")})
        if source:
            risk_sources.add(source.lower())
    return {"status": "OK", "provider": "NewsAPI", "headlines": headlines[:10], "risk_sources": len(risk_sources)}


def corroborating_context(global_data=None, news=None):
    """Only broad corroboration fields for the crypto technical engine."""
    flags = []
    pct = _number((global_data or {}).get("market_cap_24h_pct"))
    if pct is not None and pct <= -3.0:
        flags.append(f"انقباض ارزش کل بازار {pct:.2f}%")
    if int((news or {}).get("risk_sources") or 0) >= 2:
        flags.append("خبرهای ریسک از چند منبع خبری")
    return flags
