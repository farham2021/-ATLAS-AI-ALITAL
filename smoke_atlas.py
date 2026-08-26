#!/usr/bin/env python3
"""
ATLAS AI v11.2 — Smoke Test

Important:
- This test checks REAL Python imports using AST.
- It does NOT grep source text.
- Therefore strings/comments mentioning legacy imports do not cause false failures.
- bot.py remains the actual ATLAS engine.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent

BOT_FILE = ROOT / "bot.py"
SMOKE_FILE = ROOT / "smoke_atlas.py"
TEST_FILE = ROOT / "test_v11_2.py"


def fail(message: str) -> None:
    print()
    print("=" * 58)
    print("ATLAS AI v11.2 SMOKE TEST: FAIL")
    print("=" * 58)
    print(message)
    raise SystemExit(1)


def parse_file(path: Path) -> ast.Module:
    if not path.exists():
        fail(f"Missing required file: {path.name}")

    try:
        source = path.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        fail(
            f"Syntax error in {path.name}: "
            f"line {exc.lineno}, column {exc.offset}: {exc.msg}"
        )
    except Exception as exc:
        fail(f"Unable to read {path.name}: {exc}")


def real_imports(tree: ast.Module) -> list[str]:
    """
    Return only REAL Python imports.

    This deliberately ignores:
    - comments
    - strings
    - documentation
    - printed text
    """

    imports: list[str] = []

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return imports


def check_no_legacy_imports(path: Path, tree: ast.Module) -> None:
    imports = real_imports(tree)

    forbidden = {
        "bot as engine",
        "ATLAS_v12_bot",
    }

    # Only inspect actual AST import nodes.
    for module in imports:

        if module == "bot" and path.name != "bot.py":
            fail(
                f"{path.name}: legacy import of bot detected.\n"
                f"Real Python import: {module}"
            )

        if module == "ATLAS_v12_bot":
            fail(
                f"{path.name}: obsolete ATLAS_v12_bot import detected."
            )


def check_bot_exports(tree: ast.Module) -> None:
    functions = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }

    required = (
        "main",
        "build_report",
        "build_personal_report",
    )

    for name in required:
        if name not in functions:
            print(
                f"WARNING: expected function '{name}' "
                f"was not found in bot.py"
            )


def main() -> None:

    print("=" * 58)
    print("ATLAS AI v11.2 — REAL IMPORT CHECK")
    print("=" * 58)

    # --------------------------------------------------------
    # BOT
    # --------------------------------------------------------

    print("Checking bot.py ...")

    bot_tree = parse_file(BOT_FILE)

    # bot.py is allowed to import itself only conceptually,
    # but it should never contain the obsolete wrapper.
    bot_imports = real_imports(bot_tree)

    if "ATLAS_v12_bot" in bot_imports:
        fail("bot.py: obsolete ATLAS_v12_bot import detected.")

    check_bot_exports(bot_tree)

    print("PASS: bot.py")

    # --------------------------------------------------------
    # SMOKE TEST
    # --------------------------------------------------------

    print("Checking smoke_atlas.py ...")

    smoke_tree = parse_file(SMOKE_FILE)

    check_no_legacy_imports(
        SMOKE_FILE,
        smoke_tree,
    )

    print("PASS: smoke_atlas.py")

    # --------------------------------------------------------
    # V11.2 TEST
    # --------------------------------------------------------

    print("Checking test_v11_2.py ...")

    test_tree = parse_file(TEST_FILE)

    check_no_legacy_imports(
        TEST_FILE,
        test_tree,
    )

    print("PASS: test_v11_2.py")

    # --------------------------------------------------------
    # SYNTAX
    # --------------------------------------------------------

    for path, tree in (
        (BOT_FILE, bot_tree),
        (SMOKE_FILE, smoke_tree),
        (TEST_FILE, test_tree),
    ):
        compile(
            tree,
            str(path),
            "exec",
        )

    print()
    print("=" * 58)
    print("ATLAS AI v11.2 SMOKE TEST: PASS")
    print("=" * 58)
    print("PASS: Python AST parsing")
    print("PASS: Python syntax")
    print("PASS: real import validation")
    print("PASS: no legacy wrapper import")
    print("=" * 58)


if __name__ == "__main__":
    main()
