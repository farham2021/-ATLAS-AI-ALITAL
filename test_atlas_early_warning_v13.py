import unittest
from datetime import datetime, timezone, timedelta
from atlas_early_warning_v13 import assess, scan

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
def row(**updates):
    data = dict(symbol="BTC", timestamp=NOW.isoformat(), price=105,
                prev_close=100, volume_ratio=1.8,
                open_interest_change_pct=3, funding_rate=0.001,
                breakout_level=104, breakdown_level=96)
    data.update(updates)
    return data

class EarlyWarningTests(unittest.TestCase):
    def test_bullish_watch_is_not_executable(self):
        out=assess(row(),now=NOW)
        self.assertEqual(out["state"],"EARLY_BULLISH_WATCH")
        self.assertFalse(out["executable"])
        self.assertNotIn("entry",out)
    def test_risk_off_watch(self):
        out=assess(row(price=95,funding_rate=-0.001),now=NOW)
        self.assertEqual(out["state"],"EARLY_RISK_OFF_WATCH")
    def test_stale_data_fails_closed(self):
        out=assess(row(timestamp=(NOW-timedelta(hours=1)).isoformat()),now=NOW)
        self.assertEqual(out["state"],"DATA_UNAVAILABLE")
    def test_missing_oi_fails_closed(self):
        self.assertEqual(assess(row(open_interest_change_pct=None),now=NOW)["state"],"DATA_UNAVAILABLE")
    def test_weak_volume_has_no_alert(self):
        self.assertEqual(assess(row(volume_ratio=1.1),now=NOW)["state"],"NO_ALERT")
    def test_no_mutation_or_delivery(self):
        original=row()
        self.assertEqual(len(scan([original],now=NOW)),1)
        self.assertEqual(original["price"],105)

if __name__=="__main__":
    unittest.main()
