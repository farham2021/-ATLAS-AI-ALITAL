import unittest
from atlas_kronos_adapter_shadow import Candle,prepare_ohlcv,model_readiness

def bars(n=40):
    return [Candle(i*300000,100,102,99,101,10) for i in range(n)]

class KronosAdapterTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(len(prepare_ohlcv(bars())),40)
    def test_no_model_no_signal(self):
        r=model_readiness(bars())
        self.assertEqual(r["status"],"MODEL_NOT_LOADED")
        self.assertFalse(r["live_signal_allowed"])
    def test_gap_rejected(self):
        b=bars()
        b[20]=Candle(20*300000+10000000,100,102,99,101,10)
        with self.assertRaises(ValueError):prepare_ohlcv(b)
    def test_bad_volume(self):
        b=bars()
        b[0]=Candle(0,100,102,99,101,-1)
        with self.assertRaises(ValueError):prepare_ohlcv(b)
    def test_insufficient(self):
        with self.assertRaises(ValueError):prepare_ohlcv(bars(10))

if __name__=="__main__":unittest.main()
