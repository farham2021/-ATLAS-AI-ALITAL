import tempfile,unittest
from atlas_v13_receipts import record_photo_receipt,audit_photo_receipts
class ReceiptTests(unittest.TestCase):
 def test_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   p=d+"/receipts.jsonl"
   record_photo_receipt("x.png","ATLAS TSE Intelligence | now",{"ok":True,"result":{"message_id":12,"chat":{"id":123}}},p)
   r=audit_photo_receipts(p)
   self.assertEqual(r["count"],1)
   self.assertEqual(r["reports"],["ATLAS TSE Intelligence"])
 def test_fail_closed(self):
  with self.assertRaises(ValueError):record_photo_receipt("x","x",{"ok":True,"result":{}})
if __name__=="__main__":unittest.main()
