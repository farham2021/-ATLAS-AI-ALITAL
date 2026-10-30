import unittest
from datetime import datetime, timezone
from atlas_futures_png import select_five

class FuturesBoardTests(unittest.TestCase):
    def test_wait_never_has_levels(self):
        x=select_five([dict(coin="BTC",action="WAIT",executable=False,entry=100,sl=95,tp1=110,tp2=120)])[0]
        self.assertEqual(x["side"],"WAIT")
        self.assertIsNone(x["entry"])
    def test_valid_long(self):
        x=select_five([dict(coin="ETH",action="BUY",executable=True,entry=100,sl=95,tp1=110,tp2=120,confidence=80,futures_venue_verified=True,futures_liquidity_verified=True,futures_funding_verified=True,futures_timestamp=datetime.now(timezone.utc).isoformat(),futures_bid=99.99,futures_ask=100.01,futures_24h_notional_usd=10000000,futures_open_interest_usd=1000000,futures_funding_rate=0.0001,futures_exchange="verified_test_venue",futures_contract_active=True)])[0]
        self.assertEqual(x["side"],"LONG")
        self.assertEqual(x["rr"],2)
        self.assertLessEqual(x["risk_usd"],20)
        self.assertLessEqual(x["notional_usd"],6000)
    def test_invalid_short(self):
        x=select_five([dict(coin="SOL",action="SELL",executable=True,entry=100,sl=105,tp1=110,tp2=90)])[0]
        self.assertEqual(x["side"],"WAIT")
    def test_missing_futures_evidence_blocks_trade(self):
        x=select_five([dict(coin="BTC",action="BUY",executable=True,entry=100,sl=95,tp1=110,tp2=120)])[0]
        self.assertEqual(x["side"],"WAIT")
        self.assertIsNone(x["tp1"])
    def test_png_renderer(self):
        import os, tempfile
        from atlas_futures_png import render_png
        with tempfile.TemporaryDirectory() as folder:
            fn=os.path.join(folder,"preview.png")
            render_png(select_five([dict(coin="BTC",action="WAIT")]),fn)
            with open(fn,"rb") as fh: self.assertEqual(fh.read(8),bytes.fromhex("89504e470d0a1a0a"))
    def test_five_max(self):
        rows=[dict(coin=f"COIN{i}",action="WAIT",confidence=i) for i in range(9)]
        self.assertEqual(len(select_five(rows)),5)
    def test_metals_excluded(self):
        self.assertEqual(select_five([dict(coin="XAG",action="BUY",executable=True)]),[])

if __name__=="__main__": unittest.main()
