#!/usr/bin/env python3

from pathlib import Path
import ast
import re
import sys


BOT = Path("bot.py")


def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)


def source_text():
    if not BOT.exists():
        fail("bot.py not found")

    try:
        return BOT.read_text(encoding="utf-8")
    except Exception as exc:
        fail(f"cannot read bot.py: {exc}")


def parse_source(source):
    try:
        return ast.parse(source, filename=str(BOT))
    except SyntaxError as exc:
        fail(f"bot.py syntax error: {exc}")


def function_names(tree):
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def main():
    print("=" * 66)
    print("ATLAS AI v11.2 SMOKE TEST")
    print("=" * 66)

    source = source_text()
    tree = parse_source(source)
    funcs = function_names(tree)

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

    missing = [name for name in required if name not in funcs]

    if missing:
        fail(
            "Missing required functions: "
            + ", ".join(missing)
        )

    checks = {
        "VERSION 11.2":
            bool(
                re.search(
                    r'^VERSION\s*=\s*["\']ATLAS v11\.2',
                    source,
                    re.MULTILINE,
                )
            ),

        "no stale v10 markers":
            not bool(
                re.search(
                    r"ATLAS v10|v10\.[0-9]|10\.2",
                    source,
                )
            ),

        "single build_report":
            funcs.count("build_report") == 1,

        "single build_personal_report":
            funcs.count("build_personal_report") == 1,

        "single build_two_engine_reports":
            funcs.count("build_two_engine_reports") == 1,

        "single personal_report":
            funcs.count("personal_report") == 1,

        "two-engine architecture":
            all(
                x in source
                for x in ("MARKET", "PERSONAL", "BOTH")
            ),

        "personal portfolio":
            "ATLAS_PERSONAL_ASSETS" in source,

        "market excludes personal":
            (
                "market_results" in source
                and "not in personal_symbols" in source
            ),

        "metals":
            (
                "ATLAS_METALS" in source
                and all(
                    x in source
                    for x in (
                        "GOLD",
                        "SILVER",
                        "COPPER",
                    )
                )
            ),

        "TradingView links":
            "tradingview.com/chart/?symbol=" in source,

        "3H snapshot":
            (
                "send_price_snapshot" in source
                and "این پیام هر ۳ ساعت" in source
            ),

        "snapshot-only mode":
            (
                "fetch_snapshot_results" in source
                and 'run_mode == "SNAPSHOT"' in source
            ),

        "automatic scheduler":
            (
                "_automatic_run_plan" in source
                and "dt.hour % 3 == 0" in source
                and "dt.hour % 4 == 0" in source
            ),

        "public Iranian USDT sources":
            all(
                x in source.lower()
                for x in (
                    "wallex.ir",
                    "excoino.com",
                    "nobitex.ir",
                )
            ),

        "KCEX support":
            '"kcex"' in source,

        "closed candle logic":
            (
                "strip_incomplete" in source
                and "candle_is_closed" in source
            ),

        "compact report":
            all(
                x in source
                for x in (
                    "_compact_scenario_row",
                    "کلیدی:",
                    "🟢 صعودی:",
                    "🔴 نزولی:",
                )
            ),

        "Telegram preflight":
            "telegram_preflight" in source,

        "Telegram retry":
            "send_with_retry" in source,

        "Telegram independent destinations":
            (
                "TELEGRAM_CHAT_ID" in source
                and "TELEGRAM_GROUP_CHAT_ID" in source
            ),

        "Telegram safe split":
            "split_telegram" in source,

        "CSV export":
            (
                "generate_csv_report" in source
                and "send_csv_report" in source
            ),

        "no obsolete wrapper text":
            not any(
                x in source
                for x in (
                    "ATLAS_v12_bot",
                    "import bot as engine",
                    "from bot import",
                )
            ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    print()
    print("-" * 66)

    for name, passed in checks.items():
        print(
            f"{'PASS' if passed else 'FAIL'}: {name}"
        )

    print("-" * 66)

    if failed:
        print(
            "ATLAS AI v11.2 SMOKE TEST: FAIL"
        )
        print(
            "Failed checks: "
            + ", ".join(failed)
        )
        raise SystemExit(1)

    print(
        "ATLAS AI v11.2 SMOKE TEST: PASS"
    )


if __name__ == "__main__":
    main()
