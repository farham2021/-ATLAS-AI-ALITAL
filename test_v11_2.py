#!/usr/bin/env python3

from pathlib import Path
import ast
import re


BOT = Path("bot.py")


def fail(message):
    raise AssertionError(message)


def main():
    if not BOT.exists():
        fail("bot.py not found")

    source = BOT.read_text(encoding="utf-8")

    try:
        tree = ast.parse(
            source,
            filename="bot.py",
        )
    except SyntaxError as exc:
        fail(f"bot.py syntax error: {exc}")

    functions = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }

    required_functions = {
        "build_report",
        "build_personal_report",
        "build_two_engine_reports",
        "atlas_engine_mode",
        "analyze_coin",
        "main",
        "build_price_snapshot",
        "send_price_snapshot",
        "fetch_snapshot_results",
        "_automatic_run_plan",
        "generate_csv_report",
        "send_csv_report",
        "telegram_preflight",
        "telegram_send_one",
        "send_report",
    }

    missing = required_functions - functions

    if missing:
        fail(
            "Missing required functions: "
            + ", ".join(sorted(missing))
        )

    checks = [
        (
            "VERSION 11.2",
            bool(
                re.search(
                    r'^VERSION\s*=\s*["\']ATLAS v11\.2',
                    source,
                    re.MULTILINE,
                )
            ),
        ),
        (
            "MARKET engine",
            "MARKET" in source,
        ),
        (
            "PERSONAL engine",
            "PERSONAL" in source,
        ),
        (
            "BOTH mode",
            "BOTH" in source,
        ),
        (
            "4H timeframe",
            '"4H"' in source or "'4H'" in source,
        ),
        (
            "3H snapshot",
            "send_price_snapshot" in source,
        ),
        (
            "Dynamic Top 30",
            "dynamic30" in source,
        ),
        (
            "personal assets",
            "ATLAS_PERSONAL_ASSETS" in source,
        ),
        (
            "metals",
            "ATLAS_METALS" in source,
        ),
        (
            "closed candle",
            "strip_incomplete" in source,
        ),
        (
            "trade geometry",
            "TRADE_GEOMETRY_EPSILON" in source,
        ),
        (
            "Telegram retry",
            "send_with_retry" in source,
        ),
        (
            "Telegram preflight",
            "telegram_preflight" in source,
        ),
        (
            "Telegram private destination",
            "TELEGRAM_CHAT_ID" in source,
        ),
        (
            "Telegram group destination",
            "TELEGRAM_GROUP_CHAT_ID" in source,
        ),
        (
            "CSV",
            "generate_csv_report" in source,
        ),
        (
            "no obsolete v12 wrapper",
            "ATLAS_v12_bot" not in source,
        ),
        (
            "no legacy wrapper import",
            "import bot as engine" not in source,
        ),
        (
            "no legacy direct import",
            "from bot import" not in source,
        ),
        (
            "no v10",
            "ATLAS v10" not in source,
        ),
    ]

    failed = [
        name
        for name, passed in checks
        if not passed
    ]

    print("=" * 66)
    print("ATLAS AI v11.2 UNIT TEST")
    print("=" * 66)

    for name, passed in checks:
        print(
            f"{'PASS' if passed else 'FAIL'}: {name}"
        )

    if failed:
        raise AssertionError(
            "v11.2 tests failed: "
            + ", ".join(failed)
        )

    print()
    print("ATLAS AI v11.2 UNIT TEST: PASS")


if __name__ == "__main__":
    main()
