#!/usr/bin/env python3
"""
ATLAS AI v11.2
Smoke test for the native unified engine.

Important:
- This test validates bot.py directly.
- It does not import or execute bot.py.
- It does not send Telegram messages.
- It must remain independent from the production engine.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOT_FILE = ROOT / "bot.py"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def read_source() -> str:
    if not BOT_FILE.exists():
        fail("bot.py not found")

    try:
        return BOT_FILE.read_text(
            encoding="utf-8"
        )
    except Exception as exc:
        fail(f"unable to read bot.py: {exc}")


def parse_source(source: str) -> ast.Module:
    try:
        return ast.parse(
            source,
            filename=str(BOT_FILE)
        )
    except SyntaxError as exc:
        fail(
            "bot.py syntax error: "
            f"line {exc.lineno}, "
            f"column {exc.offset}: "
            f"{exc.msg}"
        )


def function_names(tree: ast.Module) -> list[str]:
    names: list[str] = []

    for node in tree.body:

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            names.append(node.name)

    return names


def class_names(tree: ast.Module) -> list[str]:
    names: list[str] = []

    for node in tree.body:

        if isinstance(
            node,
            ast.ClassDef,
        ):
            names.append(node.name)

    return names


def check_required_functions(
    functions: list[str]
) -> None:

    required = [
        "main",
        "send_report",
        "split_telegram",
    ]

    for name in required:

        if name not in functions:
            fail(
                f"required function missing: {name}"
            )


def check_engine_functions(
    functions: list[str]
) -> None:

    expected_groups = [
        (
            "report",
            "build_report",
            "build_market_report",
            "build_two_engine_reports",
        ),
        (
            "personal",
            "build_personal_report",
            "personal_report",
        ),
    ]

    for group_name, *candidates in expected_groups:

        if not any(
            candidate in functions
            for candidate in candidates
        ):
            fail(
                f"v11.2 {group_name} reporting "
                "function not found"
            )


def check_two_engine_tokens(
    source: str
) -> None:

    required_tokens = [
        "MARKET",
        "PERSONAL",
        "BOTH",
        "TOP 10",
        "DYNAMIC TOP 30",
        "TP1",
        "TP2",
    ]

    for token in required_tokens:

        if token not in source:
            fail(
                f"required v11.2 token missing: {token}"
            )


def check_telegram_tokens(
    source: str
) -> None:

    required_tokens = [
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_GROUP_CHAT_ID",
        "sendMessage",
    ]

    for token in required_tokens:

        if token not in source:
            fail(
                f"Telegram component missing: {token}"
            )


def check_version(
    source: str
) -> None:

    if "11.2" not in source:
        fail(
            "bot.py does not appear to contain "
            "ATLAS v11.2"
        )


def check_imports(
    tree: ast.Module
) -> None:

    imported_modules: list[str] = []

    for node in tree.body:

        if isinstance(node, ast.Import):

            for alias in node.names:
                imported_modules.append(
                    alias.name
                )

        elif isinstance(node, ast.ImportFrom):

            if node.module:
                imported_modules.append(
                    node.module
                )

    if "ccxt" not in imported_modules:
        print(
            "WARNING: ccxt import not detected"
        )


def check_duplicate_main(
    functions: list[str]
) -> None:

    count = functions.count("main")

    if count != 1:
        fail(
            f"main() must exist exactly once; "
            f"found {count}"
        )


def check_duplicate_report(
    functions: list[str]
) -> None:

    report_names = [
        "build_report",
        "build_market_report",
        "build_two_engine_reports",
    ]

    total = sum(
        functions.count(name)
        for name in report_names
    )

    if total == 0:
        fail(
            "no report-building function detected"
        )


def main() -> int:

    print("=" * 66)
    print("ATLAS AI v11.2 SMOKE TEST")
    print("=" * 66)

    print()
    print("1. SOURCE")

    source = read_source()

    print("PASS: bot.py exists")
    print(
        f"PASS: bot.py size = {len(source):,} characters"
    )

    print()
    print("2. AST PARSE")

    tree = parse_source(source)

    print("PASS: bot.py AST parse")

    print()
    print("3. FUNCTION STRUCTURE")

    functions = function_names(tree)

    check_required_functions(functions)
    check_engine_functions(functions)
    check_duplicate_main(functions)
    check_duplicate_report(functions)

    print(
        f"PASS: {len(functions)} top-level functions detected"
    )

    print()
    print("4. CLASS STRUCTURE")

    classes = class_names(tree)

    print(
        f"PASS: {len(classes)} top-level classes detected"
    )

    print()
    print("5. V11.2 ENGINE")

    check_version(source)
    check_two_engine_tokens(source)

    print(
        "PASS: v11.2 unified engine markers"
    )

    print()
    print("6. TELEGRAM")

    check_telegram_tokens(source)

    print(
        "PASS: Telegram delivery components detected"
    )

    print()
    print("7. IMPORTS")

    check_imports(tree)

    print("PASS: import structure inspected")

    print()
    print("=" * 66)
    print("ATLAS AI v11.2 SMOKE TEST: PASS")
    print("=" * 66)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
