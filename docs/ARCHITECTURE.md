# ATLAS AI — Architecture, Operating Contract & Evidence

**Audited baseline:** 2026-11-21. This document distinguishes code that exists, deployed production configuration observed, and capabilities that still require verification.

## Invariants

1. **Analysis Plane — GitHub:** scheduled `.github/workflows/atlas.yml` executes guarded HOURLY/DEEP4H/DAILY16/NIGHTLY23 analysis. The guard is `atlas_schedule_guard.py`; storage-only manual dispatch must not send Telegram messages or execute orders.
2. **Source of truth — Supabase PostgreSQL:** snapshots, risk audit, scheduler leases, signal lifecycle, delivery receipts and research evidence. Avoid using runner-local JSON/SQLite as canonical state.
3. **Chat Plane — Supabase Edge:** `hyper-endpoint` processes Telegram webhook/chat requests; `atlas-web` serves public read-only dashboard APIs. GitHub **must not** poll the Telegram inbox.
4. **Presentation — GitHub Pages:** `atlas-dashboard.html` plus `assets/` render snapshots. Charts from TradingView/OKX/CoinGlass are separately attributed, not silently treated as CoinGecko spot.
5. **Execution — Paper:** the inspected workflow has `ATLAS_EXECUTION_MODE: PAPER` and `ATLAS_LIVE_TRADING: "0"`. Production trading must remain disabled until independently approved controls and evidence exist.

## Verified data-contract issue and repair

At the time of audit, `public.atlas_hourly_signal_snapshots` contained `TOP10`, `PERSONAL` and `METAL` asset groups, but `/api/live-terminal` filtered exclusively on non-existent `CRYPTO`. The endpoint also misclassified a mixed `atlas_market_snapshots` result as metals. **This was a field-contract defect, not proof that spot ingestion was absent.**

Edge Function `atlas-web` **v80** corrected the public grouping:
- Prefer stored spot observations with `payload.source="coingecko"` and positive prices.
- Accept separate `TOP10` / `PERSONAL` hourly-cache fallbacks **with `source_verified=false`**, not as confirmed CoinGecko observations.
- Classify `GOLD`, `SILVER`, `COPPER` or matching metal symbols as metals, never as the crypto spot universe.
- Retain each observation's original timestamp; no invented price change or inferred derivative funding.
- Reject empty coverage with `INSUFFICIENT_DATA` and mark records as `DELAYED` beyond the existing age threshold.

**Validation status:** Supabase confirmed deployment of v80 and the source was compared byte-for-byte with the repository fix. A fresh end-to-end HTTP response was not available to the audit session. The endpoint's runtime output and live user interface still need confirmation.

## Data source and quality rules

| Data family | Primary | Backups / distinction | Must be proven |
| --- | --- | --- | --- |
| Crypto spot quotes | CoinGecko | Binance only where explicitly attributed | Source, symbol, price > 0, UTC capture time, TTL |
| Perpetuals / derivatives | Venue-specific OKX observations and CoinGlass where actually available | OKX is not CoinGlass aggregate | Venue, symbol/contract, funding interval, OI unit, age |
| Tehran stocks and funds | ATLAS Iran ingestion (verify upstream attribution per row) | No fictitious TSE or fund NAV | Market day, unit (IRR/toman), price/NAV time |
| Metals and FX | Clearly labeled market snapshots | External provider only with recorded provenance | XAU/XAG unit, USD/IRR normalization, metal fineness, TTL |

**Availability vs. validity:** a table with rows is not equivalent to a fresh source of verified prices. Surface `INSUFFICIENT_DATA`, `DELAYED`, missing provenance and source-specific outage separately.

## Release and test policy

- Create a feature branch, compare the source with the deployed function, inspect schema contract and data provenance, and review the diff.
- Run fast unit/safety tests plus Python compilation before merging. For Edge Function changes, verify the actual endpoint and Edge logs after deployment. **A successful deploy alone is not a smoke test.**
- Keep historical OOS, walk-forward, ablation, slippage/funding stress and shadow decisions separately. A shadow-positive result must **not** activate live trading.
- CI should not require production credentials, spam Telegram or place orders.
- Record release version, commit, source hash, migration/Edge version and rollback point. For production rename, audit GitHub Pages configuration, external webhooks, clone references, badges and repository secrets first.

## Backtest performance publication gate

`atlas_futures_backtest_18m.py` contains historical 4H research logic; `atlas_futures_costs.py` explicitly models fees, slippage and funding as conservative **scenarios**. Existence of these files does not establish statistically significant returns.

Before advertising performance, attach: dataset snapshot/hash; commit; instrument/venue; fees, slippage and funding; no-lookahead tests; train/validation/OOS and walk-forward boundaries; number of trades; net CAGR/returns; max drawdown; Sharpe with assumptions; turnover; failure cases; and date of independent review. Leave metrics as **Not verified** until then.

## Maintenance and reorganization

Do **not** bulk-move the current root Python modules into `atlas/` while `atlas.yml`, `bot.py`, tests and implicit imports use root paths. Instead:
1. Build an import/dependency inventory and capture an unmodified baseline of the safety suite.
2. Introduce packaging shims with backwards-compatible entrypoints and a CI matrix.
3. Move tests under `tests/` only after import and workflow references are updated.
4. Move unused/versioned modules only after code search, shadow comparison and measured non-use.

**Repository naming proposal:** `atlas-ai-platform`, after auditing downstream Pages URLs and integrations. GitHub redirects do not guarantee all Pages, badges, Actions checkout paths and deployment hooks keep working.

## Open gaps

- Verify the **v80 runtime response** and front-end source labels against representative CoinGecko and fallback data.
- Chart funding/OI history with explicitly sourced time series and gap handling; do not replace missing history with interpolation presented as fact.
- Add reliable CI and reusable tests for source grouping, stale quote rejection and never-execute guards.
- Verify deployment/Pages routing and single product navigation on actual mobile devices.
- Document the currently active paper strategy version and evidence per instrument, rather than making unsubstantiated performance claims.
