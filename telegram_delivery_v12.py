#!/usr/bin/env python3
"""ATLAS AI v12 Telegram delivery layer.

Drop-in delivery helpers for bot12.py.
- Sends to both TELEGRAM_CHAT_ID and TELEGRAM_GROUP_CHAT_ID when configured.
- Retries transient Telegram/HTTP failures.
- Never silently treats a failed destination as success.
- Splits messages below Telegram's 4096-char limit.
- Sends CSV files with sendDocument.
- Does not use data analysis.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Iterable, List, Tuple

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID", "").strip()

MAX_MESSAGE_CHARS = 3900
MAX_RETRIES = 4
BASE_DELAY = 1.5
HTTP_TIMEOUT = 30


def _destinations() -> List[str]:
    out: List[str] = []
    for value in (TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID):
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _request_json(method: str, payload: bytes, content_type: str) -> dict:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": content_type, "User-Agent": "ATLAS-AI-v12"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
        raw = response.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")
    return data


def telegram_preflight() -> dict:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing from GitHub Secrets")
    destinations = _destinations()
    if not destinations:
        raise RuntimeError(
            "No Telegram destination configured. Set TELEGRAM_CHAT_ID and/or "
            "TELEGRAM_GROUP_CHAT_ID."
        )
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
        headers={"User-Agent": "ATLAS-AI-v12"},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getMe failed: {data}")
    print(
        "Telegram preflight OK: "
        f"@{(data.get('result') or {}).get('username', 'unknown')} | "
        f"destinations={len(destinations)}"
    )
    return data.get("result") or {}


def split_telegram(text: str, max_chars: int = MAX_MESSAGE_CHARS) -> List[str]:
    text = str(text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    parts: List[str] = []
    current = ""
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        if len(block) <= max_chars:
            current = block
        else:
            for i in range(0, len(block), max_chars):
                parts.append(block[i:i + max_chars])
    if current:
        parts.append(current)
    return parts


def _send_message_once(chat_id: str, text: str) -> None:
    payload = urllib.parse.urlencode(
        {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    _request_json("sendMessage", payload, "application/x-www-form-urlencoded")


def _retry(callable_, label: str) -> None:
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            callable_()
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == MAX_RETRIES:
                break
            delay = BASE_DELAY * (2 ** (attempt - 1))
            print(f"Telegram retry: {label}; attempt={attempt}; wait={delay:.1f}s; error={exc}")
            time.sleep(delay)
    raise RuntimeError(f"Telegram delivery failed after {MAX_RETRIES} attempts: {label}: {last}")


def send_report(text: str) -> Tuple[int, int, List[str]]:
    parts = split_telegram(text)
    destinations = _destinations()
    if not destinations:
        return len(parts), 0, ["No Telegram destination configured"]

    sent = 0
    errors: List[str] = []
    for chat_id in destinations:
        for index, part in enumerate(parts, 1):
            try:
                _retry(
                    lambda cid=chat_id, p=part: _send_message_once(cid, p),
                    f"sendMessage destination={chat_id} part={index}/{len(parts)}",
                )
                sent += 1
                time.sleep(0.5)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"destination={chat_id} part={index}: {exc}")
                break
    return len(parts), sent, errors


def _multipart_document(chat_id: str, content: str, filename: str, caption: str = "") -> None:
    boundary = "----ATLAS" + uuid.uuid4().hex
    body = bytearray()

    def field(name: str, value: str) -> None:
        body.extend(
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n".encode("utf-8")
        )

    field("chat_id", str(chat_id))
    if caption:
        field("caption", caption)
    body.extend(
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\n"
        "Content-Type: text/csv; charset=utf-8\r\n\r\n".encode("utf-8")
    )
    body.extend(content.encode("utf-8-sig"))
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    _request_json(
        "sendDocument",
        bytes(body),
        f"multipart/form-data; boundary={boundary}",
    )


def send_csv(content: str, filename: str, caption: str = "") -> Tuple[int, List[str]]:
    if not content.strip():
        return 0, ["CSV is empty"]
    destinations = _destinations()
    if not destinations:
        return 0, ["No Telegram destination configured"]

    sent = 0
    errors: List[str] = []
    for chat_id in destinations:
        try:
            _retry(
                lambda cid=chat_id: _multipart_document(cid, content, filename, caption),
                f"sendDocument destination={chat_id} filename={filename}",
            )
            sent += 1
            time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"CSV destination={chat_id}: {exc}")
    return sent, errors


if __name__ == "__main__":
    telegram_preflight()
    print("Configured Telegram destinations:", _destinations())
