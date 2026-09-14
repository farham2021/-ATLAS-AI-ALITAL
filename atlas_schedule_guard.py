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
DEEP_HOURS = (0, 4, 8, 12, 20)
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
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:1000]
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


def _key_date(run_key: str) -> str:
    parts = run_key.split(":")
    if len(parts) < 2 or not parts[1]:
        return now_tehran().date().isoformat()
    return parts[1]


def fetch_row(run_key: str):
    q = urllib.parse.quote(run_key, safe="")
    _, rows = _request(
        "GET",
        f"/rest/v1/{TABLE}?run_key=eq.{q}&select=*&limit=1",
    )
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
    try:
        state = classify_row(fetch_row(run_key))
        if state in ("DONE", "RUNNING"):
            return True
        return False
    except Exception as e:
        print(f"::warning::ATLAS scheduler state unavailable: {e}")
        return None


def _rpc_row(name: str, payload: dict):
    _, data = _request("POST", f"/rest/v1/rpc/{name}", payload)
    if isinstance(data, list):
        if not data:
            raise RuntimeError(f"{name} returned an empty result")
        row = data[0]
    elif isinstance(data, dict):
        row = data
    else:
        raise RuntimeError(f"{name} returned unexpected payload: {data!r}")
    if not isinstance(row, dict):
        raise RuntimeError(f"{name} returned non-object row: {row!r}")
    return row


def claim_slot(run_key: str, cycle: str, ttl_min: int):
    try:
        row = _rpc_row(
            "atlas_scheduler_claim",
            {
                "p_run_key": run_key,
                "p_cycle": cycle,
                "p_tehran_date": _key_date(run_key),
                "p_ttl_min": max(5, int(ttl_min)),
            },
        )
        out = {
            "claimed": str(row.get("claimed") or "ERROR").upper(),
            "detail": str(row.get("detail") or ""),
            "lease_token": str(row.get("lease_token") or ""),
        }
        if out["claimed"] not in {"CLAIMED", "DONE", "LOCKED", "ERROR"}:
            return {"claimed": "ERROR", "detail": f"unexpected claim state: {out['claimed']}", "lease_token": ""}
        return out
    except Exception as e:
        return {"claimed": "ERROR", "detail": str(e), "lease_token": ""}


def mark_done(run_key: str, cycle: str, lease_token: str, source: str):
    row = _rpc_row(
        "atlas_scheduler_mark_done",
        {
            "p_run_key": run_key,
            "p_cycle": cycle,
            "p_lease_token": lease_token,
            "p_source": source,
        },
    )
    return {"result": str(row.get("result") or "ERROR").upper(), "detail": str(row.get("detail") or "")}


def force_done(run_key: str, cycle: str, source: str):
    payload = {
        "run_key": run_key,
        "cycle": cycle,
        "tehran_date": _key_date(run_key),
        "source": source or "fail-open",
        "status": "DONE",
        "lease_until": None,
        "lease_token": None,
        "completed_at": now_utc().isoformat(),
    }
    _request(
        "POST",
        f"/rest/v1/{TABLE}?on_conflict=run_key",
        payload,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    return {"result": "MARKED", "detail": "fail-open force done"}


def _plan(mode: str, run_key: str, reason: str, scheduled: bool = True):
    return {"mode": mode, "run_key": run_key, "reason": reason, "scheduled": "1" if scheduled else "0"}


def _latest_deep_slot(dt: datetime):
    candidates = [h for h in DEEP_HOURS if h <= dt.hour]
    if not candidates:
        return None
    h = max(candidates)
    return dt.replace(hour=h, minute=0, second=0, microsecond=0)


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

    deep_dt = _latest_deep_slot(dt)
    if deep_dt is not None:
        deep_key = hour_key("DEEP4H", deep_dt)
        if dt - deep_dt < timedelta(hours=4):
            s = state_getter(deep_key)
            if s is False:
                return _plan("DEEP4H", deep_key, "deep4h_due_or_recovery")
            if s is None:
                return _plan("NONE", "", "deep4h_state_unavailable")

    hourly_key = hour_key("HOURLY", dt)
    s = state_getter(hourly_key)
    if s is False:
        return _plan("HOURLY", hourly_key, "current_hour_slot")
    if s is None:
        return _plan("NONE", "", "hourly_state_unavailable")
    return _plan("NONE", "", "slot_already_done")


def write_github_output(values, path):
    with open(path, "a", encoding="utf-8") as f:
        for key, val in values.items():
            clean = str(val).replace("\r", " ").replace("\n", " ")
            f.write(f"{key}={clean}\n")


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
    if out.get("result") not in {"MARKED", "DONE"}:
        raise SystemExit(4)


def cmd_force_done(args):
    out = force_done(args.run_key, args.cycle, args.source)
    print(json.dumps(out, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="ATLAS 3.11.15 scheduler with RPC lease and fail-open")
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
    f = sub.add_parser("force-done")
    f.add_argument("--run-key", required=True)
    f.add_argument("--cycle", required=True, choices=["HOURLY", "DEEP4H", "DAILY16", "NIGHTLY23"])
    f.add_argument("--source", default="fail-open")
    args = p.parse_args()
    if args.cmd == "plan":
        cmd_plan(args)
    elif args.cmd == "claim":
        cmd_claim(args)
    elif args.cmd == "mark":
        cmd_mark(args)
    else:
        cmd_force_done(args)


if __name__ == "__main__":
    main()
