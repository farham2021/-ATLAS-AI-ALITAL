from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
TABLE = (os.environ.get("ATLAS_SCHEDULER_TABLE") or "atlas_scheduler_runs").strip()
CLAIM_RPC = (os.environ.get("ATLAS_SCHEDULER_CLAIM_RPC") or "atlas_scheduler_claim").strip()
MARK_RPC = (os.environ.get("ATLAS_SCHEDULER_MARK_RPC") or "atlas_scheduler_mark_done").strip()
DEEP_HOURS = {0, 4, 8, 12, 20}
DEFAULT_LEASE_MIN = int(os.environ.get("ATLAS_SCHEDULER_LEASE_MIN", "65") or 65)


def _conf():
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
    return url, key


def _request(method: str, path: str, body=None, prefer=None):
    url, key = _conf()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.status, (json.loads(raw) if raw else {"_ok": True})
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Supabase HTTP {e.code}: {err}") from e


def _rpc(name: str, body: dict):
    _code, payload = _request("POST", f"/rest/v1/rpc/{name}", body)
    if isinstance(payload, list):
        return payload[0] if payload else None
    return payload


def now_tehran():
    override = (os.environ.get("ATLAS_GUARD_NOW") or "").strip()
    if override:
        dt = datetime.fromisoformat(override)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TEHRAN)
        return dt.astimezone(TEHRAN)
    return datetime.now(TEHRAN)


def now_utc():
    return datetime.now(timezone.utc)


def day_key(cycle: str, day) -> str:
    return f"{cycle}:{day.isoformat()}"


def hour_key(cycle: str, dt: datetime) -> str:
    return f"{cycle}:{dt.strftime('%Y-%m-%d:%H')}"


def _parse_ts(value):
    if not value:
        return None
    raw = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_row(run_key: str):
    if not run_key:
        return None
    q = urllib.parse.quote(run_key, safe="")
    _code, rows = _request("GET", f"/rest/v1/{TABLE}?run_key=eq.{q}&select=*&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else None


def classify_row(row, now=None):
    if not row:
        return "MISSING"
    status = str(row.get("status") or "").upper()
    if status == "DONE" or (not status and row.get("completed_at")):
        return "DONE"
    lease = _parse_ts(row.get("lease_until"))
    now = now or now_utc()
    if status == "RUNNING" and lease and lease > now:
        return "RUNNING"
    return "EXPIRED"


def remote_done(run_key: str):
    """True=finished/actively leased, False=needs work, None=state unavailable."""
    try:
        state = classify_row(fetch_row(run_key))
        if state in {"DONE", "RUNNING"}:
            return True
        return False
    except Exception as e:
        print(f"::warning::ATLAS scheduler state unavailable: {e}")
        return None


def claim_slot(run_key: str, cycle: str, ttl_min: int):
    if not run_key.strip():
        return {"claimed": "ERROR", "detail": "empty run_key is forbidden", "lease_token": ""}
    dt = now_tehran()
    parts = run_key.split(":")
    key_date = parts[1] if len(parts) >= 2 else dt.date().isoformat()
    try:
        row = _rpc(
            CLAIM_RPC,
            {
                "p_run_key": run_key,
                "p_cycle": cycle,
                "p_tehran_date": key_date,
                "p_ttl_min": max(5, int(ttl_min)),
            },
        )
        if not isinstance(row, dict):
            raise RuntimeError(f"unexpected claim RPC response: {row!r}")
        return {
            "claimed": str(row.get("claimed") or "ERROR").upper(),
            "detail": str(row.get("detail") or ""),
            "lease_token": str(row.get("lease_token") or ""),
        }
    except Exception as e:
        return {"claimed": "ERROR", "detail": str(e), "lease_token": ""}


def mark_done(run_key: str, cycle: str, lease_token: str, source: str):
    if not run_key.strip() or not lease_token.strip():
        raise RuntimeError("mark requires non-empty run_key and lease_token")
    row = _rpc(
        MARK_RPC,
        {
            "p_run_key": run_key,
            "p_cycle": cycle,
            "p_lease_token": lease_token,
            "p_source": source,
        },
    )
    if not isinstance(row, dict):
        raise RuntimeError(f"unexpected mark RPC response: {row!r}")
    result = str(row.get("result") or "ERROR").upper()
    detail = str(row.get("detail") or "")
    if result not in {"MARKED", "DONE"}:
        raise RuntimeError(f"scheduler mark refused: {result}: {detail}")
    return {"result": result, "detail": detail}


def _plan(mode: str, run_key: str, reason: str, scheduled: bool = True):
    return {
        "mode": mode,
        "run_key": run_key,
        "reason": reason,
        "scheduled": "1" if scheduled else "0",
    }


def _latest_deep_slot(dt: datetime):
    candidates = [h for h in DEEP_HOURS if h <= dt.hour]
    if candidates:
        return dt.replace(hour=max(candidates), minute=0, second=0, microsecond=0)
    yday = dt - timedelta(days=1)
    return yday.replace(hour=max(DEEP_HOURS), minute=0, second=0, microsecond=0)


def choose_plan(dt: datetime, state_getter=remote_done):
    dt = dt.astimezone(TEHRAN)
    today = dt.date()

    today_daily = day_key("DAILY16", today)
    today_nightly = day_key("NIGHTLY23", today)

    # Highest priority: due reports with catch-up semantics.
    if dt.hour >= 23:
        s = state_getter(today_nightly)
        if s is not True:
            return _plan("NIGHTLY23", today_nightly, "nightly_due_or_unconfirmed")

    if dt.hour >= 16:
        s = state_getter(today_daily)
        if s is not True:
            return _plan("DAILY16", today_daily, "daily16_due_or_unconfirmed")

    if dt.hour < 2:
        yday = today - timedelta(days=1)
        prev_nightly = day_key("NIGHTLY23", yday)
        s = state_getter(prev_nightly)
        if s is not True:
            return _plan("NIGHTLY23", prev_nightly, "previous_nightly_recovery")

    # Recover the latest missed DEEP4H slot while it is still within its 4-hour window.
    # DAILY16/NIGHTLY23 above intentionally supersede deep recovery at their report times.
    latest_deep = _latest_deep_slot(dt)
    age = dt - latest_deep
    if timedelta(0) <= age < timedelta(hours=4):
        deep_key = hour_key("DEEP4H", latest_deep)
        s = state_getter(deep_key)
        if s is False:
            reason = "current_deep_slot" if dt.hour in DEEP_HOURS else "deep4h_recovery"
            return _plan("DEEP4H", deep_key, reason)
        if s is None and dt.hour in DEEP_HOURS:
            return _plan("NONE", "", "deep_slot_state_unavailable")

    # Regular hourly fallback. At exact DEEP4H hours, a completed/leased deep slot means
    # there is nothing else to run for that hour.
    if dt.hour in DEEP_HOURS:
        return _plan("NONE", "", "deep_slot_already_done")

    key = hour_key("HOURLY", dt)
    s = state_getter(key)
    if s is False:
        return _plan("HOURLY", key, "current_hour_slot")
    if s is None:
        return _plan("NONE", "", "regular_slot_state_unavailable")
    return _plan("NONE", "", "slot_already_done")


def write_github_output(values, path):
    with open(path, "a", encoding="utf-8") as f:
        for key, val in values.items():
            safe = str(val).replace("\r", " ").replace("\n", " ")
            f.write(f"{key}={safe}\n")


def cmd_plan(args):
    if args.manual:
        plan = _plan(args.manual, "", "manual_dispatch", scheduled=False)
    else:
        plan = choose_plan(now_tehran())
    print(json.dumps(plan, ensure_ascii=False))
    if args.github_output:
        write_github_output(plan, args.github_output)


def cmd_claim(args):
    out = claim_slot(args.run_key, args.cycle, args.ttl_min)
    print(json.dumps(out, ensure_ascii=False))
    if args.github_output:
        write_github_output(out, args.github_output)
    if out.get("claimed") == "ERROR":
        raise SystemExit(3)


def cmd_mark(args):
    out = mark_done(args.run_key, args.cycle, args.lease_token, args.source)
    print(json.dumps(out, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="ATLAS self-healing scheduler with atomic Supabase lease")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("plan")
    a.add_argument("--manual", choices=["HOURLY", "DEEP4H", "DAILY16", "NIGHTLY23"])
    a.add_argument("--github-output")

    c = sub.add_parser("claim")
    c.add_argument("--run-key", required=True)
    c.add_argument("--cycle", required=True, choices=["HOURLY", "DEEP4H", "DAILY16", "NIGHTLY23"])
    c.add_argument("--ttl-min", type=int, default=DEFAULT_LEASE_MIN)
    c.add_argument("--github-output")

    m = sub.add_parser("mark")
    m.add_argument("--run-key", required=True)
    m.add_argument("--cycle", required=True, choices=["HOURLY", "DEEP4H", "DAILY16", "NIGHTLY23"])
    m.add_argument("--lease-token", required=True)
    m.add_argument("--source", default="self-healing")

    args = p.parse_args()
    if args.cmd == "plan":
        cmd_plan(args)
    elif args.cmd == "claim":
        cmd_claim(args)
    else:
        cmd_mark(args)


if __name__ == "__main__":
    main()
