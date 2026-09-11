ATLAS v11.5 Phase 3.11.7 MULTIUSER SAFE

Use:
- ATLAS_bot_v11.5_PHASE3_11_7_MULTIUSER_SAFE.py -> rename to bot.py
- atlas_desk.py -> keep beside bot.py
- atlas_execution.py -> keep beside bot.py
- ATLAS_PHASE3_11_7_MULTIUSER_SAFE.yml -> .github/workflows/atlas.yml
- ATLAS_PHASE3_11_7_SUPABASE_MIGRATION.sql -> run once in Supabase SQL Editor

Architecture preserved:
- Canonical ATLAS Decision / Entry / SL / TP / Confidence / MTF / Backtest unchanged.
- Exact Top10 + Personal + Metals scope unchanged.
- Daily16 / Nightly / Book Scan architecture unchanged.
- ZEC retained in Personal and fixed portfolio output.
- Execution remains separate from Desk.

Phase 3.11.7 changes:
1) Multi-user Atlas Desk persists users/meta in Supabase.
2) New atlas_desk_deliveries ledger prevents repeated hourly signal spam.
3) Hourly/Deep Desk DM sends only NEW canonical ENTRY signals.
4) Daily16 Desk DM is deduped to once per Tehran calendar day per user.
5) Capital changes are acknowledged only after the Supabase write succeeds.
6) Telegram offset advances only after the Supabase meta write succeeds.
7) Backtest handoff to Execution is fail-closed.
8) Safe Execution persistence/lifecycle from prior cleanup restored.
9) LIVE remains deliberately blocked while generic server-side protective
   orders are required and not exchange-specifically implemented.
10) Trade API secrets are removed from the scheduled PAPER workflow.
11) Workflow/version labels unified to Phase 3.11.7.

Operational note:
For Telegram chat_member membership updates, the bot should be present in the
target supergroup with the permissions needed to receive member-status updates.
Users must initiate the private bot chat (/start) before the bot can DM them.
