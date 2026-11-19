import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from atlas_schedule_guard import choose_plan, classify_row

TEHRAN = ZoneInfo("Asia/Tehran")


class SchedulerSafetyTests(unittest.TestCase):
    def test_expired_lease_can_be_reclaimed(self):
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        row = {"status": "RUNNING", "lease_until": (now - timedelta(minutes=1)).isoformat()}
        self.assertEqual(classify_row(row, now), "EXPIRED")

    def test_active_lease_remains_locked(self):
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        row = {"status": "RUNNING", "lease_until": (now + timedelta(minutes=1)).isoformat()}
        self.assertEqual(classify_row(row, now), "RUNNING")

    def test_done_is_idempotent(self):
        self.assertEqual(classify_row({"status": "DONE"}), "DONE")

    def test_tehran_report_windows_and_keys(self):
        cases = [
            (datetime(2026, 11, 19, 12, 7, tzinfo=TEHRAN), "DEEP4H", "1205TEHRAN"),
            (datetime(2026, 11, 19, 16, 7, tzinfo=TEHRAN), "DAILY16", "1605TEHRAN"),
            (datetime(2026, 11, 19, 23, 7, tzinfo=TEHRAN), "NIGHTLY23", "2305TEHRAN"),
        ]
        for dt, expected_mode, key_suffix in cases:
            with self.subTest(expected_mode=expected_mode):
                plan = choose_plan(dt, lambda key: False)
                self.assertEqual(plan["mode"], expected_mode)
                self.assertTrue(plan["run_key"].endswith(key_suffix))
                self.assertIn("2026-11-19", plan["run_key"])

    def test_report_window_and_duplicate_guard(self):
        dt = datetime(2026, 11, 19, 16, 7, tzinfo=TEHRAN)
        self.assertEqual(choose_plan(dt, lambda key: False)["mode"], "DAILY16")
        self.assertEqual(choose_plan(dt, lambda key: True)["mode"], "NONE")

    def test_hourly_outside_report(self):
        dt = datetime(2026, 11, 19, 21, 47, tzinfo=TEHRAN)
        self.assertEqual(choose_plan(dt, lambda key: False, hourly_wake=True)["mode"], "HOURLY")

    def test_recovery_window_ends_before_next_slot(self):
        dt = datetime(2026, 11, 19, 15, 5, tzinfo=TEHRAN)
        self.assertEqual(choose_plan(dt, lambda key: False, hourly_wake=True)["mode"], "HOURLY")

    def test_tehran_slots_are_stable_across_old_europe_dst_dates(self):
        for date in ((2026, 3, 29), (2026, 10, 25)):
            dt = datetime(*date, 12, 7, tzinfo=TEHRAN)
            self.assertEqual(choose_plan(dt, lambda key: False)["mode"], "DEEP4H")


if __name__ == "__main__":
    unittest.main()
