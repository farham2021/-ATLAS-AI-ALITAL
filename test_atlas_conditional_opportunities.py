import unittest
from atlas_conditional_opportunities import discover
from atlas_futures_png import select_five
class ConditionalTests(unittest.TestCase):
    def test_short_watch_not_executable(self):
        row=dict(coin="ETH",action="WAIT",direction="SHORT",trigger=2294,confidence=66)
        p=select_five([row])[0]
        self.assertEqual(p["state"],"CONDITIONAL")
        self.assertEqual(p["side"],"SHORT")
        self.assertIsNone(p["entry"])
        self.assertEqual(p["trigger"],2294)
    def test_missing_trigger_is_not_conditional(self):
        self.assertEqual(discover([dict(coin="ETH",action="WAIT",direction="LONG")]),[])
    def test_rank_limit(self):
        rows=[dict(coin=str(i),direction="LONG",trigger=10,confidence=i) for i in range(10)]
        self.assertEqual(len(discover(rows)),5)
if __name__=="__main__": unittest.main()
