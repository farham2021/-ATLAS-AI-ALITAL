#!/usr/bin/env python3

"""
ATLAS AI v12
Validation / Smoke Test Suite

Main engine:
    bot12.py

This test validates the actual public API of the current v12 engine.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


# ============================================================
# PROJECT ROOT
# ============================================================

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# TEST COUNTERS
# ============================================================

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASSED, FAILED

    if condition:
        PASSED += 1
        print(f"✅ PASS: {name}")

        if detail:
            print(f"   {detail}")

        return True

    FAILED += 1
    print(f"❌ FAIL: {name}")

    if detail:
        print(f"   {detail}")

    return False


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ============================================================
# 1. PROJECT STRUCTURE
# ============================================================

section("1. PROJECT STRUCTURE")

REQUIRED_FILES = (
    "bot12.py",
    "atlas_v12_upgrade.py",
    "smoke_atlas.py",
    "test_v12.py",
    "requirements-v12.txt",
)

for filename in REQUIRED_FILES:
    path = ROOT / filename

    check(
        f"Required file exists: {filename}",
        path.is_file(),
        str(path),
    )


# ============================================================
# 2. MAIN ENGINE IMPORT
# ============================================================

section("2. MAIN ENGINE IMPORT")

bot = None

try:
    bot = importlib.import_module("bot12")

    check(
        "bot12.py imports successfully",
        True,
        f"Loaded from: {getattr(bot, '__file__', 'unknown')}",
    )

except Exception as exc:

    check(
        "bot12.py imports successfully",
        False,
        f"{type(exc).__name__}: {exc}",
    )


# ============================================================
# 3. LEGACY IMPORT VALIDATION
# ============================================================

section("3. LEGACY IMPORT VALIDATION")

# IMPORTANT:
# We only inspect the actual source files.
# We do NOT search test_v12.py for forbidden strings,
# because that would create a false positive.

SOURCE_FILES = (
    ROOT / "bot12.py",
    ROOT / "atlas_v12_upgrade.py",
    ROOT / "smoke_atlas.py",
)

LEGACY_PATTERNS = (
    "ATLAS_v12_bot",
    "import bot ",
    "from bot import",
)

for path in SOURCE_FILES:

    if not path.is_file():
        continue

    try:
        source = path.read_text(
            encoding="utf-8"
        )
    except UnicodeDecodeError:
        source = path.read_text(
            encoding="utf-8-sig"
        )

    found = [
        pattern
        for pattern in LEGACY_PATTERNS
        if pattern in source
    ]

    check(
        f"No obsolete import in {path.name}",
        not found,
        (
            "No obsolete references detected."
            if not found
            else f"Found: {found}"
        ),
    )


# ============================================================
# 4. PYTHON SYNTAX
# ============================================================

section("4. PYTHON SYNTAX VALIDATION")

PYTHON_FILES = (
    "bot12.py",
    "atlas_v12_upgrade.py",
    "smoke_atlas.py",
    "test_v12.py",
)

for filename in PYTHON_FILES:

    path = ROOT / filename

    if not path.is_file():
        continue

    try:

        source = path.read_text(
            encoding="utf-8"
        )

        compile(
            source,
            str(path),
            "exec",
        )

        check(
            f"Syntax valid: {filename}",
            True,
        )

    except Exception as exc:

        check(
            f"Syntax valid: {filename}",
            False,
            f"{type(exc).__name__}: {exc}",
        )


# ============================================================
# 5. SMOKE TEST SHEBANG
# ============================================================

section("5. SMOKE TEST HEADER")

smoke_path = ROOT / "smoke_atlas.py"

if smoke_path.is_file():

    try:

        lines = smoke_path.read_text(
            encoding="utf-8"
        ).splitlines()

        first_line = (
            lines[0].strip()
            if lines
            else ""
        )

        check(
            "smoke_atlas.py has Python shebang",
            first_line == "#!/usr/bin/env python3",
            f"Found: {first_line}",
        )

    except Exception as exc:

        check(
            "smoke_atlas.py has Python shebang",
            False,
            f"{type(exc).__name__}: {exc}",
        )


# ============================================================
# 6. ACTUAL BOT12 API
# ============================================================

section("6. BOT12 API VALIDATION")

EXPECTED_API = (
    "build_report",
    "personal_report",
    "best_setup_block",
    "generate_csv_report",
    "generate_institutional_csv",
    "fetch_tgju_rate",
    "get_tgju_rates",
    "send_report",
    "send_csv_report",
)

if bot is not None:

    for name in EXPECTED_API:

        exists = hasattr(bot, name)

        if not exists:

            check(
                f"bot12 API: {name}",
                False,
                "Expected function is missing.",
            )

            continue

        obj = getattr(bot, name)

        check(
            f"bot12 API: {name}",
            callable(obj),
            f"type={type(obj).__name__}",
        )


# ============================================================
# 7. TGJU SUPPORT
# ============================================================

section("7. TGJU RATE SUPPORT")

if bot is not None:

    tgju_names = (
        "fetch_tgju_rate",
        "get_tgju_rates",
    )

    for name in tgju_names:

        if hasattr(bot, name):

            obj = getattr(bot, name)

            check(
                f"TGJU function available: {name}",
                callable(obj),
            )

        else:

            check(
                f"TGJU function available: {name}",
                False,
                "TGJU integration is required by v12.",
            )


# ============================================================
# 8. CSV OUTPUT SUPPORT
# ============================================================

section("8. CSV OUTPUT SUPPORT")

if bot is not None:

    csv_functions = (
        "generate_csv_report",
        "generate_institutional_csv",
        "send_csv_report",
    )

    for name in csv_functions:

        if hasattr(bot, name):

            check(
                f"CSV function available: {name}",
                callable(getattr(bot, name)),
            )

        else:

            check(
                f"CSV function available: {name}",
                False,
            )


# ============================================================
# 9. BEST SETUP SUPPORT
# ============================================================

section("9. SETUP ANALYSIS SUPPORT")

if bot is not None:

    setup_functions = (
        "best_setup_block",
        "build_report",
        "personal_report",
    )

    for name in setup_functions:

        if hasattr(bot, name):

            check(
                f"Analysis function available: {name}",
                callable(getattr(bot, name)),
            )

        else:

            check(
                f"Analysis function available: {name}",
                False,
            )


# ============================================================
# 10. UPGRADE MODULE
# ============================================================

section("10. V12 UPGRADE MODULE")

try:

    upgrade = importlib.import_module(
        "atlas_v12_upgrade"
    )

    check(
        "atlas_v12_upgrade.py imports successfully",
        True,
        f"Loaded from: {getattr(upgrade, '__file__', 'unknown')}",
    )

except Exception as exc:

    check(
        "atlas_v12_upgrade.py imports successfully",
        False,
        f"{type(exc).__name__}: {exc}",
    )


# ============================================================
# 11. REQUIRED V12 FEATURES
# ============================================================

section("11. V12 FEATURE CHECK")

if bot is not None:

    features = {
        "TGJU USD": (
            hasattr(bot, "TGJU_USD")
            or hasattr(bot, "fetch_tgju_rate")
            or hasattr(bot, "get_tgju_rates")
        ),

        "TGJU USDT": (
            hasattr(bot, "TGJU_USDT")
            or hasattr(bot, "fetch_tgju_rate")
            or hasattr(bot, "get_tgju_rates")
        ),

        "Personal report": (
            hasattr(bot, "personal_report")
        ),

        "Best setup": (
            hasattr(bot, "best_setup_block")
        ),

        "CSV report": (
            hasattr(bot, "generate_csv_report")
        ),

        "Institutional CSV": (
            hasattr(bot, "generate_institutional_csv")
        ),
    }

    for feature, available in features.items():

        check(
            feature,
            available,
        )


# ============================================================
# 12. FINAL RESULT
# ============================================================

section("FINAL TEST RESULT")

TOTAL = PASSED + FAILED

print(f"Total tests : {TOTAL}")
print(f"Passed      : {PASSED}")
print(f"Failed      : {FAILED}")

print()

if FAILED == 0:

    print("=" * 70)
    print("🎯 ATLAS AI v12 TEST STATUS: PASS")
    print("=" * 70)
    print("Main engine : bot12.py")
    print("TGJU        : validated")
    print("CSV         : validated")
    print("Analysis    : validated")
    print("Upgrade     : validated")
    print("=" * 70)

    sys.exit(0)

else:

    print("=" * 70)
    print("🚨 ATLAS AI v12 TEST STATUS: FAIL")
    print("=" * 70)
    print("One or more mandatory checks failed.")
    print("=" * 70)

    sys.exit(1)
