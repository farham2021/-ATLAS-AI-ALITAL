import datetime as dt
import unittest
from unittest.mock import patch
from atlas_forecast_engine import forecast
UTC=dt.timezone.utc
class ForecastTests(unittest.TestCase):
 def test_no_data(self):
  self.assertEqual(forecast([])["status"],"UNAVAILABLE")
 def test_short_history(self):
  today=dt.datetime.now(UTC).replace(hour=12,minute=0,second=0,microsecond=0)
  series=[(today-dt.timedelta(days=i),100+i*.1) for i in range(20)]
  self.assertEqual(forecast(series)["status"],"UNAVAILABLE")
 def test_stale(self):
  today=dt.datetime.now(UTC)-dt.timedelta(days=10)
  series=[(today-dt.timedelta(days=i),100+i*.1) for i in range(150)]
  self.assertEqual(forecast(series)["reason"],"stale_or_future_data")
 def test_healthy_history(self):
  today=dt.datetime.now(UTC).replace(hour=12,minute=0,second=0,microsecond=0)
  series=[(today-dt.timedelta(days=i),100+(.03*(150-i))) for i in range(150)]
  result=forecast(series,90)
  self.assertEqual(result["status"],"RESEARCH_ONLY")
  self.assertGreaterEqual(result["walk_forward_folds"],3)
  self.assertIn(result["model"],("random_walk","shrinkage_momentum"))
 def test_unsupported_horizon(self):
  today=dt.datetime.now(UTC)
  self.assertEqual(forecast([(today,100)],17)["reason"],"unsupported_horizon")
if __name__=="__main__":unittest.main()
