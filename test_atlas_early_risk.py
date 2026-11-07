import unittest
from atlas_early_risk import ema,score,score_growth
class RiskGuardTests(unittest.TestCase):
 def test_ema_not_sma(self):
  prices=[100.0]*50+[200.0]
  self.assertGreater(ema(prices,20),sum(prices[-20:])/20)
 def test_support_break_triggers_early_watch(self):
  rows4=[]
  for i in range(60):
   p=100.0 if i<59 else 97.0
   rows4.append([i*14400000,p,p+1,p-1,p,100.0,i*14400000+14400000])
  rowsd=[[i*86400000,100,101,99,100,100,i*86400000+86400000] for i in range(60)]
  r=score(rows4,rowsd)
  self.assertIn(r["level"],("WATCH","HIGH","CRITICAL"))
  self.assertIn("4H support break",r["flags"])
 def test_growth_breakout_alert(self):
  rows4=[]
  for i in range(60):
   p=100+i*.1 if i<59 else 115
   rows4.append([i*14400000,p,p+.5,p-.5,p,1000 if i==59 else 100,i*14400000+14400000])
  rowsd=[[i*86400000,100+i*.1,101+i*.1,99+i*.1,100+i*.1,100,i*86400000+86400000] for i in range(60)]
  self.assertEqual(score_growth(rows4,rowsd)["level"],"GROWTH_HIGH")
 def test_healthy_market_none(self):
  rows4=[[i*14400000,100,101,99,100,100,i*14400000+14400000] for i in range(60)]
  rowsd=[[i*86400000,100,101,99,100,100,i*86400000+86400000] for i in range(60)]
  self.assertEqual(score(rows4,rowsd)["level"],"NONE")
if __name__=="__main__":unittest.main()
