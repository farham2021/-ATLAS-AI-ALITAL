#!/usr/bin/env python3
"""Fetch a fail-closed snapshot of public Kalshi event-contract prices.

This module only reads public market data. It does not place orders and does not
feed the live ATLAS signal engine.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

API_BASE = "https://external-api.kalshi.com/trade-api/v2"
MARKETS_URL = f"{API_BASE}/markets"
TARGET_SERIES = {
    "KXFED": "Fed funds rate",
    "KXFEDDECISION": "Fed meeting decision",
    "KXCPI": "US CPI",
    "KXBTC": "Bitcoin hourly range",
}
MAX_SPREAD_DOLLARS = Decimal("0.10")
MAX_EVENTS = 8
MARKETS_PER_SERIES = 100
ORDERBOOKS_PER_SERIES = 6
DISPLAY_STALE_AFTER_HOURS = 3.0


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _get_json(url: str, timeout_sec: int, retries: int = 2) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ATLAS-Macro-Event-Risk/1.0",
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP_{response.status}")
                raw = response.read(3_000_001)
                if len(raw) > 3_000_000:
                    raise RuntimeError("RESPONSE_TOO_LARGE")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("INVALID_JSON_OBJECT")
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(type(last_error).__name__ if last_error else "FETCH_FAILED")


def _get_markets(series: str, timeout_sec: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {"series_ticker": series, "status": "open", "limit": MARKETS_PER_SERIES}
    )
    payload = _get_json(f"{MARKETS_URL}?{query}", timeout_sec)
    markets = payload.get("markets")
    if not isinstance(markets, list):
        raise RuntimeError("INVALID_MARKETS_RESPONSE")
    return [item for item in markets if isinstance(item, dict)]


def _market_candidates(
    markets: list[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    candidates: list[tuple[Decimal, Decimal, dict[str, Any]]] = []
    for market in markets:
        status = str(market.get("status") or "").lower()
        if status in {"closed", "settled", "paused", "unopened", "initialized"}:
            continue
        if market.get("market_type") not in (None, "binary"):
            continue
        close_time = _timestamp(market.get("close_time"))
        volume = _decimal(market.get("volume_fp", market.get("volume")))
        if close_time is None or close_time <= now or volume is None or volume <= 0:
            continue
        hours_left = Decimal(str((close_time - now).total_seconds())) / Decimal("3600")
        candidates.append((hours_left, -volume, market))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in candidates[:ORDERBOOKS_PER_SERIES]]


def _best_level(levels: Any) -> tuple[Decimal, Decimal] | None:
    if not isinstance(levels, list):
        return None
    valid: list[tuple[Decimal, Decimal]] = []
    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price, size = _decimal(level[0]), _decimal(level[1])
        if price is not None and size is not None and size > 0:
            valid.append((price, size))
    return max(valid, key=lambda item: item[0]) if valid else None


def _get_orderbook(
    ticker: str, timeout_sec: int
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    safe_ticker = urllib.parse.quote(ticker, safe="-")
    payload = _get_json(f"{MARKETS_URL}/{safe_ticker}/orderbook", timeout_sec)
    orderbook = payload.get("orderbook_fp")
    if not isinstance(orderbook, dict):
        return None
    yes_bid = _best_level(orderbook.get("yes_dollars"))
    no_bid = _best_level(orderbook.get("no_dollars"))
    if yes_bid is None or no_bid is None:
        return None
    # Kalshi returns bids for both sides. In a binary market, YES ask = 1 - NO bid.
    yes_ask = Decimal("1") - no_bid[0]
    return yes_bid[0], yes_bid[1], yes_ask, no_bid[1]


def _verify_market(
    market: dict[str, Any],
    series: str,
    series_label: str,
    book: tuple[Decimal, Decimal, Decimal, Decimal],
    now: datetime,
) -> dict[str, Any] | None:
    bid, bid_size, ask, ask_size = book
    if not (Decimal("0.01") <= bid <= ask <= Decimal("0.99")):
        return None
    total_volume = _decimal(market.get("volume_fp", market.get("volume")))
    if total_volume is None or total_volume <= 0 or bid_size <= 0 or ask_size <= 0:
        return None

    close_time = _timestamp(market.get("close_time"))
    if close_time is None or close_time <= now:
        return None
    hours_to_close = Decimal(str((close_time - now).total_seconds())) / Decimal("3600")
    spread = ask - bid
    midpoint = (bid + ask) / Decimal("2")
    probability_pct = midpoint * Decimal("100")
    if spread > MAX_SPREAD_DOLLARS:
        return None

    uncertain_near_expiry = (
        hours_to_close <= Decimal("24")
        and Decimal("20") <= probability_pct <= Decimal("80")
    )
    volume_24h = _decimal(market.get("volume_24h_fp", market.get("volume_24h")))
    title = str(market.get("title") or "").strip()
    subtitle = str(market.get("subtitle") or market.get("yes_sub_title") or "").strip()
    if subtitle and subtitle.lower() not in title.lower():
        title = f"{title} — {subtitle}" if title else subtitle
    if not title:
        return None

    return {
        "ticker": str(market.get("ticker") or ""),
        "event_ticker": str(market.get("event_ticker") or ""),
        "series": series,
        "series_label": series_label,
        "title": title,
        "yes_bid_dollars": float(bid),
        "yes_ask_dollars": float(ask),
        "yes_mid_dollars": float(midpoint),
        "spread_dollars": float(spread),
        "implied_probability_pct": round(float(probability_pct), 2),
        "volume_total": float(total_volume),
        "volume_24h": float(volume_24h) if volume_24h is not None else None,
        "yes_bid_size": float(bid_size),
        "yes_ask_size": float(ask_size),
        "hours_to_close": round(float(hours_to_close), 2),
        "close_time_utc": close_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "quote_snapshot_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "risk_flag": "HIGH_EVENT_RISK" if uncertain_near_expiry else "NORMAL",
        "risk_basis": (
            "close_within_24h_and_yes_mid_between_20_and_80_percent"
            if uncertain_near_expiry
            else None
        ),
    }


def _select_diverse_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Limit any one series from crowding the dashboard snapshot."""
    by_series: dict[str, list[dict[str, Any]]] = {}
    for series in TARGET_SERIES:
        by_series[series] = sorted(
            (event for event in events if event["series"] == series),
            key=lambda item: (item["hours_to_close"], -item["volume_total"]),
        )
    selected: list[dict[str, Any]] = []
    while len(selected) < MAX_EVENTS:
        added = False
        for series in TARGET_SERIES:
            if by_series[series]:
                selected.append(by_series[series].pop(0))
                added = True
                if len(selected) == MAX_EVENTS:
                    break
        if not added:
            break
    return selected


def collect_macro_snapshot(timeout_sec: int = 10) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    successful_series = 0

    for series, label in TARGET_SERIES.items():
        try:
            markets = _get_markets(series, timeout_sec)
            successful_series += 1
            for market in _market_candidates(markets, started):
                ticker = str(market.get("ticker") or "")
                if not ticker:
                    continue
                try:
                    book = _get_orderbook(ticker, timeout_sec)
                    if book is None:
                        continue
                    snapshot_time = datetime.now(timezone.utc)
                    verified = _verify_market(market, series, label, book, snapshot_time)
                    if verified is not None:
                        events.append(verified)
                except Exception:
                    errors.append({"series": series, "error": "ORDERBOOK_FETCH_FAILED"})
        except Exception as exc:
            errors.append({"series": series, "error": type(exc).__name__})

    events = _select_diverse_events(events)
    if events:
        status = "PARTIAL" if errors else "OK"
    elif errors and successful_series == 0:
        status = "UNAVAILABLE"
    elif errors:
        status = "DEGRADED"
    else:
        status = "EMPTY"

    return {
        "schema_version": 2,
        "provider": "Kalshi public market-data API",
        "source_url": API_BASE,
        "status": status,
        "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "display_stale_after_hours": DISPLAY_STALE_AFTER_HOURS,
        "events": events,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="macro_events.json")
    parser.add_argument("--timeout-sec", type=int, default=10)
    args = parser.parse_args()

    snapshot = collect_macro_snapshot(max(1, args.timeout_sec))
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"macro_events status={snapshot['status']} events={len(snapshot['events'])} "
        f"errors={len(snapshot['errors'])} output={destination}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
