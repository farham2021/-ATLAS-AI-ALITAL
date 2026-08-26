#!/usr/bin/env python3

from pathlib import Path
import ast
import re
import sys

BOT = Path("bot.py")


def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)


if not BOT.exists():
    fail("bot.py not found")


source = BOT.read_text(encoding="utf-8")

try:
    tree = ast.parse(source, filename=str(BOT))
except SyntaxError as exc:
    fail(f"bot.py syntax error: {exc}")


# ============================================================
# REAL IMPORT CHECK
# Only actual Python imports are inspected.
# Comments and strings are intentionally ignored.
# ============================================================

legacy_imports = []

for node in ast.walk(tree):

    if isinstance(node, ast.Import):

        for alias in node.names:
            if alias.name == "bot":
                legacy_imports.append("import bot")

    elif isinstance(node, ast.ImportFrom):

        if node.module == "bot":
            legacy_imports.append("from bot import ...")


if legacy_imports:
    fail(
        "Obsolete wrapper/import detected: "
        + ", ".join(sorted(set(legacy_imports)))
    )


# ============================================================
# FUNCTION CONTRACT
# ============================================================

functions = {
    node.name
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}


required_functions = [
    "build_report",
    "build_personal_report",
    "build_two_engine_reports",
    "atlas_engine_mode",
    "analyze_coin",
    "main",
    "tradingview_chart_url",
    "build_price_snapshot",
    "send_price_snapshot",
    "fetch_usdt_toman_public",
    "fetch_snapshot_results",
    "_automatic_run_plan",
    "generate_csv_report",
    "send_csv_report",
    "_best_setup_block",
]


missing = [
    name
    for name in required_functions
    if name not in functions
]


if missing:
    fail(
        "Missing required functions: "
        + ", ".join(missing)
    )


# ============================================================
# VERSION
# ============================================================

if not re.search(
    r'^VERSION\s*=\s*["\']ATLAS v11\.2',
    source,
    re.MULTILINE,
):
    fail("ATLAS v11.2 VERSION marker not found")


# ============================================================
# CORE ARCHITECTURE
# ============================================================

checks = {

    "two-engine":
        all(
            x in source
            for x in ("MARKET", "PERSONAL", "BOTH")
        ),

    "personal portfolio":
        "PERSONAL" in source,

    "dynamic radar":
        "DYNAMIC" in source.upper(),

    "metals":
        all(
            x in source
            for x in ("GOLD", "SILVER", "COPPER")
        ),

    "closed candle":
        all(
            x in source
            for x in (
                "strip_incomplete",
                "candle_is_closed",
            )
        ),

    "3H snapshot":
        all(
            x in source
            for x in (
                "fetch_snapshot_results",
                "send_price_snapshot",
            )
        ),

    "automatic scheduler":
        all(
            x in source
            for x in (
                "_automatic_run_plan",
                "dt.hour % 3 == 0",
                "dt.hour % 4 == 0",
            )
        ),

    "Telegram":
        all(
            x in source
            for x in (
                "telegram_preflight",
                "telegram_send_one",
                "send_report",
            )
        ),

    "retry":
        "send_with_retry" in source,

    "CSV":
        all(
            x in source
            for x in (
                "generate_csv_report",
                "send_csv_report",
            )
        ),

    "TradingView":
        "tradingview.com/chart/?symbol=" in source,

    "public Iranian USDT":
        all(
            x in source.lower()
            for x in (
                "wallex.ir",
                "excoino.com",
                "nobitex.ir",
            )
        ),

    "no stale v10":
        not re.search(
            r'ATLAS v10|v10\.[0-9]',
            source,
            re.IGNORECASE,
        ),

    "no v12 wrapper":
        "ATLAS_v12_bot" not in source,

}


failed = [
    name
    for name, passed in checks.items()
    if not passed
]


if failed:
    fail(
        "Smoke checks failed: "
        + ", ".join(failed)
    )


print("=" * 66)
print("ATLAS AI v11.2 SMOKE TEST: PASS")
print("=" * 66)

for name in checks:
    print("PASS:", name)
