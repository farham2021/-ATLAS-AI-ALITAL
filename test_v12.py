#!/usr/bin/env python3

"""
ATLAS AI v12
Final Validation Test

Canonical engine:
    bot12.py

This test deliberately rejects obsolete engine references.
"""

from __future__ import annotations

import importlib
import pathlib
import py_compile
import sys


ROOT = pathlib.Path(__file__).resolve().parent


REQUIRED_FILES = [
    "bot12.py",
    "atlas_v12_upgrade.py",
    "telegram_delivery_v12.py",
    "smoke_atlas.py",
    "test_v12.py",
]


OBSOLETE_REFERENCES = [
    "ATLAS_v12_bot",
    "from bot import",
    "import bot ",
]


PYTHON_FILES = [
    "bot12.py",
    "atlas_v12_upgrade.py",
    "telegram_delivery_v12.py",
    "smoke_atlas.py",
    "test_v12.py",
]


def check_project_structure() -> None:
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


def check_legacy_references() -> None:
    print()
    print("=" * 70)
    print("2. LEGACY REFERENCE CHECK")
    print("=" * 70)

    for filename in PYTHON_FILES:
        path = ROOT / filename
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for obsolete in OBSOLETE_REFERENCES:
            if obsolete in text:
                raise AssertionError(
                    f"Obsolete reference found in "
                    f"{filename}: {obsolete}"
                )

        print(
            f"PASS: no obsolete engine reference in {filename}"
        )


def check_python_syntax() -> None:
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

        print(f"PASS: syntax valid: {filename}")


def check_smoke_header() -> None:
    print()
    print("=" * 70)
    print("4. SMOKE TEST HEADER")
    print("=" * 70)

    path = ROOT / "smoke_atlas.py"

    first_line = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()[0].strip()

    expected = "#!/usr/bin/env python3"

    if first_line != expected:
        raise AssertionError(
            "smoke_atlas.py must start with "
            f"{expected!r}"
        )

    print(
        "PASS: smoke_atlas.py has correct Python shebang"
    )


def check_bot12_import() -> None:
    print()
    print("=" * 70)
    print("5. BOT12 IMPORT")
    print("=" * 70)

    try:
        module = importlib.import_module("bot12")
    except Exception as exc:
        raise AssertionError(
            f"bot12.py import failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    module_path = pathlib.Path(
        getattr(module, "__file__", "")
    ).resolve()

    expected_path = (
        ROOT / "bot12.py"
    ).resolve()

    if module_path != expected_path:
        raise AssertionError(
            "Imported bot12 module is not the "
            "repository bot12.py"
        )

    print("PASS: bot12.py imports successfully")
    print(f"Loaded from: {module_path}")


def check_upgrade_module() -> None:
    print()
    print("=" * 70)
    print("6. V12 UPGRADE MODULE")
    print("=" * 70)

    try:
        module = importlib.import_module(
            "atlas_v12_upgrade"
        )
    except Exception as exc:
        raise AssertionError(
            "atlas_v12_upgrade.py import failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    print(
        "PASS: atlas_v12_upgrade.py imports successfully"
    )

    return module


def check_delivery_module() -> None:
    print()
    print("=" * 70)
    print("7. TELEGRAM DELIVERY MODULE")
    print("=" * 70)

    try:
        module = importlib.import_module(
            "telegram_delivery_v12"
        )
    except Exception as exc:
        raise AssertionError(
            "telegram_delivery_v12.py import failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    print(
        "PASS: telegram_delivery_v12.py imports successfully"
    )

    return module


def check_bot12_api() -> None:
    print()
    print("=" * 70)
    print("8. BOT12 API DISCOVERY")
    print("=" * 70)

    module = importlib.import_module("bot12")

    public_names = sorted(
        name
        for name in dir(module)
        if not name.startswith("_")
    )

    print(
        f"Public objects discovered: "
        f"{len(public_names)}"
    )

    # The v12 engine must expose at least one
    # recognized report-building function.
    candidates = [
        "build_report",
        "personal_report",
        "report",
    ]

    available = [
        name
        for name in candidates
        if callable(getattr(module, name, None))
    ]

    if not available:
        raise AssertionError(
            "bot12.py exposes none of the supported "
            "report functions: "
            + ", ".join(candidates)
        )

    print(
        "PASS: report API available: "
        + ", ".join(available)
    )


def check_delivery_api() -> None:
    print()
    print("=" * 70)
    print("9. TELEGRAM DELIVERY API")
    print("=" * 70)

    module = importlib.import_module(
        "telegram_delivery_v12"
    )

    candidates = [
        "send_report",
        "send_telegram_report",
        "deliver_report",
    ]

    available = [
        name
        for name in candidates
        if callable(getattr(module, name, None))
    ]

    if not available:
        raise AssertionError(
            "telegram_delivery_v12.py exposes none of "
            "the supported delivery functions."
        )

    print(
        "PASS: Telegram delivery API available: "
        + ", ".join(available)
    )


def check_canonical_engine() -> None:
    print()
    print("=" * 70)
    print("10. CANONICAL V12 ENGINE")
    print("=" * 70)

    bot12 = importlib.import_module("bot12")

    module_file = pathlib.Path(
        bot12.__file__
    ).resolve()

    expected = (
        ROOT / "bot12.py"
    ).resolve()

    if module_file != expected:
        raise AssertionError(
            "Canonical engine is not bot12.py"
        )

    print("PASS: canonical v12 engine = bot12.py")


def main() -> int:
    try:
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

    except Exception as exc:
        print()
        print("=" * 70)
        print("ATLAS AI v12 TEST STATUS: FAIL")
        print("=" * 70)
        print(
            f"{type(exc).__name__}: {exc}"
        )
        return 1

    print()
    print("=" * 70)
    print("ATLAS AI v12 TEST STATUS: PASS")
    print("=" * 70)
    print("All v12 validation checks completed successfully.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
