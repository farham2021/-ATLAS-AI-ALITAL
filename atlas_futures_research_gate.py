"""ATLAS Futures research gate. No exchange orders, no Telegram send side effects."""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite
from typing import Any

MAX_AGE_SECONDS = 6 * 3600
MAX_LEVERAGE = 3
MIN_CONFIDENCE = 55
MIN_RR = 2.0

def _number(value: Any) -> float | None:
    try:
        n = float(value)
        return n if isfinite(n) else None
    except (ValueError, TypeError):
        return None

def evaluate(candidate: dict, now: datetime | None = None) -> dict:
    """Fail closed; candidate's levels are never fabricated."""
    now = now or datetime.now(timezone.utc)
    side = str(candidate.get("side", "")).upper()
    entry, sl, tp1 = (_number(candidate.get(k)) for k in ("entry", "sl", "tp1"))
    confidence = _number(candidate.get("confidence"))
    stamp = candidate.get("updated_at")
    try:
        updated = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            raise ValueError("naive timestamp")
        age = (now - updated).total_seconds()
    except (TypeError, ValueError):
        age = float("inf")
    if any(v is None or v <= 0 for v in (entry, sl, tp1)):
        return {"status": "WAIT", "reason": "invalid levels"}
    correct = (side == "LONG" and sl < entry < tp1) or (side == "SHORT" and tp1 < entry < sl)
    if not correct:
        return {"status": "WAIT", "reason": "direction/levels conflict"}
    rr = abs(tp1 - entry) / abs(entry - sl)
    if age < -300 or age > MAX_AGE_SECONDS:
        return {"status": "WAIT", "reason": "stale timestamp", "rr": rr}
    if confidence is None or confidence < MIN_CONFIDENCE or rr < MIN_RR:
        return {"status": "WAIT", "reason": "quality gate", "rr": rr}
    stop_pct = abs(entry - sl) / entry * 100
    leverage_cap = min(MAX_LEVERAGE, max(1, int(4 / max(stop_pct, 0.01))))
    return {"status": "PAPER_CANDIDATE", "side": side, "symbol": candidate.get("symbol"),
            "entry": entry, "sl": sl, "tp1": tp1, "tp2": candidate.get("tp2"),
            "confidence": confidence, "rr": round(rr, 3), "leverage_cap": leverage_cap,
            "updated_at": stamp}

def rank(candidates: list[dict], now: datetime | None = None) -> list[dict]:
    accepted = [evaluate(c, now) for c in candidates]
    return sorted((c for c in accepted if c["status"] == "PAPER_CANDIDATE"),
                  key=lambda c: (-c["confidence"], -c["rr"], str(c["symbol"])))[:5]

def audit_outcomes(rows: list[dict]) -> dict:
    """Only evaluated signals with non-null directional_hit enter hit rate."""
    evaluated = [r for r in rows if r.get("status") == "evaluated" and isinstance(r.get("directional_hit"), bool)]
    n = len(evaluated)
    return {"evaluated": n, "pending_or_unscored": len(rows) - n,
            "directional_hit_rate": sum(r["directional_hit"] for r in evaluated) / n if n else None}

def telegram_preview(candidates: list[dict], now: datetime | None = None) -> str:
    """Build a research-only message; caller must explicitly authorize delivery."""
    rows = rank(candidates, now)
    if not rows:
        return "ATLAS Futures SHADOW | WAIT: no fresh validated paper candidates."
    lines = ["ATLAS Futures SHADOW | PAPER ONLY | NO LIVE ORDERS"]
    for c in rows:
        lines.append(f"{c['symbol']} {c['side']} | Entry {c['entry']} | SL {c['sl']} | TP1 {c['tp1']} | "
                     f"RR {c['rr']} | confidence {c['confidence']} | leverage CAP {c['leverage_cap']}x")
    return "\n".join(lines)

if __name__ == "__main__":
    from datetime import timedelta
    t = datetime.now(timezone.utc)
    sample = {"symbol": "TEST", "side": "LONG", "entry": 100, "sl": 98,
              "tp1": 105, "confidence": 70, "updated_at": t.isoformat()}
    assert evaluate(sample, t)["status"] == "PAPER_CANDIDATE"
    assert evaluate({**sample, "sl": 102}, t)["status"] == "WAIT"
    assert evaluate({**sample, "updated_at": (t-timedelta(hours=7)).isoformat()}, t)["status"] == "WAIT"
    assert audit_outcomes([{"status": "pending", "directional_hit": None},
                           {"status": "evaluated", "directional_hit": True}])["directional_hit_rate"] == 1.0
    print("futures research gate self-tests passed")
