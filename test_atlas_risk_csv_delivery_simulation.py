"""Offline transport verification: no network or real Telegram messages."""
import csv,io,json,os,unittest
from unittest.mock import patch
import atlas_risk_csv_digest as digest
class FakeResponse:
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def read(self):return b'{"ok":true,"result":{"message_id":12345}}'
class TestTelegramSimulation(unittest.TestCase):
 def test_multipart_send_document_ack(self):
  captured=[]
  def fake_open(req,timeout):
   captured.append(req)
   return FakeResponse()
  with patch.object(digest.urllib.request,"urlopen",side_effect=fake_open):
   receipt=digest.send_document("TEST_TOKEN","-100TEST",b"symbol,chart\r\nBTC,https://www.tradingview.com\r\n","risk.csv","ATLAS test")
  self.assertEqual(receipt,12345)
  self.assertEqual(len(captured),1)
  self.assertIn("/sendDocument",captured[0].full_url)
  self.assertIn(b'filename="risk.csv"',captured[0].data)
  self.assertIn(b"https://www.tradingview.com",captured[0].data)
 def test_two_destinations_one_csv_each(self):
  captured=[]
  def fake_send(token,chat,data,filename,caption):
   captured.append((chat,data,filename,caption))
   return 42
  items=[("BTCUSDT",dict(level="HIGH",price=1,decline24=-2,volume_ratio=1.5,flags=["support break"]))]
  with patch.dict(os.environ,{"TELEGRAM_TOKEN":"TEST","TELEGRAM_GROUP_CHAT_ID":"GROUP","ATLAS_PRIVATE_CHAT_ID":"PRIVATE"}):
   with patch.object(digest,"send_document",side_effect=fake_send):
    receipts=digest.send_digest(items)
  self.assertEqual(receipts,[42,42])
  self.assertEqual(len(captured),2)
  for _,data,filename,_ in captured:
   self.assertTrue(filename.endswith(".csv"))
   row=list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))[0]
   self.assertIn("tradingview.com",row["tradingview_url"])
 def test_no_signals_no_spam(self):
  self.assertEqual(digest.send_digest([]),[])
if __name__=="__main__":unittest.main()
