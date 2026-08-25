#!/usr/bin/env python3
"""
ATLAS AI v12 — Telegram Entry Point

Purpose:
    - Load the real v12 engine from bot12.py
    - Build the v12 market/personal report
    - Send the complete report to Telegram
    - Fail loudly if Telegram delivery fails

IMPORTANT:
    This file must NOT import:
        bot
        ATLAS_v12_bot

    The canonical v12 engine is:
        bot12.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Callable, Optional

try:
    import bot12 as engine
except Exception as exc:
    print("❌ Failed to import bot12.py")
    print(f"   {type(exc).__name__}: {exc}")
    raise


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or getattr(engine, "TELEGRAM_TOKEN", "")
)

CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or getattr(engine, "TELEGRAM_CHAT_ID", "")
)

GROUP_CHAT_ID = (
    os.getenv("TELEGRAM_GROUP_CHAT_ID")
    or os.getenv("TELEGRAM_SUPERGROUP_CHAT_ID")
    or getattr(engine, "TELEGRAM_GROUP_CHAT_ID", "")
)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _telegram_url(method: str) -> str:
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN is not configured."
        )

    return (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/{method}"
    )


def _send_telegram_message(
    chat_id: str,
    text: str,
    timeout: int = 30,
) -> dict:
    """
    Send one Telegram message.

    Uses requests if available.
    No silent failure.
    """

    if not chat_id:
        raise RuntimeError("Telegram chat ID is empty.")

    if not text:
        raise RuntimeError("Telegram message is empty.")

    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "The 'requests' package is required for Telegram delivery."
        ) from exc

    response = requests.post(
        _telegram_url("sendMessage"),
        json={
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=timeout,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Telegram HTTP error {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Telegram returned non-JSON response: {response.text[:500]}"
        ) from exc

    if not payload.get("ok"):
        raise RuntimeError(
            f"Telegram API rejected message: {payload}"
        )

    return payload


def split_telegram(text: str, limit: int = 3900) -> list[str]:
    """
    Telegram's practical text-message limit is below 4096 characters.

    Split preferably at newline boundaries.
    """

    if not text:
        return []

    text = str(text)

    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines():
        line_len = len(line) + 1

        if current and current_len + line_len > limit:
            parts.append("\n".join(current))
            current = []
            current_len = 0

        # Extremely long single line
        if line_len > limit:
            if current:
                parts.append("\n".join(current))
                current = []
                current_len = 0

            for i in range(0, len(line), limit):
                parts.append(line[i:i + limit])

            continue

        current.append(line)
        current_len += line_len

    if current:
        parts.append("\n".join(current))

    return parts


def send_report_to_chat(
    report: str,
    chat_id: str,
) -> int:
    """
    Send all report parts to one Telegram destination.
    Returns number of successfully delivered parts.
    """

    if not chat_id:
        return 0

    parts = split_telegram(report)

    if not parts:
        raise RuntimeError("No report content to send.")

    sent = 0

    for part in parts:
        _send_telegram_message(chat_id, part)
        sent += 1

        # Small delay avoids aggressive API bursts.
        if sent < len(parts):
            time.sleep(0.35)

    return sent


def send_report(
    report: str,
    *,
    send_to_group: bool = True,
) -> tuple[int, int, list[str]]:
    """
    Deliver the report.

    Returns:
        (private_sent, group_sent, errors)

    The function does not hide delivery failures.
    """

    errors: list[str] = []

    private_sent = 0
    group_sent = 0

    # Personal/chat destination
    if CHAT_ID:
        try:
            private_sent = send_report_to_chat(
                report,
                CHAT_ID,
            )
        except Exception as exc:
            errors.append(
                f"CHAT_ID delivery failed: "
                f"{type(exc).__name__}: {exc}"
            )

    # Supergroup destination
    if send_to_group and GROUP_CHAT_ID:
        try:
            group_sent = send_report_to_chat(
                report,
                GROUP_CHAT_ID,
            )
        except Exception as exc:
            errors.append(
                f"GROUP_CHAT_ID delivery failed: "
                f"{type(exc).__name__}: {exc}"
            )

    if not CHAT_ID and not GROUP_CHAT_ID:
        errors.append(
            "No Telegram destination configured."
        )

    return private_sent, group_sent, errors


# ---------------------------------------------------------------------------
# Engine compatibility
# ---------------------------------------------------------------------------

def _find_report_builder() -> Callable[..., Any]:
    """
    Find the canonical report function exposed by bot12.py.

    Priority:
        build_report
        personal_report
        report
    """

    candidates = (
        "build_report",
        "personal_report",
        "report",
    )

    for name in candidates:
        candidate = getattr(engine, name, None)

        if callable(candidate):
            return candidate

    raise RuntimeError(
        "No supported v12 report builder was found in bot12.py. "
        "Expected one of: build_report, personal_report, report."
    )


def build_report() -> str:
    """
    Build the actual ATLAS v12 report.

    No fake fallback report is generated.
    """

    builder = _find_report_builder()

    result = builder()

    # Some older project functions return:
    #     (report, ...)
    if isinstance(result, tuple):
        if not result:
            raise RuntimeError(
                "v12 report builder returned an empty tuple."
            )

        result = result[0]

    if result is None:
        raise RuntimeError(
            "v12 report builder returned None."
        )

    report = str(result).strip()

    if not report:
        raise RuntimeError(
            "v12 report builder returned an empty report."
        )

    return report


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight() -> None:
    """
    Validate the minimum runtime configuration before doing any work.
    """

    print("=" * 70)
    print("ATLAS AI v12 — TELEGRAM PREFLIGHT")
    print("=" * 70)

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "❌ Telegram bot token is missing.\n"
            "Set TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN."
        )

    if not CHAT_ID and not GROUP_CHAT_ID:
        raise RuntimeError(
            "❌ No Telegram destination configured.\n"
            "Set TELEGRAM_CHAT_ID and/or TELEGRAM_GROUP_CHAT_ID."
        )

    print("✅ Telegram token: configured")

    if CHAT_ID:
        print("✅ Personal Chat ID: configured")
    else:
        print("⚠️ Personal Chat ID: not configured")

    if GROUP_CHAT_ID:
        print("✅ Supergroup Chat ID: configured")
    else:
        print("⚠️ Supergroup Chat ID: not configured")

    print("✅ bot12.py: imported")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Full ATLAS v12 execution:
        1. Preflight
        2. Build report
        3. Send to personal chat
        4. Send to supergroup
        5. Fail if delivery failed
    """

    preflight()

    print("📊 Building ATLAS AI v12 report...")

    report = build_report()

    print(
        f"✅ Report generated successfully "
        f"({len(report)} characters)"
    )

    private_sent, group_sent, errors = send_report(
        report,
        send_to_group=True,
    )

    print("-" * 70)
    print(f"📨 Personal messages sent: {private_sent}")
    print(f"👥 Supergroup messages sent: {group_sent}")

    if errors:
        print("❌ Telegram delivery errors:")

        for error in errors:
            print(f"   - {error}")

    total_sent = private_sent + group_sent

    if total_sent == 0:
        raise RuntimeError(
            "Telegram delivery failed: 0 messages were sent."
        )

    # If a configured destination failed, do not claim full success.
    configured_destinations = int(bool(CHAT_ID)) + int(bool(GROUP_CHAT_ID))
    successful_destinations = (
        int(private_sent > 0) +
        int(group_sent > 0)
    )

    if successful_destinations < configured_destinations:
        raise RuntimeError(
            "Partial Telegram delivery failure. "
            "Check the errors above."
        )

    print("-" * 70)
    print(
        f"✅ ATLAS AI v12 delivered successfully: "
        f"{total_sent} message parts"
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user.")
        raise SystemExit(130)
    except Exception as exc:
        print(
            f"\n🚨 ATLAS AI v12 FAILED: "
            f"{type(exc).__name__}: {exc}"
        )
        raise SystemExit(1)
