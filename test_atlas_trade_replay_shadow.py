import unittest
from atlas_trade_replay_shadow import Bar, replay

BARS=[Bar(100,102,99,101),Bar(101,103,100,102),Bar(102,104,101,103),Bar(103,105,102,104)]

class ReplayTests(unittest.TestCase):
    def test_deterministic(self):
        a=replay(BARS,entry=100,stop=95,target=105,runs=50)
        self.assertEqual(a,replay(BARS,entry=100,stop=95,target=105,runs=50))
        self.assertEqual(sum(a["outcomes"].values()),50)
    def test_conservative_stop_first(self):
        bars=[Bar(100,100,100,100),Bar(100,120,80,100)]
        a=replay(bars,entry=100,stop=95,target=105,runs=20,horizon=1)
        self.assertEqual(a["outcomes"]["stop"],20)
    def test_short(self):
        a=replay(BARS,entry=100,stop=105,target=95,side="short",runs=10)
        self.assertTrue(a["shadow_only"])
    def test_invalid_bar(self):
        with self.assertRaises(ValueError):
            replay([Bar(100,99,101,100),BARS[1]],entry=100,stop=95,target=105)
    def test_wrong_side(self):
        with self.assertRaises(ValueError):
            replay(BARS,entry=100,stop=105,target=95)
    def test_not_calibrated(self):
        self.assertTrue(replay(BARS,entry=100,stop=95,target=105,runs=2)["not_calibrated_probability"])

if __name__=="__main__": unittest.main()
