import csv,io,unittest
from atlas_risk_csv_digest import csv_bytes,chart_url,FIELDS
class TestDigest(unittest.TestCase):
 def test_chart(self):
  self.assertIn("COINBASE%3ABTCUSD",chart_url("BTCUSDT"))
  with self.assertRaises(ValueError):chart_url("BTC/USDT")
 def test_csv(self):
  data=csv_bytes([("BTCUSDT",{"level":"HIGH","price":75000,"decline24":-3,"volume_ratio":2,"flags":["support break"]}),("ETHUSDT",{"level":"NONE","price":2,"decline24":0,"volume_ratio":1,"flags":[]})])
  rows=list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
  self.assertEqual(len(rows),1)
  self.assertEqual(list(rows[0]),list(FIELDS))
  self.assertEqual(rows[0]["direction"],"DROP")
  self.assertTrue(rows[0]["tradingview_url"].startswith("https://"))
 def test_csv_injection(self):
  data=csv_bytes([("BTCUSDT",{"level":"HIGH","price":1,"decline24":0,"volume_ratio":1,"flags":["=HYPERLINK(1)"]})])
  self.assertIn("'=HYPERLINK",data.decode("utf-8-sig"))
if __name__=="__main__":unittest.main()
