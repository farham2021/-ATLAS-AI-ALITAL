"""Select exactly ten desk assets and up to ten ranked dynamic risk opportunities.
The 100+ universe is scanned internally, not exported wholesale.
"""
DESK=("BTCUSDT","ETHUSDT","BNBUSDT","XRPUSDT","SOLUSDT","DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","SUIUSDT")
LEVEL={"CRITICAL":5,"GROWTH_HIGH":4,"HIGH":4,"GROWTH_WATCH":2,"WATCH":2,"NONE":0}
def priority(result):
 level=result.get("level","NONE")
 magnitude=abs(float(result.get("decline24") or 0))
 volume=float(result.get("volume_ratio") or 0)
 flags=len(result.get("flags") or [])
 return (LEVEL.get(level,0),flags,min(volume,20),magnitude)
def select(rows):
 """Input (symbol,result) pairs; output desk first, dynamic second.
 Missing/invalid signals are explicitly labelled NONE; no invented levels.
 """
 latest={}
 for symbol,result in rows:
  if symbol not in latest or priority(result)>priority(latest[symbol]):
   latest[symbol]=result
 selected=[]
 for symbol in DESK:
  selected.append((symbol,latest.get(symbol,{"level":"NONE","price":"","decline24":"","volume_ratio":"","flags":["data unavailable"],"market":"CRYPTO"})))
 candidates=[(symbol,result) for symbol,result in latest.items() if symbol not in DESK and result.get("level")!="NONE" and result.get("market","CRYPTO")=="CRYPTO"]
 candidates.sort(key=lambda pair:(tuple(-v for v in priority(pair[1])),pair[0]))
 return selected+candidates[:10]
