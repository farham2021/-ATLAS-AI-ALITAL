"""Closed-candle replay and portfolio journal statistics; research only."""
from math import isfinite
from atlas_paper_execution_v2 import simulate_closed_candle
def replay(order,bars):
 """Bars MUST be chronologically ordered closed candles; stop takes precedence."""
 order.validate()
 for index,bar in enumerate(bars):
  result=simulate_closed_candle(order,float(bar["high"]),float(bar["low"]))
  if result["status"]!="OPEN":return {"bar_index":index,**result}
 return {"status":"OPEN","bar_index":None,"net_pnl":None}
def journal(closed):
 """Closed trades with realized net P&L and initial risk; no synthetic wins."""
 if not closed:return {"trades":0,"win_rate":None,"profit_factor":None,"avg_r":None,"max_drawdown":None}
 pnl=[float(x["net_pnl"]) for x in closed];risks=[float(x["initial_risk"]) for x in closed]
 if any(not isfinite(x) for x in pnl+risks) or any(r<=0 for r in risks):raise ValueError("invalid journal")
 gains=sum(max(x,0) for x in pnl);losses=-sum(min(x,0) for x in pnl)
 running=0;peak=0;drawdown=0
 for x in pnl:
  running+=x;peak=max(peak,running);drawdown=max(drawdown,peak-running)
 return {"trades":len(pnl),"win_rate":sum(x>0 for x in pnl)/len(pnl),
 "profit_factor":gains/losses if losses else None,
 "avg_r":sum(p/r for p,r in zip(pnl,risks))/len(pnl),
 "max_drawdown_amount":drawdown}
