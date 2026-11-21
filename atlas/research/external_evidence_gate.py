"""ATLAS external research signal contract.

OctoBot execution, Kronos forecasts and MonkQL research must enter through
this fail-closed, auditable boundary. No live orders or Telegram side effects.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

PROVIDERS = frozenset({"monk_trade", "kronos", "octobot"})
MARKETS = frozenset({"us_equity", "us_futures", "crypto", "iran"})
ALLOWED = {"monk_trade": {"us_equity", "us_futures"},
           "kronos": {"us_equity", "us_futures", "crypto", "iran"},
           "octobot": {"crypto"}}
ACTIONS = frozenset({"BUY", "ACCUMULATE", "HOLD", "WAIT", "REDUCE", "SELL"})

@dataclass(frozen=True)
class ExternalEvidence:
    provider: str
    market: str
    symbol: str
    asof_utc: str
    reference_id: str
    status: str
    action: str = "WAIT"
    confidence: float | None = None
    research_only: bool = True

def validate_evidence(e: ExternalEvidence, *, now_utc: datetime,
                      max_age_seconds: int = 86400) -> dict:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if e.provider not in PROVIDERS or e.market not in MARKETS:
        raise ValueError("unknown provider or market")
    if e.market not in ALLOWED[e.provider]:
        raise ValueError("provider does not cover this market")
    if not e.symbol.strip() or not e.reference_id.strip():
        raise ValueError("symbol and source reference required")
    if e.action not in ACTIONS:
        raise ValueError("unknown action")
    if e.confidence is not None and (not isfinite(e.confidence)
                                     or not 0 <= e.confidence <= 100):
        raise ValueError("invalid confidence")
    try:
        asof = datetime.fromisoformat(e.asof_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if asof.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    age = (now_utc.astimezone(timezone.utc) -
           asof.astimezone(timezone.utc)).total_seconds()
    if age < -300 or age > max_age_seconds:
        return {"accepted": False, "reason": "STALE_OR_FUTURE", "action": "WAIT",
                "shadow_only": True}
    if e.status != "complete":
        return {"accepted": False, "reason": "INCOMPLETE_SOURCE", "action": "WAIT",
                "shadow_only": True}
    if not e.research_only:
        return {"accepted": False, "reason": "LIVE_PERMISSION_DENIED",
                "action": "WAIT", "shadow_only": True}
    return {"accepted": True, "reason": "RESEARCH_EVIDENCE_ONLY",
            "action": "WAIT", "shadow_only": True,
            "provider": e.provider, "reference_id": e.reference_id}
