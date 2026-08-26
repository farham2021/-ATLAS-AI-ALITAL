#!/usr/bin/env python3

"""
ATLAS AI v11.2
Static smoke test.

IMPORTANT:
This test validates bot.py itself.
It does NOT search for obsolete strings inside comments.
It does NOT import bot.py, so no network/API call is performed.
"""

from pathlib import Path
import ast
import re
import sys


BOT = Path("bot.py")


def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)


def read_bot():
    if not BOT.exists():
        fail("bot.py not found")

    try:
        source = BOT.read_text(encoding="utf-8")
    except Exception as exc:
        fail(f"cannot read bot.py: {exc}")

    return source


def parse_bot(source):
    try:
        return ast.parse(source, filename=str(BOT))
    except SyntaxError as exc:
        fail(f"bot.py syntax error: {exc}")


def top_level_functions(tree):
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def check_required_functions(functions):
    required = [
        "build_report",
        "build_personal_report",
        "build_two_engine_reports",
        "atlas_engine_mode",
        "analyze_coin",
        "main",
        "tradingview_chart_url",
        "build_price_snapshot",
        "_compact_scenario_row",
        "_compact_section",
        "_final_market_recommendation",
        "send_price_snapshot",
        "fetch_usdt_toman_public",
        "fetch_snapshot_results",
        "_automatic_run_plan",
        "generate_csv_report",
        "send_csv_report",
        "_best_setup_block",
    ]

    missing = [name for name in required if name not in functions]

    if missing:
        fail(
            "missing required functions: "
            + ", ".join(missing)
        )


def check_single_definitions(functions, tree):
    names = [
        "build_report",
        "build_personal_report",
        "build_two_engine_reports",
        "personal_report",
    ]

    for name in names:
        count = sum(
            1
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        )

        if count != 1:
            fail(
                f"{name} must exist exactly once "
                f"(found {count})"
            )


def check_version(source):
    if not re.search(
        r'^VERSION\s*=\s*["\']ATLAS v11\.2',
        source,
        re.MULTILINE,
    ):
        fail("VERSION is not ATLAS v11.2")


def check_no_v10(source):
    stale = re.findall(
        r"ATLAS v10(?:\.\d+)?|ATLAS v10|v10\.\d+",
        source,
        re.IGNORECASE,
    )

    if stale:
        fail(
            "stale v10 reference detected: "
            + ", ".join(sorted(set(stale)))
        )


def check_no_wrapper_imports(tree):
    """
    Check actual Python import AST nodes only.

    This deliberately ignores comments and string literals.
    """

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.strip() == "bot":
                    fail(
                        "obsolete direct import of bot detected"
                    )

        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").strip() == "bot":
                fail(
                    "obsolete 'from bot import ...' "
                    "detected"
                )


def check_two_engine(source):
    required_tokens = [
        "MARKET",
        "PERSONAL",
        "BOTH",
    ]

    for token in required_tokens:
        if token not in source:
            fail(
                f"missing two-engine token: {token}"
            )

    if "ATLAS_PERSONAL_ASSETS" not in source:
        fail("ATLAS_PERSONAL_ASSETS missing")


def check_market_personal_separation(source):
    if "market_results" not in source:
        fail("market_results missing")

    if "personal_symbols" not in source:
        fail("personal_symbols missing")


def check_metals(source):
    if "ATLAS_METALS" not in source:
        fail("ATLAS_METALS missing")

    for metal in ("GOLD", "SILVER", "COPPER"):
        if metal not in source:
            fail(f"metal missing: {metal}")


def check_tradingview(source):
    if "tradingview.com/chart/?symbol=" not in source:
        fail("TradingView chart URL support missing")


def check_snapshot(source):
    required = [
        "send_price_snapshot",
        "fetch_snapshot_results",
        "_automatic_run_plan",
        "SNAPSHOT_SYMBOLS",
        "SNAPSHOT_FLAT_THRESHOLD_PCT",
        "این پیام هر ۳ ساعت",
    ]

    for token in required:
        if token not in source:
            fail(
                f"3H snapshot feature missing: {token}"
            )

    if "dt.hour % 3 == 0" not in source:
        fail("3H automatic snapshot scheduler missing")

    if "dt.hour % 4 == 0" not in source:
        fail("4H analytical scheduler missing")


def check_public_usdt_sources(source):
    required = [
        "wallex.ir",
        "excoino.com",
        "nobitex.ir",
    ]

    lower = source.lower()

    for source_name in required:
        if source_name not in lower:
            fail(
                "public USDT source missing: "
                + source_name
            )


def check_ccxt_source(source):
    if '"kcex"' not in source:
        fail("KCEX CCXT source missing")


def check_closed_candles(source):
    required = [
        "strip_incomplete",
        "candle_is_closed",
    ]

    for token in required:
        if token not in source:
            fail(
                f"closed-candle logic missing: {token}"
            )


def check_compact_output(source):
    required = [
        "_compact_scenario_row",
        "کلیدی:",
        "🟢 صعودی:",
        "🔴 نزولی:",
    ]

    for token in required:
        if token not in source:
            fail(
                f"compact report element missing: {token}"
            )


def check_trade_geometry(source):
    required = [
        "_validate_trade_geometry",
        "invalid LONG geometry",
        "invalid SHORT geometry",
        "non-positive trade level",
        "Trade geometry blocked",
    ]

    for token in required:
        if token not in source:
            fail(
                f"trade geometry check missing: {token}"
            )


def check_snapshot_direction(source):
    required = [
        "_snapshot_previous_prices",
        "_snapshot_direction",
        "⬆️",
        "⬇️",
    ]

    for token in required:
        if token not in source:
            fail(
                f"snapshot direction feature missing: {token}"
            )


def check_csv(source):
    required = [
        "CSV_COLUMNS",
        "generate_csv_report",
        "send_csv_report",
        "MARKET_TOP10",
        "DYNAMIC_TOP30",
        "PERSONAL_PORTFOLIO",
    ]

    for token in required:
        if token not in source:
            fail(
                f"CSV feature missing: {token}"
            )


def check_best_setup(source):
    required = [
        "def _best_setup_block(",
        "MIN_EXECUTABLE_RR",
        "repeat_signal",
    ]

    for token in required:
        if token not in source:
            fail(
                f"best setup validation missing: {token}"
            )


def check_geometry_csv(source):
    required = [
        "_csv_safe_plan",
        "_validate_trade_geometry",
    ]

    for token in required:
        if token not in source:
            fail(
                f"CSV geometry protection missing: {token}"
            )


def run():
    print("=" * 66)
    print("ATLAS AI v11.2 STATIC SMOKE TEST")
    print("=" * 66)

    print("\n[1/15] Reading bot.py")
    source = read_bot()
    print("PASS: bot.py exists and is readable")

    print("\n[2/15] Parsing Python AST")
    tree = parse_bot(source)
    print("PASS: bot.py AST is valid")

    print("\n[3/15] Checking required functions")
    functions = top_level_functions(tree)
    check_required_functions(functions)
    print("PASS: required functions present")

    print("\n[4/15] Checking duplicate function definitions")
    check_single_definitions(functions, tree)
    print("PASS: no duplicate critical functions")

    print("\n[5/15] Checking version")
    check_version(source)
    print("PASS: ATLAS v11.2")

    print("\n[6/15] Checking stale v10 markers")
    check_no_v10(source)
    print("PASS: no stale v10 markers")

    print("\n[7/15] Checking actual import AST")
    check_no_wrapper_imports(tree)
    print("PASS: no obsolete executable bot import")

    print("\n[8/15] Checking two-engine architecture")
    check_two_engine(source)
    check_market_personal_separation(source)
    print("PASS: MARKET / PERSONAL / BOTH")

    print("\n[9/15] Checking metals")
    check_metals(source)
    print("PASS: GOLD / SILVER / COPPER")

    print("\n[10/15] Checking TradingView")
    check_tradingview(source)
    print("PASS: TradingView support")

    print("\n[11/15] Checking 3H snapshot")
    check_snapshot(source)
    check_snapshot_direction(source)
    print("PASS: 3H snapshot")

    print("\n[12/15] Checking market data architecture")
    check_public_usdt_sources(source)
    check_ccxt_source(source)
    check_closed_candles(source)
    print("PASS: public USDT + CCXT + closed candles")

    print("\n[13/15] Checking report / trade geometry")
    check_compact_output(source)
    check_trade_geometry(source)
    check_best_setup(source)
    print("PASS: report + trade geometry")

    print("\n[14/15] Checking CSV")
    check_csv(source)
    check_geometry_csv(source)
    print("PASS: CSV + geometry protection")

    print("\n[15/15] Final compile")
    compile(source, str(BOT), "exec")
    print("PASS: Python compile")

    print("\n" + "=" * 66)
    print("ATLAS AI v11.2 SMOKE TEST: PASS")
    print("=" * 66)


if __name__ == "__main__":
    run()
