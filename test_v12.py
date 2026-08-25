#!/usr/bin/env python3

"""
ATLAS AI v12
Final Validation Test Suite

Canonical V12 engine:
    bot12.py

This test verifies:
1. Required project files
2. Obsolete engine imports
3. Python syntax
4. Smoke-test shebang
5. bot12 import
6. V12 upgrade module
7. Telegram delivery module
8. bot12 public report API
9. Telegram delivery API
10. Canonical V12 engine path
"""

from __future__ import annotations

import importlib
import pathlib
import py_compile


ROOT = pathlib.Path(__file__).resolve().parent


REQUIRED_FILES = [
    "bot12.py",
    "atlas_v12_upgrade.py",
    "telegram_delivery_v12.py",
    "smoke_atlas.py",
    "test_v12.py",
]


PYTHON_FILES = [
    "bot12.py",
    "atlas_v12_upgrade.py",
    "telegram_delivery_v12.py",
    "smoke_atlas.py",
    "test_v12.py",
]


def check_project_structure():
    print("=" * 70)
    print("1. PROJECT STRUCTURE")
    print("=" * 70)

    for filename in REQUIRED_FILES:
        path = ROOT / filename

        if not path.is_file():
            raise AssertionError(
                f"Missing required file: {filename}"
            )

        print(f"PASS: {filename}")


def check_legacy_references():
    print()
    print("=" * 70)
    print("2. LEGACY REFERENCE CHECK")
    print("=" * 70)

    # Only real obsolete imports are checked here.
    # The test itself does not contain legacy engine names.

    forbidden_imports = (
        "from bot import",
        "import bot ",
        "import bot\n",
    )

    files_to_check = [
        "bot12.py",
        "atlas_v12_upgrade.py",
        "telegram_delivery_v12.py",
        "smoke_atlas.py",
    ]

    for filename in files_to_check:
        path = ROOT / filename

        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for pattern in forbidden_imports:
            if pattern in text:
                raise AssertionError(
                    f"Obsolete import found in "
                    f"{filename}: {pattern}"
                )

        print(
            f"PASS: no obsolete engine reference "
            f"in {filename}"
        )


def check_python_syntax():
    print()
    print("=" * 70)
    print("3. PYTHON SYNTAX VALIDATION")
    print("=" * 70)

    for filename in PYTHON_FILES:
        path = ROOT / filename

        py_compile.compile(
            str(path),
            doraise=True,
        )

        print(
            f"PASS: syntax valid: {filename}"
        )


def check_smoke_header():
    print()
    print("=" * 70)
    print("4. SMOKE TEST HEADER")
    print("=" * 70)

    path = ROOT / "smoke_atlas.py"

    lines = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    if not lines:
        raise AssertionError(
            "smoke_atlas.py is empty"
        )

    expected = "#!/usr/bin/env python3"

    if lines[0].strip() != expected:
        raise AssertionError(
            "smoke_atlas.py must start with "
            "#!/usr/bin/env python3"
        )

    print(
        "PASS: smoke_atlas.py has Python shebang"
    )


def import_module_or_fail(
    module_name: str,
):
    try:
        return importlib.import_module(
            module_name
        )
    except Exception as exc:
        raise AssertionError(
            f"{module_name} import failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def check_bot12_import():
    print()
    print("=" * 70)
    print("5. BOT12 IMPORT")
    print("=" * 70)

    module = import_module_or_fail(
        "bot12"
    )

    module_path = pathlib.Path(
        module.__file__
    ).resolve()

    expected_path = (
        ROOT / "bot12.py"
    ).resolve()

    if module_path != expected_path:
        raise AssertionError(
            "Imported engine is not the "
            "repository bot12.py"
        )

    print(
        "PASS: bot12.py imports successfully"
    )

    print(
        f"Loaded from: {module_path}"
    )


def check_upgrade_module():
    print()
    print("=" * 70)
    print("6. V12 UPGRADE MODULE")
    print("=" * 70)

    import_module_or_fail(
        "atlas_v12_upgrade"
    )

    print(
        "PASS: atlas_v12_upgrade.py "
        "imports successfully"
    )


def check_delivery_module():
    print()
    print("=" * 70)
    print("7. TELEGRAM DELIVERY MODULE")
    print("=" * 70)

    import_module_or_fail(
        "telegram_delivery_v12"
    )

    print(
        "PASS: telegram_delivery_v12.py "
        "imports successfully"
    )


def check_bot12_api():
    print()
    print("=" * 70)
    print("8. BOT12 API DISCOVERY")
    print("=" * 70)

    module = import_module_or_fail(
        "bot12"
    )

    public_names = sorted(
        name
        for name in dir(module)
        if not name.startswith("_")
    )

    print(
        f"Public objects discovered: "
        f"{len(public_names)}"
    )

    candidates = (
        "report",
        "build_report",
        "personal_report",
    )

    available = [
        name
        for name in candidates
        if callable(
            getattr(module, name, None)
        )
    ]

    if not available:
        raise AssertionError(
            "No supported report API found "
            "in bot12.py"
        )

    for name in available:
        print(
            f"PASS: bot12 API: {name}"
        )


def check_delivery_api():
    print()
    print("=" * 70)
    print("9. TELEGRAM DELIVERY API")
    print("=" * 70)

    module = import_module_or_fail(
        "telegram_delivery_v12"
    )

    candidates = (
        "send_report",
        "send_telegram_report",
        "deliver_report",
    )

    available = [
        name
        for name in candidates
        if callable(
            getattr(module, name, None)
        )
    ]

    if not available:
        raise AssertionError(
            "No Telegram delivery function "
            "found in telegram_delivery_v12.py"
        )

    for name in available:
        print(
            f"PASS: Telegram delivery API: {name}"
        )


def check_canonical_engine():
    print()
    print("=" * 70)
    print("10. CANONICAL V12 ENGINE")
    print("=" * 70)

    module = import_module_or_fail(
        "bot12"
    )

    module_path = pathlib.Path(
        module.__file__
    ).resolve()

    expected_path = (
        ROOT / "bot12.py"
    ).resolve()

    if module_path != expected_path:
        raise AssertionError(
            "Canonical V12 engine is not "
            "bot12.py"
        )

    print(
        "PASS: canonical V12 engine = bot12.py"
    )


def main():
    check_project_structure()
    check_legacy_references()
    check_python_syntax()
    check_smoke_header()
    check_bot12_import()
    check_upgrade_module()
    check_delivery_module()
    check_bot12_api()
    check_delivery_api()
    check_canonical_engine()

    print()
    print("=" * 70)
    print("ATLAS AI v12 TEST STATUS: PASS")
    print("=" * 70)
    print(
        "All V12 validation checks completed "
        "successfully."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
