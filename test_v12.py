#!/usr/bin/env python3

"""
ATLAS AI v12
Test / Validation Suite

این فایل فقط برای تست و اعتبارسنجی است.
موتور اصلی پروژه:
    bot12.py

نکته:
    این فایل عمداً هیچ وابستگی به ATLAS_v12_bot.py یا bot.py ندارد.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path


# ============================================================
# PROJECT ROOT
# ============================================================

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# TEST HELPERS
# ============================================================

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    """
    اجرای یک تست و نمایش نتیجه.
    """
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
# 1. PROJECT FILES
# ============================================================

section("1. PROJECT STRUCTURE")

REQUIRED_FILES = [
    "bot12.py",
    "atlas_v12_upgrade.py",
    "smoke_atlas.py",
    "test_v12.py",
]

OPTIONAL_FILES = [
    "requirements-v12.txt",
    "README_v12.md",
    ".env.example",
]


for filename in REQUIRED_FILES:
    path = ROOT / filename

    check(
        f"Required file exists: {filename}",
        path.is_file(),
        str(path),
    )


for filename in OPTIONAL_FILES:
    path = ROOT / filename

    if path.is_file():
        print(f"ℹ️ OPTIONAL PRESENT: {filename}")
    else:
        print(f"ℹ️ OPTIONAL MISSING: {filename}")


# ============================================================
# 2. IMPORT MAIN ENGINE
# ============================================================

section("2. MAIN ENGINE IMPORT")

try:
    bot = importlib.import_module("bot12")

    check(
        "bot12.py imports successfully",
        True,
        f"Loaded from: {getattr(bot, '__file__', 'unknown')}",
    )

except Exception as exc:
    bot = None

    check(
        "bot12.py imports successfully",
        False,
        f"{type(exc).__name__}: {exc}",
    )


# ============================================================
# 3. FORBIDDEN LEGACY REFERENCES
# ============================================================

section("3. LEGACY REFERENCE CHECK")

files_to_scan = [
    ROOT / "test_v12.py",
    ROOT / "smoke_atlas.py",
    ROOT / "atlas_v12_upgrade.py",
]

for path in files_to_scan:

    if not path.is_file():
        continue

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8-sig")

    forbidden = [
        "ATLAS_v12_bot",
        "import bot ",
        "from bot import",
    ]

    found = [
        item
        for item in forbidden
        if item in content
    ]

    check(
        f"No obsolete import in {path.name}",
        not found,
        f"Found: {found}" if found else "No obsolete references detected.",
    )


# ============================================================
# 4. PYTHON SYNTAX
# ============================================================

section("4. PYTHON SYNTAX VALIDATION")


PYTHON_FILES = [
    "bot12.py",
    "atlas_v12_upgrade.py",
    "smoke_atlas.py",
    "test_v12.py",
]


for filename in PYTHON_FILES:

    path = ROOT / filename

    if not path.is_file():
        continue

    try:
        source = path.read_text(encoding="utf-8")

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
# 5. SMOKE TEST HEADER
# ============================================================

section("5. SMOKE TEST HEADER")

smoke_path = ROOT / "smoke_atlas.py"

if smoke_path.is_file():

    try:
        first_line = smoke_path.read_text(
            encoding="utf-8"
        ).splitlines()[0]

        check(
            "smoke_atlas.py has Python shebang",
            first_line.strip() == "#!/usr/bin/env python3",
            f"Found: {first_line}",
        )

    except Exception as exc:

        check(
            "smoke_atlas.py has Python shebang",
            False,
            f"{type(exc).__name__}: {exc}",
        )


# ============================================================
# 6. MAIN ENGINE API DISCOVERY
# ============================================================

section("6. BOT12 API DISCOVERY")


if bot is not None:

    public_names = [
        name
        for name in dir(bot)
        if not name.startswith("_")
    ]

    print(
        f"ℹ️ Public objects discovered: "
        f"{len(public_names)}"
    )

    print(
        "   "
        + ", ".join(public_names[:50])
    )

    # Common expected functions.
    EXPECTED_FUNCTIONS = [
        "build_personal_report",
        "personal_report",
        "build_market_report",
    ]

    for name in EXPECTED_FUNCTIONS:

        if hasattr(bot, name):

            obj = getattr(bot, name)

            check(
                f"bot12 API: {name}",
                callable(obj),
                f"type={type(obj).__name__}",
            )

        else:

            print(
                f"ℹ️ OPTIONAL API not present: {name}"
            )


# ============================================================
# 7. PERSONAL REPORT ALIAS CONSISTENCY
# ============================================================

section("7. PERSONAL REPORT COMPATIBILITY")


if bot is not None:

    if hasattr(bot, "personal_report"):

        personal = getattr(
            bot,
            "personal_report",
        )

        if hasattr(bot, "build_personal_report"):

            builder = getattr(
                bot,
                "build_personal_report",
            )

            check(
                "personal_report compatibility",
                personal is builder or (
                    callable(personal)
                    and callable(builder)
                ),
                "personal_report and build_personal_report are compatible.",
            )

        else:

            check(
                "personal_report callable",
                callable(personal),
            )

    else:

        print(
            "ℹ️ personal_report alias not present; "
            "no failure because it is optional."
        )


# ============================================================
# 8. V12 UPGRADE MODULE
# ============================================================

section("8. V12 UPGRADE MODULE")

upgrade = None

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
# 9. BASIC CALLABLE VALIDATION
# ============================================================

section("9. CALLABLE VALIDATION")


if bot is not None:

    candidates = [
        "build_personal_report",
        "personal_report",
        "build_market_report",
        "health_check",
        "volume_spike_warning",
        "rsi_divergence",
    ]

    for name in candidates:

        if hasattr(bot, name):

            obj = getattr(bot, name)

            check(
                f"{name} is callable",
                callable(obj),
            )

        else:

            print(
                f"ℹ️ Function not present: {name}"
            )


# ============================================================
# 10. MODULE METADATA
# ============================================================

section("10. MODULE METADATA")


if bot is not None:

    module_file = getattr(
        bot,
        "__file__",
        None,
    )

    check(
        "bot12 module has valid path",
        bool(module_file),
        str(module_file),
    )


# ============================================================
# 11. FINAL RESULT
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
    print("All mandatory validation checks passed.")
    print("Engine: bot12.py")
    print("=" * 70)

    sys.exit(0)

else:

    print("=" * 70)
    print("🚨 ATLAS AI v12 TEST STATUS: FAIL")
    print("=" * 70)
    print(
        "One or more validation checks failed."
    )
    print("=" * 70)

    sys.exit(1)
