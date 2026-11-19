"""Send harmless private/group Telegram diagnostics and verify their DB receipts."""
import json
import os
import sys
import urllib.parse
import urllib.request

from atlas_telegram_receipts import build_telegram_receipt, fetch_telegram_receipt, persist_telegram_receipt


def telegram_call(token, method, payload):
    url = f"https://api.telegram.org/bot{token}/{method}"
    request = urllib.request.Request(url, data=urllib.parse.urlencode(payload).encode("utf-8"))
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    private_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    group_chat = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "").strip()
    run_id = os.environ.get("GITHUB_RUN_ID", "manual").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not token or not private_chat or not group_chat or private_chat == group_chat or not service_key:
        raise SystemExit("Missing or invalid Telegram/Supabase diagnostic credentials")

    identity = telegram_call(token, "getMe", {})
    if identity.get("ok") is not True:
        raise SystemExit("Telegram bot authentication failed")

    for destination, chat_id in (("private", private_chat), ("group", group_chat)):
        message = f"ATLAS delivery diagnostic ({destination}) — no market signal or trade instruction. Run {run_id}."
        sent = telegram_call(token, "sendMessage", {"chat_id": chat_id, "text": message})
        if sent.get("ok") is not True:
            raise SystemExit(f"Telegram send failed for {destination}")
        receipt = build_telegram_receipt(
            chat_id, sent, "sendMessage", workflow_run_id=run_id,
            cycle="TELEGRAM_DIAGNOSTIC", run_key=f"telegram-diagnostic:{run_id}",
            private_chat_id=private_chat, group_chat_id=group_chat,
        )
        if not receipt:
            raise SystemExit(f"Telegram response lacked a message ID for {destination}")
        persist_telegram_receipt(receipt)
        saved = fetch_telegram_receipt(receipt["receipt_id"])
        if not saved or int(saved.get("message_id") or 0) != receipt["message_id"]:
            raise SystemExit(f"Receipt readback did not match for {destination}")
        print(f"Telegram {destination}: delivered; receipt read-back verified; message_id={receipt['message_id']}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Telegram diagnostic failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
