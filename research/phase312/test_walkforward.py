import unittest
from walkforward import replay,summary

W=14400000
def flat(n=130):
    return [[i*W,100,101,99,100,10] for i in range(n)]
class WalkForwardTests(unittest.TestCase):
    def test_no_false_trades(self):
        result=replay(flat())
        self.assertEqual(summary(result)["test"]["trades"],0)
    def test_reject_duplicate(self):
        bars=flat()
        bars[10][0]=bars[9][0]
        with self.assertRaises(ValueError):replay(bars)
    def test_reject_gap(self):
        bars=flat()
        bars[10][0]+=1
        with self.assertRaises(ValueError):replay(bars)
    def test_reject_invalid_ohlc(self):
        bars=flat()
        bars[20][2]=90
        with self.assertRaises(ValueError):replay(bars)
    def test_invalid_cost(self):
        with self.assertRaises(ValueError):replay(flat(),fee_bps=-1)
    def test_chronological_split(self):
        result=replay(flat(130))
        self.assertEqual(result["split_index"],91)
    def test_purge_boundary(self):
        # Any train trade must have completed strictly before the test begins.
        b=flat(130)
        result=replay(b)
        split_ts=b[result["split_index"]][0]
        self.assertTrue(all(x["exit_ts"]<split_ts for x in result["train"]))
if __name__=="__main__":unittest.main()
