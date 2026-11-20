"""18-month fixed-parameter OOS research for ATLAS linear perpetuals.

Uses one exchange per dataset, actual settlement timestamps, conservative
same-candle stop handling, and explicit end-exclusive OOS windows. This script
does not write to Supabase, Telegram, or execute orders.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

from atlas_futures_v2 import MS, audit_one, make_setup
from atlas_futures_costs import ExecutionCostModel, evaluate_trade_net_r
from atlas_perp_data_and_oos import (
    FOUR_HOURS_MS,
    PerpetualDataset,
    add_months,
    build_oos_schedule,
    fetch_perpetual_dataset,
)

UTC = datetime.timezone.utc


def source_data(symbol: str, start_ms: int, end_ms: int) -> PerpetualDataset:
    """Fetch same-exchange linear USDT perpetual bars and funding."""
    return fetch_perpetual_dataset(symbol, start_ms, end_ms)


def contiguous(bars: list[tuple]) -> bool:
    return all(bars[i][0] - bars[i - 1][0] == MS for i in range(1, len(bars)))


def _dt(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone-aware trade timestamp required")
    return parsed.astimezone(UTC)


def simulate(
    symbol: str,
    bars: list[tuple],
    rates: list[tuple[int, float]],
    start_ms: int,
    end_ms: int,
    provider: str = "BYBIT_LINEAR",
    funding_mode: str = "empirical",
    setup_filter: Callable[[dict[str, Any], list[tuple]], bool] | None = None,
) -> list[dict[str, Any]]:
    """Simulate one OOS window; censored exits at its end are excluded.

    The filter is research-only. A rejected setup still consumes its original
    holding interval so later candidate generation matches the fixed baseline.
    """
    if funding_mode not in ("empirical", "scenario"):
        raise ValueError("INVALID_FUNDING_MODE")
    trades: list[dict[str, Any]] = []
    i = 220
    while i < len(bars) - 1:
        strategy_context = bars[max(0, i - 250):i + 1]
        if len(strategy_context) < 220 or not contiguous(strategy_context):
            i += 1
            continue
        signal_ms = bars[i][0] + MS
        if signal_ms < start_ms:
            i += 1
            continue
        if signal_ms >= end_ms:
            break
        setup = make_setup(symbol, provider, strategy_context, signal_ms)
        if not setup:
            i += 1
            continue

        forecast_context = bars[max(0, i - 511):i + 1]
        accepted = setup_filter is None or bool(setup_filter(setup, forecast_context))
        future = bars[i + 1:min(len(bars), i + 43)]
        if not future:
            break
        outcome = audit_one(setup, strategy_context + future, end_ms)
        if not outcome or outcome["exit_price"] is None:
            # The position was still open at the test cutoff; do not count it.
            break

        opened = _dt(setup["signal_at"])
        closed = _dt(outcome["exit_at"])
        direction = 1 if setup["side"] == "LONG" else -1
        if funding_mode == "empirical":
            signed_funding = sum(
                direction * rate for ts, rate in rates
                if signal_ms < ts <= int(closed.timestamp() * 1000)
            )
        else:
            elapsed = (closed - opened).total_seconds()
            signed_funding = direction * 0.0001 * math.floor(elapsed / (8 * 3600))

        atr_ratio = setup["indicators"]["atr14"] / setup["entry"]
        slip = min(0.005, max(0.0002, 0.1 * atr_ratio))
        costs = ExecutionCostModel(
            entry_slippage_rate=slip,
            exit_slippage_rate=slip,
            funding_rate_8h=0,
        )
        result = evaluate_trade_net_r(
            setup["side"],
            setup["entry"],
            setup["sl"],
            outcome["exit_price"],
            opened,
            closed,
            outcome["status"] == "WIN_TP2",
            costs,
        )
        risk_fraction = abs(setup["entry"] - setup["sl"]) / setup["entry"]
        funding_r = signed_funding / risk_fraction
        net_r = result["net_r"] - funding_r

        if accepted:
            trades.append({
                "symbol": symbol,
                "signal_id": setup["id"],
                "signal_at": setup["signal_at"],
                "exit_at": outcome["exit_at"],
                "side": setup["side"],
                "status": outcome["status"],
                "entry": float(setup["entry"]),
                "sl": float(setup["sl"]),
                "tp1": float(setup["tp1"]),
                "tp2": float(setup["tp2"]),
                "gross_r": result["gross_r"],
                "net_r": round(net_r, 6),
                "funding_r": round(funding_r, 6),
                "slippage_rate": slip,
                "funding_mode": funding_mode,
            })

        # Advance through the same baseline holding interval even if filtered.
        exit_ms = int(closed.timestamp() * 1000)
        bars_consumed = sum(1 for bar in future if bar[0] + MS <= exit_ms)
        i += max(1, bars_consumed)
    return trades


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda row: row["exit_at"])
    returns = [float(row["net_r"]) for row in ordered]
    if not returns:
        return {"trades": 0, "verdict": "INSUFFICIENT"}
    wins = sum(value > 0 for value in returns)
    gross_profit = sum(value for value in returns if value > 0)
    gross_loss = -sum(value for value in returns if value < 0)
    equity = peak = drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(returns),
        "win_rate": round(wins / len(returns), 4),
        "mean_net_r": round(sum(returns) / len(returns), 5),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "max_drawdown_r": round(drawdown, 4),
        "verdict": "RESEARCH_ONLY",
    }


def walk_forward(
    trades: list[dict[str, Any]],
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[dict[str, Any]]:
    """Return explicit, non-overlapping 4m-context / 2m-test windows."""
    result: list[dict[str, Any]] = []
    for window in build_oos_schedule(start, end):
        test_start = _dt(window["test_start"])
        test_end = _dt(window["test_end"])
        subset = [
            trade for trade in trades
            if test_start <= _dt(trade["signal_at"]) < test_end
            and _dt(trade["exit_at"]) <= test_end
        ]
        result.append({
            **window,
            "index": window["window_id"],
            "metrics": metrics(subset),
        })
    return result


def _aligned_end(now: datetime.datetime) -> datetime.datetime:
    value = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return value - datetime.timedelta(hours=value.hour % 4)


def _write_dataset(path: Path, data: PerpetualDataset, start_ms: int, end_ms: int) -> None:
    payload = {
        "schema_version": 1,
        "symbol": data.symbol,
        "provider": data.provider,
        "instrument_id": data.instrument_id,
        "market_type": "LINEAR_USDT_PERPETUAL",
        "timeframe": "4h",
        "start_ms": start_ms,
        "end_ms_exclusive": end_ms,
        "bars": [[int(row[0]), *[float(value) for value in row[1:]]] for row in data.bars],
        "funding_rates": [[int(ts), float(rate)] for ts, rate in data.funding_rates],
        "funding_complete": data.funding_complete,
        "metadata": data.metadata,
        "dataset_sha256": data.dataset_sha256,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTC,ETH,SOL")
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--out", default="atlas_backtest_results")
    args = parser.parse_args()
    if args.months < 12 or args.months > 24:
        raise ValueError("months must be 12..24")

    out_dir = Path(args.out)
    data_dir = out_dir / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    end = _aligned_end(datetime.datetime.now(UTC))
    start = add_months(end, -args.months)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    windows = build_oos_schedule(start, end)
    if args.months == 18 and len(windows) != 3:
        raise RuntimeError("Expected exactly three complete 4m/2m OOS windows")

    summary: dict[str, Any] = {
        "schema_version": 2,
        "created_at": datetime.datetime.now(UTC).isoformat(),
        "evaluation_protocol": "MULTI_WINDOW_FIXED_PARAMETER_OOS",
        "market_type": "LINEAR_USDT_PERPETUAL",
        "timeframe": "4h",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "oos_windows": windows,
        "oos_windows_count": len(windows),
        "oos_months_total": 2 * len(windows),
        "symbols": {},
        "dataset_sha256_by_symbol": {},
        "assumptions": {
            "same_candle_sl_tp": "SL_FIRST",
            "fees": "round-trip taker fee from atlas_futures_costs.py",
            "slippage": "ATR-based scenario assumption; not measured fills",
            "empirical_funding": "signed settled rate events at their actual timestamps",
            "incomplete_funding": "scenario 0.01% per 8h; excluded from empirical acceptance",
            "exit_boundary": "trades not closed by each test_end are censored and excluded",
            "signals": "fixed ATLAS parameters; no OOS tuning",
        },
    }

    aggregate_oos: list[dict[str, Any]] = []
    for raw_symbol in args.symbols.split(","):
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        try:
            data = source_data(symbol, start_ms, end_ms)
            bars, rates = data.bars, data.funding_rates
            _write_dataset(data_dir / f"{symbol}.json", data, start_ms, end_ms)
            funding_mode = "empirical" if data.funding_complete else "scenario"
            per_window: list[dict[str, Any]] = []
            symbol_oos: list[dict[str, Any]] = []
            for window in windows:
                test_start_ms = int(_dt(window["test_start"]).timestamp() * 1000)
                test_end_ms = int(_dt(window["test_end"]).timestamp() * 1000)
                trades = simulate(
                    symbol, bars, rates, test_start_ms, test_end_ms,
                    data.provider, funding_mode,
                )
                symbol_oos.extend(trades)
                per_window.append({
                    **window,
                    "dataset_sha256": data.dataset_sha256,
                    "metrics": metrics(trades),
                })
            aggregate_oos.extend(symbol_oos)
            summary["dataset_sha256_by_symbol"][symbol] = data.dataset_sha256
            summary["symbols"][symbol] = {
                "provider": data.provider,
                "instrument_id": data.instrument_id,
                "coverage": data.metadata,
                "dataset_sha256": data.dataset_sha256,
                "funding_mode": funding_mode,
                "windows": per_window,
                "metrics": metrics(symbol_oos),
                "verdict": "EMPIRICAL_RESEARCH" if data.funding_complete else "SCENARIO_ONLY_NOT_ACCEPTED",
            }
        except Exception as exc:
            summary["symbols"][symbol] = {
                "verdict": "FETCH_FAILED",
                "error": str(exc)[:300],
            }

    summary["aggregate_oos"] = metrics(aggregate_oos)
    summary["aggregate_oos"]["long_trades"] = sum(row["side"] == "LONG" for row in aggregate_oos)
    summary["aggregate_oos"]["short_trades"] = sum(row["side"] == "SHORT" for row in aggregate_oos)
    summary["aggregate_oos"]["minimum_sample_met"] = len(aggregate_oos) >= 50
    summary["all_symbols_covered"] = bool(summary["symbols"]) and all(
        item.get("coverage", {}).get("candle_count", 0) > 0
        for item in summary["symbols"].values()
    )
    summary["all_funding_empirical"] = summary["all_symbols_covered"] and all(
        item.get("coverage", {}).get("funding_complete") is True
        for item in summary["symbols"].values()
    )
    if summary["all_funding_empirical"] and summary["aggregate_oos"]["minimum_sample_met"]:
        summary["verdict"] = "EMPIRICAL_RESEARCH_COMPLETE"
    elif summary["all_funding_empirical"]:
        summary["verdict"] = "INSUFFICIENT_SAMPLE"
    elif summary["all_symbols_covered"]:
        summary["verdict"] = "SCENARIO_ONLY_NOT_ACCEPTED"
    else:
        summary["verdict"] = "INCOMPLETE"

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "trades.json").write_text(
        json.dumps(aggregate_oos, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["all_symbols_covered"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
