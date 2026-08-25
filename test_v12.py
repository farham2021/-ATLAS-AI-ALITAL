#!/usr/bin/env python3

import ast
import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def parse_python_file(path: Path) -> None:
    assert path.exists(), f"Missing file: {path.name}"
    ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )


def main() -> None:
    print("=" * 70)
    print("ATLAS AI v12 — VALIDATION TEST")
    print("=" * 70)

    required_files = (
        "bot12.py",
        "atlas_v12_upgrade.py",
        "smoke_atlas.py",
        "test_v12.py",
    )

    # ------------------------------------------------------------
    # 1. Required files + syntax
    # ------------------------------------------------------------
    print("\n[1] FILE / SYNTAX VALIDATION")

    for filename in required_files:
        path = ROOT / filename
        parse_python_file(path)
        print(f"PASS: {filename}")

    # ------------------------------------------------------------
    # 2. Main engine import
    # ------------------------------------------------------------
    print("\n[2] BOT12 IMPORT")

    bot = importlib.import_module("bot12")

    assert callable(
        getattr(bot, "personal_report", None)
    ), "bot12.personal_report is missing"

    assert callable(
        getattr(bot, "build_report", None)
    ), "bot12.build_report is missing"

    print("PASS: bot12 imports successfully")
    print("PASS: personal_report callable")
    print("PASS: build_report callable")

    # ------------------------------------------------------------
    # 3. Upgrade module import
    # ------------------------------------------------------------
    print("\n[3] V12 UPGRADE MODULE")

    upgrade = importlib.import_module("atlas_v12_upgrade")

    assert callable(
        getattr(upgrade, "health_check", None)
    ), "atlas_v12_upgrade.health_check is missing"

    assert callable(
        getattr(upgrade, "build_personal_report", None)
    ), "atlas_v12_upgrade.build_personal_report is missing"

    assert callable(
        getattr(upgrade, "build_market_report", None)
    ), "atlas_v12_upgrade.build_market_report is missing"

    print("PASS: atlas_v12_upgrade imports successfully")
    print("PASS: health_check callable")
    print("PASS: build_personal_report callable")
    print("PASS: build_market_report callable")

    # ------------------------------------------------------------
    # 4. Legacy import check
    # ------------------------------------------------------------
    print("\n[4] LEGACY IMPORT CHECK")

    files_to_check = (
        "bot12.py",
        "atlas_v12_upgrade.py",
        "smoke_atlas.py",
        "test_v12.py",
    )

    forbidden_patterns = (
        "import ATLAS_v12_bot",
        "from ATLAS_v12_bot import",
        "import bot",
        "from bot import",
    )

    for filename in files_to_check:
        path = ROOT / filename
        text = path.read_text(encoding="utf-8")

        found = [
            pattern
            for pattern in forbidden_patterns
            if pattern in text
        ]

        # test_v12.py itself must not contain the forbidden strings
        # as executable/import references. The test intentionally
        # avoids searching its own source for these strings.
        if filename == "test_v12.py":
            continue

        assert not found, (
            f"Legacy import(s) found in {filename}: {found}"
        )

        print(f"PASS: no legacy imports in {filename}")

    # ------------------------------------------------------------
    # 5. Smoke-test shebang
    # ------------------------------------------------------------
    print("\n[5] SMOKE TEST SHEBANG")

    smoke = ROOT / "smoke_atlas.py"
    first_line = smoke.read_text(
        encoding="utf-8"
    ).splitlines()[0].strip()

    assert first_line == "#!/usr/bin/env python3", (
        "smoke_atlas.py must start with "
        "#!/usr/bin/env python3"
    )

    print("PASS: smoke_atlas.py shebang")

    # ------------------------------------------------------------
    # 6. Final result
    # ------------------------------------------------------------
    print("\n" + "=" * 70)
    print("ATLAS AI v12 TEST STATUS: PASS")
    print("=" * 70)


if __name__ == "__main__":
    main()
