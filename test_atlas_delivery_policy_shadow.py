import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from atlas_delivery_policy_shadow import policy
T=ZoneInfo("Asia/Tehran")
class TestPolicy(unittest.TestCase):
 def test_iran_open(self):
  self.assertTrue(policy(datetime(2026,11,10,10,40,tzinfo=T),"IRAN","TABLE")["deliver"])
 def test_iran_night(self):
  self.assertFalse(policy(datetime(2026,11,10,23,0,tzinfo=T),"IRAN","TABLE")["deliver"])
 def test_iran_friday(self):
  self.assertFalse(policy(datetime(2026,11,13,10,40,tzinfo=T),"IRAN","TABLE")["deliver"])
 def test_crypto_daily(self):
  self.assertTrue(policy(datetime(2026,11,10,16,10,tzinfo=T),"CRYPTO","TABLE")["deliver"])
 def test_csv_slots(self):
  for h,m in ((10,30),(16,0),(21,30)):
   self.assertTrue(policy(datetime(2026,11,10,h,m,tzinfo=T),"CRYPTO","CSV")["deliver"])
  self.assertFalse(policy(datetime(2026,11,10,23,0,tzinfo=T),"CRYPTO","CSV")["deliver"])
 def test_critical(self):
  self.assertTrue(policy(datetime(2026,11,10,23,0,tzinfo=T),"CRYPTO","CSV",True)["deliver"])
if __name__=="__main__":unittest.main()
