import unittest
from atlas_paper_execution_v2 import PaperOrder,simulate_closed_candle

class PaperExecutionTests(unittest.TestCase):
 def test_same_candle_stop_first(self):
  x=PaperOrder("LONG",100,95,110,1)
  y=simulate_closed_candle(x,high=111,low=94)
  self.assertEqual(y["status"],"STOP")
  self.assertLess(y["net_pnl"],-5)
 def test_short_target_and_funding(self):
  x=PaperOrder("SHORT",100,105,90,1)
  y=simulate_closed_candle(x,high=101,low=89,signed_funding_rate=0.001)
  self.assertEqual(y["status"],"TARGET")
  self.assertLess(y["funding_cost"],0)
 def test_risk_limit(self):
  with self.assertRaises(ValueError):
   PaperOrder("LONG",100,90,120,20,equity=1000).validate()
 def test_leverage(self):
  with self.assertRaises(ValueError):
   PaperOrder("LONG",100,90,120,1,leverage=20).validate()
 def test_unclosed(self):
  x=PaperOrder("LONG",100,95,110,1)
  self.assertEqual(simulate_closed_candle(x,101,99)["status"],"OPEN")
if __name__=="__main__":unittest.main()
