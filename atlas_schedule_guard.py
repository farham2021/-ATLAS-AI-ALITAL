from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
TABLE = (os.environ.get("ATLAS_SCHEDULER_TABLE") or "atlas_scheduler_runs").strip()
DEEP_HOURS = {0, 4, 8, 12, 20}
DEFAULT_LEASE_MIN = int(os.environ.get("ATLAS_SCHEDULER_LEASE_MIN", "45") or 45)

# create table if not exists atlas_scheduler_runs (
#   run_key text primary key,
#   cycle text,
#   tehran_date text,
#   source text,
#   status text,
#   lease_until timestamptz,
#   completed_at timestamptz
# );
# Keep RLS enabled. GitHub must use SUPABASE_SERVICE_ROLE_KEY.


def _conf():
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
    return url, key


def _request(method: str, path: str, body=None, prefer=None, ok_statuses=None):
    url, key = _conf()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.status, (json.loads(raw) if raw else {"_ok": True})
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:500]
        if ok_statuses and e.code in ok_statuses:
            return e.code, err
        raise RuntimeError(f"Supabase HTTP {e.code}: {err}") from e


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


def date_from_run_key(run_key: str, dt=None) -> str:
    dt = dt or now_tehran()
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", str(run_key or ""))
    if m:
        return m.group(1)
    return dt.date().isoformat()


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
    q = urllib.parse.quote(run_key, safe="")
    code, rows = _request("GET", f"/rest/v1/{TABLE}?run_key=eq.{q}&select=*&limit=1")
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
    """True=finished, False=needs work, None=unknown."""
    try:
        row = fetch_row(run_key)
        state = classify_row(row)
        if state == "DONE":
            return True
        if state == "RUNNING":
            return True
        return False
    except Exception as e:
        print(f"::warning::ATLAS scheduler state unavailable: {e}")
        return None


def mark_done(run_key: str, cycle: str, source: str):
    key_date = date_from_run_key(run_key)
    row = {
        "run_key": run_key,
        "cycle": cycle,
        "tehran_date": key_date,
        "source": source,
        "status": "DONE",
        "lease_until": None,
        "completed_at": now_utc().isoformat(),
    }
    return _request(
        "POST",
        f"/rest/v1/{TABLE}?on_conflict=run_key",
        row,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def claim_slot(run_key: str, cycle: str, ttl_min: int):
    now = now_utc()
    lease = now + timedelta(minutes=max(5, ttl_min))
    key_date = date_from_run_key(run_key)
    payload = {
        "run_key": run_key,
        "cycle": cycle,
        "tehran_date": key_date,
        "source": "claim",
        "status": "RUNNING",
        "lease_until": lease.isoformat(),
        "completed_at": None,
    }

    try:
        row = fetch_row(run_key)
    except Exception as e:
        return {"claimed": "ERROR", "detail": str(e)}

    state = classify_row(row, now)
    if state == "DONE":
        return {"claimed": "DONE", "detail": "already completed"}
    if state == "RUNNING":
        return {"claimed": "LOCKED", "detail": f"lease until {row.get('lease_until')}"}

    if state == "MISSING":
        try:
            _request(
                "POST",
                f"/rest/v1/{TABLE}",
                payload,
                prefer="return=minimal",
                ok_statuses=(),
            )
            return {"claimed": "CLAIMED", "detail": "inserted RUNNING"}
        except RuntimeError as e:
            if "HTTP 409" in str(e) or "HTTP 23505" in str(e):
                row = fetch_row(run_key)
                state = classify_row(row, now)
                if state == "DONE":
                    return {"claimed": "DONE", "detail": "lost race to DONE"}
                if state == "RUNNING":
                    return {"claimed": "LOCKED", "detail": "lost race to RUNNING"}
            return {"claimed": "ERROR", "detail": str(e)}

    # EXPIRED: take over the same row.
    q = urllib.parse.quote(run_key, safe="")
    try:
        _request(
            "PATCH",
            f"/rest/v1/{TABLE}?run_key=eq.{q}&or=(status.eq.RUNNING,status.is.null)",
            {
                "status": "RUNNING",
                "source": "claim-reap",
                "lease_until": lease.isoformat(),
                "completed_at": None,
            },
            prefer="return=minimal",
        )
        return {"claimed": "CLAIMED", "detail": "reaped expired lease"}
    except Exception as e:
        return {"claimed": "ERROR", "detail": str(e)}


def _plan(mode: str, run_key: str, reason: str, scheduled: bool = True):
    return {
        "mode": mode,
        "run_key": run_key,
        "reason": reason,
        "scheduled": "1" if scheduled else "0",
    }


def choose_plan(dt: datetime, state_getter=remote_done):
    dt = dt.astimezone(TEHRAN)
    today = dt.date()

    today_daily = day_key("DAILY16", today)
    today_nightly = day_key("NIGHTLY23", today)

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

    if dt.hour == 16:
        desired, key = "DAILY16", today_daily
    elif dt.hour == 23:
        desired, key = "NIGHTLY23", today_nightly
    elif dt.hour in DEEP_HOURS:
        desired, key = "DEEP4H", hour_key("DEEP4H", dt)
    else:
        desired, key = "HOURLY", hour_key("HOURLY", dt)

    s = state_getter(key)
    if s is False:
        return _plan(desired, key, "current_hour_slot")
    if s is None:
        return _plan("NONE", "", "regular_slot_state_unavailable")
    return _plan("NONE", "", "slot_already_done")


def write_github_output(values, path):
    with open(path, "a", encoding="utf-8") as f:
        for key, val in values.items():
            f.write(f"{key}={val}\n")


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


def cmd_mark(args):
    mark_done(args.run_key, args.cycle, args.source)
    print(args.run_key)


def main():
    p = argparse.ArgumentParser(description="ATLAS self-healing scheduler with lease")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("plan")
    a.add_argument("--manual", choices=["HOURLY", "DEEP4H", "DAILY16", "NIGHTLY23"])
    a.add_argument("--github-output")

    c = sub.add_parser("claim")
    c.add_argument("--run-key", required=True)
    c.add_argument("--cycle", required=True, choices=["DAILY16", "NIGHTLY23"])
    c.add_argument("--ttl-min", type=int, default=DEFAULT_LEASE_MIN)
    c.add_argument("--github-output")

    m = sub.add_parser("mark")
    m.add_argument("--run-key", required=True)
    m.add_argument("--cycle", required=True, choices=["HOURLY", "DEEP4H", "DAILY16", "NIGHTLY23"])
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
