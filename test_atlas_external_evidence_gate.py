import unittest
from datetime import datetime, timezone
from atlas_external_evidence_gate import ExternalEvidence, validate_evidence

NOW=datetime(2026,11,8,tzinfo=timezone.utc)
def sample(**kwargs):
    x=dict(provider="monk_trade",market="us_equity",symbol="AAPL",
           asof_utc="2026-11-07T20:00:00Z",reference_id="monkql-run-1",
           status="complete")
    x.update(kwargs)
    return ExternalEvidence(**x)

class ExternalEvidenceTests(unittest.TestCase):
    def test_valid_research_never_authorizes_trade(self):
        r=validate_evidence(sample(action="BUY",confidence=90),now_utc=NOW)
        self.assertTrue(r["accepted"])
        self.assertEqual(r["action"],"WAIT")
    def test_wrong_market_rejected(self):
        with self.assertRaises(ValueError):
            validate_evidence(sample(market="crypto"),now_utc=NOW)
    def test_stale_rejected(self):
        r=validate_evidence(sample(asof_utc="2026-10-01T00:00:00Z"),now_utc=NOW)
        self.assertFalse(r["accepted"])
    def test_incomplete_rejected(self):
        self.assertEqual(validate_evidence(sample(status="partial"),now_utc=NOW)["reason"],"INCOMPLETE_SOURCE")
    def test_live_denied(self):
        self.assertEqual(validate_evidence(sample(research_only=False),now_utc=NOW)["reason"],"LIVE_PERMISSION_DENIED")
    def test_future_rejected(self):
        self.assertFalse(validate_evidence(sample(asof_utc="2026-11-09T00:00:00Z"),now_utc=NOW)["accepted"])
    def test_invalid_confidence(self):
        with self.assertRaises(ValueError):
            validate_evidence(sample(confidence=120),now_utc=NOW)

if __name__=="__main__": unittest.main()
