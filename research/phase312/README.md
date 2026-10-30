# ATLAS Phase 3.12 — Shadow Evidence Lab

This isolated module borrows **research design ideas**, not source code, from
Freqtrade/FreqAI (research separation), Microsoft Qlib (versioned evaluation),
VectorBT (multi-horizon outcomes), and LEAN (event-first execution semantics).

## Current implementation
- No arbitrary 30-day waiting requirement. Use all *valid closed candles* already
  available; labels remain IMMATURE when the future horizon is unavailable.
- Evaluate LONG/SHORT trade geometry and TP-first / SL-first / AMBIGUOUS / TIMEOUT.
- Return MFE/MAE and terminal return in risk units (R).
- Cohort summaries keep model_version and regime separate.
- No network, database writes, Telegram, broker, auto-trading, or calibration.
- Run tests: `python -m unittest discover -s research/phase312 -p 'test_*.py'`

## Required before connecting live snapshots
1. Confirm OHLCV candle timestamp units (milliseconds), candle closure, and
   consistent timeframe. Never mix 1h and 4h horizons.
2. Use a stable canonical signal ID; de-duplicate repeated signal snapshots.
3. Enforce OHLCV validity, gaps, source provenance, and data freshness.
4. Preserve immutable model version, decision timestamp, source, and regime.
5. Do not treat TIMEOUT, AMBIGUOUS, or IMMATURE as wins.
6. Account for spread, fees, slippage, funding and executable price.
7. Add purged walk-forward validation and regime-aware reliability analysis
   before promoting any probability model.
8. Integrate only in research/shadow workflows after CI and human review.

**Do not merge directly into production without validation.** No existing
GitHub Analysis Plane, Supabase Chat Plane, or Telegram behavior is changed.
