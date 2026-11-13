# ATLAS architecture integration — research-first

## Architecture (existing systems preserved)
GitHub Analysis Plane -> Supabase DB source of truth -> Edge Function Chat Plane -> PWA / Telegram. All new modules in this change are **offline research modules** and cannot change live signals, orders, billing, Telegram or database rows.

## Capability matrix
| Inspiration | ATLAS implementation | Current acceptance |
|---|---|---|
| OpenBB provider adapters | `providerRegistry` with ordered failover, validation and freshness | Interface implemented; live provider adapters not connected |
| OpenBB OHLCV normalization | `normalizeCandles` and freshness gate | Implemented for supplied rows; real OHLCV ingestion missing |
| OpenCharts trading desk | Existing TradingView widgets and PWA | Existing UI only; drawing, paper trading and journal not implemented |
| OpenCharts breakout alert | Early warning audit of recorded directional signals | Historical audit helper only; no production trigger |
| VectorBT backtesting | Cost-aware EMA research backtest | Implemented baseline; not vectorized parameter search |
| VectorBT walk-forward | `strategyTournament` explicitly marks missing proper isolation | **Not implemented**; do not claim validated |
| QuantStats performance | `performance` total return, CAGR, drawdown, Sharpe, Sortino, Calmar | Implemented for supplied periodic returns; not yet linked to live audit |
| QuantStats client report | `clientReport` provenance-aware JSON output | Prototype only; no PDF, subscription or tenant access |

## ATLAS differentiators
1. Early Warning Score: `signalScore` with explicit factor weights and evidence gate. Score is **not** a probability.
2. Cross-Market Radar: `crossMarketRadar` correlates aligned timestamped returns, refuses insufficient overlap.
3. Strategy Tournament: `strategyTournament` demonstrates comparison but explicitly warns of in-sample contamination; **not a production selector**.
4. Client Intelligence: `clientReport` creates a research JSON with source and disclaimer, not a customer portal.

## Acceptance requirements for production
- Authenticated provider connections, historical OHLCV, provenance, quality and rate limits.
- Point-in-time feature calculation and strict train/test/walk-forward isolation; fees, spread, slippage, funding and liquidity.
- Signal lifecycle linkage, calibration, precision/recall, alert lead-time and false-alarm evaluation.
- Risk engine with covariance, VaR/CVaR, exposure and stress tests.
- Chart drawing, simulated orders and auditable journal.
- Real multi-tenant authentication and RLS, plans, payments, security review and retention controls.
- Passing unit, API, PWA and Telegram end-to-end tests.
- No deployment to production alerts until explicit shadow acceptance.

## Repository files
`research/quant-core.cjs`, `research/atlas-intelligence.cjs`, `tests/atlas-quant-core.test.cjs`, `tests/atlas-intelligence.test.cjs`, `.github/workflows/atlas-web-e2e.yml`.
