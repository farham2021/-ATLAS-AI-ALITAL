# ATLAS Architecture & Hard Engineering Rules

This document records the current engineering contract for ATLAS. A proposal
that changes an invariant must update this file and include evidence from the
research artifact. Research adapters remain separate from the live signal path.

## 1. Architecture and data integrity

- **System ownership:** GitHub Actions is the Analysis Plane, Supabase is the
  source of truth, and the Supabase Edge Function/Webhook is the Chat Plane.
  Do not add GitHub Telegram inbox polling.
- **No fabricated market data:** reject a signal when the selected provider
  cannot supply valid, closed, fresh candles. A provider fallback is allowed
  only when it supplies the same explicitly identified market type and the
  selected source is recorded with the data. Never relabel spot candles as
  perpetual data.
- **Futures data parity:** the ATLAS Futures signal engine and its futures
  backtest use 4-hour linear USDT perpetual candles. Preserve exchange,
  instrument ID, timeframe, and funding provenance. Reject a setup when the
  latest closed candle is stale or the required candle history has gaps.
- **Conservative bar ordering:** when one OHLC candle touches both SL and TP,
  score the stop first. This is a worst-case bar-level assumption, not a claim
  about the actual intrabar path.
- **Funding accounting:** use signed, settled funding events and their actual
  timestamps when available. Never assume every perpetual contract settles
  exactly every eight hours. If a scenario funding rate is used because actual
  history is incomplete, label the result `SCENARIO_ONLY_NOT_ACCEPTED`.
- **Iran-market units:** conversion between rial and toman must use explicit
  source/unit metadata. Never infer the unit from the magnitude of a number.
- **Secrets and delivery:** never commit API keys or user tokens. Keep
  diagnostics separate from market alerts and record delivery receipts per
  destination.

## 2. Backtest and OOS protocol

- **Fixed-parameter windows:** for an 18-month history, use three complete
  cycles of four months of context followed by two months of OOS evaluation.
  The context is not a training period unless a documented fitting step is
  actually run. The strategy parameters remain frozen in the current protocol.
- **Boundary semantics:** serialize each `[test_start, test_end)` interval.
  A trade is counted in a window only when its signal and completed outcome
  fall within that same test interval. Exclude or report unsettled trades at
  the boundary; do not settle them with prices from the next window.
- **Provenance:** hash the complete canonical OHLCV and funding dataset,
  including provider, instrument, and timeframe. Put the per-window dates,
  data hash, funding coverage, cost assumptions, strategy version, and sample
  count in the baseline artifact. Do not use one trailing `oos_start` field to
  describe multiple disjoint windows.
- **Costs and metrics:** report gross R and Net R separately. Net R includes
  round-trip fees, slippage assumptions, and signed funding cash flows. Mark
  assumed slippage as a scenario rather than an actual fill. Win rate alone is
  insufficient; report trade count, mean Net R, profit factor, and maximum
  drawdown in R.
- **Acceptance:** incomplete candles, incomplete empirical funding, fewer
  than the configured minimum OOS trade count, or an incomplete window cannot
  be labeled as an empirical baseline.

## 3. Forecast research and TimesFM

- **Shadow isolation:** TimesFM and any other unvalidated forecast model may
  read the exact baseline dataset and write a separate research artifact. It
  must not change live setup generation, leverage, delivery, or execution.
- **Allowed self-hosted model:** evaluate TimesFM 2.5 weights under their
  Apache-2.0 terms. Do not self-host TimesFM 3.0 weights for commercial or
  production use; review the current model license before changing versions.
- **Quantile meaning:** a 10th/90th quantile forecast is a marginal forecast
  for a specific horizon. It is not a calibrated probability that price will
  touch an SL at any point across a multi-candle path. Report horizon-wise
  quantile coverage and assess SL-hit filtering separately against realized
  trades.
- **Comparators:** use the same perpetual candles, funding, OOS intervals,
  strategy, and costs for the unfiltered ATLAS baseline, TimesFM shadow, and a
  Random Walk benchmark. Report quantile loss/coverage, Net R, maximum
  drawdown, sample count, and warm inference latency. No result is promoted
  from the shadow path automatically.

## 4. Change-control checklist

Before merging a futures-engine change, record the base commit, changed files,
market-data source, OOS windows, dataset hash, funding mode, cost assumptions,
and artifact link. Keep operational UI/authentication work separate from
research-only forecast experiments.
