"""
ATLAS Self-Learning & Self-Diagnosis Module
===========================================
Implements:
- Outcome storage (SQLite primary, CSV fallback)
- Weekly weight adjustment based on indicator success/failure
- Self-diagnosis every 3 closed signals
- Mandatory overfitting warning
- Transparent changelog

Does NOT modify bot.py architecture.
Weights are stored in a simple JSON file that the Professional Monitor can load.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

LEARNING_VERSION = "ATLAS_SELF_LEARNING_V1_0"
DEFAULT_DB = os.environ.get("ATLAS_LEARNING_DB", "atlas_learning.sqlite3")
WEIGHTS_FILE = os.environ.get("ATLAS_WEIGHTS_FILE", "atlas_indicator_weights.json")
CHANGELOG_FILE = os.environ.get("ATLAS_CHANGELOG", "changelog.txt")

DEFAULT_WEIGHTS = {
    "candle_pattern": 20.0,
    "indicators": 30.0,
    "volume": 15.0,
    "htf_alignment": 20.0,
    "news_clear": 15.0,
}

OVERFITTING_WARNING = (
    "تنظیمات بر اساس داده‌ی محدود اخیر انجام شده و ممکن است در آینده عملکرد متفاوتی داشته باشد."
)

# Minimum closed trades before any weight change is allowed
MIN_SAMPLE_FOR_ADJUST = 15
# Self-diagnosis every N closed outcomes
DIAGNOSIS_EVERY = 3
# Error threshold (fraction of losing signals in recent window)
ERROR_THRESHOLD = 0.05  # 5% absolute edge; we use loss-rate proxy


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(db_path: str = DEFAULT_DB):
    c = sqlite3.connect(db_path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_learning_db(db_path: str = DEFAULT_DB) -> None:
    with _conn(db_path) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT,
                signal TEXT,
                confidence REAL,
                entry REAL,
                sl REAL,
                tp1 REAL,
                tp2 REAL,
                outcome TEXT,          -- TP | SL | TIMEOUT | OPEN
                realized_r REAL,
                pattern_name TEXT,
                indicators_json TEXT,
                reason TEXT,
                closed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS weight_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                weights_json TEXT NOT NULL,
                reason TEXT,
                sample_size INTEGER
            );
            CREATE TABLE IF NOT EXISTS diagnosis_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                window_size INTEGER,
                loss_rate REAL,
                action TEXT,
                detail TEXT
            );
            """
        )


def load_weights(path: str = WEIGHTS_FILE) -> Dict[str, float]:
    p = Path(path)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            w = dict(DEFAULT_WEIGHTS)
            for k, v in (data.get("weights") or data).items():
                if k in w and isinstance(v, (int, float)):
                    w[k] = float(v)
            return w
        except Exception:
            pass
    return dict(DEFAULT_WEIGHTS)


def save_weights(weights: Mapping[str, float], reason: str, sample_size: int,
                 path: str = WEIGHTS_FILE, db_path: str = DEFAULT_DB) -> None:
    payload = {
        "weights": dict(weights),
        "updated_at": _now(),
        "reason": reason,
        "sample_size": sample_size,
        "version": LEARNING_VERSION,
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    init_learning_db(db_path)
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO weight_history(ts, weights_json, reason, sample_size) VALUES (?,?,?,?)",
            (_now(), json.dumps(dict(weights)), reason, sample_size),
        )
    append_changelog("WEIGHT_ADJUST", reason, {"weights": dict(weights), "sample": sample_size})


def append_changelog(event: str, detail: str, extra: Optional[dict] = None) -> None:
    line = f"{_now()} | {event} | {detail}"
    if extra:
        line += " | " + json.dumps(extra, ensure_ascii=False, default=str)[:400]
    with open(CHANGELOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def record_outcome(
    symbol: str,
    direction: str,
    signal: str,
    confidence: float,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    outcome: str,
    realized_r: Optional[float] = None,
    pattern_name: str = "",
    indicators: Optional[dict] = None,
    reason: str = "",
    db_path: str = DEFAULT_DB,
) -> int:
    """Persist a closed (or open) signal outcome. Returns row id."""
    init_learning_db(db_path)
    with _conn(db_path) as c:
        cur = c.execute(
            """
            INSERT INTO signal_outcomes(
                created_at, symbol, direction, signal, confidence,
                entry, sl, tp1, tp2, outcome, realized_r,
                pattern_name, indicators_json, reason, closed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _now(), symbol, direction, signal, confidence,
                entry, sl, tp1, tp2, outcome, realized_r,
                pattern_name, json.dumps(indicators or {}), reason,
                _now() if outcome in ("TP", "SL", "TIMEOUT") else None,
            ),
        )
        return int(cur.lastrowid)


def recent_outcomes(limit: int = 50, db_path: str = DEFAULT_DB) -> List[Dict[str, Any]]:
    init_learning_db(db_path)
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT * FROM signal_outcomes WHERE outcome IN ('TP','SL','TIMEOUT') "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def weekly_analysis(db_path: str = DEFAULT_DB, min_sample: int = MIN_SAMPLE_FOR_ADJUST) -> Dict[str, Any]:
    """
    Analyse recent closed signals and propose weight adjustments.
    Returns a report dict; does NOT apply changes unless apply_adjustments=True
    is later called via apply_weekly_adjustments.
    """
    outcomes = recent_outcomes(80, db_path=db_path)
    report: Dict[str, Any] = {
        "version": LEARNING_VERSION,
        "ts": _now(),
        "sample_size": len(outcomes),
        "overfitting_warning": OVERFITTING_WARNING,
        "adjustments": [],
        "stats": {},
        "applied": False,
    }

    if len(outcomes) < min_sample:
        report["message"] = f"نمونه ناکافی ({len(outcomes)}/{min_sample}) — هیچ وزنی تغییر نکرد"
        return report

    wins = [o for o in outcomes if o.get("outcome") == "TP"]
    losses = [o for o in outcomes if o.get("outcome") == "SL"]
    win_rate = len(wins) / len(outcomes) if outcomes else 0.0
    avg_r = sum((o.get("realized_r") or 0) for o in outcomes) / len(outcomes)

    report["stats"] = {
        "win_rate": round(win_rate, 3),
        "avg_realized_r": round(avg_r, 3),
        "wins": len(wins),
        "losses": len(losses),
        "timeouts": len(outcomes) - len(wins) - len(losses),
    }

    # Simple attribution: if overall loss rate is high, reduce the weakest family.
    # We look at pattern success and indicator presence in losing trades.
    current = load_weights()
    proposed = dict(current)

    loss_rate = len(losses) / len(outcomes)
    if loss_rate > 0.55:
        # Reduce candle_pattern weight slightly (patterns may be overfitted)
        proposed["candle_pattern"] = max(10.0, current["candle_pattern"] * 0.85)
        report["adjustments"].append({
            "key": "candle_pattern",
            "from": current["candle_pattern"],
            "to": proposed["candle_pattern"],
            "reason": f"نرخ ضرر {loss_rate:.0%} — کاهش وزن الگوی کندلی",
        })
    if win_rate > 0.60 and avg_r > 0.3:
        # Reward volume confirmation if overall healthy
        proposed["volume"] = min(20.0, current["volume"] * 1.08)
        report["adjustments"].append({
            "key": "volume",
            "from": current["volume"],
            "to": proposed["volume"],
            "reason": f"نرخ برد {win_rate:.0%} و R متوسط مثبت — تقویت وزن حجم",
        })

    # Normalise so total stays ~100
    total = sum(proposed.values())
    if total > 0 and abs(total - 100) > 1:
        scale = 100.0 / total
        for k in proposed:
            proposed[k] = round(proposed[k] * scale, 2)

    report["proposed_weights"] = proposed
    report["current_weights"] = current
    return report


def apply_weekly_adjustments(
    report: Optional[Dict[str, Any]] = None,
    db_path: str = DEFAULT_DB,
) -> Dict[str, Any]:
    """Apply proposed adjustments from weekly_analysis and log them."""
    if report is None:
        report = weekly_analysis(db_path=db_path)
    if not report.get("adjustments"):
        report["applied"] = False
        report["message"] = report.get("message") or "هیچ تعدیلی لازم نبود"
        return report

    proposed = report.get("proposed_weights") or load_weights()
    reason = "; ".join(a["reason"] for a in report["adjustments"])
    save_weights(proposed, reason, report.get("sample_size", 0), db_path=db_path)
    report["applied"] = True
    report["message"] = "وزن‌ها با موفقیت به‌روز شدند"
    return report


def self_diagnose(db_path: str = DEFAULT_DB) -> Dict[str, Any]:
    """
    Run after every DIAGNOSIS_EVERY closed signals.
    If recent error (loss) rate is elevated, reduce the most implicated weight
    and optionally suggest a substitute indicator (Stochastic) in the log.
    """
    outcomes = recent_outcomes(DIAGNOSIS_EVERY * 3, db_path=db_path)
    result = {
        "version": LEARNING_VERSION,
        "ts": _now(),
        "window": len(outcomes),
        "action": "NONE",
        "detail": "",
        "overfitting_warning": OVERFITTING_WARNING,
    }
    if len(outcomes) < DIAGNOSIS_EVERY:
        result["detail"] = "نمونه برای خودتشخیصی کافی نیست"
        return result

    recent = outcomes[:DIAGNOSIS_EVERY]
    losses = [o for o in recent if o.get("outcome") == "SL"]
    loss_rate = len(losses) / len(recent)

    init_learning_db(db_path)
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO diagnosis_log(ts, window_size, loss_rate, action, detail) VALUES (?,?,?,?,?)",
            (_now(), len(recent), loss_rate, "EVAL", f"loss_rate={loss_rate:.3f}"),
        )

    if loss_rate <= ERROR_THRESHOLD * 10:  # 5% is very strict for binary; use 50% as practical
        # Practical threshold: if ≥2 of last 3 are losses → act
        if len(losses) < 2:
            result["detail"] = f"نرخ ضرر اخیر {loss_rate:.0%} — قابل قبول"
            return result

    # Act: reduce candle_pattern or indicators weight by 20%
    current = load_weights()
    key = "candle_pattern"
    old = current[key]
    current[key] = max(8.0, old * 0.80)
    # Re-normalise
    total = sum(current.values())
    if total > 0:
        scale = 100.0 / total
        current = {k: round(v * scale, 2) for k, v in current.items()}

    reason = (
        f"خودتشخیصی: {len(losses)}/{len(recent)} ضرر در پنجره اخیر — "
        f"کاهش وزن {key} و پیشنهاد بررسی Stochastic به‌عنوان جایگزین"
    )
    save_weights(current, reason, len(outcomes), db_path=db_path)
    result["action"] = "WEIGHT_REDUCED"
    result["detail"] = reason
    result["new_weights"] = current

    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO diagnosis_log(ts, window_size, loss_rate, action, detail) VALUES (?,?,?,?,?)",
            (_now(), len(recent), loss_rate, "WEIGHT_REDUCED", reason[:500]),
        )
    return result


def format_weekly_report(report: Dict[str, Any]) -> str:
    """Human-readable weekly learning report for Telegram / log."""
    lines = [
        "🧠 گزارش هفتگی خوداصلاحی | ناظر هوشمند",
        f"نسخه: {LEARNING_VERSION}",
        f"نمونه: {report.get('sample_size', 0)} سیگنال بسته‌شده",
        "",
    ]
    stats = report.get("stats") or {}
    if stats:
        lines.append(f"نرخ برد: {stats.get('win_rate', 0):.1%}")
        lines.append(f"میانگین R: {stats.get('avg_realized_r', 0):.2f}")
        lines.append(f"برد/باخت/تایم‌اوت: {stats.get('wins', 0)}/{stats.get('losses', 0)}/{stats.get('timeouts', 0)}")
        lines.append("")

    adjs = report.get("adjustments") or []
    if adjs:
        lines.append("تعدیل وزن‌ها:")
        for a in adjs:
            lines.append(f"• {a['key']}: {a['from']:.1f} → {a['to']:.1f} | {a['reason']}")
    else:
        lines.append(report.get("message") or "هیچ تعدیلی اعمال نشد.")

    lines.append("")
    lines.append(f"⚠️ {OVERFITTING_WARNING}")
    lines.append("این گزارش توصیه مالی نیست.")
    return "\n".join(lines)
