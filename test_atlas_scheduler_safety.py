import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from atlas_schedule_guard import choose_plan, classify_row

PARIS = ZoneInfo("Europe/Paris")

class SchedulerSafetyTests(unittest.TestCase):
    def test_expired_lease_can_be_reclaimed(self):
        now = datetime(2026,11,13,tzinfo=timezone.utc)
        row = {"status":"RUNNING","lease_until":(now-timedelta(minutes=1)).isoformat()}
        self.assertEqual(classify_row(row,now),"EXPIRED")

    def test_active_lease_remains_locked(self):
        now = datetime(2026,11,13,tzinfo=timezone.utc)
        row = {"status":"RUNNING","lease_until":(now+timedelta(minutes=1)).isoformat()}
        self.assertEqual(classify_row(row,now),"RUNNING")

    def test_done_is_idempotent(self):
        self.assertEqual(classify_row({"status":"DONE"}),"DONE")

    def test_report_window_and_duplicate_guard(self):
        dt = datetime(2026,11,13,14,52,tzinfo=PARIS)
        self.assertEqual(choose_plan(dt,lambda key: False)["mode"],"DAILY16")
        self.assertEqual(choose_plan(dt,lambda key: True)["mode"],"NONE")

    def test_hourly_outside_report(self):
        dt = datetime(2026,11,13,21,47,tzinfo=PARIS)
        self.assertEqual(choose_plan(dt,lambda key: False,hourly_wake=True)["mode"],"HOURLY")

    def test_dst_transition(self):
        for date in ((2026,3,29),(2026,10,25)):
            dt=datetime(*date,14,52,tzinfo=PARIS)
            self.assertEqual(choose_plan(dt,lambda key: False)["mode"],"DAILY16")

if __name__ == "__main__":
    unittest.main()
