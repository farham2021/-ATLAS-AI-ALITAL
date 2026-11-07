"""ATLAS Quant Lab: deterministic, shadow-only research acceptance gate.

No external data fetching, live orders, Telegram, or database writes.
A strategy cannot pass without verified out-of-sample evidence.
"""
from dataclasses import dataclass
from math import isfinite

REQUIRED_CHECKS = ("publication_split", "parameter_stability", "net_costs",
                   "historical_shocks", "independent_challenge",
                   "multiple_testing", "untouched_holdout", "data_integrity")
STATES = ("REJECTED", "RESEARCH_ONLY", "PAPER_TRADING", "VALIDATED")

@dataclass(frozen=True)
class ResearchEvidence:
    strategy_id: str
    rule_version: str
    data_snapshot_id: str
    benchmark: str
    trial_count: int
    checks: dict
    gross_sharpe: float | None = None
    net_sharpe: float | None = None
    out_of_sample_sharpe: float | None = None
    paper_execution_verified: bool = False
    critical_bias: bool = False

def assess(evidence: ResearchEvidence) -> dict:
    """Missing/unknown checks fail closed. No arbitrary Sharpe cutoff."""
    if not all((evidence.strategy_id, evidence.rule_version,
                evidence.data_snapshot_id, evidence.benchmark)):
        raise ValueError("strategy, rules, dataset and benchmark required")
    if isinstance(evidence.trial_count, bool) or evidence.trial_count < 1:
        raise ValueError("positive trial count required")
    if not isinstance(evidence.checks, dict):
        raise ValueError("checks must be a dictionary")
    if any(v is not None and (not isinstance(v, (int, float)) or
           isinstance(v, bool) or not isfinite(v))
           for v in (evidence.gross_sharpe, evidence.net_sharpe,
                     evidence.out_of_sample_sharpe)):
        raise ValueError("invalid Sharpe")
    missing = [name for name in REQUIRED_CHECKS if evidence.checks.get(name) is not True]
    if evidence.critical_bias or any(evidence.checks.get(k) is False
                                      for k in ("data_integrity", "untouched_holdout")):
        status = "REJECTED"
    elif missing or evidence.net_sharpe is None or evidence.out_of_sample_sharpe is None:
        status = "RESEARCH_ONLY"
    elif evidence.paper_execution_verified:
        status = "VALIDATED"
    else:
        status = "PAPER_TRADING"
    return {"strategy_id": evidence.strategy_id, "status": status,
            "missing_checks": missing, "trial_count": evidence.trial_count,
            "shadow_only": True, "no_live_trading": True}
