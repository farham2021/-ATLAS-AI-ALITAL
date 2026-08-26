#!/usr/bin/env python3
"""
ATLAS AI v11.2 — Smoke Test

Purpose:
- Validate bot.py syntax and structure.
- Validate that the v11.2 engine is self-contained.
- Ensure no obsolete launcher/import pattern remains.
- Do NOT import_bot_as_engine.
- Do NOT send Telegram messages.
- Do NOT execute the analytical engine.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOT = ROOT / "bot.py"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def read_source(path: Path) -> str:
    if not path.exists():
        fail(f"Missing required file: {path.name}")

    try:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        fail(f"Cannot read {path.name}: {exc}")

    return ""


def validate_python(source: str, filename: str) -> ast.AST:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        fail(
            f"Python syntax error in {filename}: "
            f"line {exc.lineno}, column {exc.offset}: {exc.msg}"
        )

    return tree


def validate_no_obsolete_imports(source: str, filename: str) -> None:
    forbidden = (
        "import bot as engine",
        "from bot import",
        "import bot ",
        "ATLAS_v12_bot",
        "ATLAS_v11_bot",
        "ATLAS_bot_v11",
    )

    for pattern in forbidden:
        if pattern in source:
            fail(
                f"Obsolete reference found in "
                f"{filename}: {pattern}"
            )


def validate_import_ast(tree: ast.AST, filename: str) -> None:
    """
    AST-level validation is more reliable than grep because it
    detects actual Python imports rather than comments/docstrings.
    """

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "bot" and alias.asname == "engine":
                    fail(
                        f"Obsolete import found in {filename}: "
                        f"import bot as engine"
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.module == "bot":
                fail(
                    f"Obsolete import found in {filename}: "
                    f"from bot import ..."
                )


def validate_required_symbols(source: str) -> None:
    """
    These are intentionally lightweight structural checks.
    They do not execute bot.py.
    """

    required = [
        "VERSION",
        "build_report",
        "build_personal_report",
    ]

    missing = [
        name
        for name in required
        if name not in source
    ]

    if missing:
        fail(
            "bot.py is missing expected v11.2 symbols: "
            + ", ".join(missing)
        )


def validate_v11_2_markers(source: str) -> None:

    markers = [
        "ATLAS",
        "4H",
        "TELEGRAM",
    ]

    missing = [
        marker
        for marker in markers
        if marker not in source
    ]

    if missing:
        fail(
            "Expected ATLAS v11.2 markers missing: "
            + ", ".join(missing)
        )


def main() -> None:

    print("=" * 70)
    print("ATLAS AI v11.2 — SMOKE TEST")
    print("=" * 70)

    # --------------------------------------------------------
    # 1. FILE
    # --------------------------------------------------------

    print("\n1. SOURCE FILE")

    source = read_source(BOT)

    print(f"PASS: {BOT.name}")

    # --------------------------------------------------------
    # 2. PYTHON AST
    # --------------------------------------------------------

    print("\n2. PYTHON SYNTAX")

    tree = validate_python(
        source,
        BOT.name,
    )

    print("PASS: bot.py syntax")

    # --------------------------------------------------------
    # 3. OBSOLETE STRING CHECK
    # --------------------------------------------------------

    print("\n3. OBSOLETE REFERENCE CHECK")

    validate_no_obsolete_imports(
        source,
        BOT.name,
    )

    print("PASS: no obsolete textual references")

    # --------------------------------------------------------
    # 4. AST IMPORT CHECK
    # --------------------------------------------------------

    print("\n4. ACTIVE IMPORT CHECK")

    validate_import_ast(
        tree,
        BOT.name,
    )

    print("PASS: no obsolete active imports")

    # --------------------------------------------------------
    # 5. REQUIRED ENGINE SYMBOLS
    # --------------------------------------------------------

    print("\n5. ENGINE STRUCTURE")

    validate_required_symbols(source)

    print("PASS: required engine symbols detected")

    # --------------------------------------------------------
    # 6. V11.2 MARKERS
    # --------------------------------------------------------

    print("\n6. V11.2 MARKERS")

    validate_v11_2_markers(source)

    print("PASS: ATLAS / 4H / Telegram markers detected")

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    print("\n" + "=" * 70)
    print("ATLAS AI v11.2 SMOKE TEST: PASS")
    print("=" * 70)


if __name__ == "__main__":
    raise SystemExit(main())
