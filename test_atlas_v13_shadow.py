import unittest
from atlas_v13_shadow import early_warning,rank_opportunities,allocation_gap,score_outcomes,delivery_audit
class V13Tests(unittest.TestCase):
 def test_early_watch(self):
  self.assertEqual(early_warning(dict(symbol="BTC",market_data_verified=True,signal_verified=True,change_pct_24h=-4,volume_ratio=2,oi_change_pct_24h=3))["direction"],"RISK_OFF")
 def test_unverified(self):
  self.assertEqual(early_warning({"symbol":"BTC"})["state"],"DATA_UNAVAILABLE")
 def test_rank(self):
  r=dict(symbol="ETH",market_data_verified=True,signal_verified=True,decision="BUY",entry=100,sl=95,tp1=112,confidence=80)
  self.assertEqual(len(rank_opportunities([r])),1)
  self.assertEqual(len(rank_opportunities([{**r,"signal_verified":False}])),0)
 def test_allocation(self):
  self.assertEqual(allocation_gap({"gold":30},{"gold":.5,"cash":.5},100),{"gold":20.0,"cash":50.0})
 def test_outcomes(self):
  self.assertEqual(score_outcomes([dict(closed=True,gross_r=2,fee_r=.1,slippage_r=.1)])["expectancy_r"],1.8)
 def test_delivery(self):
  self.assertFalse(delivery_audit([("dm","iran")],[])["complete"])
  self.assertTrue(delivery_audit([("dm","iran")],[dict(destination="dm",report="iran",ok=True,message_id=42)])["complete"])
if __name__=="__main__": unittest.main()
