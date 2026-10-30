import unittest
from datetime import datetime,timedelta,timezone
from atlas_futures_evidence import verify
class EvidenceTests(unittest.TestCase):
    def sample(self):
        return dict(futures_timestamp=datetime.now(timezone.utc).isoformat(),futures_bid=99.99,futures_ask=100.01,
            futures_24h_notional_usd=10000000,futures_open_interest_usd=1000000,futures_funding_rate=.0001,
            futures_exchange="test_venue",futures_contract_active=True)
    def test_verified(self):
        self.assertTrue(verify(self.sample())[0])
    def test_stale(self):
        r=self.sample();r["futures_timestamp"]=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        self.assertEqual(verify(r)[1],"STALE_OR_FUTURE_DATA")
    def test_spread(self):
        r=self.sample();r["futures_ask"]=101
        self.assertEqual(verify(r)[1],"WIDE_SPREAD")
    def test_missing_funding(self):
        r=self.sample();r.pop("futures_funding_rate")
        self.assertEqual(verify(r)[1],"FUNDING_UNVERIFIED_OR_EXTREME")
if __name__=="__main__":unittest.main()
