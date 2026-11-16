"""ATLAS research-only paper execution simulator. Never routes real orders."""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class PaperOrder:
    side: str
    entry: float
    stop: float
    target: float
    quantity: float
    leverage: float = 1
    equity: float = 10000
    risk_limit_pct: float = 1.5

    def validate(self):
        vals=(self.entry,self.stop,self.target,self.quantity,self.leverage,self.equity)
        if not all(isfinite(v) and v>0 for v in vals):
            raise ValueError("invalid positive finite inputs")
        if self.side not in ("LONG","SHORT") or not 1<=self.leverage<=3:
            raise ValueError("side/leverage out of bounds")
        if not (self.stop<self.entry<self.target if self.side=="LONG"
                else self.target<self.entry<self.stop):
            raise ValueError("invalid protective stop/target geometry")
        if self.quantity*abs(self.entry-self.stop)>self.equity*self.risk_limit_pct/100:
            raise ValueError("position exceeds 1.5% stop-risk cap")
        if self.quantity*self.entry>self.equity*self.leverage:
            raise ValueError("insufficient simulated margin")

def simulate_closed_candle(order:PaperOrder,high:float,low:float,
                           maker_bps:float=2,taker_bps:float=5,
                           spread_bps:float=2,slippage_bps:float=3,
                           signed_funding_rate:float=0):
    """Closed-candle conservative execution; same-candle TP+SL -> SL.
    Funding signed positive = paid by LONG, received by SHORT.
    Synthetic costs, not historical fill evidence.
    """
    order.validate()
    if not all(isfinite(v) for v in (high,low,maker_bps,taker_bps,spread_bps,slippage_bps,signed_funding_rate)):
        raise ValueError("nonfinite candle/cost")
    if high<low or low<=0 or min(maker_bps,taker_bps,spread_bps,slippage_bps)<0:
        raise ValueError("invalid candle/cost")
    stop_hit=low<=order.stop if order.side=="LONG" else high>=order.stop
    target_hit=high>=order.target if order.side=="LONG" else low<=order.target
    if not (stop_hit or target_hit):
        return {"status":"OPEN","exit":None,"net_pnl":None}
    exit_price=order.stop if stop_hit else order.target
    direction=1 if order.side=="LONG" else -1
    gross=direction*(exit_price-order.entry)*order.quantity
    notional=order.quantity*(order.entry+exit_price)
    execution_cost=notional*(taker_bps+spread_bps/2+slippage_bps)/10000
    funding_cost=direction*signed_funding_rate*order.quantity*order.entry
    net=gross-execution_cost-funding_cost
    return {"status":"STOP" if stop_hit else "TARGET","exit":exit_price,
            "gross_pnl":gross,"execution_cost":execution_cost,
            "funding_cost":funding_cost,"net_pnl":net,
            "net_r":net/(order.quantity*abs(order.entry-order.stop)),
            "cost_model":"SCENARIO_ONLY","real_order":False}
