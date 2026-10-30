"""Run: python -m unittest discover -s research/phase312 -p 'test_*.py'"""
import unittest
from evidence_lab import evaluate_signal,evaluate_batch,summarize

S={"symbol":"BTC","signal_candle_ts":1000,"direction":"LONG","entry":100,
   "sl":95,"tp1":110,"model_version":"v12","regime":"RANGE"}

class EvidenceLabTests(unittest.TestCase):
    def label(self,bars,s=S):
        return evaluate_signal(s,bars,(1,))[0]["label"]
    def test_tp(self): self.assertEqual(self.label([[2000,100,111,99,108,10]]),"TP_FIRST")
    def test_sl(self): self.assertEqual(self.label([[2000,100,104,94,96,10]]),"SL_FIRST")
    def test_ambiguous(self): self.assertEqual(self.label([[2000,100,112,94,101,10]]),"AMBIGUOUS")
    def test_immature(self): self.assertEqual(self.label([]),"IMMATURE")
    def test_no_same_candle_leak(self):
        self.assertEqual(self.label([[1000,100,120,90,100,10],[2000,100,102,99,101,10]]),"TIMEOUT")
    def test_short(self):
        s={**S,"direction":"SHORT","sl":105,"tp1":90}
        self.assertEqual(self.label([[2000,100,101,89,91,10]],s),"TP_FIRST")
    def test_invalid_geometry(self):
        with self.assertRaises(ValueError): self.label([],{**S,"sl":105})
    def test_version_cohorts(self):
        rows=evaluate_batch([S,{**S,"model_version":"v11"}],
                            {"BTC":[[2000,100,111,99,108,10]]},(1,))
        self.assertEqual(len(summarize(rows)),2)

if __name__=="__main__": unittest.main()
