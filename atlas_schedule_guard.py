from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
TABLE = (os.environ.get("ATLAS_SCHEDULER_TABLE") or "atlas_scheduler_runs").strip()

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
            return json.loads(raw) if raw else {"_ok": True}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Supabase HTTP {e.code}: {err}") from e

def _now_tehran():
    # Test override is intentionally supported for CI/smoke testing only.
    override = (os.environ.get("ATLAS_GUARD_NOW") or "").strip()
    if override:
        dt = datetime.fromisoformat(override)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TEHRAN)
        return dt.astimezone(TEHRAN)
    return datetime.now(TEHRAN)

def run_key(cycle: str, dt=None) -> str:
    dt = dt or _now_tehran()
    return f"{cycle.upper()}:{dt.strftime('%Y-%m-%d')}"

def is_done(cycle: str, dt=None) -> bool:
    key = urllib.parse.quote(run_key(cycle, dt), safe="")
    path = f"/rest/v1/{TABLE}?run_key=eq.{key}&select=run_key&limit=1"
    rows = _request("GET", path)
    return isinstance(rows, list) and bool(rows)

def mark_done(cycle: str, source: str, dt=None):
    dt = dt or _now_tehran()
    row = {
        "run_key": run_key(cycle, dt),
        "cycle": cycle.upper(),
        "tehran_date": dt.strftime("%Y-%m-%d"),
        "source": source,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    return _request(
        "POST",
        f"/rest/v1/{TABLE}?on_conflict=run_key",
        row,
        prefer="resolution=merge-duplicates,return=minimal",
    )

def recovery_target(dt=None) -> str:
    dt = dt or _now_tehran()
    # Several recovery chances during the hour after the intended report time.
    if dt.hour == 16 and dt.minute >= 5:
        return "DAILY16"
    if dt.hour == 23 and dt.minute >= 5:
        return "NIGHTLY23"
    return "NONE"

def cmd_check(cycle: str):
    # Fail closed: if state cannot be checked, do not risk duplicate reports.
    print("false" if is_done(cycle) else "true")

def cmd_detect():
    cycle = recovery_target()
    if cycle == "NONE":
        print("NONE")
        return
    # Fail closed on Supabase error. Multiple cron chances remain within the hour.
    print("NONE" if is_done(cycle) else cycle)

def cmd_mark(cycle: str, source: str):
    mark_done(cycle, source)
    print(run_key(cycle))

def main():
    p = argparse.ArgumentParser(description="ATLAS scheduled report exactly-once guard")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check")
    c.add_argument("cycle", choices=["DAILY16", "NIGHTLY23"])

    d = sub.add_parser("detect")

    m = sub.add_parser("mark")
    m.add_argument("cycle", choices=["DAILY16", "NIGHTLY23"])
    m.add_argument("--source", default="scheduled")

    args = p.parse_args()
    if args.cmd == "check":
        cmd_check(args.cycle)
    elif args.cmd == "detect":
        cmd_detect()
    elif args.cmd == "mark":
        cmd_mark(args.cycle, args.source)

if __name__ == "__main__":
    main()
