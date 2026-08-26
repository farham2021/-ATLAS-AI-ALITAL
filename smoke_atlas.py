#!/usr/bin/env python3
"""
ATLAS AI v11.2
Offline smoke test.

This test validates the real bot.py engine directly.
It does NOT use a wrapper engine and does NOT send Telegram messages.
"""

from pathlib import Path
import ast
import sys


BOT = Path(__file__).with_name("bot.py")


def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)


# ============================================================
# 1. BOT FILE
# ============================================================

if not BOT.exists():
    fail("bot.py not found")

print("PASS: bot.py exists")


# ============================================================
# 2. AST / SYNTAX
# ============================================================

source = BOT.read_text(
    encoding="utf-8",
    errors="ignore",
)

try:
    tree = ast.parse(source)
except SyntaxError as exc:
    fail(f"bot.py syntax error: {exc}")

print("PASS: bot.py AST parse")


# ============================================================
# 3. REQUIRED FUNCTIONS
# ============================================================

function_names = {
    node.name
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}

required_functions = (
    "main",
    "build_report",
    "build_personal_report",
    "generate_csv_report",
)

for name in required_functions:
    if name not in function_names:
        fail(f"missing required function: {name}")

    print(f"PASS: function {name}()")


# ============================================================
# 4. REQUIRED V11.2 TOKENS
# ============================================================

required_tokens = (
    "ATLAS",
    "11.2",
    "MARKET",
    "PERSONAL",
    "BOTH",
    "4H",
    "TP1",
    "TP2",
    "SL",
    "R/R",
    "BUY",
    "SELL",
    "WAIT",
)

upper_source = source.upper()

for token in required_tokens:
    if token.upper() not in upper_source:
        fail(f"missing required token: {token}")

    print(f"PASS: token {token}")


# ============================================================
# 5. TELEGRAM DELIVERY
# ============================================================

telegram_tokens = (
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_GROUP_CHAT_ID",
)

for token in telegram_tokens:
    if token not in source:
        fail(f"missing Telegram configuration token: {token}")

    print(f"PASS: Telegram configuration {token}")


# ============================================================
# 6. NO OBSOLETE WRAPPER
# ============================================================

# IMPORTANT:
# Do NOT search for the literal text
# "import bot as engine"
# because a test that contains that text would fail its own check.
#
# Instead inspect the AST for an actual import statement.

for node in ast.walk(tree):

    if isinstance(node, ast.Import):

        for alias in node.names:

            if alias.name == "bot":
                fail(
                    "bot.py must not import itself as an engine"
                )

    if isinstance(node, ast.ImportFrom):

        if node.module == "bot":
            fail(
                "bot.py must not use 'from bot import ...'"
            )


print("PASS: no self-import / obsolete wrapper")


# ============================================================
# 7. V11.2 CONFIGURATION
# ============================================================

config_tokens = (
    "ATLAS_ENGINE",
    "ATLAS_RUN_MODE",
    "ATLAS_TIMEFRAME",
    "ATLAS_MIN_EXECUTABLE_RR",
    "ATLAS_MIN_WATCH_CONFIDENCE",
)

for token in config_tokens:

    if token not in source:
        print(
            f"WARNING: configuration token not found: {token}"
        )
    else:
        print(
            f"PASS: configuration {token}"
        )


# ============================================================
# 8. CSV / REPORT ENGINE
# ============================================================

csv_tokens = (
    "generate_csv_report",
    "CSV",
    "PERSONAL_PORTFOLIO",
)

for token in csv_tokens:

    if token.upper() not in upper_source:
        print(
            f"WARNING: CSV/report token not found: {token}"
        )
    else:
        print(
            f"PASS: report token {token}"
        )


# ============================================================
# 9. TELEGRAM SAFETY
# ============================================================

# The smoke test must never send a Telegram message.
# Only static source validation is performed here.

print("PASS: smoke test is offline")
print("PASS: no Telegram network call performed")


# ============================================================
# FINAL
# ============================================================

print()
print("=" * 70)
print("ATLAS AI v11.2 SMOKE TEST: PASS")
print("=" * 70)
print("PASS: bot.py exists")
print("PASS: Python syntax")
print("PASS: required functions")
print("PASS: v11.2 engine tokens")
print("PASS: Telegram configuration")
print("PASS: no obsolete self-import")
print("PASS: offline smoke test")
print("=" * 70)
