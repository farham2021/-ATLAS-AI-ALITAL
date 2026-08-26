#!/usr/bin/env python3
"""
ATLAS AI v11.2
Smoke Test

This file validates the v11.2 engine itself.
Legacy-reference validation is intentionally handled by GitHub Actions,
not by this Python smoke test.
"""

from pathlib import Path
import ast
import re
import sys


BOT = Path("bot.py")


def fail(message: str) -> None:
    print("FAIL:", message)
    raise SystemExit(1)


def read_bot() -> str:
    if not BOT.exists():
        fail("bot.py not found")

    try:
        source = BOT.read_text(encoding="utf-8")
    except Exception as exc:
        fail(f"unable to read bot.py: {exc}")

    if not source.strip():
        fail("bot.py is empty")

    return source


def parse_bot(source: str):
    try:
        return ast.parse(source, filename=str(BOT))
    except SyntaxError as exc:
        fail(f"bot.py syntax error: {exc}")


def get_functions(tree):
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def check_version(source: str) -> None:
    patterns = (
        r'VERSION\s*=\s*["\']ATLAS v11\.2',
        r'ATLAS_VERSION',
        r'v11\.2',
    )

    if not any(re.search(pattern, source, re.IGNORECASE) for pattern in patterns):
        fail("ATLAS v11.2 version marker not found")

    print("PASS: v11.2 version marker")


def check_two_engine(source: str) -> None:
    required = (
        "MARKET",
        "PERSONAL",
        "BOTH",
    )

    missing = [item for item in required if item not in source]

    if missing:
        fail(
            "two-engine architecture missing: "
            + ", ".join(missing)
        )

    print("PASS: MARKET / PERSONAL / BOTH")


def check_portfolio(source: str) -> None:
    if "ATLAS_PERSONAL_ASSETS" not in source:
        fail("personal portfolio definition not found")

    print("PASS: personal portfolio")


def check_market_engine(functions) -> None:
    candidates = (
        "build_report",
        "build_two_engine_reports",
        "analyze_coin",
    )

    if not any(name in functions for name in candidates):
        fail("market analytical functions not found")

    print("PASS: market analytical engine")


def check_personal_engine(functions) -> None:
    candidates = (
        "build_personal_report",
        "build_two_engine_reports",
        "personal_report",
    )

    if not any(name in functions for name in candidates):
        fail("personal analytical functions not found")

    print("PASS: personal analytical engine")


def check_metals(source: str) -> None:
    required = (
        "GOLD",
        "SILVER",
        "COPPER",
    )

    missing = [item for item in required if item not in source]

    if missing:
        fail(
            "metals support missing: "
            + ", ".join(missing)
        )

    print("PASS: GOLD / SILVER / COPPER")


def check_snapshot(source: str) -> None:
    snapshot_markers = (
        "build_price_snapshot",
        "send_price_snapshot",
        "fetch_snapshot_results",
        "snapshot",
    )

    if not any(
        marker in source
        for marker in snapshot_markers
    ):
        fail("price snapshot functionality not found")

    print("PASS: price snapshot")


def check_csv(source: str, functions) -> None:
    function_ok = any(
        name in functions
        for name in (
            "generate_csv_report",
            "generate_csv",
            "send_csv_report",
            "send_csv",
        )
    )

    text_ok = (
        "csv" in source.lower()
        and (
            "DictWriter" in source
            or "csv.writer" in source
        )
    )

    if not function_ok and not text_ok:
        fail("CSV reporting functionality not found")

    print("PASS: CSV reporting")


def check_trade_geometry(source: str) -> None:
    markers = (
        "TP1",
        "TP2",
        "R/R",
        "rr",
        "stop",
        "support",
        "resistance",
    )

    found = sum(
        1 for marker in markers
        if marker in source
    )

    if found < 4:
        fail("trade geometry markers are incomplete")

    print("PASS: trade geometry")


def check_closed_candle(source: str) -> None:
    markers = (
        "closed",
        "candle",
    )

    if not all(
        marker in source.lower()
        for marker in markers
    ):
        fail("closed-candle logic markers not found")

    print("PASS: closed-candle protection")


def check_telegram(source: str) -> None:
    markers = (
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_GROUP_CHAT_ID",
    )

    missing = [
        marker
        for marker in markers
        if marker not in source
    ]

    if missing:
        fail(
            "Telegram configuration markers missing: "
            + ", ".join(missing)
        )

    print("PASS: Telegram configuration")


def check_main(functions) -> None:
    if "main" not in functions:
        fail("main() not found")

    print("PASS: main()")


def compile_source(source: str) -> None:
    try:
        compile(
            source,
            str(BOT),
            "exec",
        )
    except SyntaxError as exc:
        fail(f"compile failed: {exc}")

    print("PASS: Python compilation")


def main() -> int:
    print("=" * 66)
    print("ATLAS AI v11.2 SMOKE TEST")
    print("=" * 66)

    source = read_bot()
    tree = parse_bot(source)
    functions = get_functions(tree)

    print()
    print("ENGINE VALIDATION")
    print("-" * 66)

    compile_source(source)
    check_version(source)
    check_two_engine(source)
    check_market_engine(functions)
    check_personal_engine(functions)
    check_portfolio(source)
    check_metals(source)
    check_snapshot(source)
    check_csv(source, functions)
    check_trade_geometry(source)
    check_closed_candle(source)
    check_telegram(source)
    check_main(functions)

    print()
    print("=" * 66)
    print("ATLAS AI v11.2 SMOKE TEST: PASS")
    print("=" * 66)

    return 0


if __name__ == "__main__":
    sys.exit(main())
