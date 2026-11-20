"""Shared perpetual-market data and fixed-parameter OOS helpers for ATLAS.

This module is research-only. It fetches linear USDT perpetual candles and
settled funding events from a single exchange per dataset. Missing or stale
candles fail closed. Funding coverage is reported separately because some
exchange endpoints retain less history than the price-candle endpoints.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


UTC = timezone.utc
FOUR_HOURS_MS = 4 * 60 * 60 * 1000
BYBIT_BASE = "https://api.bybit.com"
BYBIT_ALT_BASE = "https://api.bytick.com"  # documented Bybit mainnet alias
OKX_BASE = "https://www.okx.com"
BINANCE_UM_BASE = "https://fapi.binance.com"


class PerpetualDataError(RuntimeError):
    """Raised when an exchange response cannot be safely used."""


@dataclass(frozen=True)
class OOSWindow:
    window_id: int
    context_start: str
    context_end: str
    test_start: str
    test_end: str
    mode: str = "FIXED_PARAMETER_OOS"


@dataclass(frozen=True)
class PerpetualDataset:
    symbol: str
    provider: str
    instrument_id: str
    bars: list[tuple[int, float, float, float, float, float]]
    funding_rates: list[tuple[int, float]]
    funding_complete: bool
    metadata: dict[str, Any]
    dataset_sha256: str


def _symbol(value: str) -> str:
    symbol = str(value).strip().upper()
    if not symbol or len(symbol) > 16 or not symbol.isascii() or not symbol.isalnum():
        raise ValueError("Invalid base symbol")
    return symbol


def _utc_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")
    return int(value.astimezone(UTC).timestamp() * 1000)


def _iso(value_ms: int) -> str:
    return datetime.fromtimestamp(value_ms / 1000, UTC).isoformat()


def add_months(value: datetime, months: int) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def build_oos_schedule(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Return complete 4-month context / 2-month test windows, end-exclusive.

    For an 18-month range this produces exactly three test windows. Partial
    trailing windows are omitted instead of being mislabeled as complete.
    """
    start_ms, end_ms = _utc_ms(start), _utc_ms(end)
    if end_ms <= start_ms:
        raise ValueError("OOS end must be after start")
    windows: list[dict[str, Any]] = []
    index = 0
    while True:
        context_start = add_months(start.astimezone(UTC), index * 6)
        context_end = add_months(start.astimezone(UTC), index * 6 + 4)
        test_end = add_months(start.astimezone(UTC), index * 6 + 6)
        if _utc_ms(test_end) > end_ms:
            break
        window = OOSWindow(
            window_id=index + 1,
            context_start=context_start.isoformat(),
            context_end=context_end.isoformat(),
            test_start=context_end.isoformat(),
            test_end=test_end.isoformat(),
        )
        windows.append(asdict(window))
        index += 1
    if not windows:
        raise ValueError("DATASET_TOO_SHORT_FOR_COMPLETE_OOS_WINDOW")
    return windows


def _parse_rows(rows: list[list[Any]], now_ms: int, okx: bool) -> list[tuple[int, float, float, float, float, float]]:
    unique: dict[int, tuple[int, float, float, float, float, float]] = {}
    for row in rows:
        try:
            if len(row) < (9 if okx else 6):
                continue
            if okx and str(row[8]) != "1":
                continue
            ts = int(row[0])
            if ts + FOUR_HOURS_MS > now_ms:
                continue
            open_, high, low, close, volume = map(float, row[1:6])
            values = (open_, high, low, close, volume)
            if not all(math.isfinite(x) for x in values):
                continue
            if min(open_, high, low, close) <= 0 or volume < 0:
                continue
            if low > min(open_, close) or high < max(open_, close) or low > high:
                continue
            unique[ts] = (ts, open_, high, low, close, volume)
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
    return [unique[ts] for ts in sorted(unique)]


def _validate_full_history(bars: list[tuple[int, float, float, float, float, float]], start_ms: int, end_ms: int) -> None:
    if start_ms % FOUR_HOURS_MS or end_ms % FOUR_HOURS_MS:
        raise PerpetualDataError("UNALIGNED_4H_RANGE")
    expected = (end_ms - start_ms) // FOUR_HOURS_MS
    if len(bars) != expected:
        raise PerpetualDataError(f"INCOMPLETE_CANDLE_COUNT_{len(bars)}_EXPECTED_{expected}")
    if not bars or bars[0][0] != start_ms or bars[-1][0] != end_ms - FOUR_HOURS_MS:
        raise PerpetualDataError("CANDLE_RANGE_BOUNDARY_MISMATCH")
    for left, right in zip(bars, bars[1:]):
        if right[0] - left[0] != FOUR_HOURS_MS:
            raise PerpetualDataError("NON_CONTIGUOUS_4H_CANDLES")


def _funding_coverage(rates: list[tuple[int, float]], start_ms: int, end_ms: int) -> dict[str, Any]:
    rates = sorted({int(ts): float(rate) for ts, rate in rates}.items())
    gaps = [right[0] - left[0] for left, right in zip(rates, rates[1:])]
    typical_gap = int(statistics.median(gaps)) if gaps else None
    # Funding intervals can change, so use observed cadence. A gap at least
    # twice the median is treated as potentially missing settlement data.
    allowed_gap = min(24 * 60 * 60 * 1000, int(typical_gap * 1.5)) if typical_gap else None
    first_gap = rates[0][0] - start_ms if rates else None
    last_gap = end_ms - rates[-1][0] if rates else None
    max_gap = max(gaps) if gaps else None
    complete = len(rates) >= 2 and (
        first_gap is not None
        and last_gap is not None
        and allowed_gap is not None
        and first_gap <= allowed_gap
        and last_gap <= allowed_gap
        and max_gap is not None
        and max_gap <= allowed_gap
    )
    return {
        "funding_events": len(rates),
        "funding_first_ms": rates[0][0] if rates else None,
        "funding_last_ms": rates[-1][0] if rates else None,
        "funding_typical_interval_hours": round(typical_gap / 3_600_000, 3) if typical_gap is not None else None,
        "funding_allowed_gap_hours": round(allowed_gap / 3_600_000, 3) if allowed_gap is not None else None,
        "funding_max_gap_hours": round(max_gap / 3_600_000, 3) if max_gap is not None else None,
        "funding_edge_gap_start_hours": round(first_gap / 3_600_000, 3) if first_gap is not None else None,
        "funding_edge_gap_end_hours": round(last_gap / 3_600_000, 3) if last_gap is not None else None,
        "funding_complete": complete,
        "funding_completeness_rule": "no edge or internal gap greater than 1.5x observed median interval (capped at 24h); actual settlement timestamps retained",
    }


def dataset_sha256(
    symbol: str,
    provider: str,
    bars: list[tuple[int, float, float, float, float, float]],
    funding_rates: list[tuple[int, float]],
) -> str:
    payload = {
        "schema_version": 1,
        "symbol": _symbol(symbol),
        "provider": provider,
        "market_type": "LINEAR_USDT_PERPETUAL",
        "timeframe": "4h",
        "bars": [[int(ts), *[float(v) for v in values]] for ts, *values in bars],
        "funding_rates": [[int(ts), float(rate)] for ts, rate in sorted(funding_rates)],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PerpetualDataFetcher:
    """Fetch linear USDT swap data, preserving provider and instrument identity."""

    def __init__(self, timeout_sec: int = 20, retries: int = 4, sleep=time.sleep):
        self.timeout_sec = timeout_sec
        self.retries = retries
        self.sleep = sleep
        self.bybit_hosts_used: set[str] = set()

    def _get_json(self, url: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "ATLAS-Quant-Engine/2.1", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as response:
                    if response.status != 200:
                        raise PerpetualDataError(f"HTTP_{response.status}")
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, (dict, list)):
                    raise PerpetualDataError("INVALID_JSON_RESPONSE")
                if isinstance(payload, dict):
                    if "retCode" in payload and int(payload.get("retCode", -1)) != 0:
                        raise PerpetualDataError(f"BYBIT_{payload.get('retCode')}_{payload.get('retMsg')}")
                    if "code" in payload and str(payload.get("code")) != "0":
                        raise PerpetualDataError(f"EXCHANGE_{payload.get('code')}_{payload.get('msg')}")
                return payload
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code < 500 and exc.code != 429:
                    break
            except (OSError, ValueError, json.JSONDecodeError, PerpetualDataError) as exc:
                last_error = exc
                if isinstance(exc, PerpetualDataError) and not str(exc).startswith(("HTTP_429", "BYBIT_10006")):
                    break
            if attempt + 1 < self.retries:
                self.sleep(min(2 ** attempt, 8))
        raise PerpetualDataError(f"UPSTREAM_REQUEST_FAILED: {last_error}")

    @staticmethod
    def _url(base: str, path: str, params: dict[str, Any]) -> str:
        return base + path + "?" + urllib.parse.urlencode(params)

    def _bybit_json(self, url: str) -> Any:
        """Try Bybit mainnet host, then its documented api.bytick.com alias."""
        try:
            payload = self._get_json(url)
            self.bybit_hosts_used.add(BYBIT_BASE)
            return payload
        except PerpetualDataError as primary_error:
            if not url.startswith(BYBIT_BASE):
                raise
            alternate_url = BYBIT_ALT_BASE + url[len(BYBIT_BASE):]
            try:
                payload = self._get_json(alternate_url)
                self.bybit_hosts_used.add(BYBIT_ALT_BASE)
                return payload
            except PerpetualDataError as alternate_error:
                raise PerpetualDataError(
                    f"BYBIT_DOCUMENTED_HOSTS_FAILED: primary={primary_error}; "
                    f"alternate={alternate_error}"
                ) from alternate_error

    def _bybit_candles(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float, float, float, float, float]]:
        result: dict[int, list[Any]] = {}
        cursor = end_ms - 1
        while cursor >= start_ms:
            payload = self._bybit_json(self._url(BYBIT_BASE, "/v5/market/kline", {
                "category": "linear", "symbol": symbol + "USDT", "interval": "240",
                "end": cursor, "limit": 1000,
            }))
            rows = payload.get("result", {}).get("list", [])
            if not rows:
                break
            for row in rows:
                ts = int(row[0])
                if start_ms <= ts < end_ms:
                    result[ts] = row[:6]
            oldest = min(int(row[0]) for row in rows)
            if oldest >= cursor:
                raise PerpetualDataError("BYBIT_CANDLE_PAGINATION_DID_NOT_ADVANCE")
            cursor = oldest - 1
            self.sleep(0.1)
        return _parse_rows([result[ts] for ts in sorted(result)], end_ms, okx=False)

    def _okx_candles(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float, float, float, float, float]]:
        instrument = f"{symbol}-USDT-SWAP"
        result: dict[int, list[Any]] = {}
        cursor = end_ms
        while cursor > start_ms:
            payload = self._get_json(self._url(OKX_BASE, "/api/v5/market/history-candles", {
                "instId": instrument, "bar": "4H", "after": cursor, "limit": 300,
            }))
            rows = payload.get("data", [])
            if not rows:
                break
            for row in rows:
                ts = int(row[0])
                if start_ms <= ts < end_ms and len(row) > 8 and str(row[8]) == "1":
                    result[ts] = row
            oldest = min(int(row[0]) for row in rows)
            if oldest >= cursor:
                raise PerpetualDataError("OKX_CANDLE_PAGINATION_DID_NOT_ADVANCE")
            cursor = oldest - 1
            self.sleep(0.12)
        return _parse_rows([result[ts] for ts in sorted(result)], end_ms, okx=True)

    def _binance_candles(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float, float, float, float, float]]:
        """Fetch USDⓈ-M linear perpetual 4H klines in ascending pages."""
        result: dict[int, list[Any]] = {}
        cursor = start_ms
        while cursor < end_ms:
            payload = self._get_json(self._url(BINANCE_UM_BASE, "/fapi/v1/klines", {
                "symbol": symbol + "USDT", "interval": "4h", "startTime": cursor,
                "endTime": end_ms - 1, "limit": 1500,
            }))
            if not isinstance(payload, list):
                raise PerpetualDataError("BINANCE_INVALID_KLINE_RESPONSE")
            if not payload:
                break
            for row in payload:
                ts = int(row[0])
                if start_ms <= ts < end_ms:
                    result[ts] = row[:6]
            newest = max(int(row[0]) for row in payload)
            if newest < cursor:
                raise PerpetualDataError("BINANCE_CANDLE_PAGINATION_DID_NOT_ADVANCE")
            cursor = newest + FOUR_HOURS_MS
            if len(payload) < 1500:
                break
            self.sleep(0.1)
        return _parse_rows([result[ts] for ts in sorted(result)], end_ms, okx=False)

    def _bybit_funding(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        result: dict[int, float] = {}
        cursor = end_ms - 1
        while cursor >= start_ms:
            payload = self._bybit_json(self._url(BYBIT_BASE, "/v5/market/funding/history", {
                "category": "linear", "symbol": symbol + "USDT", "endTime": cursor, "limit": 200,
            }))
            rows = payload.get("result", {}).get("list", [])
            if not rows:
                break
            for row in rows:
                ts = int(row["fundingRateTimestamp"])
                rate = float(row["fundingRate"])
                if start_ms <= ts < end_ms and math.isfinite(rate):
                    result[ts] = rate
            oldest = min(int(row["fundingRateTimestamp"]) for row in rows)
            if oldest >= cursor:
                raise PerpetualDataError("BYBIT_FUNDING_PAGINATION_DID_NOT_ADVANCE")
            cursor = oldest - 1
            self.sleep(0.1)
        return sorted(result.items())

    def _binance_funding(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        """Fetch actual USDⓈ-M settled funding events in chronological pages."""
        result: dict[int, float] = {}
        cursor = start_ms
        while cursor < end_ms:
            payload = self._get_json(self._url(BINANCE_UM_BASE, "/fapi/v1/fundingRate", {
                "symbol": symbol + "USDT", "startTime": cursor,
                "endTime": end_ms - 1, "limit": 1000,
            }))
            if not isinstance(payload, list):
                raise PerpetualDataError("BINANCE_INVALID_FUNDING_RESPONSE")
            if not payload:
                break
            for item in payload:
                ts = int(item["fundingTime"])
                rate = float(item["fundingRate"])
                if start_ms <= ts < end_ms and math.isfinite(rate):
                    result[ts] = rate
            newest = max(int(item["fundingTime"]) for item in payload)
            if newest < cursor:
                raise PerpetualDataError("BINANCE_FUNDING_PAGINATION_DID_NOT_ADVANCE")
            cursor = newest + 1
            if len(payload) < 1000:
                break
            self.sleep(0.1)
        return sorted(result.items())

    def _okx_funding(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        instrument = f"{symbol}-USDT-SWAP"
        result: dict[int, float] = {}
        cursor = end_ms
        while cursor > start_ms:
            payload = self._get_json(self._url(OKX_BASE, "/api/v5/public/funding-rate-history", {
                "instId": instrument, "after": cursor, "limit": 400,
            }))
            rows = payload.get("data", [])
            if not rows:
                break
            for row in rows:
                ts = int(row["fundingTime"])
                raw_rate = row.get("realizedRate") or row.get("fundingRate")
                rate = float(raw_rate)
                if start_ms <= ts < end_ms and math.isfinite(rate):
                    result[ts] = rate
            oldest = min(int(row["fundingTime"]) for row in rows)
            if oldest >= cursor:
                raise PerpetualDataError("OKX_FUNDING_PAGINATION_DID_NOT_ADVANCE")
            cursor = oldest - 1
            self.sleep(0.12)
        return sorted(result.items())

    def fetch_latest_perp_4h(
        self,
        base_symbol: str,
        now_ms: int | None = None,
        limit: int = 300,
        min_bars: int = 220,
    ) -> tuple[str, list[tuple[int, float, float, float, float, float]]]:
        """Return fresh closed 4H linear perpetual candles; reject spot/unverified data."""
        symbol = _symbol(base_symbol)
        now_ms = now_ms or int(time.time() * 1000)
        errors: list[str] = []
        sources = ("BYBIT_LINEAR", "OKX_SWAP", "BINANCE_USDM_PERP")
        for provider in sources:
            try:
                if provider == "BYBIT_LINEAR":
                    payload = self._bybit_json(self._url(BYBIT_BASE, "/v5/market/kline", {
                        "category": "linear", "symbol": symbol + "USDT", "interval": "240", "limit": limit,
                    }))
                    rows = payload.get("result", {}).get("list", [])
                    bars = _parse_rows(rows, now_ms, okx=False)
                elif provider == "OKX_SWAP":
                    payload = self._get_json(self._url(OKX_BASE, "/api/v5/market/candles", {
                        "instId": f"{symbol}-USDT-SWAP", "bar": "4H", "limit": min(limit, 300),
                    }))
                    bars = _parse_rows(payload.get("data", []), now_ms, okx=True)
                else:
                    payload = self._get_json(self._url(BINANCE_UM_BASE, "/fapi/v1/klines", {
                        "symbol": symbol + "USDT", "interval": "4h", "limit": min(limit, 1500),
                    }))
                    if not isinstance(payload, list):
                        raise PerpetualDataError("BINANCE_INVALID_KLINE_RESPONSE")
                    bars = _parse_rows(payload, now_ms, okx=False)
                if len(bars) < min_bars:
                    raise PerpetualDataError(f"INSUFFICIENT_CLOSED_CANDLES_{len(bars)}")
                if any(right[0] - left[0] != FOUR_HOURS_MS for left, right in zip(bars[-min_bars:], bars[-min_bars + 1:])):
                    raise PerpetualDataError("NON_CONTIGUOUS_4H_CANDLES")
                age = now_ms - (bars[-1][0] + FOUR_HOURS_MS)
                if age < 0 or age > FOUR_HOURS_MS + 5 * 60 * 1000:
                    raise PerpetualDataError(f"STALE_PERP_CANDLES_{age}MS")
                return provider, bars
            except Exception as exc:
                errors.append(f"{provider}:{str(exc)[:160]}")
        raise PerpetualDataError("NO_FRESH_PERPETUAL_SOURCE: " + "; ".join(errors))

    def fetch_dataset(self, base_symbol: str, start_ms: int, end_ms: int) -> PerpetualDataset:
        """Fetch 4H candles and funding from one provider; prefer complete coverage."""
        symbol = _symbol(base_symbol)
        if start_ms % FOUR_HOURS_MS or end_ms % FOUR_HOURS_MS or end_ms <= start_ms:
            raise PerpetualDataError("UNALIGNED_OR_INVALID_4H_RANGE")
        candidates: list[PerpetualDataset] = []
        errors: list[str] = []
        sources = (
            ("BYBIT_LINEAR", f"{symbol}USDT", self._bybit_candles, self._bybit_funding),
            ("OKX_SWAP", f"{symbol}-USDT-SWAP", self._okx_candles, self._okx_funding),
            ("BINANCE_USDM_PERP", f"{symbol}USDT", self._binance_candles, self._binance_funding),
        )
        for provider, instrument, candle_fn, funding_fn in sources:
            try:
                bars = candle_fn(symbol, start_ms, end_ms)
                _validate_full_history(bars, start_ms, end_ms)
                rates = funding_fn(symbol, start_ms, end_ms)
                coverage = _funding_coverage(rates, start_ms, end_ms)
                metadata = {
                    "provider": provider,
                    "instrument_id": instrument,
                    "bybit_api_hosts": sorted(self.bybit_hosts_used) if provider == "BYBIT_LINEAR" else [],
                    "market_type": "LINEAR_USDT_PERPETUAL",
                    "timeframe": "4h",
                    "start_ms": start_ms,
                    "end_ms_exclusive": end_ms,
                    "candle_count": len(bars),
                    "expected_candle_count": (end_ms - start_ms) // FOUR_HOURS_MS,
                    "first_candle_ms": bars[0][0],
                    "last_candle_ms": bars[-1][0],
                    **coverage,
                }
                candidates.append(PerpetualDataset(
                    symbol=symbol,
                    provider=provider,
                    instrument_id=instrument,
                    bars=bars,
                    funding_rates=rates,
                    funding_complete=bool(coverage["funding_complete"]),
                    metadata=metadata,
                    dataset_sha256=dataset_sha256(symbol, provider, bars, rates),
                ))
                if coverage["funding_complete"]:
                    return candidates[-1]
            except Exception as exc:
                errors.append(f"{provider}:{str(exc)[:180]}")
        if candidates:
            # Preserve the best actual same-exchange snapshot, but its scenario
            # funding cannot be counted as empirical validation evidence.
            best = max(candidates, key=lambda item: (item.funding_complete, len(item.funding_rates)))
            return PerpetualDataset(
                symbol=best.symbol,
                provider=best.provider,
                instrument_id=best.instrument_id,
                bars=best.bars,
                funding_rates=best.funding_rates,
                funding_complete=best.funding_complete,
                metadata={**best.metadata, "alternate_source_errors": errors},
                dataset_sha256=best.dataset_sha256,
            )
        raise PerpetualDataError("NO_COMPLETE_PERPETUAL_CANDLE_SOURCE: " + "; ".join(errors))


def fetch_perpetual_dataset(base_symbol: str, start_ms: int, end_ms: int) -> PerpetualDataset:
    return PerpetualDataFetcher().fetch_dataset(base_symbol, start_ms, end_ms)


def fetch_latest_perp_4h(
    base_symbol: str,
    now_ms: int | None = None,
    limit: int = 300,
    min_bars: int = 220,
) -> tuple[str, list[tuple[int, float, float, float, float, float]]]:
    return PerpetualDataFetcher().fetch_latest_perp_4h(base_symbol, now_ms, limit, min_bars)
