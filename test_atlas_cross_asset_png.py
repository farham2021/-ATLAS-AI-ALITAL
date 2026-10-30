import os
import tempfile
import unittest
from atlas_cross_asset_png import summarize, render_png

class CrossAssetTests(unittest.TestCase):
    def test_no_data_no_buy(self):
        data=summarize([])
        self.assertTrue(all(not items for items in data.values()))
    def test_unverified_buy_is_wait(self):
        data=summarize([dict(symbol="XAG",action="BUY")])
        self.assertEqual(data["METALS"][0]["action"],"WAIT")
    def test_verified_market(self):
        data=summarize([dict(symbol="USD",decision="HOLD",market_data_verified=True,signal_verified=True)])
        self.assertEqual(data["USD / USDT IRAN"][0]["action"],"HOLD")
    def test_render_png(self):
        with tempfile.TemporaryDirectory() as folder:
            name=os.path.join(folder,"board.png")
            render_png(summarize([]),name)
            with open(name,"rb") as f:
                self.assertEqual(f.read(8),bytes.fromhex("89504e470d0a1a0a"))

if __name__=="__main__":
    unittest.main()
