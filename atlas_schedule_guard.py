from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
TABLE = (os.environ.get("ATLAS_SCHEDULER_TABLE") or "atlas_scheduler_runs").strip()
DEEP_HOURS = {0, 4, 8, 12, 20}


def _conf():
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
    return url, key


def _request(method: str, path: str, body=None, prefer=None):
    url, key = _conf()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"_ok": True}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Supabase HTTP {e.code}: {err}") from e


def now_tehran():
    override = (os.environ.get("ATLAS_GUARD_NOW") or "").strip()
    if override:
        dt = datetime.fromisoformat(override)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TEHRAN)
        return dt.astimezone(TEHRAN)
    return datetime.now(TEHRAN)


def day_key(cycle: str, day) -> str:
    return f"{cycle}:{day.isoformat()}"


def hour_key(cycle: str, dt: datetime) -> str:
    return f"{cycle}:{dt.strftime('%Y-%m-%d:%H')}"


def remote_done(run_key: str):
    try:
        q = urllib.parse.quote(run_key, safe="")
        rows = _request("GET", f"/rest/v1/{TABLE}?run_key=eq.{q}&select=run_key&limit=1")
        if not isinstance(rows, list):
            return None
        return bool(rows)
    except Exception as e:
        print(f"::warning::ATLAS scheduler state unavailable: {e}")
        return None


def mark_done(run_key: str, cycle: str, source: str):
    dt = now_tehran()
    parts = run_key.split(":")
    key_date = parts[1] if len(parts) >= 2 else dt.date().isoformat()
    row = {
        "run_key": run_key,
        "cycle": cycle,
        "tehran_date": key_date,
        "source": source,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    return _request(
        "POST",
        f"/rest/v1/{TABLE}?on_conflict=run_key",
        row,
        prefer="resolution=merge-duplicates,return=minimal",
    )


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
        desired = "DAILY16"
        key = today_daily
    elif dt.hour == 23:
        desired = "NIGHTLY23"
        key = today_nightly
    elif dt.hour in DEEP_HOURS:
        desired = "DEEP4H"
        key = hour_key(desired, dt)
    else:
        desired = "HOURLY"
        key = hour_key(desired, dt)

    s = state_getter(key)
    if s is False:
        return _plan(desired, key, "current_hour_slot")
    if s is None:
        return _plan("NONE", "", "regular_slot_state_unavailable")
    return _plan("NONE", "", "slot_already_done")


def write_github_output(plan, path):
    with open(path, "a", encoding="utf-8") as f:
        for key in ("mode", "run_key", "reason", "scheduled"):
            f.write(f"{key}={plan.get(key, '')}\n")


def cmd_plan(args):
    if args.manual:
        plan = _plan(args.manual, "", "manual_dispatch", scheduled=False)
    else:
        plan = choose_plan(now_tehran())
    print(json.dumps(plan, ensure_ascii=False))
    if args.github_output:
        write_github_output(plan, args.github_output)


def cmd_mark(args):
    mark_done(args.run_key, args.cycle, args.source)
    print(args.run_key)


def main():
    p = argparse.ArgumentParser(description="ATLAS self-healing scheduler")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("plan")
    a.add_argument("--manual", choices=["HOURLY", "DEEP4H", "DAILY16", "NIGHTLY23"])
    a.add_argument("--github-output")

    m = sub.add_parser("mark")
    m.add_argument("--run-key", required=True)
    m.add_argument("--cycle", required=True, choices=["HOURLY", "DEEP4H", "DAILY16", "NIGHTLY23"])
    m.add_argument("--source", default="self-healing")

    args = p.parse_args()
    if args.cmd == "plan":
        cmd_plan(args)
    else:
        cmd_mark(args)


if __name__ == "__main__":
    main()
