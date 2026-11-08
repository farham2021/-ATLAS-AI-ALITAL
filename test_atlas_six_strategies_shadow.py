import unittest
from datetime import date,timedelta
from atlas_six_strategies_shadow import *

class TestSixStrategies(unittest.TestCase):
    def test_santa(self):
        dec=[date(2025,12,x) for x in (22,23,24,26,29,30,31)]
        jan=[date(2026,1,x) for x in (2,5,6)]
        self.assertEqual(santa("2025-12-26",dec,jan)["signal"],1)
        self.assertEqual(santa("2026-01-06",dec,jan)["signal"],0)
    def test_sue(self):
        prior=[dict(available_at=f"2025-0{i+1}-01",actual_eps=i%2,consensus_eps=0) for i in range(4)]
        r=dict(available_at="2025-07-01",actual_eps=2,consensus_eps=1)
        self.assertGreater(sue("2025-08-01",r,prior)["score"],0)
        with self.assertRaises(ValueError):sue("2025-06-01",r,prior)
    def test_low_vol(self):
        rows=[dict(available_at=(date(2025,1,1)+timedelta(days=i)).isoformat(),**{"return":.01 if i%2 else -.01}) for i in range(60)]
        self.assertGreater(low_vol("2025-04-01",rows)["score"],0)
        with self.assertRaises(ValueError):low_vol("2025-01-20",rows)
    def test_piotroski(self):
        p=dict(available_at="2024-03-01",roa=-.01,cfo=-.02,leverage=.5,current_ratio=1,shares=100,gross_margin=.2,asset_turnover=.7)
        c=dict(available_at="2025-03-01",roa=.1,cfo=.2,leverage=.4,current_ratio=1.2,shares=100,gross_margin=.3,asset_turnover=.8)
        self.assertEqual(piotroski("2025-04-01",c,p)["score"],9)
    def test_high_52w(self):
        rows=[dict(available_at=(date(2025,1,1)+timedelta(days=i)).isoformat(),adjusted_high=110,adjusted_close=100) for i in range(200)]
        self.assertAlmostEqual(high_52w("2025-08-01",rows)["score"],100/110)
    def test_magic(self):
        r=dict(available_at="2025-04-01",ebit=20,enterprise_value=100,net_working_capital=10,net_fixed_assets=40)
        self.assertAlmostEqual(magic_formula("2025-05-01",r)["return_on_capital"],.4)
        ranks=magic_rank([dict(symbol="A",earnings_yield=.2,return_on_capital=.4),dict(symbol="B",earnings_yield=.1,return_on_capital=.2)])
        self.assertEqual(ranks[0]["symbol"],"A")
    def test_fail_closed(self):
        with self.assertRaises(ValueError):magic_formula("2025-05-01",dict(available_at="2025-04-01",ebit=20,enterprise_value=0,net_working_capital=10,net_fixed_assets=40))
        with self.assertRaises(ValueError):magic_rank([dict(symbol="A",earnings_yield=.2,return_on_capital=.4)])
if __name__=="__main__": unittest.main()
