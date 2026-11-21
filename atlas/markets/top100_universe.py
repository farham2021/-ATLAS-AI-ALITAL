"""ATLAS ranked top-100 crypto universe with validated USD spot pairs.
CoinGecko ranking is discovery only, never a price/candle signal.
"""
import json,urllib.request,urllib.parse
URL="https://api.coingecko.com/api/v3/coins/markets"
def discover_top100(timeout=25,include_beyond=True):
 rows=[]
 for page in (1,2) if include_beyond else (1,):
  query=urllib.parse.urlencode({"vs_currency":"usd","order":"market_cap_desc","per_page":100,"page":page,"sparkline":"false"})
  req=urllib.request.Request(URL+"?"+query,headers={"Accept":"application/json","User-Agent":"ATLAS-RiskGuard/1"})
  try:
   with urllib.request.urlopen(req,timeout=timeout) as r:part=json.load(r)
  except Exception:
   if page==1:raise
   break
  if not isinstance(part,list):
   if page==1:raise ValueError("top100 invalid")
   break
  rows.extend(part)
 if not isinstance(rows,list) or len(rows)<80:raise ValueError("top100 universe unavailable/incomplete")
 result=[];seen=set()
 for row in rows:
  if not isinstance(row,dict):continue
  ticker=str(row.get("symbol") or "").upper()
  rank=row.get("market_cap_rank")
  if not ticker.isascii() or not ticker.isalnum() or not ticker or not isinstance(rank,int) or not 1<=rank<=(200 if include_beyond else 100):continue
  if ticker in seen:continue
  seen.add(ticker)
  result.append({"symbol":ticker+"USDT","coin_id":str(row["id"]),"rank":rank})
 return result
