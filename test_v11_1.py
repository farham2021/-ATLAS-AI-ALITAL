#!/usr/bin/env python3

from pathlib import Path
import ast
import re

BOT = Path("bot.py")
SMOKE = Path("smoke_atlas.py")

def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)

if not BOT.exists():
    fail("bot.py not found")

if not SMOKE.exists():
    fail("smoke_atlas.py not found")

source = BOT.read_text(encoding="utf-8")
smoke = SMOKE.read_text(encoding="utf-8")

try:
    tree = ast.parse(source, filename="bot.py")
except SyntaxError as exc:
    fail(f"bot.py syntax error: {exc}")

functions = {
    node.name
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}

required_functions = {
    "build_report",
    "build_personal_report",
    "build_two_engine_reports",
    "atlas_engine_mode",
    "analyze_coin",
    "main",
    "tradingview_chart_url",
    "build_price_snapshot",
    "send_price_snapshot",
    "fetch_snapshot_results",
    "_automatic_run_plan",
    "generate_csv_report",
    "send_csv_report",
    "_best_setup_block",
    "_validate_trade_geometry",
    "send_report",
    "telegram_send_one",
    "telegram_preflight",
}

missing = sorted(required_functions - functions)

if missing:
    fail(
        "Missing required v11.2 functions: "
        + ", ".join(missing)
    )

checks = {
    "version v11.2":
        bool(re.search(
            r'VERSION\s*=\s*["\']ATLAS v11\.2',
            source
        )),

    "two engine architecture":
        all(
            x in source
            for x in ("MARKET", "PERSONAL", "BOTH")
        ),

    "fixed personal portfolio":
        "ATLAS_PERSONAL_ASSETS" in source,

    "dynamic top 30":
        "DYNAMIC_TOP30" in source
        or "dynamic30" in source,

    "metals":
        all(
            x in source
            for x in ("GOLD", "SILVER", "COPPER")
        ),

    "closed candle":
        "strip_incomplete" in source
        and "candle_is_closed" in source,

    "trade geometry":
        "_validate_trade_geometry" in source,

    "telegram retry":
        "TELEGRAM_MAX_RETRIES" in source
        or "send_with_retry" in source,

    "telegram private":
        "TELEGRAM_CHAT_ID" in source,

    "telegram supergroup":
        "TELEGRAM_GROUP_CHAT_ID" in source,

    "telegram send report":
        "send_report" in source,

    "telegram preflight":
        "telegram_preflight" in source,

    "safe telegram split":
        "split_telegram" in source,

    "csv export":
        "generate_csv_report" in source
        and "send_csv_report" in source,

    "snapshot":
        "send_price_snapshot" in source
        and "build_price_snapshot" in source,

    "three hour scheduler":
        "_automatic_run_plan" in source
        and "dt.hour % 3 == 0" in source,

    "four hour scheduler":
        "_automatic_run_plan" in source
        and "dt.hour % 4 == 0" in source,

    "no automatic trading":
        "No automatic orders" in source
        or "No automatic order" in source,

    "no obsolete v12 wrapper":
        "import bot as engine" not in source,

    "no obsolete ATLAS_v12_bot":
        "ATLAS_v12_bot" not in source,

    "no legacy from bot import":
        "from bot import" not in source,
}

failed = [
    name
    for name, passed in checks.items()
    if not passed
]

if failed:
    print("=" * 70)
    print("ATLAS AI v11.2 TEST STATUS: FAIL")
    print("=" * 70)

    for name in failed:
        print("FAIL:", name)

    raise SystemExit(1)

print("=" * 70)
print("ATLAS AI v11.2 TEST STATUS: PASS")
print("=" * 70)

for name in checks:
    print("PASS:", name)

print()
print("ATLAS v11.2 core architecture validated.")
