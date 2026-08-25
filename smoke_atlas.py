#!/usr/bin/env python3

from pathlib import Path
import ast
import re

BOT = Path("bot.py")

def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)

if not BOT.exists():
    fail("bot.py not found")

source = BOT.read_text(encoding="utf-8")

try:
    tree = ast.parse(source, filename="bot.py")
except SyntaxError as exc:
    fail(f"bot.py syntax error: {exc}")

functions = {
    node.name
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}

required = [
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
]

missing = [
    name for name in required
    if name not in functions
]

if missing:
    fail(
        "Missing required functions: "
        + ", ".join(missing)
    )

checks = {
    "VERSION v11.2":
        bool(re.search(
            r'^VERSION\s*=\s*["\']ATLAS v11\.2',
            source,
            re.M
        )),

    "two-engine":
        all(
            x in source
            for x in ("MARKET", "PERSONAL", "BOTH")
        ),

    "personal portfolio":
        "ATLAS_PERSONAL_ASSETS" in source,

    "dynamic top30":
        "DYNAMIC_TOP30" in source
        or "dynamic30" in source,

    "metals":
        all(
            x in source
            for x in ("GOLD", "SILVER", "COPPER")
        ),

    "TradingView":
        "tradingview.com/chart/?symbol=" in source,

    "3h snapshot":
        "send_price_snapshot" in source
        and "این پیام هر ۳ ساعت" in source,

    "snapshot path":
        "fetch_snapshot_results" in source,

    "automatic scheduler":
        "_automatic_run_plan" in source,

    "closed candle":
        "strip_incomplete" in source
        and "candle_is_closed" in source,

    "trade geometry":
        "_validate_trade_geometry" in source,

    "CSV":
        "generate_csv_report" in source
        and "send_csv_report" in source,

    "Telegram":
        "send_report" in source
        and "TELEGRAM_CHAT_ID" in source
        and "TELEGRAM_GROUP_CHAT_ID" in source,

    "Telegram retry":
        "TELEGRAM_MAX_RETRIES" in source
        or "send_with_retry" in source,

    "no forced signal":
        "NO TRADE" in source,

    "no automatic orders":
        "No automatic orders" in source
        or "No automatic order" in source,

    "no v12 wrapper":
        "import bot as engine" not in source,
}

failed = [
    name
    for name, ok in checks.items()
    if not ok
]

if failed:
    print("=" * 70)
    print("ATLAS v11.2 SMOKE TEST: FAIL")
    print("=" * 70)

    for name in failed:
        print("FAIL:", name)

    raise SystemExit(1)

compile(source, "bot.py", "exec")

print("=" * 70)
print("ATLAS v11.2 SMOKE TEST: PASS")
print("=" * 70)

for name in checks:
    print("OK:", name)
