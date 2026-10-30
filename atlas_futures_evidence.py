"""Evidence gate for futures plans. Missing, stale or high-cost data never pass."""
from datetime import datetime, timezone
import math

def number(v):
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError): return None

def verify(row, now=None, max_age_seconds=300, max_spread_bps=15):
    now=now or datetime.now(timezone.utc)
    ts=row.get("futures_timestamp")
    if isinstance(ts,(int,float)):
        ts=datetime.fromtimestamp(ts,timezone.utc)
    elif isinstance(ts,str):
        try: ts=datetime.fromisoformat(ts.replace("Z","+00:00"))
        except ValueError: ts=None
    if not isinstance(ts,datetime) or ts.tzinfo is None: return False,"MISSING_TIMESTAMP"
    age=(now-ts.astimezone(timezone.utc)).total_seconds()
    if age<0 or age>max_age_seconds: return False,"STALE_OR_FUTURE_DATA"
    bid=number(row.get("futures_bid"));ask=number(row.get("futures_ask"))
    if bid is None or ask is None or bid<=0 or ask<bid: return False,"INVALID_ORDERBOOK"
    spread=20000*(ask-bid)/(ask+bid)
    if spread>max_spread_bps: return False,"WIDE_SPREAD"
    volume=number(row.get("futures_24h_notional_usd"))
    if volume is None or volume<5_000_000: return False,"LOW_LIQUIDITY"
    oi=number(row.get("futures_open_interest_usd"))
    if oi is None or oi<=0: return False,"MISSING_OPEN_INTEREST"
    funding=number(row.get("futures_funding_rate"))
    if funding is None or abs(funding)>0.005: return False,"FUNDING_UNVERIFIED_OR_EXTREME"
    if not row.get("futures_exchange") or row.get("futures_contract_active") is not True:
        return False,"UNVERIFIED_VENUE"
    return True,"VERIFIED"
