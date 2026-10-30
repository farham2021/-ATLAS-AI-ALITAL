import unittest
from data_quality import validate_closed_candles,continuous_forward_window
W=3600000
def bar(t,o=100,h=105,l=95,c=101,v=10):return [t,o,h,l,c,v]
class DataQualityTests(unittest.TestCase):
    def test_open_excluded(self):
        a,r=validate_closed_candles([bar(W)],"1h",W*2-1)
        self.assertEqual(a,[])
        self.assertEqual(r["open"],1)
    def test_closed_accepted(self):
        a,r=validate_closed_candles([bar(W)],"1h",W*2)
        self.assertEqual(len(a),1)
    def test_invalid_ohlc_rejected(self):
        a,r=validate_closed_candles([bar(W,h=90)],"1h",W*3)
        self.assertEqual(r["malformed"],1)
    def test_contiguous_window(self):
        a=[bar(W),bar(2*W),bar(3*W)]
        self.assertEqual(len(continuous_forward_window(a,W,2,"1h")),2)
    def test_gap_immature(self):
        self.assertIsNone(continuous_forward_window([bar(W),bar(3*W)],W,2,"1h"))
if __name__=="__main__":unittest.main()
