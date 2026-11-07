import unittest
from atlas_portfolio_risk_shield import Observation,evaluate,transitions,classify

def o(i,nav,flow=0):return Observation(f"2026-11-{i+1:02d}",nav,flow)
class ShadowRiskShieldTests(unittest.TestCase):
 def test_exact_thresholds(self):
  for d,expected in ((.0499,"NONE"),(.05,"WATCH"),(.0799,"WATCH"),(.08,"HIGH"),(.1199,"HIGH"),(.12,"CRITICAL")):
   self.assertEqual(classify(d),expected)
 def test_escalations(self):
  r=evaluate([o(0,100),o(1,95),o(2,92),o(3,88)])
  self.assertEqual([x["level"] for x in transitions(r)],["WATCH","HIGH","CRITICAL"])
 def test_contribution_not_gain(self):
  r=evaluate([o(0,100),o(1,200,100),o(2,190)])
  self.assertEqual(r[1]["drawdown_pct"],0)
  self.assertEqual(r[2]["level"],"WATCH")
 def test_withdrawal_not_loss(self):
  r=evaluate([o(0,100),o(1,50,-50)])
  self.assertEqual(r[-1]["level"],"NONE")
 def test_peak_reset(self):
  r=evaluate([o(0,100),o(1,90),o(2,120),o(3,114)])
  self.assertEqual(r[-1]["level"],"WATCH")
 def test_invalid_series(self):
  with self.assertRaises(ValueError):evaluate([o(0,100),o(0,95)])
  with self.assertRaises(ValueError):evaluate([o(0,100),o(1,0,-100)])
 def test_no_repeat(self):
  r=evaluate([o(0,100),o(1,94),o(2,93),o(3,91)])
  self.assertEqual(len(transitions(r)),2)
if __name__=="__main__":unittest.main()
