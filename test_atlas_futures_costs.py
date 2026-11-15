import unittest
from datetime import datetime,timezone,timedelta
from atlas_futures_costs import evaluate_trade_net_r,ExecutionCostModel
T=datetime(2026,1,1,tzinfo=timezone.utc)
class NetRTests(unittest.TestCase):
 def test_long_stop_cost(self):
  r=evaluate_trade_net_r("LONG",65000,63700,63700,T,T+timedelta(hours=16))
  self.assertEqual(r["gross_r"],-1)
  self.assertEqual(r["funding_intervals"],2)
  self.assertAlmostEqual(r["net_r"],-1.0892,places=3)
 def test_short_profit(self):
  r=evaluate_trade_net_r("SHORT",100,105,90,T,T+timedelta(hours=4),True)
  self.assertEqual(r["gross_r"],2)
  self.assertGreater(r["net_r"],1.9)
 def test_tight_stop_increases_cost_r(self):
  a=evaluate_trade_net_r("LONG",100,99,99,T,T+timedelta(hours=1))
  b=evaluate_trade_net_r("LONG",100,98,98,T,T+timedelta(hours=1))
  self.assertGreater(a["cost_r"],b["cost_r"])
 def test_invalid(self):
  with self.assertRaises(ValueError):evaluate_trade_net_r("LONG",100,100,110,T,T)
 def test_funding_credit(self):
  r=evaluate_trade_net_r("SHORT",100,105,100,T,T+timedelta(hours=8),costs=ExecutionCostModel(funding_rate_8h=-0.0001))
  self.assertEqual(r["funding_intervals"],1)
if __name__=="__main__":unittest.main()
