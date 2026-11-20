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

API_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
TARGET_SERIES = {
    "KXFED": "Fed funds rate",
    "KXFEDDECISION": "Fed meeting decision",
    "KXCPI": "US CPI",
    "KXBTC": "Bitcoin hourly range",
}
MAX_MARKET_AGE_HOURS = Decimal("6")
MAX_SPREAD_DOLLARS = Decimal("0.10")
MAX_EVENTS = 8
PAGE_SIZE = 100


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


def _get_markets(series: str, timeout_sec: int, retries: int = 2) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {"series_ticker": series, "status": "open", "limit": PAGE_SIZE}
    )
    request = urllib.request.Request(
        f"{API_URL}?{query}",
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
            markets = payload.get("markets")
            if not isinstance(markets, list):
                raise RuntimeError("INVALID_MARKETS_RESPONSE")
            return [item for item in markets if isinstance(item, dict)]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(type(last_error).__name__ if last_error else "FETCH_FAILED")


def _price_dollars(market: dict[str, Any], field: str, legacy_field: str) -> Decimal | None:
    value = _decimal(market.get(field))
    if value is not None:
        return value
    # Compatibility for older API responses that expressed prices in cents.
    cents = _decimal(market.get(legacy_field))
    return cents / Decimal("100") if cents is not None else None


def _volume(market: dict[str, Any], field: str, legacy_field: str) -> Decimal | None:
    value = _decimal(market.get(field))
    return value if value is not None else _decimal(market.get(legacy_field))


def _verify_market(
    market: dict[str, Any],
    series: str,
    series_label: str,
    now: datetime,
) -> dict[str, Any] | None:
    status = str(market.get("status") or "").lower()
    if status in {"closed", "settled", "paused", "unopened", "initialized"}:
        return None

    bid = _price_dollars(market, "yes_bid_dollars", "yes_bid")
    ask = _price_dollars(market, "yes_ask_dollars", "yes_ask")
    if bid is None or ask is None or not (
        Decimal("0.01") <= bid <= ask <= Decimal("0.99")
    ):
        return None

    # Require a live two-sided quote with size, nonzero traded volume, and a
    # recent exchange update. Total volume is used as the nonzero eligibility
    # check; 24-hour volume is also emitted for inspection.
    bid_size = _volume(market, "yes_bid_size_fp", "yes_bid_size")
    ask_size = _volume(market, "yes_ask_size_fp", "yes_ask_size")
    total_volume = _volume(market, "volume_fp", "volume")
    if (
        bid_size is None
        or ask_size is None
        or bid_size <= 0
        or ask_size <= 0
        or total_volume is None
        or total_volume <= 0
    ):
        return None

    updated = _timestamp(market.get("updated_time"))
    close_time = _timestamp(market.get("close_time"))
    if updated is None or close_time is None:
        return None
    age_hours = Decimal(str((now - updated).total_seconds())) / Decimal("3600")
    hours_to_close = Decimal(str((close_time - now).total_seconds())) / Decimal("3600")
    if age_hours < 0 or age_hours > MAX_MARKET_AGE_HOURS or hours_to_close <= 0:
        return None

    spread = ask - bid
    midpoint = (bid + ask) / Decimal("2")
    probability_pct = midpoint * Decimal("100")
    if spread > MAX_SPREAD_DOLLARS:
        return None

    uncertain_near_expiry = (
        hours_to_close <= Decimal("24")
        and Decimal("20") <= probability_pct <= Decimal("80")
    )
    volume_24h = _volume(market, "volume_24h_fp", "volume_24h")
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
        "updated_at_utc": updated.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    now = datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    successful_series = 0

    for series, label in TARGET_SERIES.items():
        try:
            markets = _get_markets(series, timeout_sec)
            successful_series += 1
            for market in markets:
                verified = _verify_market(market, series, label, now)
                if verified is not None:
                    events.append(verified)
        except Exception as exc:
            errors.append({"series": series, "error": type(exc).__name__})

    events = _select_diverse_events(events)
    if events:
        status = "PARTIAL" if errors else "OK"
    else:
        status = "UNAVAILABLE" if successful_series == 0 else "EMPTY"

    return {
        "schema_version": 1,
        "provider": "Kalshi public market-data API",
        "source_url": API_URL,
        "status": status,
        "fetched_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_quote_age_hours": float(MAX_MARKET_AGE_HOURS),
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
