"""Kronos-small OOS evaluator for ATLAS. Research-only; never changes live signals.

Kronos' public predictor averages its internal sample_count trajectories. This
adapter therefore batches repeated copies of each input with sample_count=1 to
retain separate stochastic OHLCV paths for first-touch risk estimation.

Run only after the ATLAS baseline is accepted. The Kronos source checkout and
both Hugging Face checkpoints are pinned below for reproducibility.
"""
from __future__ import annotations

import argparse
import datetime as dt
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
MODEL_ID = "NeoQuasar/Kronos-small"
MODEL_REVISION = "901c26c1332695a2a8f243eb2f37243a37bea320"
TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"
KRONOS_CODE_REVISION = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"


def _time_ms(value: str) -> int:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMEZONE_AWARE_TIMESTAMP_REQUIRED")
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def _positive(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"INVALID_{label}")
    return number


def _validate_setup(setup: dict[str, Any]) -> tuple[str, float, float]:
    side = str(setup["side"]).upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError("INVALID_SETUP_SIDE")
    entry = _positive(setup["entry"], "ENTRY")
    sl = _positive(setup["sl"], "SL")
    tp1 = _positive(setup["tp1"], "TP1")
    if (side == "LONG" and not sl < entry < tp1) or (
        side == "SHORT" and not tp1 < entry < sl
    ):
        raise ValueError("INVALID_SETUP_LEVEL_ORDER")
    return side, sl, tp1


def _validate_candle(open_: float, high: float, low: float, close: float, volume: float) -> None:
    values = (open_, high, low, close, volume)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("NONFINITE_CANDLE")
    if min(open_, high, low, close) <= 0 or volume < 0:
        raise ValueError("INVALID_CANDLE_VALUE")
    if low > min(open_, close) or high < max(open_, close) or low > high:
        raise ValueError("INVALID_OHLC_GEOMETRY")


def _project_forecast_candle(
    open_: float, high: float, low: float, close: float, volume: float
) -> tuple[tuple[float, float, float, float, float], bool]:
    """Project generated wick bounds to a valid OHLC envelope; preserve O/C and count repairs."""
    values = (open_, high, low, close, volume)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("NONFINITE_KRONOS_FORECAST")
    if min(open_, high, low, close) <= 0 or volume < 0:
        raise ValueError("INVALID_KRONOS_FORECAST_VALUE")
    projected_high = max(high, open_, close)
    projected_low = min(low, open_, close)
    repaired = projected_high != high or projected_low != low
    projected = (open_, projected_high, projected_low, close, volume)
    _validate_candle(*projected)
    return projected, repaired


def _first_touch(path: list[tuple[float, float, float, float, float]],
                 side: str, sl: float, tp1: float) -> str:
    for open_, high, low, close, volume in path:
        _validate_candle(open_, high, low, close, volume)
        if side == "LONG":
            hit_sl, hit_tp = low <= sl, high >= tp1
        else:
            hit_sl, hit_tp = high >= sl, low <= tp1
        if hit_sl:  # Conservative same-candle ordering.
            return "SL"
        if hit_tp:
            return "TP1"
    return "OPEN"


def _path_risk(paths: list[list[tuple[float, float, float, float, float]]],
               side: str, sl: float, tp1: float) -> dict[str, Any]:
    if not paths:
        raise ValueError("NO_KRONOS_PATHS")
    outcomes = [_first_touch(path, side, sl, tp1) for path in paths]
    count = len(outcomes)
    sl_count = sum(outcome == "SL" for outcome in outcomes)
    tp_count = sum(outcome == "TP1" for outcome in outcomes)
    probability = sl_count / count
    return {
        "path_count": count,
        "sl_first_probability": probability,
        "tp1_first_probability": tp_count / count,
        "unresolved_probability": sum(outcome == "OPEN" for outcome in outcomes) / count,
        "sl_probability_mc_se": math.sqrt(probability * (1.0 - probability) / count),
    }


def _actual_outcome(future: list[tuple], side: str, sl: float, tp1: float) -> str:
    return _first_touch(
        [(float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
         for row in future],
        side, sl, tp1,
    )


class KronosPathForecaster:
    def __init__(
        self,
        paths: int = 128,
        batch_size: int = 16,
        temperature: float = 1.0,
        top_p: float = 0.9,
        device: str = "cpu",
        seed: int = 20261120,
    ):
        if paths < 1 or batch_size < 1 or temperature <= 0 or not 0 < top_p <= 1:
            raise ValueError("INVALID_KRONOS_SAMPLING_CONFIG")
        self.paths = int(paths)
        self.batch_size = min(int(batch_size), self.paths)
        self.temperature = float(temperature)
        self.top_p = float(top_p)
        self.device = device
        self.seed = int(seed)
        self.predictor = None
        self.load_latency_ms: float | None = None
        self.forecast_candles_total = 0
        self.geometry_repairs_total = 0

    def load(self) -> None:
        if self.predictor is not None:
            return
        started = time.perf_counter()
        import pandas as pd
        import torch
        from model import Kronos, KronosPredictor, KronosTokenizer

        torch.manual_seed(self.seed)
        tokenizer = KronosTokenizer.from_pretrained(
            TOKENIZER_ID, revision=TOKENIZER_REVISION
        )
        model = Kronos.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
        self.predictor = KronosPredictor(
            model, tokenizer, device=self.device, max_context=CONTEXT
        )
        self.pd = pd
        self.load_latency_ms = round((time.perf_counter() - started) * 1000, 2)

    def forecast_paths(self, bars: list[tuple]) -> tuple[list[list[tuple]], float]:
        self.load()
        if len(bars) < CONTEXT:
            raise ValueError("INSUFFICIENT_KRONOS_CONTEXT")
        window = bars[-CONTEXT:]
        if any(
            int(right[0]) - int(left[0]) != FOUR_HOURS_MS
            for left, right in zip(window, window[1:])
        ):
            raise ValueError("NON_CONTIGUOUS_KRONOS_CONTEXT")
        for row in window:
            if len(row) != 6:
                raise ValueError("INVALID_KRONOS_CONTEXT_ROW")
            _validate_candle(*map(float, row[1:6]))

        pd = self.pd
        frame = pd.DataFrame(
            [
                dict(open=float(row[1]), high=float(row[2]), low=float(row[3]),
                     close=float(row[4]), volume=float(row[5]))
                for row in window
            ]
        )
        last_ts = int(window[-1][0])
        x_ts = pd.Series(pd.to_datetime([int(row[0]) for row in window], unit="ms", utc=True))
        y_ts = pd.Series(pd.to_datetime(
            [last_ts + FOUR_HOURS_MS * step for step in range(1, HORIZON + 1)],
            unit="ms", utc=True,
        ))

        # Leave amount absent so Kronos applies its documented volume*mean-OHLC fallback.
        # The ATLAS artifact does not contain a uniform cross-exchange quote-amount field.
        outputs: list[list[tuple]] = []
        started = time.perf_counter()
        for start in range(0, self.paths, self.batch_size):
            size = min(self.batch_size, self.paths - start)
            forecasts = self.predictor.predict_batch(
                df_list=[frame.copy() for _ in range(size)],
                x_timestamp_list=[x_ts.copy() for _ in range(size)],
                y_timestamp_list=[y_ts.copy() for _ in range(size)],
                pred_len=HORIZON,
                T=self.temperature,
                top_p=self.top_p,
                sample_count=1,
                verbose=False,
            )
            if not isinstance(forecasts, list) or len(forecasts) != size:
                raise ValueError("UNEXPECTED_KRONOS_BATCH_RESULT")
            for forecast in forecasts:
                if len(forecast) != HORIZON:
                    raise ValueError("UNEXPECTED_KRONOS_HORIZON")
                columns = ("open", "high", "low", "close", "volume")
                if any(name not in forecast.columns for name in columns):
                    raise ValueError("MISSING_KRONOS_OHLCV_COLUMN")
                path = []
                for i in range(HORIZON):
                    raw_candle = tuple(float(forecast.iloc[i][name]) for name in columns)
                    candle, repaired = _project_forecast_candle(*raw_candle)
                    self.forecast_candles_total += 1
                    self.geometry_repairs_total += int(repaired)
                    path.append(candle)
                outputs.append(path)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if len(outputs) != self.paths:
            raise ValueError("KRONOS_PATH_COUNT_MISMATCH")
        return outputs, latency_ms


class RandomWalkPathForecaster:
    """Driftless empirical OHLC bootstrap with the same context and horizon."""

    def __init__(self, paths: int, seed: int):
        import numpy as np
        self.paths = paths
        self.rng = np.random.default_rng(seed)

    def forecast_paths(self, bars: list[tuple]) -> list[list[tuple]]:
        window = bars[-CONTEXT:]
        if len(window) < 3:
            raise ValueError("INSUFFICIENT_RANDOM_WALK_CONTEXT")
        body, upper, lower, volumes = [], [], [], []
        for row in window:
            _, open_, high, low, close, volume = row
            body.append(math.log(close / open_))
            upper.append(math.log(high / max(open_, close)))
            lower.append(math.log(min(open_, close) / low))
            volumes.append(float(volume))
        mean_body = statistics.mean(body)
        result = []
        for _ in range(self.paths):
            current = float(window[-1][4])
            path = []
            for _step in range(HORIZON):
                i = int(self.rng.integers(0, len(window)))
                open_ = current
                close = open_ * math.exp(body[i] - mean_body)
                high = max(open_, close) * math.exp(upper[i])
                low = min(open_, close) * math.exp(-lower[i])
                path.append((open_, high, low, close, volumes[i]))
                current = close
            result.append(path)
        return result


def _oos_bounds(windows: list[dict[str, Any]]) -> list[tuple[int, int]]:
    bounds = [(_time_ms(w["test_start"]), _time_ms(w["test_end"])) for w in windows]
    if len(bounds) != 3 or any(start >= end for start, end in bounds):
        raise ValueError("BASELINE_MISSING_THREE_VALID_OOS_WINDOWS")
    if any(bounds[i][1] > bounds[i + 1][0] for i in range(2)):
        raise ValueError("OVERLAPPING_OOS_WINDOWS")
    return bounds


def _load_dataset(path: Path, expected_hash: str) -> tuple[dict[str, Any], list[tuple], list[tuple[int, float]]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    bars = [tuple([int(row[0]), *[float(value) for value in row[1:6]]]) for row in obj["bars"]]
    rates = [(int(row[0]), float(row[1])) for row in obj["funding_rates"]]
    actual_hash = dataset_sha256(obj["symbol"], obj["provider"], bars, rates)
    if actual_hash != expected_hash or actual_hash != obj.get("dataset_sha256"):
        raise ValueError(f"DATASET_HASH_MISMATCH_{obj.get('symbol')}")
    return obj, bars, rates


class ShadowFilter:
    def __init__(
        self,
        kronos: KronosPathForecaster,
        random_walk: RandomWalkPathForecaster,
        bars: list[tuple],
        bounds: list[tuple[int, int]],
        threshold: float,
    ):
        if not 0 < threshold < 1:
            raise ValueError("INVALID_SL_RISK_THRESHOLD")
        self.kronos = kronos
        self.random_walk = random_walk
        self.bars = bars
        self.by_ts = {int(row[0]): row for row in bars}
        self.bounds = bounds
        self.threshold = threshold
        self.records: list[dict[str, Any]] = []
        self.bypassed_horizon = 0
        self.inference_latency_total = 0.0

    def __call__(self, setup: dict[str, Any], context: list[tuple]) -> bool:
        signal_ms = _time_ms(setup["signal_at"])
        interval = next((b for b in self.bounds if b[0] <= signal_ms < b[1]), None)
        if interval is None:
            return True
        future_times = [signal_ms + FOUR_HOURS_MS * i for i in range(HORIZON)]
        if future_times[-1] + FOUR_HOURS_MS > interval[1]:
            self.bypassed_horizon += 1
            return True
        future = [self.by_ts.get(ts) for ts in future_times]
        if any(row is None for row in future):
            raise ValueError("OOS_DATA_GAP_AFTER_SETUP")

        side, sl, tp1 = _validate_setup(setup)
        paths, latency_ms = self.kronos.forecast_paths(context)
        rw_paths = self.random_walk.forecast_paths(context)
        self.inference_latency_total += latency_ms
        model_risk = _path_risk(paths, side, sl, tp1)
        rw_risk = _path_risk(rw_paths, side, sl, tp1)
        actual = _actual_outcome(future, side, sl, tp1)
        reject_model = model_risk["sl_first_probability"] >= self.threshold
        reject_rw = rw_risk["sl_first_probability"] >= self.threshold
        self.records.append({
            "symbol": setup["symbol"],
            "signal_id": setup["id"],
            "signal_at": setup["signal_at"],
            "side": side,
            "model_sl_first_probability": model_risk["sl_first_probability"],
            "model_mc_standard_error": model_risk["sl_probability_mc_se"],
            "model_tp1_first_probability": model_risk["tp1_first_probability"],
            "model_unresolved_probability": model_risk["unresolved_probability"],
            "random_walk_sl_first_probability": rw_risk["sl_first_probability"],
            "actual_path_outcome": actual,
            "actual_sl_first": actual == "SL",
            "model_rejects": reject_model,
            "random_walk_rejects": reject_rw,
            "latency_ms": latency_ms,
            "path_count": self.kronos.paths,
        })
        return not reject_model


def _calibration(rows: list[dict[str, Any]], probability_key: str) -> dict[str, Any]:
    settled = [r for r in rows if r["actual_path_outcome"] in ("SL", "TP1")]
    if not settled:
        return {"settled_origins": 0, "brier_score": None, "bins": []}
    brier = statistics.mean(
        (float(r[probability_key]) - float(r["actual_sl_first"])) ** 2 for r in settled
    )
    bins = []
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        group = [
            r for r in settled
            if low <= float(r[probability_key]) < high
            or (index == 9 and float(r[probability_key]) == 1.0)
        ]
        if group:
            bins.append({
                "range": [round(low, 1), round(high, 1)],
                "origins": len(group),
                "mean_predicted": round(statistics.mean(float(r[probability_key]) for r in group), 6),
                "observed_sl_first_rate": round(
                    sum(bool(r["actual_sl_first"]) for r in group) / len(group), 6
                ),
            })
    return {
        "settled_origins": len(settled),
        "unresolved_origins": sum(r["actual_path_outcome"] == "OPEN" for r in rows),
        "brier_score": round(brier, 8),
        "bins": bins,
    }


def _diagnostics(rows: list[dict[str, Any]], reject_key: str) -> dict[str, Any]:
    rejected = [r for r in rows if r[reject_key]]
    settled_rejected = [r for r in rejected if r["actual_path_outcome"] in ("SL", "TP1")]
    actual_sl = [r for r in rows if r["actual_path_outcome"] == "SL"]
    return {
        "forecast_origins": len(rows),
        "rejected_setups": len(rejected),
        "actual_sl_first_origins": len(actual_sl),
        "rejected_actual_sl_first_origins": sum(r["actual_path_outcome"] == "SL" for r in rejected),
        "stop_recall": (
            round(sum(r["actual_path_outcome"] == "SL" for r in rejected) / len(actual_sl), 6)
            if actual_sl else None
        ),
        "rejection_precision_on_settled": (
            round(sum(r["actual_path_outcome"] == "SL" for r in settled_rejected) / len(settled_rejected), 6)
            if settled_rejected else None
        ),
    }


def evaluate(
    summary_path: Path,
    data_dir: Path,
    out_dir: Path,
    symbols: list[str],
    paths: int = 128,
    batch_size: int = 16,
    threshold: float = 0.5,
    device: str = "cpu",
    seed: int = 20261120,
) -> dict[str, Any]:
    baseline = json.loads(summary_path.read_text(encoding="utf-8"))
    if baseline.get("verdict") != "EMPIRICAL_RESEARCH_COMPLETE":
        raise ValueError("BASELINE_NOT_EMPIRICALLY_ACCEPTED; KRONOS_SHADOW_NOT_STARTED")
    windows = baseline.get("oos_windows")
    bounds = _oos_bounds(windows if isinstance(windows, list) else [])
    kronos = KronosPathForecaster(paths, batch_size, device=device, seed=seed)
    output: dict[str, Any] = {
        "status": "SHADOW_ONLY",
        "model": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "tokenizer": TOKENIZER_ID,
        "tokenizer_revision": TOKENIZER_REVISION,
        "kronos_code_revision": KRONOS_CODE_REVISION,
        "license": "MIT",
        "market_type": "LINEAR_USDT_PERPETUAL",
        "timeframe": "4h",
        "horizon_bars": HORIZON,
        "context_bars": CONTEXT,
        "paths_per_setup": paths,
        "batch_size": batch_size,
        "sampling": {"temperature": 1.0, "top_p": 0.9, "seed": seed, "device": device},
        "sl_risk_threshold": threshold,
        "threshold_note": "Freeze before OOS evaluation; never tune on test outcomes.",
        "oos_windows": windows,
        "symbols": {},
    }
    all_records: list[dict[str, Any]] = []
    baseline_all: list[dict[str, Any]] = []
    kronos_all: list[dict[str, Any]] = []
    random_walk_all: list[dict[str, Any]] = []

    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        expected = baseline.get("symbols", {}).get(symbol)
        if not expected or expected.get("verdict") != "EMPIRICAL_RESEARCH":
            raise ValueError(f"SYMBOL_NOT_EMPIRICALLY_ACCEPTED_{symbol}")
        expected_hash = expected.get("dataset_sha256")
        if not expected_hash:
            raise ValueError(f"BASELINE_HASH_MISSING_{symbol}")
        obj, bars, rates = _load_dataset(data_dir / f"{symbol}.json", expected_hash)
        if obj.get("provider") != expected.get("provider"):
            raise ValueError(f"PROVIDER_MISMATCH_{symbol}")
        if not obj.get("funding_complete") or not expected.get("coverage", {}).get("funding_complete"):
            raise ValueError(f"FUNDING_NOT_EMPIRICAL_{symbol}")

        provider = obj["provider"]
        gate = ShadowFilter(
            kronos, RandomWalkPathForecaster(paths, seed), bars, bounds, threshold
        )
        base_trades: list[dict[str, Any]] = []
        model_trades: list[dict[str, Any]] = []
        rw_trades: list[dict[str, Any]] = []
        for window in windows:
            start_ms, end_ms = _time_ms(window["test_start"]), _time_ms(window["test_end"])
            base_trades += backtest.simulate(
                symbol, bars, rates, start_ms, end_ms, provider, "empirical"
            )
            model_trades += backtest.simulate(
                symbol, bars, rates, start_ms, end_ms, provider, "empirical",
                setup_filter=gate,
            )
            decisions = {r["signal_at"]: r["random_walk_rejects"] for r in gate.records}

            def rw_filter(setup: dict[str, Any], _context: list[tuple]) -> bool:
                return not decisions.get(setup["signal_at"], False)

            rw_trades += backtest.simulate(
                symbol, bars, rates, start_ms, end_ms, provider, "empirical",
                setup_filter=rw_filter,
            )

        baseline_all += base_trades
        kronos_all += model_trades
        random_walk_all += rw_trades
        all_records += gate.records
        output["symbols"][symbol] = {
            "provider": provider,
            "dataset_sha256": expected_hash,
            "funding_mode": "empirical",
            "baseline_metrics": backtest.metrics(base_trades),
            "kronos_filtered_metrics": backtest.metrics(model_trades),
            "random_walk_filtered_metrics": backtest.metrics(rw_trades),
            "kronos_path_risk_calibration": _calibration(
                gate.records, "model_sl_first_probability"
            ),
            "random_walk_path_risk_calibration": _calibration(
                gate.records, "random_walk_sl_first_probability"
            ),
            "kronos_filter_diagnostics": _diagnostics(gate.records, "model_rejects"),
            "random_walk_filter_diagnostics": _diagnostics(gate.records, "random_walk_rejects"),
            "bypassed_without_complete_horizon": gate.bypassed_horizon,
        }

    output["baseline_aggregate_metrics"] = backtest.metrics(baseline_all)
    output["kronos_filtered_aggregate_metrics"] = backtest.metrics(kronos_all)
    output["random_walk_filtered_aggregate_metrics"] = backtest.metrics(random_walk_all)
    output["kronos_path_risk_calibration"] = _calibration(
        all_records, "model_sl_first_probability"
    )
    output["random_walk_path_risk_calibration"] = _calibration(
        all_records, "random_walk_sl_first_probability"
    )
    output["forecast_origins"] = len(all_records)
    output["mean_inference_latency_ms_per_setup"] = (
        round(kronos.inference_latency_total / len(all_records), 2) if all_records else None
    )
    output["model_load_latency_ms"] = kronos.load_latency_ms
    output["forecast_candles_total"] = kronos.forecast_candles_total
    output["forecast_candle_geometry_repairs"] = kronos.geometry_repairs_total
    output["forecast_candle_geometry_repair_rate"] = (
        round(kronos.geometry_repairs_total / kronos.forecast_candles_total, 6)
        if kronos.forecast_candles_total else None
    )
    output["geometry_policy"] = (
        "Generated High/Low are expanded only as needed to enclose unchanged Open/Close; "
        "all repairs are counted. Nonfinite, nonpositive, or negative-volume forecasts fail closed."
    )
    output["promotion"] = (
        "NOT_AUTOMATIC; require sufficient sample size, calibrated path risk, "
        "and preregistered OOS improvement in Net R and drawdown over both comparators."
    )
    output["path_risk_definition"] = (
        "Fraction of independent generated OHLC paths that touch SL before TP1 "
        "within 12 bars; realized OOS OHLC uses SL-first same-bar ordering."
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "path_origins.json").write_text(
        json.dumps(all_records, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Kronos-small only after empirical baseline acceptance."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--symbols", default="BTC,ETH,SOL")
    parser.add_argument("--paths", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=20261120)
    parser.add_argument("--out", type=Path, default=Path("atlas_kronos_shadow_results"))
    args = parser.parse_args()
    result = evaluate(
        args.baseline, args.data_dir, args.out, args.symbols.split(","),
        paths=args.paths, batch_size=args.batch_size, threshold=args.threshold,
        device=args.device, seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
