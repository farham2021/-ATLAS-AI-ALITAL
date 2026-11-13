#!/usr/bin/env python3
"""ATLAS opt-in personal alert worker. Read-only market data; idempotent Telegram delivery."""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
NOW = dt.datetime.now(dt.timezone.utc)
TIMEOUT = 15

def request(url, method="GET", payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
        return json.loads(raw) if raw else None

def db(table, query="", method="GET", payload=None, prefer=None):
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    return request(URL + "/rest/v1/" + table + ("?" + query if query else ""), method, payload, headers)

def iso(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))

def deliver(chat_id, text):
    result = request("https://api.telegram.org/bot" + TOKEN + "/sendMessage",
                     "POST", {"chat_id": chat_id, "text": text},
                     {"Content-Type": "application/json"})
    if not result.get("ok"):
        raise RuntimeError("telegram_send_failed")

def main():
    prefs = db("atlas_desk_alert_preferences", "select=user_id,symbol,rise_pct,fall_pct,enabled&enabled=eq.true&limit=500")
    if not prefs:
        print("No opt-in alert preferences; no messages sent")
        return
    users = {u["user_id"]: u for u in db("atlas_desk_users", "select=user_id,chat_id,dm_started&limit=1000")}
    languages = {u["user_id"]: u["language"] for u in db("atlas_desk_language_preferences", "select=user_id,language&limit=1000")}
    memberships = {u["user_id"]: u for u in db("atlas_desk_memberships", "select=user_id,status,expires_at&limit=1000")}
    symbols = sorted({p["symbol"] for p in prefs})
    sent = 0
    for symbol in symbols:
        sym = urllib.parse.quote(symbol, safe="")
        # 1-hour change between two actual market snapshots; do not extrapolate from stale records.
        rows = db("atlas_market_snapshots", "select=symbol,price,captured_at&symbol=eq." + sym + "&order=captured_at.desc&limit=180")
        if len(rows) < 2:
            rows = db("atlas_hourly_signal_snapshots", "select=symbol,price,captured_at&symbol=eq." + sym + "&order=captured_at.desc&limit=180")
        if len(rows) < 2:
            continue
        current = rows[0]
        try:
            latest = iso(current["captured_at"])
            if NOW - latest > dt.timedelta(minutes=100):
                continue
            old = next((r for r in rows[1:] if dt.timedelta(minutes=45) <= latest-iso(r["captured_at"]) <= dt.timedelta(minutes=90)), None)
            if not old:
                continue
            price, prior = float(current["price"]), float(old["price"])
            if price <= 0 or prior <= 0:
                continue
            change = 100 * (price / prior - 1)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        for pref in (p for p in prefs if p["symbol"] == symbol):
            uid = pref["user_id"]
            user = users.get(uid)
            member = memberships.get(uid, {})
            if not user or not user.get("dm_started") or not user.get("chat_id"):
                continue
            if member.get("status") in ("blocked", "expired"):
                continue
            if member.get("expires_at") and iso(member["expires_at"]) < NOW:
                continue
            direction = "rise" if change > 0 else "fall"
            threshold = pref.get("rise_pct" if change > 0 else "fall_pct")
            if threshold is None or abs(change) < float(threshold):
                continue
            # Cooldown prevents repeated notifications while threshold remains crossed.
            recent = db("atlas_desk_alert_deliveries",
                        "select=id&user_id=eq." + urllib.parse.quote(uid, safe="") +
                        "&symbol=eq." + sym + "&direction=eq." + direction +
                        "&status=eq.sent&source_timestamp=gte." +
                        urllib.parse.quote((NOW - dt.timedelta(hours=4)).isoformat(), safe="") + "&limit=1")
            if recent:
                continue
            payload = {"user_id": uid, "symbol": symbol, "direction": direction,
                       "source_timestamp": current["captured_at"], "pct_change": round(change, 5),
                       "threshold_pct": float(threshold), "status": "pending"}
            # Conflict-safe claim; only the first worker sends.
            claim = db("atlas_desk_alert_deliveries", "on_conflict=user_id,symbol,direction,source_timestamp",
                       "POST", payload, "resolution=ignore-duplicates,return=representation")
            if not claim:
                continue
            delivery_id = claim[0]["id"]
            en = languages.get(uid) == "en"
            text = (f"ATLAS {'RISE' if change>0 else 'FALL'} ALERT\n{symbol}: {change:+.2f}% / 1h\n"
                    f"Last price: {price:g}\nThreshold: {threshold}%\nSnapshot: {latest.isoformat()}\n"
                    "Stored market data; not a trade instruction.") if en else (
                    f"هشدار {'صعود' if change>0 else 'ریزش'} ATLAS\n{symbol}: {change:+.2f}٪ در یک ساعت\n"
                    f"آخرین قیمت: {price:g}\nآستانه: {threshold}٪\nزمان داده: {latest.isoformat()}\n"
                    "بر اساس داده ذخیره‌شده؛ دستور معامله نیست.")
            try:
                deliver(user["chat_id"], text)
                db("atlas_desk_alert_deliveries", "id=eq." + str(delivery_id), "PATCH",
                   {"status": "sent", "attempted_at": NOW.isoformat(), "delivered_at": dt.datetime.now(dt.timezone.utc).isoformat()})
                sent += 1
            except Exception as e:
                db("atlas_desk_alert_deliveries", "id=eq." + str(delivery_id), "PATCH",
                   {"status": "failed", "attempted_at": NOW.isoformat(), "error_message": type(e).__name__[:120]})
                print(f"Delivery failed for {symbol}: {type(e).__name__}", file=sys.stderr)
    print(f"Alert worker finished: {sent} successful Telegram API sends")

if __name__ == "__main__":
    main()
