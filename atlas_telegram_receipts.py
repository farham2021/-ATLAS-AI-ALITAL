"""Privacy-preserving Telegram delivery receipt persistence for ATLAS."""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TABLE = (os.environ.get("ATLAS_TELEGRAM_RECEIPTS_TABLE") or "atlas_telegram_delivery_receipts").strip()
METHODS = {"sendMessage", "sendPhoto", "sendDocument", "sendAudio"}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_telegram_receipt(chat_id, response, method, workflow_run_id="", cycle="UNKNOWN",
                           run_key="", private_chat_id="", group_chat_id=""):
    """Return metadata for a successful Telegram response; never retain the raw chat ID."""
    if method not in METHODS or not isinstance(response, dict) or response.get("ok") is not True:
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    try:
        message_id = int(result.get("message_id") or 0)
    except (TypeError, ValueError):
        return None
    if message_id <= 0:
        return None
    response_chat = result.get("chat", {}).get("id") if isinstance(result.get("chat"), dict) else None
    raw_chat_id = str(response_chat if response_chat is not None else chat_id or "").strip()
    if not raw_chat_id:
        return None
    private_id, group_id = str(private_chat_id or "").strip(), str(group_chat_id or "").strip()
    destination_kind = "group" if group_id and raw_chat_id == group_id else (
        "private" if private_id and raw_chat_id == private_id else "other"
    )
    run_id = str(workflow_run_id or "local").strip()
    cycle_value = str(cycle or "UNKNOWN").strip().upper()
    key_value = str(run_key or "").strip() or None
    receipt_id = _sha256("\0".join((run_id, cycle_value, method, raw_chat_id, str(message_id))))
    timestamp = result.get("date")
    telegram_date = None
    if timestamp is not None:
        try:
            telegram_date = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    return {
        "receipt_id": receipt_id,
        "workflow_run_id": run_id,
        "run_key": key_value,
        "cycle": cycle_value,
        "destination_kind": destination_kind,
        "destination_hash": _sha256(raw_chat_id),
        "method": method,
        "message_id": message_id,
        "telegram_date": telegram_date,
    }


def _request(method, path, payload=None):
    base_url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    service_key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not base_url or not service_key:
        raise RuntimeError("Supabase service credentials are missing")
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}",
               "Content-Type": "application/json"}
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Supabase receipt HTTP {exc.code}") from None


def persist_telegram_receipt(receipt):
    """Insert idempotently; safe to retry after an ambiguous network failure."""
    if not isinstance(receipt, dict) or not receipt.get("receipt_id"):
        raise ValueError("A complete receipt is required")
    path = f"/rest/v1/{TABLE}?on_conflict=receipt_id"
    _request("POST", path, receipt)
    return receipt["receipt_id"]


def fetch_telegram_receipt(receipt_id):
    """Read back one receipt using the service-role key."""
    q = urllib.parse.quote(str(receipt_id), safe="")
    path = (f"/rest/v1/{TABLE}?receipt_id=eq.{q}"
            "&select=receipt_id,workflow_run_id,run_key,cycle,destination_kind,destination_hash,method,message_id,telegram_date,recorded_at"
            "&limit=1")
    _, rows = _request("GET", path)
    return rows[0] if isinstance(rows, list) and rows else None
