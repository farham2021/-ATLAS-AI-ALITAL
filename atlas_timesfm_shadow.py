"""Shadow-only TimesFM 2.5 comparison on an accepted ATLAS perpetual OOS baseline.

No Supabase, Telegram, production signals, or order execution. The quantile
filter is a research heuristic; pointwise price quantiles are not path-touch
probabilities.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

import atlas_futures_backtest_18m as backtest
from atlas_perp_data_and_oos import FOUR_HOURS_MS, dataset_sha256

UTC = dt.timezone.utc
HORIZON = 12
CONTEXT = 512
Q10_INDEX = 1
Q50_INDEX = 5
Q90_INDEX = 9
Z10 = 1.2815515655446004


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone-aware artifact timestamps required")
    return parsed.astimezone(UTC)


def _time_ms(value: str) -> int:
    return int(_parse_time(value).timestamp() * 1000)


class TimesFM25Forecaster:
    def __init__(self, checkpoint: str = "google/timesfm-2.5-200m-pytorch"):
        self.checkpoint = checkpoint
        self.model = None
        self.np = None
        self.load_latency_ms: float | None = None

    def load(self) -> None:
        if self.model is not None:
            return
        started = time.perf_counter()
        import numpy as np
        import timesfm

        self.np = np
        self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            self.checkpoint,
            torch_compile=False,
        )
        self.model.compile(timesfm.ForecastConfig(
            max_context=CONTEXT,
            max_horizon=HORIZON,
            normalize_inputs=True,
            per_core_batch_size=1,
            use_continuous_quantile_head=True,
            fix_quantile_crossing=True,
            infer_is_positive=False,
        ))
        self.load_latency_ms = round((time.perf_counter() - started) * 1000, 2)

    def forecast(self, close_prices: list[float]) -> dict[str, Any]:
        self.load()
        np = self.np
        if len(close_prices) < 100:
            raise ValueError("INSUFFICIENT_CONTEXT_FOR_TIMESFM")
        close = np.asarray(close_prices[-CONTEXT:], dtype=np.float32)
        if not np.isfinite(close).all() or (close <= 0).any():
            raise ValueError("INVALID_CLOSE_SERIES")
        log_close = np.log(close)
        started = time.perf_counter()
        point, quantile = self.model.forecast(horizon=HORIZON, inputs=[log_close])
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        point_arr = np.asarray(point)
        q_arr = np.asarray(quantile)
        if point_arr.shape != (1, HORIZON) or q_arr.shape != (1, HORIZON, 10):
            raise ValueError(f"UNEXPECTED_TIMESFM_OUTPUT_SHAPE_{point_arr.shape}_{q_arr.shape}")
        q_price = np.exp(q_arr[0])
        point_price = np.exp(point_arr[0])
        if not np.isfinite(q_price).all() or not np.isfinite(point_price).all():
            raise ValueError("NONFINITE_TIMESFM_FORECAST")
        return {
            "point": point_price.astype(float).tolist(),
            "q10": q_price[:, Q10_INDEX].astype(float).tolist(),
            "q50": q_price[:, Q50_INDEX].astype(float).tolist(),
            "q90": q_price[:, Q90_INDEX].astype(float).tolist(),
            "latency_ms": latency_ms,
        }


def random_walk_quantiles(close_prices: list[float], horizon: int = HORIZON) -> dict[str, list[float]]:
    """Driftless log-price random walk with expanding marginal 10/50/90 bands."""
    if len(close_prices) < 3 or any(not math.isfinite(x) or x <= 0 for x in close_prices):
        raise ValueError("INVALID_RANDOM_WALK_CONTEXT")
    history = [math.log(value) for value in close_prices[-101:]]
    returns = [history[i] - history[i - 1] for i in range(1, len(history))]
    sigma = statistics.stdev(returns) if len(returns) > 1 else 0.0
    last = float(close_prices[-1])
    q10, q50, q90 = [], [], []
    for step in range(1, horizon + 1):
        width = Z10 * sigma * math.sqrt(step)
        q10.append(last * math.exp(-width))
        q50.append(last)
        q90.append(last * math.exp(width))
    return {"q10": q10, "q50": q50, "q90": q90}


def _pinball(actual: float, forecast: float, tau: float) -> float:
    error = actual - forecast
    return max(tau * error, (tau - 1.0) * error)


def evaluate_quantiles(records: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    rows = [record for record in records if record.get(prefix + "_actual")]
    if not rows:
        return {"origins": 0, "status": "NO_COMPLETE_12_BAR_FORECASTS"}
    by_horizon = []
    for horizon_index in range(HORIZON):
        pairs = []
        for row in rows:
            origin = float(row["origin_close"])
            actual = math.log(float(row[prefix + "_actual"][horizon_index]) / origin)
            q10 = math.log(float(row[prefix + "_q10"][horizon_index]) / origin)
            q50 = math.log(float(row[prefix + "_q50"][horizon_index]) / origin)
            q90 = math.log(float(row[prefix + "_q90"][horizon_index]) / origin)
            pairs.append((actual, q10, q50, q90))
        q10_hits = sum(actual < q10 for actual, q10, _, _ in pairs)
        q90_exceeds = sum(actual > q90 for actual, _, _, q90 in pairs)
        covered = sum(q10 <= actual <= q90 for actual, q10, _, q90 in pairs)
        count = len(pairs)
        by_horizon.append({
            "horizon_bars": horizon_index + 1,
            "observations": count,
            "q10_breach_rate": round(q10_hits / count, 4),
            "q90_exceed_rate": round(q90_exceeds / count, 4),
            "central_80_coverage": round(covered / count, 4),
            "pinball_q10_log_return": round(statistics.mean(_pinball(a, lo, 0.1) for a, lo, _, _ in pairs), 8),
            "pinball_q50_log_return": round(statistics.mean(_pinball(a, med, 0.5) for a, _, med, _ in pairs), 8),
            "pinball_q90_log_return": round(statistics.mean(_pinball(a, hi, 0.9) for a, _, _, hi in pairs), 8),
        })
    return {"origins": len(rows), "nominal_tail_rate": 0.10, "by_horizon": by_horizon}


def _oos_bounds(windows: list[dict[str, Any]]) -> list[tuple[int, int]]:
    return [(_time_ms(window["test_start"]), _time_ms(window["test_end"])) for window in windows]


def _in_oos(signal_ms: int, bounds: list[tuple[int, int]]) -> tuple[int, int] | None:
    for start_ms, end_ms in bounds:
        if start_ms <= signal_ms < end_ms:
            return start_ms, end_ms
    return None


class ShadowFilter:
    def __init__(
        self,
        forecaster: TimesFM25Forecaster,
        bars: list[tuple],
        oos_bounds: list[tuple[int, int]],
    ):
        self.forecaster = forecaster
        self.bars = bars
        self.oos_bounds = oos_bounds
        self.records: list[dict[str, Any]] = []
        self.bypassed_horizon = 0
        self.by_ts = {bar[0]: bar for bar in bars}

    def __call__(self, setup: dict[str, Any], context: list[tuple]) -> bool:
        signal_ms = _time_ms(setup["signal_at"])
        interval = _in_oos(signal_ms, self.oos_bounds)
        if interval is None:
            return True
        _, end_ms = interval
        future_times = [signal_ms + FOUR_HOURS_MS * i for i in range(HORIZON)]
        if future_times[-1] + FOUR_HOURS_MS > end_ms:
            self.bypassed_horizon += 1
            return True
        forecast = self.forecaster.forecast([float(bar[4]) for bar in context])
        rw = random_walk_quantiles([float(bar[4]) for bar in context])
        actual_bars = [self.by_ts.get(ts) for ts in future_times]
        if any(bar is None for bar in actual_bars):
            raise ValueError("OOS_DATA_GAP_AFTER_SIGNAL")
        actual_close = [float(bar[4]) for bar in actual_bars]
        side = setup["side"]
        stop = float(setup["sl"])
        model_rejects = min(forecast["q10"]) <= stop if side == "LONG" else max(forecast["q90"]) >= stop
        rw_rejects = min(rw["q10"]) <= stop if side == "LONG" else max(rw["q90"]) >= stop
        self.records.append({
            "symbol": setup["symbol"],
            "signal_at": setup["signal_at"],
            "side": side,
            "entry": float(setup["entry"]),
            "sl": stop,
            "origin_close": float(context[-1][4]),
            "model_rejects": bool(model_rejects),
            "rw_rejects": bool(rw_rejects),
            "model_point": forecast["point"],
            "model_q10": forecast["q10"],
            "model_q50": forecast["q50"],
            "model_q90": forecast["q90"],
            "rw_q10": rw["q10"],
            "rw_q50": rw["q50"],
            "rw_q90": rw["q90"],
            "model_actual": actual_close,
            "rw_actual": actual_close,
            "actual_min_low": min(float(bar[3]) for bar in actual_bars),
            "actual_max_high": max(float(bar[2]) for bar in actual_bars),
            "latency_ms": forecast["latency_ms"],
        })
        return not model_rejects


def _trade_filter_diagnostics(
    records: list[dict[str, Any]],
    baseline_trades: list[dict[str, Any]],
    decision_key: str,
) -> dict[str, Any]:
    outcomes = {row["signal_at"]: row for row in baseline_trades}
    evaluated = [row for row in records if row["signal_at"] in outcomes]
    rejected = [row for row in evaluated if row[decision_key]]
    stopped_signals = {
        signal for signal, trade in outcomes.items()
        if trade["status"] in ("LOSS", "TP1_EXIT")
    }
    rejected_stops = [row for row in rejected if row["signal_at"] in stopped_signals]
    stopped_count = sum(row["signal_at"] in stopped_signals for row in evaluated)
    return {
        "oos_setups_with_settled_outcome": len(evaluated),
        "rejected": len(rejected),
        "rejected_and_later_stopped": len(rejected_stops),
        "baseline_stop_outcomes": stopped_count,
        "stop_recall": round(len(rejected_stops) / stopped_count, 4) if stopped_count else None,
        "rejection_precision": round(len(rejected_stops) / len(rejected), 4) if rejected else None,
        "note": "Quantile-stop overlap is a rejection heuristic, not a path-touch probability.",
    }


def _load_dataset(path: Path, expected_hash: str) -> tuple[dict[str, Any], list[tuple], list[tuple[int, float]]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    bars = [tuple([int(row[0]), *[float(value) for value in row[1:6]]]) for row in obj["bars"]]
    rates = [(int(row[0]), float(row[1])) for row in obj["funding_rates"]]
    computed = dataset_sha256(obj["symbol"], obj["provider"], bars, rates)
    if computed != expected_hash or computed != obj.get("dataset_sha256"):
        raise ValueError(f"DATASET_HASH_MISMATCH_{obj.get('symbol')}")
    return obj, bars, rates


def evaluate(
    summary_path: Path,
    data_dir: Path,
    out_dir: Path,
    symbols: list[str],
) -> dict[str, Any]:
    baseline = json.loads(summary_path.read_text(encoding="utf-8"))
    if baseline.get("verdict") != "EMPIRICAL_RESEARCH_COMPLETE":
        raise ValueError("BASELINE_NOT_EMPIRICALLY_ACCEPTED; TimesFM shadow was not started")
    windows = baseline.get("oos_windows")
    if not isinstance(windows, list) or len(windows) != 3:
        raise ValueError("BASELINE_MISSING_THREE_EXPLICIT_OOS_WINDOWS")

    forecaster = TimesFM25Forecaster()
    bounds = _oos_bounds(windows)
    result: dict[str, Any] = {
        "status": "SHADOW_ONLY",
        "model": "TimesFM 2.5",
        "checkpoint": forecaster.checkpoint,
        "license": "Apache-2.0",
        "horizon_bars": HORIZON,
        "bar_interval": "4h",
        "forecast_horizon_hours": HORIZON * 4,
        "baseline_dataset_contract": "same provider-specific 4H perpetual bars, settled funding, and SHA-256 as accepted baseline",
        "oos_windows": windows,
        "symbols": {},
    }
    aggregate_baseline: list[dict[str, Any]] = []
    aggregate_model: list[dict[str, Any]] = []
    aggregate_rw: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []

    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        baseline_symbol = baseline.get("symbols", {}).get(symbol)
        if not baseline_symbol or baseline_symbol.get("verdict") != "EMPIRICAL_RESEARCH":
            raise ValueError(f"SYMBOL_NOT_EMPIRICALLY_ACCEPTED_{symbol}")
        expected_hash = baseline_symbol.get("dataset_sha256")
        if not expected_hash:
            raise ValueError(f"BASELINE_DATASET_HASH_MISSING_{symbol}")
        obj, bars, rates = _load_dataset(data_dir / f"{symbol}.json", expected_hash)
        if obj.get("provider") != baseline_symbol.get("provider"):
            raise ValueError(f"PROVIDER_MISMATCH_{symbol}")
        if not obj.get("funding_complete") or not baseline_symbol.get("coverage", {}).get("funding_complete"):
            raise ValueError(f"FUNDING_NOT_EMPIRICAL_{symbol}")

        provider = obj["provider"]
        baseline_trades: list[dict[str, Any]] = []
        model_trades: list[dict[str, Any]] = []
        rw_trades: list[dict[str, Any]] = []
        gate = ShadowFilter(forecaster, bars, bounds)
        for window in windows:
            test_start_ms = _time_ms(window["test_start"])
            test_end_ms = _time_ms(window["test_end"])
            baseline_trades.extend(backtest.simulate(
                symbol, bars, rates, test_start_ms, test_end_ms, provider, "empirical"
            ))
            model_trades.extend(backtest.simulate(
                symbol, bars, rates, test_start_ms, test_end_ms, provider, "empirical",
                setup_filter=gate,
            ))
            rw_rejections = {row["signal_at"]: row["rw_rejects"] for row in gate.records}

            def rw_filter(setup: dict[str, Any], _context: list[tuple]) -> bool:
                return not rw_rejections.get(setup["signal_at"], False)

            rw_trades.extend(backtest.simulate(
                symbol, bars, rates, test_start_ms, test_end_ms, provider, "empirical",
                setup_filter=rw_filter,
            ))

        aggregate_baseline.extend(baseline_trades)
        aggregate_model.extend(model_trades)
        aggregate_rw.extend(rw_trades)
        all_records.extend(gate.records)
        result["symbols"][symbol] = {
            "provider": provider,
            "dataset_sha256": expected_hash,
            "funding_mode": "empirical",
            "baseline_metrics": backtest.metrics(baseline_trades),
            "timesfm_filtered_metrics": backtest.metrics(model_trades),
            "random_walk_filtered_metrics": backtest.metrics(rw_trades),
            "timesfm_filter_diagnostics": _trade_filter_diagnostics(
                gate.records, baseline_trades, "model_rejects"
            ),
            "random_walk_filter_diagnostics": _trade_filter_diagnostics(
                gate.records, baseline_trades, "rw_rejects"
            ),
            "forecast_origins": len(gate.records),
            "bypassed_without_full_12_bar_horizon": gate.bypassed_horizon,
        }

    result["baseline_aggregate_metrics"] = backtest.metrics(aggregate_baseline)
    result["timesfm_filtered_aggregate_metrics"] = backtest.metrics(aggregate_model)
    result["random_walk_filtered_aggregate_metrics"] = backtest.metrics(aggregate_rw)
    result["timesfm_quantile_coverage"] = evaluate_quantiles(all_records, "model")
    result["random_walk_quantile_coverage"] = evaluate_quantiles(all_records, "rw")
    result["average_inference_latency_ms"] = round(
        statistics.mean([row["latency_ms"] for row in all_records]), 2
    ) if all_records else None
    result["model_load_latency_ms"] = forecaster.load_latency_ms
    result["timesfm_package_version"] = importlib.metadata.version("timesfm")
    result["promotion"] = "NOT_AUTOMATIC; compare OOS Net R, drawdown, sample size, and marginal quantile calibration"
    result["quantile_note"] = (
        "Pointwise close quantiles do not represent the probability of touching a stop anywhere along the 12-bar path. "
        "Calibration scores use log returns."
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "forecast_origins.json").write_text(
        json.dumps(all_records, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TimesFM 2.5 after baseline acceptance (shadow only).")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--symbols", default="BTC,ETH,SOL")
    parser.add_argument("--out", type=Path, default=Path("atlas_timesfm_shadow_results"))
    args = parser.parse_args()
    output = evaluate(args.baseline, args.data_dir, args.out, args.symbols.split(","))
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
