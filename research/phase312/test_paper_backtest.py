import unittest
from paper_backtest import backtest

class PaperBacktestTests(unittest.TestCase):
    def test_short_history_has_no_trades(self):
        rows=[[i*14400000,100,101,99,100,10] for i in range(50)]
        result=backtest(rows)
        self.assertEqual(result["signals"],0)
        self.assertIsNone(result["resolved_expectancy_r"])
    def test_flat_market_no_false_breakouts(self):
        rows=[[i*14400000,100,101,99,100,10] for i in range(100)]
        self.assertEqual(backtest(rows)["signals"],0)
    def test_cost_parameters_do_not_create_signals(self):
        rows=[[i*14400000,100,101,99,100,10] for i in range(100)]
        self.assertEqual(backtest(rows,fee_bps=10,slippage_bps=10)["signals"],0)

if __name__=="__main__":unittest.main()
