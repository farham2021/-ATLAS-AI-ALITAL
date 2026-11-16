"""Deterministic guards for the 18-month research evaluator."""
import datetime
import unittest
from atlas_futures_backtest_18m import add_months, walk_forward, metrics
UTC=datetime.timezone.utc

class ResearchWindowTests(unittest.TestCase):
 def test_month_end(self):
  self.assertEqual(add_months(datetime.datetime(2026,3,31,tzinfo=UTC),-1),datetime.datetime(2026,2,28,tzinfo=UTC))
 def test_three_complete_nonoverlapping_folds(self):
  start=datetime.datetime(2025,5,16,12,tzinfo=UTC)
  end=add_months(start,18)
  windows=walk_forward([],start,end)
  self.assertEqual(len(windows),3)
  self.assertEqual(windows[0]["test_start"],add_months(start,4).isoformat())
  self.assertEqual(windows[1]["test_start"],add_months(start,10).isoformat())
  self.assertEqual(windows[2]["test_end"],end.isoformat())
  self.assertEqual(windows[0]["test_end"],add_months(start,6).isoformat())
 def test_oos_boundary_not_training(self):
  start=datetime.datetime(2025,5,16,12,tzinfo=UTC)
  trades=[{"signal_at":add_months(start,4).isoformat(),"exit_at":add_months(start,4).isoformat(),"net_r":1},
          {"signal_at":add_months(start,6).isoformat(),"exit_at":add_months(start,6).isoformat(),"net_r":1}]
  windows=walk_forward(trades,start,add_months(start,18))
  self.assertEqual(windows[0]["metrics"]["trades"],1)
  self.assertEqual(windows[1]["metrics"]["trades"],0)
 def test_empty_metrics(self):
  self.assertEqual(metrics([])["verdict"],"INSUFFICIENT")

if __name__=="__main__":unittest.main()
