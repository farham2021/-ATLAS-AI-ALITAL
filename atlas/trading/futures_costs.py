"""Conservative scenario costs for ATLAS shadow/paper results; not actual exchange fills."""
from dataclasses import dataclass
from datetime import datetime
import math

@dataclass(frozen=True)
class ExecutionCostModel:
    entry_fee_rate: float = 0.0005
    exit_fee_rate: float = 0.0005
    entry_slippage_rate: float = 0.0003
    exit_slippage_rate: float = 0.0003
    funding_rate_8h: float = 0.0001

def evaluate_trade_net_r(side, entry_price, stop_loss, exit_price, opened_at, closed_at,
                         is_limit_tp=False, costs=ExecutionCostModel()):
    """Return gross/cost/net R, assuming fixed notional quantity and scenario funding.

    Positive funding_rate_8h means a payment by this position. Negative means credit.
    Intervals are estimated from holding duration, NOT actual funding timestamps.
    """
    prices=(entry_price,stop_loss,exit_price)
    if not all(math.isfinite(x) and x>0 for x in prices):raise ValueError("Positive finite prices required")
    risk=abs(entry_price-stop_loss)
    if risk<=0:raise ValueError("Stop must differ from entry")
    if side not in ("LONG","SHORT"):raise ValueError("Invalid side")
    if opened_at.tzinfo is None or closed_at.tzinfo is None or closed_at<opened_at:
        raise ValueError("Timezone-aware ordered timestamps required")
    rates=(costs.entry_fee_rate,costs.exit_fee_rate,costs.entry_slippage_rate,costs.exit_slippage_rate,costs.funding_rate_8h)
    if not all(math.isfinite(x) for x in rates) or any(x<0 for x in rates[:4]):
        raise ValueError("Invalid cost rates")
    direction=1 if side=="LONG" else -1
    gross=direction*(exit_price-entry_price)/risk
    intervals=math.floor((closed_at-opened_at).total_seconds()/28800)
    entry_cost=entry_price*(costs.entry_fee_rate+costs.entry_slippage_rate)
    exit_cost=exit_price*(costs.exit_fee_rate+(0 if is_limit_tp else costs.exit_slippage_rate))
    funding=entry_price*intervals*costs.funding_rate_8h
    cost_r=(entry_cost+exit_cost+funding)/risk
    return {"gross_r":round(gross,6),"cost_r":round(cost_r,6),"net_r":round(gross-cost_r,6),
            "funding_intervals":intervals,"total_cost_pct":round((entry_cost+exit_cost+funding)/entry_price*100,6),
            "cost_model":"scenario_fixed_rates_v1"}
