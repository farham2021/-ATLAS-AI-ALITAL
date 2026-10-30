import json
import tempfile
import unittest
from atlas_v13_runtime import run_v13_cycle
class RuntimeTests(unittest.TestCase):
 def test_real_rows_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   path=d+"/out.json"
   state=run_v13_cycle([{"symbol":"BTC","change_pct_24h":-5}],[],[],path)
   self.assertEqual(state["alerts"],0)
   self.assertEqual(state["verified"],0)
   self.assertEqual(json.load(open(path))["mode"],"SHADOW")
if __name__=="__main__":unittest.main()
