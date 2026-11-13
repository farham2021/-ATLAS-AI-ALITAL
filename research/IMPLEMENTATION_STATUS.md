# ATLAS accelerated development — implementation register

## Verified repository additions
- `research/quant-core.cjs`: strict OHLCV validation, SMA/EMA/RSI/MACD/ATR, stale-data gate, cost-aware long/flat research backtest.
- `tests/atlas-quant-core.test.cjs`: data validation, warm-up, freshness, costs and drawdown assertions.
- `.github/workflows/atlas-web-e2e.yml`: runs quantitative tests before browser smoke tests.

## Existing infrastructure (inspected; preserved)
- Supabase `atlas_market_snapshots` stores timestamped prices but does not itself provide validated OHLCV candles.
- `atlas_signal_audit` stores directional hit, horizon, and realized return; `atlas_signal_lifecycle` stores state and trade levels.
- Existing PWA, Telegram delivery, and database tables remain unchanged by this research module.

## Not complete — do not market as production-ready
1. OHLCV provider adapters, source provenance, rate limits, symbol mapping, gap detection, and historical ingestion.
2. Out-of-sample / walk-forward validation, leakage controls, multiple-testing correction, execution realism, performance statistics.
3. Portfolio correlation, VaR/CVaR, concentration and liquidity stress.
4. Fundamentals, economic calendar, news credibility, and explainable impact analysis.
5. Authenticated multi-tenant accounts, subscriptions, payments, billing, privacy/security review.
6. End-to-end browser/API/Telegram production verification and live monitoring.

## Deployment safety
Research calculations are shadow-only and cannot emit production signals or place trades. Do not change existing thresholds, credentials, data, or Telegram routing without explicit validation.
