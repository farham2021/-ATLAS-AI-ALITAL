# ATLAS AI — delivery safety audit (2026-11-13)

Status: isolated audit branch, **not deployed**. No Supabase or Telegram mutation.

## Confirmed by reading main-branch source

- `atlas_early_risk.py:main` calls `send_digest` for the selected symbols without checking existing alert-state freshness first. Its legacy `alert()` dedupe helper is not invoked by `main()`.
- `atlas_risk_csv_digest.py:send_digest` sends sequentially to configured destinations. If the first succeeds and the second fails, rerun can duplicate the first document. No durable per-destination delivery receipt is stored.
- After all destinations succeed, `main()` writes alert state for every selected non-NONE signal. A database failure after Telegram success can cause duplicate delivery on retry.
- `atlas_schedule_guard.py` chooses Europe/Paris windows, while `.github/workflows/atlas_risk_csv_sessions.yml` explicitly schedules UTC slots corresponding to Tehran 10:30, 16:00, 21:30. These are separate schedulers and must not be conflated.
- Missing OHLCV data is excluded and logged, not interpreted as safe. Coverage must accompany every digest.

## Safe remediation sequence (no silent production change)

1. Add a Supabase append-only delivery ledger keyed by (session, digest hash, destination), with unique constraints and row-level protections. Preserve all existing tables/rows; use additive migration only after verified backup.
2. Introduce a per-destination delivery state machine (PENDING, SENDING, ACKNOWLEDGED, UNKNOWN) and persist Telegram message_id on success. A timeout after a possible send must become UNKNOWN, not an unconditional retry.
3. Keep risk signal state separate from transport receipt state; do not mark a signal delivered until the destination receipt is confirmed.
4. Add unit tests simulating first destination success + second failure, database failure after send, retry, stale OHLCV, zero coverage, and duplicate session invocation.
5. Run shadow tests and a dry-run workflow; inspect logs and current production schema before proposing a production deployment.

## Access / verification limits

GitHub source read succeeded. Supabase account selection currently returns `link_id must identify an eligible linked account`; live DB and Edge Functions cannot be verified in this session. Telegram delivery and production GitHub Actions outcomes are not verified. No accounting project changes.
