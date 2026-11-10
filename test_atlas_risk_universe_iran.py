import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from atlas_top100_universe import discover_top100
from atlas_iran_risk_snapshot import scan_iran
class Response:
 def __init__(self,body):self.body=body
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def read(self):return self.body
class TestUniverseAndIran(unittest.TestCase):
 def test_top100_deduplicates(self):
  import json
  rows=[dict(id="coin"+str(i),symbol="x"+str(i),market_cap_rank=i) for i in range(1,101)]
  rows[1]["symbol"]="x1"
  with patch("atlas_top100_universe.urllib.request.urlopen",return_value=Response(json.dumps(rows).encode())):
   got=discover_top100()
  self.assertEqual(len(got),99)
  self.assertEqual(got[0]["symbol"],"X1USDT")
 def test_iran_requires_fresh_provider_pct(self):
  import json,os
  now=datetime(2026,11,10,9,tzinfo=timezone.utc)
  rows=[dict(symbol="TEST",captured_at=now.isoformat(),price=100,payload={"pct":-4}),dict(symbol="STALE",captured_at="2026-10-01T00:00:00Z",price=100,payload={"pct":-9})]
  def fake(*args,**kwargs):return Response(json.dumps(rows).encode())
  with patch.dict(os.environ,{"SUPABASE_URL":"https://example.invalid","SUPABASE_SERVICE_ROLE_KEY":"test"}):
   with patch("atlas_iran_risk_snapshot.urllib.request.urlopen",side_effect=fake):
    alerts,coverage=scan_iran(now)
  self.assertEqual(len(alerts),4)
  self.assertTrue(all(a[1]["level"]=="HIGH" for a in alerts))
if __name__=="__main__":unittest.main()
