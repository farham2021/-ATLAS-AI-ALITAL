import datetime as dt
import unittest
from unittest.mock import patch

import atlas_watchdog


UTC = dt.timezone.utc


class EarlyRiskWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 30, 20, tzinfo=UTC)

    def check_rows(self, rows):
        with patch.object(atlas_watchdog, "get", return_value=rows):
            return atlas_watchdog.check(self.now)

    def test_failed_cycle_warns_until_a_later_success(self):
        failed = self.check_rows([{
            "cycle": "EARLY_RISK", "status": "ERROR",
            "completed_at": (self.now - dt.timedelta(minutes=20)).isoformat(),
        }])
        self.assertTrue(any(x.startswith("EARLY_RISK: latest scanner cycle failed") for x in failed["warnings"]))
        recovered = self.check_rows([
            {"cycle": "EARLY_RISK", "status": "DONE", "completed_at": (self.now - dt.timedelta(minutes=10)).isoformat()},
            {"cycle": "EARLY_RISK", "status": "ERROR", "completed_at": (self.now - dt.timedelta(minutes=20)).isoformat()},
        ])
        self.assertFalse(any(x.startswith("EARLY_RISK: latest scanner cycle failed") for x in recovered["warnings"]))

    def test_active_lease_suppresses_stale_heartbeat_warning(self):
        rows = [{
            "cycle": "EARLY_RISK", "status": "RUNNING", "completed_at": None,
            "lease_until": (self.now + dt.timedelta(minutes=20)).isoformat(),
        }]
        result = self.check_rows(rows)
        self.assertFalse(any(x.startswith("EARLY_RISK: last successful") for x in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
