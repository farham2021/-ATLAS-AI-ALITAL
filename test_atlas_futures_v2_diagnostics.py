import unittest
import atlas_futures_v2 as m

class DiagnosticsTest(unittest.TestCase):
 def bars(self,n=240,step=m.MS):
  return [(i*step,100.0,101.0,99.0,100.0,1000.0) for i in range(n)]
 def test_insufficient(self):
  info,setup=m.diagnose("BTC","TEST",self.bars(200),240*m.MS)
  self.assertEqual(info["status"],"INSUFFICIENT_CANDLES")
  self.assertIsNone(setup)
 def test_non_contiguous(self):
  b=self.bars();b[-1]=(b[-1][0]+m.MS,*b[-1][1:])
  info,_=m.diagnose("BTC","TEST",b,241*m.MS)
  self.assertEqual(info["status"],"NON_CONTIGUOUS_CANDLES")
 def test_stale(self):
  info,_=m.diagnose("BTC","TEST",self.bars(),250*m.MS)
  self.assertEqual(info["status"],"STALE_DATA")
 def test_no_setup(self):
  info,_=m.diagnose("BTC","TEST",self.bars(),240*m.MS)
  self.assertEqual(info["status"],"NO_SETUP")
if __name__=="__main__":unittest.main()
