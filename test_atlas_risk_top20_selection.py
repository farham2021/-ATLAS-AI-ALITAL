import unittest
from atlas_risk_top20_selection import select,DESK
class TestSelection(unittest.TestCase):
 def test_ten_plus_ten(self):
  rows=[(s,dict(level="WATCH",price=1,decline24=-1,volume_ratio=1,flags=["weak"])) for s in DESK]
  rows += [("ALT"+str(i)+"USDT",dict(level="CRITICAL" if i<10 else "WATCH",price=1,decline24=-i,volume_ratio=2,flags=["break"])) for i in range(25)]
  result=select(rows)
  self.assertEqual(len(result),20)
  self.assertEqual(tuple(s for s,_ in result[:10]),DESK)
  self.assertEqual(len(set(s for s,_ in result)),20)
  self.assertTrue(all(r["level"]=="CRITICAL" for _,r in result[10:]))
 def test_missing_desk_fail_closed(self):
  result=select([])
  self.assertEqual(len(result),10)
  self.assertTrue(all(r["level"]=="NONE" for _,r in result))
if __name__=="__main__":unittest.main()
