import json
import os
import unittest
from unittest import mock

import atlas_telegram_receipts as receipts


class FakeResponse:
    def __init__(self, payload, status=201):
        self.payload, self.status = payload, status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TelegramReceiptTests(unittest.TestCase):
    def response(self, chat_id=12345, message_id=77):
        return {"ok": True, "result": {"message_id": message_id, "date": 1795075200,
                "chat": {"id": chat_id, "type": "private"}}}

    def test_receipt_redacts_chat_id_and_is_deterministic(self):
        args = dict(chat_id="12345", response=self.response(), method="sendMessage",
                    workflow_run_id="9001", cycle="DEEP4H",
                    run_key="DEEP4H:2026-11-19:1205TEHRAN",
                    private_chat_id="12345", group_chat_id="-100999")
        first, second = receipts.build_telegram_receipt(**args), receipts.build_telegram_receipt(**args)
        self.assertEqual(first, second)
        self.assertEqual(first["destination_kind"], "private")
        self.assertNotIn("12345", json.dumps(first))
        self.assertEqual(first["message_id"], 77)
        self.assertEqual(len(first["destination_hash"]), 64)

    def test_group_destination_is_classified(self):
        receipt = receipts.build_telegram_receipt("-100999", self.response(-100999, 78), "sendPhoto",
                                                   private_chat_id="12345", group_chat_id="-100999")
        self.assertEqual(receipt["destination_kind"], "group")
        self.assertEqual(receipt["method"], "sendPhoto")

    def test_failed_or_incomplete_responses_have_no_receipt(self):
        self.assertIsNone(receipts.build_telegram_receipt("12345", {"ok": False}, "sendMessage"))
        self.assertIsNone(receipts.build_telegram_receipt("12345", {"ok": True, "result": {}}, "sendMessage"))
        self.assertIsNone(receipts.build_telegram_receipt("12345", self.response(), "sendVoice"))

    def test_service_role_insert_and_readback(self):
        receipt = receipts.build_telegram_receipt("12345", self.response(), "sendMessage",
                                                   workflow_run_id="9002", cycle="TELEGRAM_DIAGNOSTIC")
        readback = [{**receipt, "recorded_at": "2026-11-19T00:00:00+00:00"}]
        seen = []

        def fake_urlopen(request, timeout):
            seen.append(request)
            if request.method == "POST":
                self.assertEqual(json.loads(request.data.decode()), receipt)
                self.assertIn("on_conflict=receipt_id", request.full_url)
                return FakeResponse(None, 201)
            return FakeResponse(readback, 200)

        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://example.supabase.co",
                                          "SUPABASE_SERVICE_ROLE_KEY": "service-secret-test-only"}):
            with mock.patch.object(receipts.urllib.request, "urlopen", side_effect=fake_urlopen):
                self.assertEqual(receipts.persist_telegram_receipt(receipt), receipt["receipt_id"])
                saved = receipts.fetch_telegram_receipt(receipt["receipt_id"])
        self.assertEqual(saved["message_id"], receipt["message_id"])
        self.assertEqual(len(seen), 2)
        for request in seen:
            self.assertEqual(request.headers["Apikey"], "service-secret-test-only")
            self.assertEqual(request.headers["Authorization"], "Bearer service-secret-test-only")


if __name__ == "__main__":
    unittest.main()
