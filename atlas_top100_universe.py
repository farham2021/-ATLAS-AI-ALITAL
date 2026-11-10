"""ATLAS ranked top-100 crypto universe with validated USD spot pairs.
CoinGecko ranking is discovery only, never a price/candle signal.
"""
import json,urllib.request,urllib.parse
URL="https://api.coingecko.com/api/v3/coins/markets"
def discover_top100(timeout=25):
 query=urllib.parse.urlencode({"vs_currency":"usd","order":"market_cap_desc","per_page":100,"page":1,"sparkline":"false"})
 req=urllib.request.Request(URL+"?"+query,headers={"Accept":"application/json","User-Agent":"ATLAS-RiskGuard/1"})
 with urllib.request.urlopen(req,timeout=timeout) as r:rows=json.load(r)
 if not isinstance(rows,list) or len(rows)<80:raise ValueError("top100 universe unavailable/incomplete")
 result=[];seen=set()
 for row in rows:
  if not isinstance(row,dict):continue
  ticker=str(row.get("symbol") or "").upper()
  rank=row.get("market_cap_rank")
  if not ticker.isascii() or not ticker.isalnum() or not ticker or not isinstance(rank,int) or not 1<=rank<=100:continue
  if ticker in seen:continue
  seen.add(ticker)
  result.append({"symbol":ticker+"USDT","coin_id":str(row["id"]),"rank":rank})
 return result
