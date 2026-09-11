# ============================================================
# ATLAS Desk v1.2 — multi-user personal desk
#
# Flow:
#   1) New member joins the Telegram supergroup
#      -> welcome in the group, pointing them to private chat
#   2) User opens the bot in private chat, sends /start
#   3) User sends /capital 4000  (USDT / USD)
#   4) Daily (always) and hourly (only if a new ENTRY exists)
#      each user gets their own sized entry/exit card in DM
#
# Persistence: Supabase primary (GitHub runners are ephemeral).
# SQLite is only an in-run cache.
# Does not place orders. Does not rewrite Entry/SL/TP math.
#
# Create this table once in Supabase:
#   create table if not exists atlas_desk_users (
#     user_id text primary key,
#     chat_id text,
#     username text,
#     first_name text,
#     equity_usdt double precision,
#     seen_in_group boolean default false,
#     dm_started boolean default false,
#     hourly_on boolean default true,
#     welcomed_at timestamptz,
#     updated_at timestamptz,
#     created_at timestamptz default now()
#   );
#   create table if not exists atlas_desk_meta (
#     key text primary key,
#     value text,
#     updated_at timestamptz
#   );
# ============================================================

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
DESK_DB = os.environ.get("ATLAS_DESK_SQLITE", "atlas_desk.sqlite3")
DESK_VERSION = "ATLAS Desk v1.2"
SUPABASE_TABLE_USERS = "atlas_desk_users"
SUPABASE_TABLE_META = "atlas_desk_meta"
SUPABASE_TABLE_DELIVERIES = "atlas_desk_deliveries"

EXECUTABLE = {"BUY CONFIRMATION", "SELL CONFIRMATION"}
DEFAULT_PERSONAL = (
    "BTC", "ETH", "BNB", "XRP", "SOL", "TRX", "DOGE", "ADA", "LINK",
    "XLM", "SUI", "AVAX", "LTC", "SHIB", "HBAR", "DOT", "BCH", "XMR",
    "NEAR", "ONDO", "TAO", "ZEC",
)

_CAPITAL_RE = re.compile(
    r"(?i)^\s*(?:/)?(?:capital|equity|cap|deskcapital|سرمایه|موجودی)\s+"
    r"([0-9]+(?:[.,][0-9]+)?)\s*(k|usdt|usd|tether|dollar|دلار|تتر)?\s*$"
)
_STATUS_RE = re.compile(r"(?i)^\s*(?:/)?(?:desk|status|میز|وضعیت)\s*$")
_HELP_RE = re.compile(r"(?i)^\s*(?:/)?(?:start|help|راهنما)(?:@\w+)?(?:\s+desk)?\s*$")
_HOURLY_ON_RE = re.compile(r"(?i)^\s*(?:/)?(?:hourlyon|ساعتی_روشن)\s*$")
_HOURLY_OFF_RE = re.compile(r"(?i)^\s*(?:/)?(?:hourlyoff|ساعتی_خاموش)\s*$")


def _parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _f(x, default=None):
    try:
        if x is None or isinstance(x, bool):
            return default
        v = float(str(x).replace(",", ""))
        return v if math.isfinite(v) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _now_utc():
    return datetime.now(timezone.utc)


def _now_tehran():
    return datetime.now(TEHRAN)


def desk_enabled():
    return _parse_bool(os.environ.get("ATLAS_DESK_ENABLED", "1"), True)


def risk_pct():
    return max(0.1, min(5.0, _f(os.environ.get("ATLAS_DESK_RISK_PCT"), 1.5) or 1.5))


def group_chat_id():
    return str(os.environ.get("TELEGRAM_GROUP_CHAT_ID", "") or "").strip()


def personal_universe(extra=None):
    raw = os.environ.get("ATLAS_DESK_SYMBOLS", "").strip()
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()] if raw else list(DEFAULT_PERSONAL)
    for s in extra or []:
        u = str(s).upper()
        if u and u not in symbols and u not in {"USDT", "USDC", "DAI"}:
            symbols.append(u)
    return symbols


# ---------- SQLite cache ----------

def _conn():
    c = sqlite3.connect(DESK_DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_desk_db():
    with _conn() as c:
        c.executescript(
            """
            create table if not exists desk_users(
                user_id text primary key,
                chat_id text,
                username text,
                first_name text,
                equity_usdt real,
                seen_in_group integer default 0,
                dm_started integer default 0,
                hourly_on integer default 1,
                welcomed_at text,
                updated_at text
            );
            create table if not exists desk_meta(
                key text primary key,
                value text
            );
            create table if not exists desk_deliveries(
                delivery_key text primary key,
                user_id text not null,
                signal_hash text,
                delivery_type text not null,
                sent_at text not null
            );
            """
        )


# ---------- Supabase ----------

def _sb_conf():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip() or os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not url or not key:
        return None
    return url, key


def _sb_headers(key):
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_request(method, path, body=None, extra_prefer=None):
    conf = _sb_conf()
    if not conf:
        return None
    url, key = conf
    headers = _sb_headers(key)
    if extra_prefer:
        headers["Prefer"] = extra_prefer
    data = None if body is None else json.dumps(body, ensure_ascii=False, default=str).encode()
    req = urllib.request.Request(url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"_ok": True}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:400]
        print(f"⚠️ Desk Supabase {method} {path} HTTP {e.code}: {err}")
        return None
    except Exception as e:
        print(f"⚠️ Desk Supabase {method} {path}: {e}")
        return None


def sb_get_users():
    rows = _sb_request("GET", f"/rest/v1/{SUPABASE_TABLE_USERS}?select=*")
    return rows if isinstance(rows, list) else []


def sb_upsert_user(row):
    return _sb_request(
        "POST",
        f"/rest/v1/{SUPABASE_TABLE_USERS}?on_conflict=user_id",
        row,
        extra_prefer="resolution=merge-duplicates,return=minimal",
    )


def sb_get_meta(key):
    rows = _sb_request("GET", f"/rest/v1/{SUPABASE_TABLE_META}?key=eq.{urllib.parse.quote(key)}&select=value")
    if not isinstance(rows, list) or not rows:
        return None
    return (rows[0] or {}).get("value")


def sb_set_meta(key, value):
    return _sb_request(
        "POST",
        f"/rest/v1/{SUPABASE_TABLE_META}?on_conflict=key",
        {"key": key, "value": str(value), "updated_at": _now_utc().isoformat()},
        extra_prefer="resolution=merge-duplicates,return=minimal",
    )


def _sb_success(value):
    return value is not None


def _signal_hash(r):
    raw = "|".join(str(x) for x in (
        str(r.get("coin") or "").upper(),
        str(r.get("decision_state") or "").upper(),
        str(r.get("direction") or "").upper(),
        r.get("entry"), r.get("sl"), r.get("tp1"), r.get("tp2"),
        r.get("signal_candle_ts"),
    ))
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _delivery_key(user_id, signal_hash, delivery_type):
    raw = f"{user_id}|{signal_hash}|{delivery_type}"
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def sb_delivery_exists(delivery_key):
    rows = _sb_request(
        "GET",
        f"/rest/v1/{SUPABASE_TABLE_DELIVERIES}?delivery_key=eq.{urllib.parse.quote(delivery_key)}&select=delivery_key&limit=1",
    )
    return isinstance(rows, list) and bool(rows)


def sb_record_delivery(row):
    return _sb_request(
        "POST",
        f"/rest/v1/{SUPABASE_TABLE_DELIVERIES}?on_conflict=delivery_key",
        row,
        extra_prefer="resolution=merge-duplicates,return=minimal",
    )


def delivery_exists(delivery_key):
    if sb_delivery_exists(delivery_key):
        return True
    init_desk_db()
    with _conn() as c:
        row = c.execute(
            "select delivery_key from desk_deliveries where delivery_key=?",
            (delivery_key,),
        ).fetchone()
    return bool(row)


def record_delivery(user_id, signal_hash, delivery_type):
    key = _delivery_key(user_id, signal_hash, delivery_type)
    ts = _now_utc().isoformat()
    remote = sb_record_delivery({
        "delivery_key": key,
        "user_id": str(user_id),
        "signal_hash": str(signal_hash),
        "delivery_type": str(delivery_type),
        "sent_at": ts,
    })
    if not _sb_success(remote):
        return False
    init_desk_db()
    with _conn() as c:
        c.execute(
            "insert or replace into desk_deliveries(delivery_key,user_id,signal_hash,delivery_type,sent_at) values (?,?,?,?,?)",
            (key, str(user_id), str(signal_hash), str(delivery_type), ts),
        )
    return True


# ---------- user store ----------

def _row_from_any(r):
    return {
        "user_id": str(r.get("user_id") or ""),
        "chat_id": str(r.get("chat_id") or r.get("user_id") or ""),
        "username": r.get("username") or "",
        "first_name": r.get("first_name") or "",
        "equity_usdt": _f(r.get("equity_usdt")),
        "seen_in_group": 1 if r.get("seen_in_group") in (True, 1, "1", "t", "true") else 0,
        "dm_started": 1 if r.get("dm_started") in (True, 1, "1", "t", "true") else 0,
        "hourly_on": 0 if r.get("hourly_on") in (False, 0, "0", "f", "false") else 1,
        "welcomed_at": r.get("welcomed_at"),
        "updated_at": r.get("updated_at"),
    }


def load_users():
    init_desk_db()
    remote = sb_get_users()
    users = {}
    for r in remote or []:
        row = _row_from_any(r)
        if row["user_id"]:
            users[row["user_id"]] = row
    with _conn() as c:
        for r in c.execute("select * from desk_users"):
            row = _row_from_any(dict(r))
            if row["user_id"] and row["user_id"] not in users:
                users[row["user_id"]] = row
    return users


def save_user(row):
    """Persist user state remotely first; SQLite is only a mirror.

    A user-facing success acknowledgement must never be based only on the
    ephemeral GitHub runner filesystem.
    """
    init_desk_db()
    row = _row_from_any(row)
    row["updated_at"] = _now_utc().isoformat()
    remote = {
        "user_id": row["user_id"],
        "chat_id": row["chat_id"],
        "username": row["username"],
        "first_name": row["first_name"],
        "equity_usdt": row["equity_usdt"],
        "seen_in_group": bool(row["seen_in_group"]),
        "dm_started": bool(row["dm_started"]),
        "hourly_on": bool(row["hourly_on"]),
        "welcomed_at": row["welcomed_at"],
        "updated_at": row["updated_at"],
    }
    result = sb_upsert_user(remote)
    if not _sb_success(result):
        raise RuntimeError("Atlas Desk persistent user write failed")

    with _conn() as c:
        c.execute(
            """
            insert into desk_users(user_id,chat_id,username,first_name,equity_usdt,
                seen_in_group,dm_started,hourly_on,welcomed_at,updated_at)
            values (?,?,?,?,?,?,?,?,?,?)
            on conflict(user_id) do update set
                chat_id=excluded.chat_id,
                username=excluded.username,
                first_name=excluded.first_name,
                equity_usdt=excluded.equity_usdt,
                seen_in_group=excluded.seen_in_group,
                dm_started=excluded.dm_started,
                hourly_on=excluded.hourly_on,
                welcomed_at=excluded.welcomed_at,
                updated_at=excluded.updated_at
            """,
            (
                row["user_id"], row["chat_id"], row["username"], row["first_name"],
                row["equity_usdt"], row["seen_in_group"], row["dm_started"],
                row["hourly_on"], row["welcomed_at"], row["updated_at"],
            ),
        )
    return row


def merge_user(user_id, **fields):
    users = load_users()
    cur = users.get(str(user_id), {
        "user_id": str(user_id),
        "chat_id": str(fields.get("chat_id") or user_id),
        "username": "",
        "first_name": "",
        "equity_usdt": None,
        "seen_in_group": 0,
        "dm_started": 0,
        "hourly_on": 1,
        "welcomed_at": None,
    })
    for k, v in fields.items():
        if v is not None:
            cur[k] = v
    return save_user(cur)


# ---------- Telegram API ----------

def _token():
    return os.environ.get("TELEGRAM_TOKEN", "").strip()


def _telegram_get(method, params=None):
    token = _token()
    if not token:
        return None
    q = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"https://api.telegram.org/bot{token}/{method}"
    if q:
        url += "?" + q
    req = urllib.request.Request(url, headers={"User-Agent": "ATLAS-Desk/1.1"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def bot_username():
    cached = sb_get_meta("bot_username")
    if cached:
        return cached.lstrip("@")
    init_desk_db()
    with _conn() as c:
        row = c.execute("select value from desk_meta where key='bot_username'").fetchone()
    if row and row["value"]:
        return row["value"]
    try:
        data = _telegram_get("getMe")
        uname = ((data or {}).get("result") or {}).get("username") or ""
    except Exception:
        uname = ""
    if uname:
        sb_set_meta("bot_username", uname)
        with _conn() as c:
            c.execute(
                "insert or replace into desk_meta(key,value) values ('bot_username',?)",
                (uname,),
            )
    return uname


def get_offset():
    remote = sb_get_meta("telegram_offset")
    if remote and str(remote).isdigit():
        return int(remote)
    init_desk_db()
    with _conn() as c:
        row = c.execute("select value from desk_meta where key='telegram_offset'").fetchone()
    return int(row["value"]) if row and str(row["value"]).isdigit() else 0


def set_offset(n):
    n = int(n)
    result = sb_set_meta("telegram_offset", str(n))
    if not _sb_success(result):
        raise RuntimeError("Atlas Desk persistent Telegram offset write failed")
    init_desk_db()
    with _conn() as c:
        c.execute(
            "insert or replace into desk_meta(key,value) values ('telegram_offset',?)",
            (str(n),),
        )


def parse_capital_text(text):
    text = (text or "").replace("\u200c", " ").strip()
    m = _CAPITAL_RE.match(text)
    if not m:
        return None
    amount = _f(m.group(1).replace(",", "."))
    if amount is None:
        return None
    if (m.group(2) or "").lower() == "k":
        amount *= 1000.0
    return amount


def welcome_text(first_name=""):
    name = (first_name or "دوست").strip()
    uname = bot_username()
    link = f"https://t.me/{uname}?start=desk" if uname else "چت خصوصی همین ربات"
    return (
        f"سلام {name}\n"
        f"به {DESK_VERSION} خوش آمدی.\n\n"
        "سیگنال ورود و خروج اینجا در گروه عمومی نمی‌آید.\n"
        "شخصی است و فقط در چت خصوصی ربات برایت ارسال می‌شود.\n\n"
        "کارهایی که باید بکنی:\n"
        f"۱) ربات را در خصوصی باز کن: {link}\n"
        "۲) بفرست /start\n"
        "۳) سرمایه‌ات را به دلار/تتر بفرست، مثلاً:\n"
        "/capital 4000\n\n"
        "بعد روزانه — و اگر سیگنال ورود جدید باشد ساعتی — "
        "ورود، حد ضرر و حد سود متناسب با سرمایه خودت را می‌گیری.\n"
        "ربات سفارش نمی‌گذارد؛ فقط سیگنال می‌دهد."
    )


def private_help_text():
    return (
        f"{DESK_VERSION}\n"
        "این چت خصوصی میز سرمایه توست.\n\n"
        "ثبت سرمایه (دلار / تتر):\n"
        "/capital 4000\n"
        "یا: سرمایه 2500\n\n"
        "وضعیت: /desk\n"
        "سیگنال ساعتی روشن: /hourlyon\n"
        "سیگنال ساعتی خاموش (فقط روزانه): /hourlyoff\n\n"
        "سیگنال‌ها روی لیست شخصی ATLAS ساخته می‌شوند.\n"
        "WATCH یعنی ورود نکن. خروج = SL یا TP همان سیگنال ورود."
    )


# ---------- ingest ----------

def _is_private(chat):
    return (chat or {}).get("type") == "private"


def _is_target_group(chat):
    cid = str((chat or {}).get("id") or "")
    gid = group_chat_id()
    return bool(gid) and cid == gid


def ingest_telegram_commands(sender=None):
    """Welcome new group members + read private /capital. Safe on GitHub cron."""
    if not desk_enabled():
        return {"welcomes": 0, "commands": 0}
    if not _token():
        return {"welcomes": 0, "commands": 0, "error": "no token"}

    last = get_offset()
    try:
        data = _telegram_get(
            "getUpdates",
            {
                "offset": last + 1,
                "timeout": 0,
                "allowed_updates": json.dumps(
                    ["message", "edited_message", "chat_member", "my_chat_member"]
                ),
            },
        )
    except Exception as e:
        print(f"⚠️ Desk getUpdates failed: {e}")
        return {"welcomes": 0, "commands": 0, "error": str(e)}

    if not data or not data.get("ok"):
        return {"welcomes": 0, "commands": 0}

    welcomes = 0
    commands = 0
    max_id = last
    users = load_users()

    def reply(chat_id, text):
        if not sender or not chat_id or not text:
            return False
        try:
            return bool(sender(str(chat_id), text))
        except Exception as e:
            print(f"⚠️ Desk reply failed: {e}")
            return False

    def welcome_member(member, chat):
        nonlocal welcomes
        if not member or member.get("is_bot"):
            return
        uid = str(member.get("id") or "")
        if not uid:
            return
        existing = users.get(uid, {})
        if existing.get("welcomed_at") and existing.get("seen_in_group"):
            merge_user(
                uid,
                seen_in_group=1,
                first_name=member.get("first_name") or existing.get("first_name"),
                username=member.get("username") or existing.get("username"),
            )
            return
        row = merge_user(
            uid,
            chat_id=existing.get("chat_id") or uid,
            first_name=member.get("first_name") or "",
            username=member.get("username") or "",
            seen_in_group=1,
            welcomed_at=_now_utc().isoformat(),
            dm_started=existing.get("dm_started") or 0,
            equity_usdt=existing.get("equity_usdt"),
            hourly_on=existing.get("hourly_on", 1),
        )
        users[uid] = row
        if reply(chat.get("id"), welcome_text(member.get("first_name") or "")):
            welcomes += 1

    for upd in data.get("result") or []:
        uid_upd = int(upd.get("update_id") or 0)
        if uid_upd > max_id:
            max_id = uid_upd

        cm = upd.get("chat_member")
        if cm and _is_target_group(cm.get("chat") or {}):
            new_s = ((cm.get("new_chat_member") or {}).get("status") or "")
            if new_s in ("member", "administrator", "restricted"):
                welcome_member((cm.get("new_chat_member") or {}).get("user") or {}, cm.get("chat") or {})

        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if not chat:
            continue

        for member in msg.get("new_chat_members") or []:
            if _is_target_group(chat):
                welcome_member(member, chat)

        text = (msg.get("text") or "").strip()
        from_user = msg.get("from") or {}
        if from_user.get("is_bot") or not text:
            continue
        user_id = str(from_user.get("id") or "")
        if not user_id:
            continue

        # Private desk commands only. Group stays welcome-only.
        if not _is_private(chat):
            if text.startswith("/start") and _is_target_group(chat):
                reply(chat.get("id"), welcome_text(from_user.get("first_name") or ""))
            continue

        commands += 1
        existing = users.get(user_id, {})
        merge_user(
            user_id,
            chat_id=str(chat.get("id") or user_id),
            first_name=from_user.get("first_name") or existing.get("first_name") or "",
            username=from_user.get("username") or existing.get("username") or "",
            dm_started=1,
            seen_in_group=existing.get("seen_in_group") or 0,
            equity_usdt=existing.get("equity_usdt"),
            hourly_on=existing.get("hourly_on", 1),
            welcomed_at=existing.get("welcomed_at"),
        )
        users = load_users()
        me = users.get(user_id, {})

        amount = parse_capital_text(text)
        if amount is not None:
            if amount < 50:
                reply(chat.get("id"), "حداقل سرمایه ۵۰ USDT است.")
            elif amount > 10_000_000:
                reply(chat.get("id"), "عدد سرمایه غیرمنطقی است. مقدار را به دلار/تتر بفرست.")
            else:
                merge_user(user_id, equity_usdt=round(amount, 2), dm_started=1, chat_id=str(chat.get("id")))
                risk_usd = amount * risk_pct() / 100.0
                note = ""
                if not me.get("seen_in_group") and group_chat_id():
                    note = "\nاگر عضو سوپرگروه هستی، سیگنال‌ها از سیکل بعدی می‌آید."
                reply(
                    chat.get("id"),
                    f"✅ سرمایه تو ثبت شد: {amount:,.2f} USDT\n"
                    f"ریسک هر معامله: {risk_pct():.2f}% = {risk_usd:,.2f} USDT\n"
                    "سیگنال ورود/خروج از این به بعد با همین عدد سایز می‌شود."
                    + note,
                )
        elif _STATUS_RE.match(text):
            eq = _f(me.get("equity_usdt"))
            if not eq:
                reply(chat.get("id"), "هنوز سرمایه نداری.\nبفرست: /capital 4000")
            else:
                reply(
                    chat.get("id"),
                    f"{DESK_VERSION}\n"
                    f"سرمایه تو: {eq:,.2f} USDT\n"
                    f"ریسک هر معامله: {risk_pct():.2f}% = {eq * risk_pct() / 100.0:,.2f} USDT\n"
                    f"سیگنال ساعتی: {'روشن' if me.get('hourly_on', 1) else 'خاموش'}\n"
                    f"عضو گروه: {'بله' if me.get('seen_in_group') else 'هنوز دیده نشد'}",
                )
        elif _HOURLY_ON_RE.match(text):
            merge_user(user_id, hourly_on=1)
            reply(chat.get("id"), "سیگنال ساعتی روشن شد. فقط وقتی ورود قطعی باشد پیام می‌آید.")
        elif _HOURLY_OFF_RE.match(text):
            merge_user(user_id, hourly_on=0)
            reply(chat.get("id"), "سیگنال ساعتی خاموش شد. فقط گزارش روزانه می‌آید.")
        elif _HELP_RE.match(text) or text.startswith("/start"):
            reply(chat.get("id"), private_help_text())

    if max_id > last:
        set_offset(max_id)
    print(f"💼 Desk ingest: updates={len(data.get('result') or [])} welcomes={welcomes} commands={commands}")
    return {"welcomes": welcomes, "commands": commands}


# ---------- sizing + cards ----------

def size_for_capital(entry, sl, equity, risk):
    entry, sl, equity = _f(entry), _f(sl), _f(equity)
    if not entry or not sl or not equity or entry <= 0 or sl <= 0 or equity <= 0:
        return None
    stop = abs(entry - sl)
    if stop / entry < 0.0015:
        return None
    risk_usd = equity * (risk / 100.0)
    qty = risk_usd / stop
    notional = qty * entry
    if notional > equity:
        qty = equity / entry
        notional = qty * entry
        risk_usd = qty * stop
    return {
        "qty": qty,
        "notional": notional,
        "risk_usd": risk_usd,
        "risk_pct": (risk_usd / equity) * 100.0,
    }


def _fmt_px(x):
    x = _f(x)
    if x is None:
        return "—"
    if abs(x) >= 1000:
        return f"{x:,.2f}"
    if abs(x) >= 1:
        return f"{x:,.4f}"
    return f"{x:.6f}"


def _fmt_qty(x):
    x = _f(x)
    if x is None:
        return "—"
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:,.4f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")


def classify(r):
    state = str(r.get("decision_state") or r.get("action") or "").upper()
    if state in EXECUTABLE and not r.get("repeat_signal") and str(r.get("gate") or "PASS") in ("PASS", "", "None"):
        return "ENTRY"
    if "WATCH" in state or state in EXECUTABLE:
        return "WATCH"
    return "NO"


def build_entry_card(r, equity, risk):
    coin = str(r.get("coin") or "").upper()
    side = "خرید / LONG" if str(r.get("direction") or "").upper() == "LONG" else "فروش / SHORT"
    sized = size_for_capital(r.get("entry"), r.get("sl"), equity, risk)
    lines = [
        f"📌 ورود {coin}",
        f"جهت: {side}",
        f"قیمت ورود: {_fmt_px(r.get('entry'))} USDT",
        f"خروج ضرر (SL): {_fmt_px(r.get('sl'))} USDT",
        f"خروج سود ۱ (TP1): {_fmt_px(r.get('tp1'))} USDT",
    ]
    if _f(r.get("tp2")):
        lines.append(f"خروج سود ۲ (TP2): {_fmt_px(r.get('tp2'))} USDT")
    if sized:
        lines += [
            f"مقدار برای تو: {_fmt_qty(sized['qty'])} {coin}",
            f"ارزش حدودی: {sized['notional']:,.2f} USDT",
            f"ریسک این معامله: {sized['risk_usd']:,.2f} USDT ({sized['risk_pct']:.2f}%)",
        ]
    else:
        lines.append("مقدار قابل محاسبه نبود.")
    bits = []
    if _f(r.get("rr")) is not None:
        bits.append(f"R/R {_f(r.get('rr')):.2f}")
    if _f(r.get("confidence")) is not None:
        bits.append(f"اعتماد {_f(r.get('confidence')):.0f}")
    if bits:
        lines.append(" | ".join(bits))
    lines.append("سفارش خودکار نیست. اگر قبول داری خودت در صرافی بگذار.")
    return "\n".join(lines)


def build_watch_line(r):
    coin = str(r.get("coin") or "").upper()
    return f"• {coin}: ورود نکن — {r.get('decision_state') or 'WATCH'} @ {_fmt_px(r.get('price') or r.get('entry'))}"


def split_results(results, personal_symbols=None):
    universe = set(personal_universe(personal_symbols))
    entries, watches = [], []
    for r in results or []:
        coin = str(r.get("coin") or "").upper()
        if coin not in universe:
            continue
        kind = classify(r)
        if kind == "ENTRY":
            entries.append(r)
        elif kind == "WATCH":
            watches.append(r)
    return entries, watches


def build_user_report(user, entries, watches, kind="daily"):
    equity = _f(user.get("equity_usdt"))
    name = user.get("first_name") or "تریدر"
    risk = risk_pct()
    title = "گزارش روزانه" if kind == "daily" else "سیگنال جدید ساعتی"
    lines = [
        f"💼 {DESK_VERSION} | {title}",
        f"سلام {name}",
        f"{_now_tehran().strftime('%Y-%m-%d %H:%M')} تهران",
        f"سرمایه تو: {equity:,.2f} USDT",
        f"ریسک هر معامله: {risk:.2f}% = {equity * risk / 100.0:,.2f} USDT",
        "",
    ]
    if entries:
        lines.append("=== سیگنال ورود + خروج ===")
        for r in entries:
            lines.append(build_entry_card(r, equity, risk))
            lines.append("")
    else:
        lines.append("الان سیگنال ورود قطعی در لیست شخصی نیست.")
        lines.append("")
    if watches and kind == "daily":
        lines.append("=== فقط مراقبت؛ ورود نکن ===")
        for r in watches[:12]:
            lines.append(build_watch_line(r))
        lines.append("")
    lines.append("خروج = رسیدن قیمت به SL یا TP همین سیگنال.")
    return "\n".join(lines).strip()


def eligible_subscribers(users, require_group=True):
    out = []
    for u in users.values():
        if not u.get("dm_started"):
            continue
        if not _f(u.get("equity_usdt")):
            continue
        if require_group and group_chat_id() and not u.get("seen_in_group"):
            continue
        if not u.get("chat_id"):
            continue
        out.append(u)
    return out


def current_cycle():
    if _parse_bool(os.environ.get("ATLAS_PHASE37_DAILY_REPORT", "0")):
        return "daily"
    if _parse_bool(os.environ.get("ATLAS_PHASE39_NIGHTLY_REPORT", "0")):
        return "nightly"
    if _parse_bool(os.environ.get("ATLAS_PHASE37_DEEP_4H", "0")):
        return "deep"
    return "hourly"


def should_push(cycle, user, has_entries):
    if cycle == "daily":
        return True
    if cycle == "nightly":
        return False
    if not has_entries:
        return False
    if not user.get("hourly_on", 1):
        return False
    return _parse_bool(os.environ.get("ATLAS_DESK_HOURLY_PUSH", "1"), True)


def run_desk_cycle(results, personal_symbols=None, sender=None, send_report=True):
    """Multi-user Desk cycle.

    - Ingests welcome/private commands on every cycle.
    - DAILY16: one personal report per user per Tehran day.
    - HOURLY/DEEP: sends only ENTRY signals not previously delivered to that user.
    - NIGHTLY: no Desk push.
    """
    if not desk_enabled():
        print("💼 Atlas Desk disabled")
        return {"enabled": False}

    ingest = ingest_telegram_commands(sender=sender)
    entries, watches = split_results(results, personal_symbols=personal_symbols)
    users = load_users()
    require_group = not _parse_bool(os.environ.get("ATLAS_DESK_ALLOW_DM_ONLY", "0"))
    subs = eligible_subscribers(users, require_group=require_group)
    cycle = current_cycle()

    sent = 0
    skipped = 0
    deduped = 0
    persist_errors = 0

    if send_report and sender:
        for user in subs:
            uid = str(user.get("user_id") or "")
            chat_id = str(user.get("chat_id") or "")
            if not uid or not chat_id:
                skipped += 1
                continue

            # DAILY16: exactly once per Tehran calendar day per user.
            if cycle == "daily":
                day = _now_tehran().strftime("%Y-%m-%d")
                daily_hash = f"DAILY:{day}"
                dkey = _delivery_key(uid, daily_hash, "DAILY")
                if delivery_exists(dkey):
                    deduped += 1
                    continue
                text = build_user_report(user, entries, watches, kind="daily")
                try:
                    if sender(chat_id, text):
                        if record_delivery(uid, daily_hash, "DAILY"):
                            sent += 1
                        else:
                            persist_errors += 1
                except Exception as e:
                    print(f"⚠️ Desk daily push {uid}: {e}")
                continue

            # NIGHTLY23 never sends Desk cards.
            if cycle == "nightly":
                skipped += 1
                continue

            # HOURLY/DEEP: only new canonical ENTRY signals for users with hourly_on.
            if not user.get("hourly_on", 1) or not _parse_bool(os.environ.get("ATLAS_DESK_HOURLY_PUSH", "1"), True):
                skipped += 1
                continue

            new_entries = []
            delivery_rows = []
            for r in entries:
                sh = _signal_hash(r)
                dkey = _delivery_key(uid, sh, "ENTRY")
                if delivery_exists(dkey):
                    deduped += 1
                    continue
                new_entries.append(r)
                delivery_rows.append((sh, dkey))

            if not new_entries:
                skipped += 1
                continue

            text = build_user_report(user, new_entries, [], kind="hourly")
            try:
                if sender(chat_id, text):
                    all_persisted = True
                    for sh, _dkey in delivery_rows:
                        if not record_delivery(uid, sh, "ENTRY"):
                            all_persisted = False
                            persist_errors += 1
                    if all_persisted:
                        sent += 1
            except Exception as e:
                print(f"⚠️ Desk hourly push {uid}: {e}")

    print(
        f"💼 Desk cycle={cycle} users={len(users)} subs={len(subs)} "
        f"entries={len(entries)} sent={sent} skipped={skipped} deduped={deduped} "
        f"persist_errors={persist_errors} ingest={ingest}"
    )
    return {
        "enabled": True,
        "cycle": cycle,
        "ingest": ingest,
        "users": len(users),
        "subscribers": len(subs),
        "entries": len(entries),
        "watches": len(watches),
        "telegram_sent": sent,
        "deduped": deduped,
        "persist_errors": persist_errors,
        "stats": {"entries": len(entries), "watches": len(watches), "equity": None},
    }

