#!/usr/bin/env python3
"""
ATLAS AI v11.2
Smoke test and structural validation.

Important:
This file must not contain legacy engine-reference strings,
even inside comments or diagnostic messages.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

REQUIRED_FILES = (
    "bot.py",
    "smoke_atlas.py",
    "test_v11_2.py",
)

FORBIDDEN_PATTERNS = (
    "ATLAS_v12_bot",
    "import bot as engine",
    "from bot import",
    "import bot ",
)


def fail(message: str) -> None:
    print()
    print("=" * 66)
    print("ATLAS AI v11.2 SMOKE TEST: FAIL")
    print("=" * 66)
    print(message)
    raise SystemExit(1)


def check_required_files() -> None:
    print("=" * 66)
    print("1. PROJECT STRUCTURE")
    print("=" * 66)

    for filename in REQUIRED_FILES:
        path = ROOT / filename

        if not path.is_file():
            fail(f"Missing required file: {filename}")

        print(f"PASS: {filename}")


def check_legacy_references() -> None:
    print()
    print("=" * 66)
    print("2. LEGACY REFERENCE CHECK")
    print("=" * 66)

    files_to_check = (
        "bot.py",
        "smoke_atlas.py",
        "test_v11_2.py",
    )

    for filename in files_to_check:
        path = ROOT / filename

        if not path.is_file():
            fail(f"Cannot inspect missing file: {filename}")

        source = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for pattern in FORBIDDEN_PATTERNS:
            if pattern in source:
                fail(
                    f"Obsolete reference found in "
                    f"{filename}: {pattern}"
                )

        print(f"PASS: {filename}")


def check_python_syntax() -> None:
    print()
    print("=" * 66)
    print("3. PYTHON SYNTAX")
    print("=" * 66)

    python_files = (
        "bot.py",
        "smoke_atlas.py",
        "test_v11_2.py",
    )

    for filename in python_files:
        path = ROOT / filename

        try:
            source = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            ast.parse(
                source,
                filename=str(path),
            )

        except SyntaxError as exc:
            fail(
                f"Syntax error in {filename}: "
                f"line {exc.lineno}, "
                f"column {exc.offset}: "
                f"{exc.msg}"
            )

        except Exception as exc:
            fail(
                f"Unable to parse {filename}: "
                f"{type(exc).__name__}: {exc}"
            )

        print(f"PASS: {filename}")


def check_bot_importable() -> None:
    print()
    print("=" * 66)
    print("4. BOT MODULE LOAD")
    print("=" * 66)

    sys.path.insert(0, str(ROOT))

    try:
        import bot

    except Exception as exc:
        fail(
            "bot.py could not be imported.\n"
            f"{type(exc).__name__}: {exc}"
        )

    version = getattr(
        bot,
        "VERSION",
        None,
    )

    if version is None:
        fail(
            "bot.py loaded successfully, "
            "but VERSION is missing."
        )

    print(f"PASS: bot.py imported")
    print(f"PASS: VERSION = {version}")


def check_environment() -> None:
    print()
    print("=" * 66)
    print("5. ENVIRONMENT")
    print("=" * 66)

    expected_version = os.getenv(
        "ATLAS_VERSION",
        "11.2",
    )

    expected_timeframe = os.getenv(
        "ATLAS_TIMEFRAME",
        "4H",
    )

    print(
        f"ATLAS_VERSION = {expected_version}"
    )

    print(
        f"ATLAS_TIMEFRAME = {expected_timeframe}"
    )

    if expected_version != "11.2":
        fail(
            "ATLAS_VERSION must be 11.2 "
            f"but is {expected_version!r}"
        )

    if expected_timeframe != "4H":
        fail(
            "ATLAS_TIMEFRAME must be 4H "
            f"but is {expected_timeframe!r}"
        )

    print("PASS: v11.2 environment")


def check_required_bot_symbols() -> None:
    print()
    print("=" * 66)
    print("6. BOT API")
    print("=" * 66)

    import bot

    required_symbols = (
        "main",
    )

    for symbol in required_symbols:
        if not hasattr(bot, symbol):
            fail(
                f"Required bot symbol missing: {symbol}"
            )

        print(
            f"PASS: bot.{symbol}"
        )


def main() -> int:
    print()
    print("=" * 66)
    print("ATLAS AI v11.2 — SMOKE TEST")
    print("=" * 66)

    check_required_files()
    check_legacy_references()
    check_python_syntax()
    check_environment()
    check_bot_importable()
    check_required_bot_symbols()

    print()
    print("=" * 66)
    print("ATLAS AI v11.2 TEST STATUS: PASS")
    print("=" * 66)
    print("Project structure: PASS")
    print("Legacy reference check: PASS")
    print("Python syntax: PASS")
    print("Bot module load: PASS")
    print("Environment: PASS")
    print("Bot API: PASS")
    print("=" * 66)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
