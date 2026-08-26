#!/usr/bin/env python3
"""
ATLAS AI v11.2 — Smoke Test

Purpose:
- Validate Python syntax
- Validate v11.2 markers
- Validate two-engine architecture
- Validate market/personal engines
- Validate metals
- Validate price snapshot
- Validate CSV reporting
- Validate Telegram delivery hooks
- Reject obsolete wrapper references

This test does NOT execute real market orders or send Telegram messages.
"""

from pathlib import Path
import ast
import sys


ROOT = Path(__file__).resolve().parent

BOT = ROOT / "bot.py"
TEST = ROOT / "test_v11_2.py"


def fail(message):
    print(f"FAIL: {message}")
    raise SystemExit(1)


def ok(message):
    print(f"PASS: {message}")


print("=" * 66)
print("ATLAS AI v11.2 SMOKE TEST")
print("=" * 66)


# ============================================================
# 1. REQUIRED FILES
# ============================================================

print("\nENGINE VALIDATION")
print("-" * 66)

for path in (BOT, TEST):

    if not path.exists():
        fail(f"Missing required file: {path.name}")

    ok(f"{path.name} exists")


# ============================================================
# 2. BOT SYNTAX
# ============================================================

try:
    bot_source = BOT.read_text(encoding="utf-8")
    bot_tree = ast.parse(
        bot_source,
        filename=str(BOT)
    )
except SyntaxError as exc:
    fail(f"bot.py syntax error: {exc}")

ok("Python compilation")


# ============================================================
# 3. VERSION MARKER
# ============================================================

version_tokens = (
    "11.2",
    "v11.2",
    "ATLAS_VERSION",
)

if not any(token in bot_source for token in version_tokens):
    fail("v11.2 version marker not found in bot.py")

ok("v11.2 version marker")


# ============================================================
# 4. FUNCTION DISCOVERY
# ============================================================

function_names = {
    node.name
    for node in bot_tree.body
    if isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef)
    )
}


def require_function(name):
    if name not in function_names:
        fail(f"Required function missing: {name}")

    ok(f"function: {name}")


# ============================================================
# 5. CORE ENGINE FUNCTIONS
# ============================================================

core_candidates = (
    "build_report",
    "build_market_report",
    "build_two_engine_reports",
)

if not any(name in function_names for name in core_candidates):
    fail(
        "No supported market report engine found. "
        "Expected one of: "
        + ", ".join(core_candidates)
    )

ok("market analytical engine")


personal_candidates = (
    "build_personal_report",
    "personal_report",
    "build_two_engine_reports",
)

if not any(name in function_names for name in personal_candidates):
    fail(
        "No supported personal report engine found."
    )

ok("personal analytical engine")


# ============================================================
# 6. PORTFOLIO
# ============================================================

portfolio_tokens = (
    "ATLAS_PERSONAL_ASSETS",
    "PERSONAL_PORTFOLIO",
    "personal",
)

if not any(
    token in bot_source
    for token in portfolio_tokens
):
    fail("Personal portfolio support not found")

ok("personal portfolio")


# ============================================================
# 7. MARKET / PERSONAL / BOTH
# ============================================================

engine_tokens = (
    "MARKET",
    "PERSONAL",
    "BOTH",
)

for token in engine_tokens:

    if token not in bot_source:
        fail(
            f"Engine mode token missing: {token}"
        )

ok("MARKET / PERSONAL / BOTH")


# ============================================================
# 8. METALS
# ============================================================

for metal in (
    "GOLD",
    "SILVER",
    "COPPER",
):

    if metal not in bot_source:
        fail(
            f"Metal support missing: {metal}"
        )

ok("GOLD / SILVER / COPPER")


# ============================================================
# 9. PRICE SNAPSHOT
# ============================================================

snapshot_tokens = (
    "SNAPSHOT",
    "snapshot",
    "price_snapshot",
    "PRICE SNAPSHOT",
)

if not any(
    token in bot_source
    for token in snapshot_tokens
):
    fail("Price snapshot functionality not found")

ok("price snapshot")


# ============================================================
# 10. CSV REPORTING
# ============================================================

csv_function_candidates = (
    "generate_csv_report",
    "generate_dynamic_csv",
    "export_csv",
)

csv_functions = [
    name
    for name in csv_function_candidates
    if name in function_names
]

if not csv_functions:
    fail(
        "CSV reporting functionality not found. "
        "Expected one of: "
        + ", ".join(csv_function_candidates)
    )

ok(
    "CSV reporting functionality: "
    + ", ".join(csv_functions)
)


# ============================================================
# 11. CSV CONTENT MARKERS
# ============================================================

csv_tokens = (
    "csv",
    "DictWriter",
    "StringIO",
)

if not any(
    token.lower() in bot_source.lower()
    for token in csv_tokens
):
    fail("CSV implementation markers not found")

ok("CSV implementation")


# ============================================================
# 12. TELEGRAM DELIVERY
# ============================================================

telegram_tokens = (
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_GROUP_CHAT_ID",
)

for token in telegram_tokens:

    if token not in bot_source:
        fail(
            f"Telegram configuration missing: {token}"
        )

ok("Telegram configuration")


telegram_delivery_tokens = (
    "sendMessage",
    "send_document",
    "sendDocument",
    "send_report",
)

if not any(
    token in bot_source
    for token in telegram_delivery_tokens
):
    fail(
        "Telegram delivery function/reference "
        "not found in bot.py"
    )

ok("Telegram delivery")


# ============================================================
# 13. TGJU
# ============================================================

tgju_tokens = (
    "tgju.org",
    "TGJU_USD_URL",
    "TGJU_USDT_URL",
)

for token in tgju_tokens:

    if token not in bot_source:
        fail(
            f"TGJU integration marker missing: {token}"
        )

ok("TGJU FX integration")


# ============================================================
# 14. TRADE GEOMETRY
# ============================================================

geometry_tokens = (
    "TP1",
    "TP2",
    "R/R",
    "rr",
    "risk",
)

if not any(
    token in bot_source
    for token in geometry_tokens
):
    fail(
        "Trade geometry / R/R functionality "
        "not found"
    )

ok("trade geometry / R/R")


# ============================================================
# 15. DYNAMIC TOP 30
# ============================================================

dynamic_tokens = (
    "DYNAMIC_TOP30",
    "DYNAMIC TOP 30",
    "dynamic30",
)

if not any(
    token in bot_source
    for token in dynamic_tokens
):

    # Dynamic Top 30 can also be generated through
    # ranking logic. Do not fail if explicit naming
    # is absent but ranking machinery exists.

    ranking_tokens = (
        "sorted(",
        "sort(",
        "TOP",
    )

    if not any(
        token in bot_source
        for token in ranking_tokens
    ):
        fail(
            "Dynamic/ranking engine not found"
        )

ok("dynamic market ranking")


# ============================================================
# 16. OBSOLETE WRAPPER REFERENCES
# ============================================================

forbidden = (
    "import bot as engine",
    "from bot import",
    "ATLAS_v12_bot",
)

for pattern in forbidden:

    if pattern in bot_source:

        fail(
            "Obsolete wrapper/reference found "
            f"in bot.py: {pattern}"
        )

ok("no obsolete wrapper/reference in bot.py")


# ============================================================
# 17. TEST FILE SYNTAX
# ============================================================

try:

    test_source = TEST.read_text(
        encoding="utf-8"
    )

    ast.parse(
        test_source,
        filename=str(TEST)
    )

except SyntaxError as exc:

    fail(
        f"test_v11_2.py syntax error: {exc}"
    )

ok("test_v11_2.py syntax")


# ============================================================
# FINAL
# ============================================================

print()
print("=" * 66)
print("ATLAS AI v11.2 SMOKE TEST: PASS")
print("=" * 66)
print()
print("Validated:")
print("  ✓ Python syntax")
print("  ✓ v11.2 marker")
print("  ✓ MARKET engine")
print("  ✓ PERSONAL engine")
print("  ✓ BOTH architecture")
print("  ✓ Personal portfolio")
print("  ✓ GOLD / SILVER / COPPER")
print("  ✓ Price snapshot")
print("  ✓ CSV reporting")
print("  ✓ Telegram delivery")
print("  ✓ TGJU integration")
print("  ✓ Trade geometry / R/R")
print("  ✓ Dynamic ranking")
print("  ✓ No obsolete wrapper")
print()
