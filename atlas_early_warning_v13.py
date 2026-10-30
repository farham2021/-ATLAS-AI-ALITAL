"""ATLAS v13 early-warning research engine. Pure, fail-closed, no delivery/trading."""
from datetime import datetime, timezone
from math import isfinite

VERSION = "ATLAS_EARLY_WARNING_V13_SHADOW_1"

def _num(value):
    try:
        x = float(value)
        return x if isfinite(x) else None
    except (TypeError, ValueError):
        return None

def assess(row, now=None, max_age_seconds=900):
    """Return advisory candidate only with fresh, corroborated observations.

    Expected normalized inputs: symbol, timestamp (ISO UTC), price, prev_close,
    volume_ratio, open_interest_change_pct, funding_rate, breakout_level,
    breakdown_level. Never converts an alert into an executable order.
    """
    result = {"symbol": str(row.get("symbol") or "UNKNOWN"),
              "state": "NO_ALERT", "direction": None, "reasons": [],
              "version": VERSION, "shadow_only": True, "executable": False}
    try:
        stamp = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return {**result, "state": "DATA_UNAVAILABLE", "reasons": ["timezone_missing"]}
        clock = now or datetime.now(timezone.utc)
        age = (clock - stamp.astimezone(timezone.utc)).total_seconds()
        if not 0 <= age <= max_age_seconds:
            return {**result, "state": "DATA_UNAVAILABLE", "reasons": ["stale_or_future_data"]}
    except (KeyError, ValueError, TypeError, OverflowError):
        return {**result, "state": "DATA_UNAVAILABLE", "reasons": ["timestamp_invalid"]}
    price = _num(row.get("price"))
    previous = _num(row.get("prev_close"))
    volume = _num(row.get("volume_ratio"))
    oi = _num(row.get("open_interest_change_pct"))
    funding = _num(row.get("funding_rate"))
    upper = _num(row.get("breakout_level"))
    lower = _num(row.get("breakdown_level"))
    if any(x is None for x in (price, previous, volume, oi, funding, upper, lower)):
        return {**result, "state": "DATA_UNAVAILABLE", "reasons": ["missing_market_evidence"]}
    if min(price, previous, upper, lower) <= 0 or lower >= upper or volume < 0:
        return {**result, "state": "DATA_UNAVAILABLE", "reasons": ["invalid_market_evidence"]}
    # These are initial research thresholds, not empirically calibrated probabilities.
    if price >= upper and volume >= 1.5 and oi >= 2 and funding < 0.003:
        return {**result, "state": "EARLY_BULLISH_WATCH",
                "direction": "LONG", "reasons": ["breakout", "volume_expansion", "oi_increase"]}
    if price <= lower and volume >= 1.5 and oi >= 2 and funding > -0.003:
        return {**result, "state": "EARLY_RISK_OFF_WATCH",
                "direction": "SHORT", "reasons": ["breakdown", "volume_expansion", "oi_increase"]}
    return result

def scan(rows, now=None):
    return [assess(row, now=now) for row in rows]
