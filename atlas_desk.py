# ============================================================
# ATLAS Desk v1.4 — multi-user desk + personal holdings
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
#   create table if not exists atlas_desk_holdings (
#     user_id text not null,
#     coin text not null,
#     qty double precision not null default 0,
#     updated_at timestamptz,
#     primary key (user_id, coin)
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
DESK_VERSION = "ATLAS Desk v1.4"
SUPABASE_TABLE_USERS = os.environ.get("ATLAS_DESK_USERS_TABLE", "atlas_desk_users").strip() or "atlas_desk_users"
SUPABASE_TABLE_META = os.environ.get("ATLAS_DESK_META_TABLE", "atlas_desk_meta").strip() or "atlas_desk_meta"
SUPABASE_TABLE_DELIVERIES = os.environ.get("ATLAS_DESK_DELIVERY_TABLE", "atlas_desk_deliveries").strip() or "atlas_desk_deliveries"
SUPABASE_TABLE_HOLDINGS = os.environ.get("ATLAS_DESK_HOLDINGS_TABLE", "atlas_desk_holdings").strip() or "atlas_desk_holdings"

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
_HOLD_RE = re.compile(
    r"(?i)^\s*(?:/)?(?:hold|دارایی)\s+([A-Za-z]{2,10})\s+([0-9]+(?:[.,][0-9]+)?)\s*$"
)
_UNHOLD_RE = re.compile(
    r"(?i)^\s*(?:/)?(?:unhold|حذف)\s+([A-Za-z]{2,10})\s*$"
)
_PORT_RE = re.compile(r"(?i)^\s*(?:/)?(?:portfolio|holds|bag|سبد|داراییها|دارایی‌ها)\s*$")


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
            create table if not exists desk_holdings(
                user_id text not null,
                coin text not null,
                qty real not null default 0,
                updated_at text,
                primary key(user_id, coin)
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
    """Stable identity for one canonical signal event."""
    raw = "|".join(str(x) for x in (
        str(r.get("coin") or "").upper(),
        str(r.get("decision_state") or "").upper(),
        str(r.get("direction") or "").upper(),
        r.get("signal_candle_ts"),
    ))
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _signal_level_hash(r):
    """Fingerprint current Entry/SL/TP geometry for update notifications."""
    base = _signal_hash(r)
    raw = "|".join(str(x) for x in (
        base, r.get("entry"), r.get("sl"), r.get("tp1"), r.get("tp2"),
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


def _norm_coin(coin):
    return str(coin or "").strip().upper().replace("/USDT", "").replace("USDT", "")


def sb_get_holdings(user_id=None):
    """Return list on successful Supabase read, None on read failure."""
    path = f"/rest/v1/{SUPABASE_TABLE_HOLDINGS}?select=user_id,coin,qty"
    if user_id:
        path += f"&user_id=eq.{urllib.parse.quote(str(user_id))}"
    rows = _sb_request("GET", path)
    if rows is None:
        return None
    return rows if isinstance(rows, list) else []


def sb_upsert_holding(row):
    return _sb_request(
        "POST",
        f"/rest/v1/{SUPABASE_TABLE_HOLDINGS}?on_conflict=user_id,coin",
        row,
        extra_prefer="resolution=merge-duplicates,return=minimal",
    )


def sb_delete_holding(user_id, coin):
    path = (
        f"/rest/v1/{SUPABASE_TABLE_HOLDINGS}"
        f"?user_id=eq.{urllib.parse.quote(str(user_id))}"
        f"&coin=eq.{urllib.parse.quote(coin)}"
    )
    return _sb_request("DELETE", path)


def load_all_holdings():
    """user_id -> {COIN: qty}; fail-closed when configured Supabase read fails."""
    init_desk_db()
    out = {}
    remote = sb_get_holdings()
    if remote is None:
        if _sb_conf():
            raise RuntimeError("Atlas Desk holdings read failed; refusing to infer an empty portfolio")
        with _conn() as c:
            rows = [dict(r) for r in c.execute(
                "select user_id,coin,qty from desk_holdings where qty>0"
            )]
    else:
        rows = remote

    for r in rows or []:
        uid = str(r.get("user_id") or "")
        coin = _norm_coin(r.get("coin"))
        qty = _f(r.get("qty"), 0.0) or 0.0
        if not uid or not coin or qty <= 0:
            continue
        out.setdefault(uid, {})[coin] = qty
    return out


def set_holding(user_id, coin, qty):
    coin = _norm_coin(coin)
    qty = _f(qty, 0.0) or 0.0
    if not user_id or not coin:
        raise ValueError("invalid holding")
    if qty <= 0:
        return delete_holding(user_id, coin)
    ts = _now_utc().isoformat()
    remote = sb_upsert_holding({
        "user_id": str(user_id),
        "coin": coin,
        "qty": qty,
        "updated_at": ts,
    })
    if not _sb_success(remote):
        raise RuntimeError("Atlas Desk persistent holding write failed")
    init_desk_db()
    with _conn() as c:
        c.execute(
            "insert or replace into desk_holdings(user_id,coin,qty,updated_at) values (?,?,?,?)",
            (str(user_id), coin, qty, ts),
        )
    return coin, qty


def delete_holding(user_id, coin):
    coin = _norm_coin(coin)
    remote = sb_delete_holding(user_id, coin)
    if remote is None and _sb_conf():
        raise RuntimeError("Atlas Desk persistent holding delete failed")
    init_desk_db()
    with _conn() as c:
        c.execute("delete from desk_holdings where user_id=? and coin=?", (str(user_id), coin))
    return coin


def format_portfolio(user_id):
    try:
        bag = load_all_holdings().get(str(user_id), {})
    except Exception:
        return (
            "⚠️ فعلاً دسترسی پایدار به سبد ممکن نیست. "
            "هیچ دارایی‌ای حذف یا صفر فرض نشده؛ کمی بعد دوباره /portfolio را بفرست."
        )
    if not bag:
        return "سبد خالی است.\nثبت کن: /hold BTC 0.05"
    lines = ["📦 سبد دارایی تو"]
    for coin in sorted(bag):
        lines.append(f"• {coin}: {_fmt_qty(bag[coin])}")
    lines.append("\nتغییر: /hold ETH 1.2\nحذف: /unhold ETH")
    return "\n".join(lines)


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
        "۴) دارایی‌های فعلی‌ات را ثبت کن، مثلاً:\n"
        "/hold BTC 0.05\n"
        "/hold ETH 1.2\n\n"
        "بعد روزانه — و اگر سیگنال ورود جدید باشد ساعتی — "
        "ورود و خروج متناسب با سرمایه و سبد خودت را می‌گیری.\n"
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
        "سبد دارایی: /portfolio\n"
        "ثبت دارایی: /hold BTC 0.05\n"
        "حذف دارایی: /unhold BTC\n"
        "سیگنال ساعتی روشن: /hourlyon\n"
        "سیگنال ساعتی خاموش (فقط روزانه): /hourlyoff\n\n"
        "سیگنال خروج فقط برای ارزی می‌آید که در سبدت باشد.\n"
        "خرید جدید با سرمایه ثبت‌شده سایز می‌شود.\n"
        "WATCH یعنی ورود نکن. خروج = SL یا TP همان سیگنال."
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
                    "سیگنال ورود با همین سرمایه سایز می‌شود.\n"
                    "دارایی‌هایت را هم ثبت کن: /hold BTC 0.05"
                    + note,
                )
        elif _HOLD_RE.match(text):
            m = _HOLD_RE.match(text)
            coin, raw_qty = _norm_coin(m.group(1)), _f(m.group(2).replace(",", "."))
            allowed = set(personal_universe())
            if coin not in allowed:
                reply(chat.get("id"), f"{coin} در لیست شخصی ATLAS نیست.\nمجاز: {', '.join(DEFAULT_PERSONAL)}")
            elif raw_qty is None:
                reply(chat.get("id"), "مقدار نامعتبر است. مثال: /hold BTC 0.05")
            elif raw_qty <= 0:
                delete_holding(user_id, coin)
                reply(chat.get("id"), f"{coin} از سبد حذف شد.\n{format_portfolio(user_id)}")
            else:
                set_holding(user_id, coin, raw_qty)
                reply(chat.get("id"), f"✅ {coin} ثبت شد: {_fmt_qty(raw_qty)}\n\n{format_portfolio(user_id)}")
        elif _UNHOLD_RE.match(text):
            coin = _norm_coin(_UNHOLD_RE.match(text).group(1))
            delete_holding(user_id, coin)
            reply(chat.get("id"), f"{coin} از سبد حذف شد.\n{format_portfolio(user_id)}")
        elif _PORT_RE.match(text):
            reply(chat.get("id"), format_portfolio(user_id))
        elif _STATUS_RE.match(text):
            eq = _f(me.get("equity_usdt"))
            try:
                bag = load_all_holdings().get(user_id, {})
                bag_status = None
            except Exception:
                bag = {}
                bag_status = "⚠️ وضعیت سبد موقتاً قابل دریافت نیست و صفر فرض نشده است."
            if not eq:
                reply(chat.get("id"), "هنوز سرمایه نداری.\nبفرست: /capital 4000")
            else:
                reply(
                    chat.get("id"),
                    f"{DESK_VERSION}\n"
                    f"سرمایه تو: {eq:,.2f} USDT\n"
                    f"ریسک هر معامله: {risk_pct():.2f}% = {eq * risk_pct() / 100.0:,.2f} USDT\n"
                    + (f"تعداد دارایی ثبت‌شده: {len(bag)}\n" if bag_status is None else bag_status + "\n")
                    + f"سیگنال ساعتی: {'روشن' if me.get('hourly_on', 1) else 'خاموش'}\n"
                    + f"عضو گروه: {'بله' if me.get('seen_in_group') else 'هنوز دیده نشد'}\n\n"
                    + format_portfolio(user_id),
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


def build_entry_card(r, equity, risk, held_qty=None):
    coin = str(r.get("coin") or "").upper()
    direction = str(r.get("direction") or "").upper()
    is_long = direction == "LONG"
    side = "خرید / LONG" if is_long else "خروج / کاهش موقعیت"
    entry, sl = r.get("entry"), r.get("sl")
    sized = size_for_capital(entry, sl, equity, risk)
    held_qty = _f(held_qty)
    lines = [
        f"📌 {'افزایش / ورود' if is_long else 'خروج'} {coin}",
        f"جهت: {side}",
        f"قیمت ورود: {_fmt_px(entry)} USDT",
        f"خروج ضرر (SL): {_fmt_px(sl)} USDT",
        f"خروج سود ۱ (TP1): {_fmt_px(r.get('tp1'))} USDT",
    ]
    if _f(r.get("tp2")):
        lines.append(f"خروج سود ۲ (TP2): {_fmt_px(r.get('tp2'))} USDT")
    if held_qty and held_qty > 0:
        lines.append(f"موجودی ثبت‌شده تو: {_fmt_qty(held_qty)} {coin}")
    if not is_long and held_qty and held_qty > 0:
        px = _f(entry) or 0.0
        stop = abs((_f(entry) or 0) - (_f(sl) or 0))
        lines += [
            f"حداکثر مقدار قابل خروج بر اساس سبد ثبت‌شده: {_fmt_qty(held_qty)} {coin}",
            f"ارزش حدودی: {held_qty * px:,.2f} USDT" if px else "ارزش حدودی: —",
        ]
        if stop and px:
            lines.append(f"ریسک این خروج روی موجودی: {held_qty * stop:,.2f} USDT")
    elif sized:
        label = "مقدار خرید پیشنهادی" if is_long else "مقدار پیشنهادی"
        lines += [
            f"{label}: {_fmt_qty(sized['qty'])} {coin}",
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


def personalize_signals(entries, watches, holdings):
    """SELL only if the user holds the coin. BUY stays available as a new entry."""
    holdings = holdings or {}
    kept_e, kept_w = [], []
    for r in entries or []:
        coin = _norm_coin(r.get("coin"))
        direction = str(r.get("direction") or "").upper()
        if direction == "SHORT" and not holdings.get(coin):
            continue
        kept_e.append(r)
    for r in watches or []:
        coin = _norm_coin(r.get("coin"))
        state = str(r.get("decision_state") or "")
        if "BEARISH" in state and not holdings.get(coin):
            continue
        kept_w.append(r)
    return kept_e, kept_w


def build_user_report(user, entries, watches, kind="daily", holdings=None):
    equity = _f(user.get("equity_usdt"))
    name = user.get("first_name") or "تریدر"
    risk = risk_pct()
    holdings = holdings or {}
    title = ("گزارش روزانه" if kind == "daily" else "به‌روزرسانی سیگنال" if kind == "update" else "سیگنال جدید ساعتی")
    lines = [
        f"💼 {DESK_VERSION} | {title}",
        f"سلام {name}",
        f"{_now_tehran().strftime('%Y-%m-%d %H:%M')} تهران",
        f"سرمایه تو: {equity:,.2f} USDT",
        f"ریسک هر معامله: {risk:.2f}% = {equity * risk / 100.0:,.2f} USDT",
    ]
    if holdings:
        bag = "، ".join(f"{c} {_fmt_qty(q)}" for c, q in sorted(holdings.items()))
        lines.append(f"سبد تو: {bag}")
    else:
        lines.append("سبد خالی است. ثبت کن: /hold BTC 0.05")
    lines.append("")
    if entries:
        lines.append("=== سیگنال ورود + خروج ===")
        for r in entries:
            coin = _norm_coin(r.get("coin"))
            lines.append(build_entry_card(r, equity, risk, held_qty=holdings.get(coin)))
            lines.append("")
    else:
        lines.append("الان سیگنال قابل اجرا برای سبد/سرمایه تو نیست.")
        lines.append("")
    if watches and kind == "daily":
        lines.append("=== فقط مراقبت؛ ورود نکن ===")
        for r in watches[:12]:
            lines.append(build_watch_line(r))
        lines.append("")
    lines.append("برای خروج، ATLAS فقط تا سقف موجودی ثبت‌شده همان ارز را نمایش می‌دهد؛ خرید جدید از روی سرمایه سایز می‌شود.")
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
    """Multi-user Desk cycle with persistent dedupe and holdings-aware personalization."""
    if not desk_enabled():
        print("💼 Atlas Desk disabled")
        return {"enabled": False}

    ingest = ingest_telegram_commands(sender=sender)
    entries, watches = split_results(results, personal_symbols=personal_symbols)
    users = load_users()

    holdings_ok = True
    holdings_error = None
    try:
        holdings_by_user = load_all_holdings()
    except Exception as e:
        holdings_by_user = {}
        holdings_ok = False
        holdings_error = str(e)
        print(f"⚠️ Desk holdings unavailable; exit personalization fail-closed: {e}")

    require_group = not _parse_bool(os.environ.get("ATLAS_DESK_ALLOW_DM_ONLY", "0"))
    subs = eligible_subscribers(users, require_group=require_group)
    cycle = current_cycle()

    sent = skipped = deduped = updates_sent = persist_errors = 0

    if send_report and sender:
        for user in subs:
            uid = str(user.get("user_id") or "")
            chat_id = str(user.get("chat_id") or "")
            if not uid or not chat_id:
                skipped += 1
                continue

            bag = holdings_by_user.get(uid, {}) if holdings_ok else {}
            if holdings_ok:
                user_entries, user_watches = personalize_signals(entries, watches, bag)
            else:
                user_entries = [r for r in entries if str(r.get("direction") or "").upper() == "LONG"]
                user_watches = [
                    r for r in watches
                    if "BEARISH" not in str(r.get("decision_state") or "").upper()
                ]

            if cycle == "daily":
                day = _now_tehran().strftime("%Y-%m-%d")
                daily_hash = f"DAILY:{day}"
                if delivery_exists(_delivery_key(uid, daily_hash, "DAILY")):
                    deduped += 1
                    continue
                text = build_user_report(
                    user, user_entries, user_watches, kind="daily",
                    holdings=bag if holdings_ok else {}
                )
                if not holdings_ok:
                    text += (
                        "\n\n⚠️ وضعیت سبد از Supabase موقتاً در دسترس نبود؛ "
                        "هیچ سیگنال خروج شخصی‌سازی‌شده‌ای در این گزارش صادر نشد."
                    )
                try:
                    if sender(chat_id, text):
                        if record_delivery(uid, daily_hash, "DAILY"):
                            sent += 1
                        else:
                            persist_errors += 1
                except Exception as e:
                    print(f"⚠️ Desk daily push {uid}: {e}")
                continue

            if cycle == "nightly":
                skipped += 1
                continue

            if not user.get("hourly_on", 1) or not _parse_bool(
                os.environ.get("ATLAS_DESK_HOURLY_PUSH", "1"), True
            ):
                skipped += 1
                continue

            new_entries, new_records = [], []
            updated_entries, update_records = [], []

            for r in user_entries:
                base_hash = _signal_hash(r)
                level_hash = _signal_level_hash(r)
                entry_seen = delivery_exists(_delivery_key(uid, base_hash, "ENTRY"))
                level_seen = delivery_exists(_delivery_key(uid, level_hash, "LEVEL"))

                if not entry_seen:
                    new_entries.append(r)
                    new_records.append((base_hash, level_hash))
                elif not level_seen:
                    updated_entries.append(r)
                    update_records.append(level_hash)
                else:
                    deduped += 1

            if new_entries:
                text = build_user_report(
                    user, new_entries, [], kind="hourly",
                    holdings=bag if holdings_ok else {}
                )
                try:
                    if sender(chat_id, text):
                        ok = True
                        for base_hash, level_hash in new_records:
                            ok = record_delivery(uid, base_hash, "ENTRY") and ok
                            ok = record_delivery(uid, level_hash, "LEVEL") and ok
                        if ok:
                            sent += 1
                        else:
                            persist_errors += 1
                except Exception as e:
                    print(f"⚠️ Desk hourly entry push {uid}: {e}")

            if updated_entries:
                text = build_user_report(
                    user, updated_entries, [], kind="update",
                    holdings=bag if holdings_ok else {}
                )
                try:
                    if sender(chat_id, text):
                        ok = True
                        for level_hash in update_records:
                            ok = record_delivery(uid, level_hash, "LEVEL") and ok
                        if ok:
                            sent += 1
                            updates_sent += 1
                        else:
                            persist_errors += 1
                except Exception as e:
                    print(f"⚠️ Desk hourly update push {uid}: {e}")

            if not new_entries and not updated_entries:
                skipped += 1

    print(
        f"💼 Desk cycle={cycle} users={len(users)} subs={len(subs)} "
        f"entries={len(entries)} sent={sent} updates={updates_sent} skipped={skipped} "
        f"deduped={deduped} persist_errors={persist_errors} holdings_ok={holdings_ok} ingest={ingest}"
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
        "updates_sent": updates_sent,
        "deduped": deduped,
        "persist_errors": persist_errors,
        "holdings_ok": holdings_ok,
        "holdings_error": holdings_error,
        "stats": {"entries": len(entries), "watches": len(watches), "equity": None},
    }

