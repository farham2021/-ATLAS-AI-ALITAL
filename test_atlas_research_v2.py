import unittest
from atlas_quant_risk_v2 import compute
from atlas_paper_execution_v2 import PaperOrder
from atlas_paper_replay_journal_v2 import replay,journal
class ResearchV2Tests(unittest.TestCase):
 def test_insufficient(self):self.assertEqual(compute([],[])["status"],"INSUFFICIENT_DATA")
 def test_six_factor(self):
  bars=[{"close":100+i*.1,"high":101+i*.1,"low":99+i*.1,"volume":100+i%10} for i in range(260)]
  x=compute(bars,bars)
  self.assertEqual(x["status"],"RESEARCH");self.assertEqual(len(x["components"]),6)
  self.assertAlmostEqual(sum(x["weights"].values()),1)
  self.assertTrue(0<=x["risk_score"]<=100)
  self.assertTrue(-100<=x["bias_score"]<=100)
 def test_stop_precedence(self):
  x=PaperOrder("LONG",100,95,110,1)
  y=replay(x,[{"high":102,"low":99},{"high":112,"low":94}])
  self.assertEqual(y["bar_index"],1);self.assertEqual(y["status"],"STOP")
 def test_journal(self):
  j=journal([{"net_pnl":10,"initial_risk":5},{"net_pnl":-5,"initial_risk":5}])
  self.assertEqual(j["trades"],2);self.assertEqual(j["profit_factor"],2)
  self.assertEqual(j["win_rate"],.5)
if __name__=="__main__":unittest.main()
