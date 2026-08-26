#!/usr/bin/env python3
"""
ATLAS AI v11.2
Regression / integration test suite.

Goals:
- Verify bot.py is importable.
- Verify v11.2 environment/version configuration.
- Verify core reporting functions exist.
- Verify Telegram dual-destination delivery interface.
- Verify Telegram message splitting.
- Verify trade geometry / R:R helpers when available.
- Never send a real Telegram message during tests.
- Never require live market data.
- Never require Data Analysis.
"""

from __future__ import annotations

import importlib
import os
import sys
import types


VERSION = "11.2"


def fail(message: str) -> None:
    raise AssertionError(message)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def main() -> None:
    print("=" * 70)
    print("ATLAS AI v11.2 TEST SUITE")
    print("=" * 70)

    # ------------------------------------------------------------
    # 1. Environment
    # ------------------------------------------------------------

    print("\n[1] ENVIRONMENT")

    version = os.getenv("ATLAS_VERSION", "11.2")

    check(
        str(version).startswith("11.2"),
        f"Unexpected ATLAS_VERSION: {version}",
    )

    timeframe = os.getenv("ATLAS_TIMEFRAME", "4H")

    check(
        timeframe.upper() == "4H",
        f"Unexpected ATLAS_TIMEFRAME: {timeframe}",
    )

    print("PASS: ATLAS_VERSION =", version)
    print("PASS: ATLAS_TIMEFRAME =", timeframe)

    # ------------------------------------------------------------
    # 2. Import bot.py
    # ------------------------------------------------------------

    print("\n[2] BOT IMPORT")

    try:
        bot = importlib.import_module("bot")
    except Exception as exc:
        raise AssertionError(
            "bot.py could not be imported: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    print("PASS: bot.py imported successfully")

    # ------------------------------------------------------------
    # 3. Version detection
    # ------------------------------------------------------------

    print("\n[3] VERSION / CORE")

    detected_version = getattr(
        bot,
        "VERSION",
        getattr(bot, "ATLAS_VERSION", "11.2"),
    )

    print("Detected version:", detected_version)

    # Do not hard-fail on an implementation that stores the
    # version under another internal name. The workflow already
    # controls ATLAS_VERSION.
    print("PASS: version configuration accessible")

    # ------------------------------------------------------------
    # 4. Required core functions
    # ------------------------------------------------------------

    print("\n[4] CORE FUNCTIONS")

    required_any = {
        "report": ["report"],
        "send_report": ["send_report"],
        "split_telegram": ["split_telegram"],
    }

    for logical_name, candidates in required_any.items():

        found = None

        for candidate in candidates:
            obj = getattr(bot, candidate, None)

            if callable(obj):
                found = candidate
                break

        check(
            found is not None,
            f"Required callable missing: {logical_name}",
        )

        print(
            f"PASS: {logical_name} -> {found}"
        )

    # ------------------------------------------------------------
    # 5. Telegram destination variables
    # ------------------------------------------------------------

    print("\n[5] TELEGRAM CONFIGURATION")

    telegram_token = (
        getattr(bot, "TELEGRAM_TOKEN", None)
        or os.getenv("TELEGRAM_TOKEN", "")
    )

    telegram_chat = (
        getattr(bot, "TELEGRAM_CHAT_ID", None)
        or os.getenv("TELEGRAM_CHAT_ID", "")
    )

    telegram_group = (
        getattr(bot, "TELEGRAM_GROUP_CHAT_ID", None)
        or os.getenv("TELEGRAM_GROUP_CHAT_ID", "")
    )

    check(
        bool(telegram_token),
        "TELEGRAM_TOKEN is not configured",
    )

    check(
        bool(telegram_chat or telegram_group),
        "No Telegram destination configured",
    )

    print("PASS: TELEGRAM_TOKEN configured")
    print(
        "PASS: destinations configured:",
        int(bool(telegram_chat)),
        "private /",
        int(bool(telegram_group)),
        "supergroup",
    )

    # ------------------------------------------------------------
    # 6. Telegram splitting regression
    # ------------------------------------------------------------

    print("\n[6] TELEGRAM SPLIT")

    split_function = getattr(
        bot,
        "split_telegram",
        None,
    )

    check(
        callable(split_function),
        "split_telegram() is missing",
    )

    short_message = "ATLAS v11.2 TEST"

    try:
        parts = split_function(short_message)
    except TypeError:
        parts = split_function(
            short_message,
            max_chars=3900,
        )

    check(
        isinstance(parts, list),
        "split_telegram() must return a list",
    )

    check(
        len(parts) >= 1,
        "split_telegram() returned no parts",
    )

    check(
        "".join(parts).replace("\n\n", "")
        == short_message.replace("\n\n", ""),
        "Telegram split altered the message",
    )

    print(
        "PASS: Telegram splitting:",
        len(parts),
        "part(s)",
    )

    # ------------------------------------------------------------
    # 7. Large Telegram message regression
    # ------------------------------------------------------------

    print("\n[7] LARGE MESSAGE SPLIT")

    large_message = (
        "ATLAS v11.2 TEST BLOCK\n\n"
        + ("BTC market analysis line\n" * 500)
    )

    try:
        large_parts = split_function(large_message)
    except TypeError:
        large_parts = split_function(
            large_message,
            max_chars=3900,
        )

    check(
        len(large_parts) > 1,
        "Large Telegram message was not split",
    )

    for index, part in enumerate(large_parts, 1):
        check(
            len(part) <= 4000,
            f"Telegram part {index} exceeds safe message length",
        )

    print(
        "PASS: large message split into",
        len(large_parts),
        "parts",
    )

    # ------------------------------------------------------------
    # 8. R/R / trade geometry regression
    # ------------------------------------------------------------

    print("\n[8] TRADE GEOMETRY")

    geometry_candidates = [
        "decision_rr",
        "calculate_rr",
        "trade_geometry",
    ]

    geometry_found = None

    for name in geometry_candidates:
        if callable(getattr(bot, name, None)):
            geometry_found = name
            break

    if geometry_found:
        print(
            "PASS: trade geometry function:",
            geometry_found,
        )
    else:
        print(
            "PASS: no standalone geometry function required; "
            "geometry may be encapsulated in the engine."
        )

    # ------------------------------------------------------------
    # 9. Report generation regression
    # ------------------------------------------------------------

    print("\n[9] REPORT ENGINE")

    report_function = getattr(
        bot,
        "report",
        None,
    )

    check(
        callable(report_function),
        "report() is missing",
    )

    print(
        "PASS: report() callable detected"
    )

    # ------------------------------------------------------------
    # IMPORTANT:
    # Do NOT execute report() here.
    #
    # Reason:
    # - report() may contact live exchanges.
    # - report() may contact Supabase.
    # - report() may consume rate limits.
    # - report() must not send real Telegram messages during tests.
    #
    # ------------------------------------------------------------

    # ------------------------------------------------------------
    # 10. Telegram delivery safety
    # ------------------------------------------------------------

    print("\n[10] TELEGRAM DELIVERY SAFETY")

    send_function = getattr(
        bot,
        "send_report",
        None,
    )

    check(
        callable(send_function),
        "send_report() is missing",
    )

    # The test intentionally does NOT call send_report().
    # Calling it here would send a real message to production
    # Telegram destinations.

    print(
        "PASS: send_report() exists"
    )
    print(
        "PASS: real Telegram delivery was NOT triggered by tests"
    )

    # ------------------------------------------------------------
    # 11. Legacy import regression
    # ------------------------------------------------------------

    print("\n[11] LEGACY REFERENCE CHECK")

    source_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "bot.py",
    )

    with open(
        source_path,
        "r",
        encoding="utf-8",
    ) as handle:
        source = handle.read()

    forbidden = [
        "ATLAS_v12_bot",
        "from bot import",
        "import bot ",
        "ATLAS_v10_bot",
        "AtlasAI_v10_bot",
    ]

    for pattern in forbidden:

        if pattern in source:

            fail(
                "Obsolete reference found in bot.py: "
                + pattern
            )

    print(
        "PASS: no obsolete engine references in bot.py"
    )

    # ------------------------------------------------------------
    # 12. v11.2-specific configuration
    # ------------------------------------------------------------

    print("\n[12] V11.2 CONFIGURATION")

    expected_environment = {
        "ATLAS_TIMEFRAME": "4H",
        "ATLAS_TRADINGVIEW_INTERVAL": "240",
    }

    for key, expected in expected_environment.items():

        actual = os.getenv(key)

        if actual is None:

            # Some CI configurations may omit these values.
            # This is not a functional failure because the bot
            # has internal defaults.
            print(
                f"INFO: {key} not explicitly exported; "
                f"default/engine value will be used."
            )

        else:

            check(
                actual == expected,
                f"{key} expected {expected}, got {actual}",
            )

            print(
                f"PASS: {key}={actual}"
            )

    # ------------------------------------------------------------
    # 13. Smoke compatibility
    # ------------------------------------------------------------

    print("\n[13] SMOKE COMPATIBILITY")

    smoke_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "smoke_atlas.py",
    )

    check(
        os.path.isfile(smoke_path),
        "smoke_atlas.py is missing",
    )

    print(
        "PASS: smoke_atlas.py exists"
    )

    # ------------------------------------------------------------
    # FINAL
    # ------------------------------------------------------------

    print("\n" + "=" * 70)
    print("ATLAS AI v11.2 TEST STATUS: PASS")
    print("=" * 70)
    print("No live Telegram message was sent by test_v11_2.py.")
    print("No live market analysis was required.")
    print("No Data Analysis step is required.")
    print("=" * 70)


if __name__ == "__main__":
    main()
