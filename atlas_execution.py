# ============================================================
# ATLAS Execution Layer — Phase 3.11.7 MULTIUSER SAFE
# Additive OMS / paper-execution layer.
#
# GUARANTEES:
# - Canonical ATLAS analysis fields are READ-ONLY here.
# - Only BUY/SELL CONFIRMATION may create an execution intent.
# - WATCH / Book Scan / Advisory never create intents.
# - Persistent execution state is Supabase-primary with SQLite mirror.
# - New execution is fail-closed if required persistent state is unavailable.
# - PAPER lifecycle is reconciled across GitHub runs.
# - LIVE stays dark unless every explicit lock is open.
# - Spot SELL is rejected by default (prevents accidental liquidation of holdings).
# - LIVE protective exits are REQUIRED by default; because generic CCXT bracket
#   semantics are exchange-specific, this build deliberately blocks LIVE rather
#   than pretending SL/TP protection exists when it cannot be guaranteed.
# ============================================================

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
EXEC_VERSION = "ATLAS v11.5 PHASE 3.11.7 MULTIUSER SAFE"

EXECUTABLE_STATES = {"BUY CONFIRMATION", "SELL CONFIRMATION"}
DEFAULT_SYMBOLS = ("BTC", "ETH")
LIVE_CONFIRM_PHRASE = "I_ACCEPT_LIVE_RISK"

EXEC_DB = os.environ.get("ATLAS_EXEC_SQLITE", "atlas_execution.sqlite3")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    or os.environ.get("SUPABASE_ANON_KEY", "").strip()
)
INTENT_TABLE = os.environ.get("ATLAS_EXEC_INTENT_TABLE", "atlas_exec_intents").strip()
EVENT_TABLE = os.environ.get("ATLAS_EXEC_EVENT_TABLE", "atlas_exec_events").strip()


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
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _now_utc():
    return datetime.now(timezone.utc)


def _now_tehran():
    return datetime.now(TEHRAN)


def execution_enabled():
    return _parse_bool(os.environ.get("ATLAS_EXECUTION_ENABLED", "1"), True)


def execution_mode():
    mode = os.environ.get("ATLAS_EXECUTION_MODE", "PAPER").strip().upper()
    return mode if mode in ("PAPER", "LIVE") else "PAPER"


def allowed_symbols():
    raw = os.environ.get("ATLAS_EXEC_SYMBOLS", "BTC,ETH")
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return tuple(syms or DEFAULT_SYMBOLS)


def market_kind():
    kind = os.environ.get("ATLAS_TRADE_MARKET", "spot").strip().lower() or "spot"
    return "swap" if kind in ("swap", "perp", "perpetual", "future", "futures") else "spot"


def equity_usdt():
    return max(0.0, _f(os.environ.get("ATLAS_EXEC_EQUITY_USDT"), 10000.0) or 10000.0)


def risk_pct():
    return max(0.1, min(5.0, _f(os.environ.get("RISK_PER_TRADE_PCT"), 1.5) or 1.5))


def max_portfolio_risk_pct():
    return max(1.0, min(20.0, _f(os.environ.get("MAX_PORTFOLIO_OPEN_RISK_PCT"), 6.0) or 6.0))


def max_leverage():
    configured = max(1.0, min(5.0, _f(os.environ.get("ATLAS_EXEC_MAX_LEVERAGE"), 3.0) or 3.0))
    return 1.0 if market_kind() == "spot" else configured


def max_open_positions():
    return max(1, int(_f(os.environ.get("ATLAS_EXEC_MAX_OPEN"), 2) or 2))


def daily_kill_r():
    return max(1.0, _f(os.environ.get("ATLAS_DAILY_KILL_R"), 3.0) or 3.0)


def min_rr():
    return max(1.0, _f(os.environ.get("ATLAS_MIN_EXECUTABLE_RR"), 2.0) or 2.0)


def min_confidence():
    return max(50.0, _f(os.environ.get("ATLAS_MIN_CONFIDENCE"), 55.0) or 55.0)


def require_persistence():
    return _parse_bool(os.environ.get("ATLAS_EXEC_REQUIRE_PERSISTENCE", "1"), True)


def require_protective_orders():
    return _parse_bool(os.environ.get("ATLAS_EXEC_REQUIRE_PROTECTIVE", "1"), True)


def allow_spot_sell():
    return _parse_bool(os.environ.get("ATLAS_EXEC_ALLOW_SPOT_SELL", "0"), False)


def supabase_enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY and INTENT_TABLE and EVENT_TABLE)


def _sb_headers(prefer="return=representation"):
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _sb_request(method, table, params=None, payload=None, prefer="return=representation", timeout=15):
    if not supabase_enabled():
        raise RuntimeError("Supabase execution persistence not configured")
    q = urllib.parse.urlencode(params or {})
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if q:
        url += "?" + q
    data = None if payload is None else json.dumps(payload, default=str).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers=_sb_headers(prefer), method=method
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else None


def _sb_select(table, params=None):
    try:
        out = _sb_request("GET", table, params=params, payload=None)
        return out if isinstance(out, list) else []
    except Exception:
        return []


def _sb_upsert(table, row, on_conflict):
    try:
        params = {"on_conflict": on_conflict}
        _sb_request(
            "POST",
            table,
            params=params,
            payload=row,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return True
    except Exception:
        return False


def _sb_insert(table, row):
    try:
        _sb_request("POST", table, payload=row, prefer="return=minimal")
        return True
    except Exception:
        return False


def _sb_patch(table, match, row):
    try:
        params = {k: f"eq.{v}" for k, v in match.items()}
        _sb_request("PATCH", table, params=params, payload=row, prefer="return=minimal")
        return True
    except Exception:
        return False


def intent_hash(coin, side, entry, sl, candle_ts):
    raw = f"{coin}|{side}|{entry}|{sl}|{candle_ts}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _conn():
    c = sqlite3.connect(EXEC_DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_exec_db():
    with _conn() as c:
        c.executescript(
            """
            create table if not exists order_intents(
                intent_hash text primary key,
                created_at text not null,
                updated_at text not null,
                coin text not null,
                side text not null,
                state_src text,
                entry real,
                sl real,
                tp1 real,
                tp2 real,
                rr real,
                confidence real,
                qty real,
                notional real,
                risk_pct real,
                leverage_used real,
                mode text not null,
                status text not null,
                reason text,
                broker_ref text,
                signal_candle_ts text,
                fill_price real,
                close_price real,
                realized_r real,
                close_day text,
                extra_json text
            );
            create table if not exists exec_events(
                id integer primary key autoincrement,
                ts text not null,
                coin text,
                intent_hash text,
                event text not null,
                detail text
            );
            """
        )


def _local_upsert(row):
    cols = [
        "intent_hash","created_at","updated_at","coin","side","state_src",
        "entry","sl","tp1","tp2","rr","confidence","qty","notional",
        "risk_pct","leverage_used","mode","status","reason","broker_ref",
        "signal_candle_ts","fill_price","close_price","realized_r",
        "close_day","extra_json"
    ]
    vals = [row.get(k) for k in cols]
    placeholders = ",".join("?" for _ in cols)
    update_cols = [c for c in cols if c != "intent_hash"]
    update_sql = ",".join(f"{c}=excluded.{c}" for c in update_cols)
    with _conn() as c:
        c.execute(
            f"insert into order_intents({','.join(cols)}) values({placeholders}) "
            f"on conflict(intent_hash) do update set {update_sql}",
            vals,
        )


def _persist_intent(row):
    row = dict(row)
    row["updated_at"] = row.get("updated_at") or _now_utc().isoformat()
    remote_ok = _sb_upsert(INTENT_TABLE, row, "intent_hash") if supabase_enabled() else False
    _local_upsert(row)
    if require_persistence() and not remote_ok:
        raise RuntimeError("persistent execution ledger unavailable")
    return remote_ok


def _log_event(coin, event, detail, h=None):
    row = {
        "ts": _now_utc().isoformat(),
        "coin": coin,
        "intent_hash": h,
        "event": event,
        "detail": str(detail)[:4000],
    }
    if supabase_enabled():
        _sb_insert(EVENT_TABLE, row)
    with _conn() as c:
        c.execute(
            "insert into exec_events(ts,coin,intent_hash,event,detail) values(?,?,?,?,?)",
            (row["ts"], coin, h, event, row["detail"]),
        )


def _remote_intents(params=None):
    if not supabase_enabled():
        return []
    base = {"select": "*", "order": "created_at.asc"}
    if params:
        base.update(params)
    return _sb_select(INTENT_TABLE, base)


def open_intents():
    statuses = "PAPER_WORKING,PAPER_OPEN,LIVE_SUBMITTED,LIVE_OPEN,OPEN"
    rows = _remote_intents({"status": f"in.({statuses})"})
    if rows:
        for row in rows:
            try:
                _local_upsert(row)
            except Exception:
                pass
        return rows
    if require_persistence() and supabase_enabled():
        # Empty is a valid state; distinguish it from a failed read by checking a tiny read.
        probe = _sb_select(INTENT_TABLE, {"select": "intent_hash", "limit": "1"})
        if probe == []:
            # Could be either empty or failed. We permit empty here; new-intent save is still fail-closed.
            pass
    with _conn() as c:
        local = c.execute(
            "select * from order_intents where status in "
            "('PAPER_WORKING','PAPER_OPEN','LIVE_SUBMITTED','LIVE_OPEN','OPEN')"
        ).fetchall()
    return [dict(r) for r in local]


def today_realized_r():
    day = _now_tehran().strftime("%Y-%m-%d")
    rows = _remote_intents({
        "select": "realized_r,close_day,status",
        "close_day": f"eq.{day}",
        "status": "in.(PAPER_CLOSED,LIVE_CLOSED)",
    })
    if rows:
        return sum(_f(r.get("realized_r"), 0.0) or 0.0 for r in rows)
    with _conn() as c:
        local = c.execute(
            "select realized_r from order_intents where close_day=? "
            "and status in ('PAPER_CLOSED','LIVE_CLOSED')", (day,)
        ).fetchall()
    return sum(_f(r[0], 0.0) or 0.0 for r in local)


def hash_exists(h):
    rows = _remote_intents({
        "select": "intent_hash,status",
        "intent_hash": f"eq.{h}",
        "limit": "1",
    })
    if rows:
        return rows[0]
    with _conn() as c:
        row = c.execute(
            "select intent_hash,status from order_intents where intent_hash=?", (h,)
        ).fetchone()
    return dict(row) if row else None


def _update_intent(h, updates):
    updates = dict(updates)
    updates["updated_at"] = _now_utc().isoformat()
    remote_ok = _sb_patch(INTENT_TABLE, {"intent_hash": h}, updates) if supabase_enabled() else False
    with _conn() as c:
        sets = ",".join(f"{k}=?" for k in updates)
        c.execute(
            f"update order_intents set {sets} where intent_hash=?",
            list(updates.values()) + [h],
        )
    if require_persistence() and not remote_ok:
        raise RuntimeError("persistent execution ledger update failed")
    return remote_ok


def size_position(entry, sl, equity, risk, max_lev):
    entry = _f(entry)
    sl = _f(sl)
    if entry is None or sl is None or entry <= 0 or sl <= 0:
        return None
    stop = abs(entry - sl)
    if stop / entry < 0.0015:
        return None
    risk_usd = equity * (risk / 100.0)
    qty = risk_usd / stop
    notional = qty * entry
    lev = notional / equity if equity else 0.0
    if lev > max_lev:
        qty = (equity * max_lev) / entry
        notional = qty * entry
        risk_usd = qty * stop
        risk = (risk_usd / equity) * 100.0 if equity else risk
        lev = max_lev
    return {
        "qty": round(qty, 8),
        "notional": round(notional, 2),
        "risk_pct": round(risk, 4),
        "leverage_used": round(lev, 3),
        "stop_dist": round(stop, 8),
    }


def _paper_fill_condition(side, market_price, entry):
    market_price = _f(market_price)
    entry = _f(entry)
    if market_price is None or entry is None:
        return False
    if side == "BUY":
        return market_price <= entry
    return market_price >= entry


def _paper_reconcile_one(row, market_price):
    h = row["intent_hash"]
    side = str(row.get("side") or "").upper()
    status = str(row.get("status") or "")
    entry = _f(row.get("entry"))
    sl = _f(row.get("sl"))
    tp2 = _f(row.get("tp2"))
    price = _f(market_price)
    rr = _f(row.get("rr"), 0.0) or 0.0
    if price is None:
        return None

    if status == "PAPER_WORKING" and _paper_fill_condition(side, price, entry):
        _update_intent(h, {
            "status": "PAPER_OPEN",
            "fill_price": entry,
            "reason": f"paper entry filled at {entry}",
        })
        _log_event(row.get("coin"), "PAPER_OPEN", f"filled @ {entry}", h)
        status = "PAPER_OPEN"

    if status != "PAPER_OPEN":
        return None

    close = None
    realized_r = None
    reason = None
    if side == "BUY":
        if sl is not None and price <= sl:
            close, realized_r, reason = sl, -1.0, "paper SL hit"
        elif tp2 is not None and price >= tp2:
            close, realized_r, reason = tp2, rr, "paper TP2 hit"
    else:
        if sl is not None and price >= sl:
            close, realized_r, reason = sl, -1.0, "paper SL hit"
        elif tp2 is not None and price <= tp2:
            close, realized_r, reason = tp2, rr, "paper TP2 hit"

    if close is not None:
        close_day = _now_tehran().strftime("%Y-%m-%d")
        _update_intent(h, {
            "status": "PAPER_CLOSED",
            "close_price": close,
            "realized_r": realized_r,
            "close_day": close_day,
            "reason": reason,
        })
        _log_event(row.get("coin"), "PAPER_CLOSED", f"{reason}; R={realized_r:.3f}", h)
        return {"intent_hash": h, "status": "PAPER_CLOSED", "realized_r": realized_r}
    return None


def reconcile_paper_positions(results):
    by_coin = {
        str(r.get("coin") or "").upper(): _f(r.get("price"))
        for r in (results or [])
    }
    events = []
    for row in open_intents():
        if str(row.get("mode") or "").upper() != "PAPER":
            continue
        evt = _paper_reconcile_one(row, by_coin.get(str(row.get("coin") or "").upper()))
        if evt:
            events.append(evt)
    return events


def independent_risk_check(result, context):
    """Second gate. Never trusts the analysis engine alone."""
    reasons = []
    coin = str(result.get("coin") or "").upper()
    state = str(result.get("decision_state") or "")
    direction = str(result.get("direction") or "").upper()
    gate = str(result.get("gate") or "")
    entry = _f(result.get("entry"))
    sl = _f(result.get("sl"))
    tp1 = _f(result.get("tp1"))
    tp2 = _f(result.get("tp2"))
    rr = _f(result.get("rr"))
    conf = _f(result.get("confidence"), 0.0) or 0.0

    if coin not in context["symbols"]:
        reasons.append(f"{coin} outside exec universe")
    if state not in EXECUTABLE_STATES:
        reasons.append(f"state {state} not executable")
    if result.get("repeat_signal"):
        reasons.append("repeat signal")
    if gate and gate != "PASS":
        reasons.append(f"analysis gate {gate}")
    if not context.get("backtest_ok", False):
        reasons.append("backtest gate unavailable/down")
    if direction not in ("LONG", "SHORT"):
        reasons.append("direction missing")
    if (state == "BUY CONFIRMATION" and direction != "LONG") or (
        state == "SELL CONFIRMATION" and direction != "SHORT"
    ):
        reasons.append("state/direction mismatch")
    if entry is None or sl is None or tp1 is None or tp2 is None:
        reasons.append("incomplete geometry")
    if direction == "LONG" and entry is not None and sl is not None and sl >= entry:
        reasons.append("long SL not below entry")
    if direction == "SHORT" and entry is not None and sl is not None and sl <= entry:
        reasons.append("short SL not above entry")
    if rr is None or rr < context["min_rr"]:
        reasons.append(f"RR {rr} < {context['min_rr']}")
    if conf < context["min_conf"]:
        reasons.append(f"confidence {conf:.0f} < {context['min_conf']:.0f}")
    if context["market_kind"] == "spot" and direction == "SHORT" and not allow_spot_sell():
        reasons.append("spot SHORT/SELL blocked; prevents accidental sale of holdings")
    if context["open_count"] >= context["max_open"]:
        reasons.append("max open positions")
    if context["open_risk"] + context["risk_pct"] > context["max_port_risk"] + 1e-9:
        reasons.append("portfolio risk cap")
    if context["realized_r"] <= -context["kill_r"]:
        reasons.append(f"daily kill switch {context['realized_r']:.2f}R")

    sized = None
    if entry is not None and sl is not None and not reasons:
        sized = size_position(entry, sl, context["equity"], context["risk_pct"], context["max_lev"])
        if sized is None:
            reasons.append("stop too tight or size failed")
        elif sized["qty"] <= 0:
            reasons.append("qty=0")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "size": sized,
        "coin": coin,
        "state": state,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr": rr,
        "confidence": conf,
        "side": "BUY" if direction == "LONG" else "SELL",
        "signal_candle_ts": result.get("signal_candle_ts"),
        "market_price": _f(result.get("price")),
    }


def _live_base_locks_open():
    return (
        execution_mode() == "LIVE"
        and _parse_bool(os.environ.get("ATLAS_LIVE_TRADING", "0"))
        and os.environ.get("ATLAS_LIVE_CONFIRM", "").strip() == LIVE_CONFIRM_PHRASE
        and bool(os.environ.get("ATLAS_TRADE_API_KEY", "").strip())
        and bool(os.environ.get("ATLAS_TRADE_API_SECRET", "").strip())
    )


def live_locks_open():
    """Fail-closed LIVE gate.

    This Phase intentionally refuses LIVE while protective-order enforcement is
    required, because a generic cross-exchange CCXT implementation cannot safely
    promise bracket semantics. PAPER remains fully functional.
    """
    if not _live_base_locks_open():
        return False
    if require_persistence() and not supabase_enabled():
        return False
    if require_protective_orders():
        return False
    return True


def _live_block_reason():
    if execution_mode() != "LIVE":
        return "execution mode is PAPER"
    if not _parse_bool(os.environ.get("ATLAS_LIVE_TRADING", "0")):
        return "ATLAS_LIVE_TRADING lock closed"
    if os.environ.get("ATLAS_LIVE_CONFIRM", "").strip() != LIVE_CONFIRM_PHRASE:
        return "live confirmation phrase missing"
    if not os.environ.get("ATLAS_TRADE_API_KEY", "").strip() or not os.environ.get("ATLAS_TRADE_API_SECRET", "").strip():
        return "trade API credentials missing"
    if require_persistence() and not supabase_enabled():
        return "persistent execution ledger unavailable"
    if require_protective_orders():
        return "LIVE blocked until exchange-specific server-side protective orders are implemented"
    return "unknown LIVE lock"


def _create_live_client():
    import ccxt
    ex_id = os.environ.get("ATLAS_TRADE_EXCHANGE", "bybit").strip().lower() or "bybit"
    klass = getattr(ccxt, ex_id, None)
    if klass is None:
        raise RuntimeError(f"unknown exchange {ex_id}")
    client = klass({
        "apiKey": os.environ.get("ATLAS_TRADE_API_KEY", "").strip(),
        "secret": os.environ.get("ATLAS_TRADE_API_SECRET", "").strip(),
        "enableRateLimit": True,
        "options": {"defaultType": "swap" if market_kind() == "swap" else "spot"},
    })
    if _parse_bool(os.environ.get("ATLAS_TRADE_SANDBOX", "1")) and hasattr(client, "set_sandbox_mode"):
        client.set_sandbox_mode(True)
    client.load_markets()
    return client, ex_id


def _place_live_limit(check, h):
    """Entry submission only; unreachable while protective-order lock is required."""
    client, ex_id = _create_live_client()
    coin = check["coin"]
    symbol = os.environ.get("ATLAS_TRADE_SYMBOL_" + coin, "").strip()
    if not symbol:
        symbol = f"{coin}/USDT:USDT" if market_kind() == "swap" else f"{coin}/USDT"
    market = client.market(symbol)
    qty = float(client.amount_to_precision(symbol, check["size"]["qty"]))
    price = float(client.price_to_precision(symbol, check["entry"]))
    if qty <= 0 or price <= 0:
        raise RuntimeError("precision reduced qty/price to zero")

    limits = market.get("limits") or {}
    min_amt = _f((limits.get("amount") or {}).get("min"))
    min_cost = _f((limits.get("cost") or {}).get("min"))
    if min_amt is not None and qty < min_amt:
        raise RuntimeError(f"qty {qty} below exchange minimum {min_amt}")
    if min_cost is not None and qty * price < min_cost:
        raise RuntimeError(f"notional {qty*price:.4f} below exchange minimum {min_cost}")

    side = "buy" if check["side"] == "BUY" else "sell"
    if market_kind() == "spot":
        bal = client.fetch_balance()
        if side == "buy":
            free_quote = _f(((bal.get("free") or {}).get("USDT")), 0.0) or 0.0
            if free_quote + 1e-9 < qty * price:
                raise RuntimeError("insufficient free USDT")
        elif not allow_spot_sell():
            raise RuntimeError("spot SELL blocked")

    params = {"clientOrderId": h}
    if ex_id == "bybit":
        params["orderLinkId"] = h
    order = client.create_order(symbol, "limit", side, qty, price, params)
    ref = str(order.get("id") or order.get("orderId") or "")
    return True, ref or json.dumps(order, default=str)[:300]


def evaluate_results(results, backtest_ok=False):
    init_exec_db()

    if require_persistence() and not supabase_enabled():
        raise RuntimeError("Execution fail-closed: Supabase persistence is required but unavailable")

    paper_events = reconcile_paper_positions(results)

    open_rows = open_intents()
    ctx = {
        "symbols": set(allowed_symbols()),
        "equity": equity_usdt(),
        "risk_pct": risk_pct(),
        "max_port_risk": max_portfolio_risk_pct(),
        "max_lev": max_leverage(),
        "max_open": max_open_positions(),
        "kill_r": daily_kill_r(),
        "min_rr": min_rr(),
        "min_conf": min_confidence(),
        "backtest_ok": bool(backtest_ok),
        "open_count": len(open_rows),
        "open_risk": sum(_f(r.get("risk_pct"), 0) or 0 for r in open_rows),
        "realized_r": today_realized_r(),
        "market_kind": market_kind(),
    }

    live = live_locks_open()
    requested_mode = execution_mode()
    mode = "LIVE" if live else "PAPER"
    accepted, rejected, skipped = [], [], []

    if requested_mode == "LIVE" and not live:
        _log_event(None, "LIVE_BLOCKED", _live_block_reason())

    for r in results or []:
        coin = str(r.get("coin") or "").upper()
        if coin in ("GOLD", "SILVER", "COPPER"):
            continue
        state = str(r.get("decision_state") or "")
        if state not in EXECUTABLE_STATES:
            continue

        check = independent_risk_check(r, ctx)
        if not check["ok"]:
            rejected.append(check)
            _log_event(coin, "REJECT", " | ".join(check["reasons"]))
            continue

        h = intent_hash(
            check["coin"], check["side"], check["entry"], check["sl"], check["signal_candle_ts"]
        )
        existing = hash_exists(h)
        if existing:
            skipped.append({**check, "intent_hash": h, "status": existing["status"]})
            continue

        # Default = persistent PAPER intent. LIVE only if every lock is truly open.
        status = "PAPER_WORKING"
        broker_ref = ""
        reason = "paper intent accepted; no exchange order"
        if _paper_fill_condition(check["side"], check["market_price"], check["entry"]):
            status = "PAPER_OPEN"
            reason = "paper intent accepted and entry considered filled"

        if live:
            ok, ref = _place_live_limit(check, h)
            if not ok:
                raise RuntimeError(f"live submit failed: {ref}")
            status = "LIVE_SUBMITTED"
            broker_ref = str(ref)
            reason = "live limit submitted"

        row = {
            "intent_hash": h,
            "created_at": _now_utc().isoformat(),
            "updated_at": _now_utc().isoformat(),
            "coin": check["coin"],
            "side": check["side"],
            "state_src": check["state"],
            "entry": check["entry"],
            "sl": check["sl"],
            "tp1": check["tp1"],
            "tp2": check["tp2"],
            "rr": check["rr"],
            "confidence": check["confidence"],
            "qty": check["size"]["qty"],
            "notional": check["size"]["notional"],
            "risk_pct": check["size"]["risk_pct"],
            "leverage_used": check["size"]["leverage_used"],
            "mode": mode,
            "status": status,
            "reason": reason,
            "broker_ref": broker_ref,
            "signal_candle_ts": str(check["signal_candle_ts"] or ""),
            "fill_price": check["entry"] if status == "PAPER_OPEN" else None,
            "close_price": None,
            "realized_r": None,
            "close_day": None,
            "extra_json": json.dumps(
                {
                    "size": check["size"],
                    "market_price_at_intent": check["market_price"],
                    "exec_version": EXEC_VERSION,
                },
                default=str,
            ),
        }

        _persist_intent(row)
        _log_event(coin, status, reason, h)
        accepted.append(row)
        ctx["open_count"] += 1
        ctx["open_risk"] += row["risk_pct"]

    return {
        "version": EXEC_VERSION,
        "mode": mode,
        "requested_mode": requested_mode,
        "live_locks": live,
        "live_block_reason": None if live else _live_block_reason(),
        "persistence": "SUPABASE+SQLITE" if supabase_enabled() else "SQLITE_ONLY",
        "paper_events": paper_events,
        "context": ctx,
        "accepted": accepted,
        "rejected": rejected,
        "skipped": skipped,
        "open": open_intents(),
    }


def format_execution_report(payload):
    ctx = payload["context"]
    lines = [
        "⚙️ ATLAS | Execution Layer 3.11.7",
        f"Mode: {payload['mode']} | Requested: {payload['requested_mode']} | "
        f"Live locks: {'OPEN' if payload['live_locks'] else 'CLOSED'}",
        f"Persistence: {payload.get('persistence')}",
        f"{_now_tehran().strftime('%Y-%m-%d %H:%M')} Tehran",
        "منبع حقیقت: فقط BUY/SELL CONFIRMATION + گیت مستقل اجرا",
        "",
        f"Equity {ctx['equity']:.0f} USDT | Risk/trade {ctx['risk_pct']:.2f}% | "
        f"Open risk {ctx['open_risk']:.2f}% / cap {ctx['max_port_risk']:.1f}%",
        f"Open {ctx['open_count']}/{ctx['max_open']} | Today R {ctx['realized_r']:.2f} | "
        f"Kill {-ctx['kill_r']:.1f}R | Market {ctx['market_kind'].upper()}",
        f"Universe: {', '.join(sorted(ctx['symbols']))}",
        "",
    ]

    if payload.get("paper_events"):
        lines.append("🧾 PAPER RECONCILIATION")
        for evt in payload["paper_events"]:
            lines.append(f"• {evt['status']} | R={evt.get('realized_r')}")
        lines.append("")

    if payload["accepted"]:
        lines.append("✅ ACCEPTED")
        for row in payload["accepted"]:
            lines.append(
                f"• {row['coin']} {row['side']} {row['status']} qty={row['qty']} "
                f"@ {row['entry']} SL {row['sl']} TP1 {row['tp1']} TP2 {row['tp2']} "
                f"RR {row['rr']} risk {row['risk_pct']:.2f}% lev {row['leverage_used']:.2f}x"
            )
        lines.append("")
    else:
        lines.append("✅ ACCEPTED: none")
        lines.append("")

    if payload["skipped"]:
        lines.append("↺ SKIPPED (idempotent)")
        for row in payload["skipped"]:
            lines.append(f"• {row['coin']} {row['side']} already {row.get('status')}")
        lines.append("")

    if payload["rejected"]:
        lines.append("🚫 REJECTED by exec gate")
        for row in payload["rejected"][:12]:
            lines.append(f"• {row['coin']}: " + " | ".join(row["reasons"]))
        lines.append("")

    lines.append("WATCH / Book Scan / Advisory وارد Execution Layer نمی‌شوند.")
    if not payload["live_locks"]:
        lines.append("🔒 LIVE بسته است: " + str(payload.get("live_block_reason")))
    return "\n".join(lines)


def send_execution_report(text, sender=None):
    if sender is None:
        return 0
    dests = []
    for key in ("TELEGRAM_CHAT_ID", "TELEGRAM_GROUP_CHAT_ID"):
        val = os.environ.get(key, "").strip()
        if val and val not in dests:
            dests.append(val)
    sent = 0
    for dest in dests:
        try:
            if sender(dest, text):
                sent += 1
        except Exception:
            pass
    return sent


def run_execution_cycle(results, backtest_ok=False, sender=None, send_telegram=True):
    """Entry point called from bot.py. Analysis fields are read-only."""
    if not execution_enabled():
        print("⚙️ Execution layer disabled")
        return {
            "enabled": False, "accepted": [], "rejected": [], "skipped": [],
            "paper_events": [], "telegram_sent": 0,
        }

    payload = evaluate_results(results, backtest_ok=backtest_ok)
    text = format_execution_report(payload)
    print(text)

    sent = 0
    if send_telegram and sender is not None:
        force = _parse_bool(os.environ.get("ATLAS_PHASE37_DAILY_REPORT", "0"))
        if force or payload["accepted"] or payload["rejected"] or payload.get("paper_events"):
            sent = send_execution_report(text, sender=sender)

    payload["telegram_sent"] = sent
    payload["enabled"] = True
    payload["report"] = text
    return payload
