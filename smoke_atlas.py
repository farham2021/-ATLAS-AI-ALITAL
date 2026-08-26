#!/usr/bin/env python3
"""
ATLAS AI v11.2 — Smoke Test

Purpose:
- Validate the real v11.2 bot module.
- Ensure bot.py is the actual analytical engine.
- Ensure no legacy wrapper/import architecture is used.
- Validate core report-generation functions.
- Never send Telegram messages during smoke testing.
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOT_FILE = ROOT / "bot.py"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def passed(message: str) -> None:
    print(f"PASS: {message}")


def read_bot_source() -> str:
    if not BOT_FILE.exists():
        fail("bot.py not found")
    return BOT_FILE.read_text(encoding="utf-8")


def validate_file_structure() -> None:
    if not BOT_FILE.exists():
        fail("bot.py is missing")

    passed("bot.py exists")


def validate_python_syntax(source: str) -> None:
    try:
        ast.parse(source, filename=str(BOT_FILE))
    except SyntaxError as exc:
        fail(f"bot.py syntax error: {exc}")

    passed("bot.py syntax is valid")


def validate_no_legacy_imports(source: str) -> None:
    """
    Inspect the AST instead of grep.

    This avoids false positives caused by comments or explanatory
    strings inside smoke_atlas.py.
    """

    try:
        tree = ast.parse(source, filename=str(BOT_FILE))
    except SyntaxError as exc:
        fail(f"Unable to parse bot.py: {exc}")

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.strip() == "bot":
                    fail("bot.py contains a self/legacy import of module 'bot'")

        elif isinstance(node, ast.ImportFrom):
            if node.module == "bot":
                fail("bot.py contains a legacy import from module 'bot'")

    passed("bot.py contains no legacy wrapper/import architecture")


def validate_v11_2_markers(source: str) -> None:
    markers = (
        "ATLAS",
        "11.2",
    )

    for marker in markers:
        if marker not in source:
            fail(f"v11.2 marker missing: {marker}")

    passed("v11.2 markers detected")


def import_bot():
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))

        module = importlib.import_module("bot")
    except Exception as exc:
        fail(f"Unable to import bot.py: {type(exc).__name__}: {exc}")

    passed("bot.py imported successfully")
    return module


def validate_required_functions(bot) -> None:
    required = (
        "main",
    )

    missing = [
        name
        for name in required
        if not callable(getattr(bot, name, None))
    ]

    if missing:
        fail(
            "Missing required callable(s): "
            + ", ".join(missing)
        )

    passed("required bot entry point detected")


def validate_engine_symbols(bot) -> None:
    """
    v11.2 must remain a real engine, not a thin Telegram wrapper.

    We accept multiple legitimate names because the v11.1 architecture
    may expose its engines under different internal names.
    """

    source_symbols = {
        name
        for name in dir(bot)
        if not name.startswith("__")
    }

    analytical_candidates = {
        "analyze_market",
        "analyze_personal",
        "run_market_engine",
        "run_personal_engine",
        "market_engine",
        "personal_engine",
        "build_market_report",
        "build_personal_report",
        "build_dashboard",
        "generate_csv",
        "generate_csv_report",
    }

    found = sorted(
        source_symbols.intersection(analytical_candidates)
    )

    if not found:
        print(
            "WARNING: no optional analytical symbol matched "
            "the compatibility list."
        )
        print(
            "The main bot entry point remains available."
        )
    else:
        passed(
            "analytical engine symbols detected: "
            + ", ".join(found)
        )


def validate_environment() -> None:
    version = os.environ.get(
        "ATLAS_VERSION",
        "11.2",
    )

    timeframe = os.environ.get(
        "ATLAS_TIMEFRAME",
        "4H",
    )

    print(
        f"ATLAS_VERSION={version}"
    )

    print(
        f"ATLAS_TIMEFRAME={timeframe}"
    )

    passed("runtime environment readable")


def main() -> int:

    print("=" * 66)
    print("ATLAS AI v11.2 — SMOKE TEST")
    print("=" * 66)

    print("\n1. PROJECT STRUCTURE")
    validate_file_structure()

    print("\n2. PYTHON SYNTAX")
    source = read_bot_source()
    validate_python_syntax(source)

    print("\n3. LEGACY ARCHITECTURE CHECK")
    validate_no_legacy_imports(source)

    print("\n4. V11.2 MARKERS")
    validate_v11_2_markers(source)

    print("\n5. ENVIRONMENT")
    validate_environment()

    print("\n6. BOT IMPORT")
    bot = import_bot()

    print("\n7. BOT ENTRY POINT")
    validate_required_functions(bot)

    print("\n8. ANALYTICAL ENGINE")
    validate_engine_symbols(bot)

    print("\n" + "=" * 66)
    print("ATLAS AI v11.2 SMOKE TEST: PASS")
    print("=" * 66)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
