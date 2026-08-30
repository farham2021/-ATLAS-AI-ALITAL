#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATLAS v11.5 Self-Updater (Final)
این اسکریپت تمام اصلاحات را اعمال می‌کند و تابع init_sqlite را به‌طور کامل بازنویسی می‌کند.
استفاده: python patch_bot.py
"""

import os
import re
import sys

def apply_patches(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    total = len(lines)

    # ========== ۱. اضافه کردن تنظیمات جدید ==========
    config_insert = """
# ============================================================
# SNAPSHOT DIRECTION THRESHOLDS (NEW)
# ============================================================
SNAPSHOT_FLAT_THRESHOLD_PCT = float(os.environ.get("ATLAS_SNAPSHOT_FLAT_THRESHOLD_PCT", "0.10"))
SNAPSHOT_4H_THRESHOLD_PCT = float(os.environ.get("ATLAS_SNAPSHOT_4H_THRESHOLD", "0.15"))
SNAPSHOT_24H_THRESHOLD_PCT = float(os.environ.get("ATLAS_SNAPSHOT_24H_THRESHOLD", "0.30"))
SNAPSHOT_7D_THRESHOLD_PCT = float(os.environ.get("ATLAS_SNAPSHOT_7D_THRESHOLD", "0.50"))

# ============================================================
# SELF-HEALING SETTINGS
# ============================================================
ATLAS_SELF_HEAL_BATCH = int(os.environ.get("ATLAS_SELF_HEAL_BATCH", "15"))
ATLAS_SHARPE_MIN_PERIOD = int(os.environ.get("ATLAS_SHARPE_MIN_PERIOD", "20"))
"""
    found_config = False
    for idx, line in enumerate(lines):
        if "SNAPSHOT_24H_THRESHOLD_PCT" in line:
            lines.insert(idx+1, config_insert)
            found_config = True
            break
    if found_config:
        print("✅ تنظیمات جدید اضافه شد.")
    else:
        print("⚠️ تنظیمات جدید اضافه نشد (SNAPSHOT_24H_THRESHOLD_PCT یافت نشد).")

    # ========== ۲. جایگزینی کامل تابع init_sqlite ==========
    new_init_sqlite = """
def init_sqlite():
    with sqlite_conn() as c:
        # ایجاد جدول‌های اصلی (بدون feature_vector)
        c.executescript(\"\"\"
        create table if not exists signal_outcomes(
            id integer primary key autoincrement,
            coin text not null,
            direction text not null,
            entry real, sl real, tp1 real, tp2 real,
            issued_at text not null,
            status text default 'OPEN',
            outcome text,
            exit_price real,
            exit_at text,
            pnl_pct real,
            bars_to_exit integer,
            notes text
        );
        create table if not exists model_weights(
            feature text primary key,
            weight real not null,
            baseline_weight real not null,
            samples integer default 0,
            wins integer default 0,
            losses integer default 0,
            updated_at text,
            reason text
        );
        create table if not exists self_healing_cursor(
            id integer primary key check(id=1),
            processed_closed integer not null default 0,
            updated_at text
        );
        create table if not exists self_healing_processed(
            signal_id integer primary key,
            processed_at text not null
        );
        create table if not exists telegram_sent_reports(
            report_hash text not null,
            destination text not null,
            sent_at text not null,
            primary key(report_hash, destination)
        );
        create table if not exists snapshot_prices(
            symbol text primary key,
            price real not null,
            captured_at text not null
        );
        create table if not exists backtest_gate_cache(
            id integer primary key check(id=1),
            timestamp text not null,
            passed integer not null,
            details text
        );
        create table if not exists candle_events(
            coin text not null,
            timeframe text not null,
            last_closed_ts integer,
            last_status text,
            observed_at text not null,
            primary key(coin, timeframe)
        );
        create table if not exists signal_memory(
            coin text primary key,
            direction text,
            action text,
            confidence real,
            signal_candle_ts integer,
            entry real,
            sl real,
            tp1 real,
            tp2 real,
            last_seen_at text not null,
            decision_state text
        );
        create table if not exists decision_events(
            id integer primary key autoincrement,
            timestamp text not null,
            coin text not null,
            state text not null,
            confidence real,
            rr real,
            btc_regime text,
            breadth real,
            reason text
        );
        create table if not exists backtests(
            id integer primary key autoincrement,
            timestamp text,
            model_version text,
            coin text,
            timeframe text,
            period_days integer,
            trades integer,
            wins integer,
            losses integer,
            win_rate real,
            avg_profit real,
            avg_loss real,
            max_drawdown real,
            profit_factor real,
            baseline_profit_factor real,
            baseline_win_rate real,
            improvement_pct real,
            passed integer,
            details text
        );
        \"\"\")

        # اضافه کردن ستون feature_vector به صورت شرطی
        c.execute("PRAGMA table_info(signal_outcomes)")
        columns = [row[1] for row in c.fetchall()]
        if "feature_vector" not in columns:
            c.execute("ALTER TABLE signal_outcomes ADD COLUMN feature_vector text;")
            print("✅ ستون feature_vector به signal_outcomes اضافه شد.")

        # ایجاد جدول price_history به صورت شرطی
        c.execute(\"\"\"
            CREATE TABLE IF NOT EXISTS price_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                price REAL NOT NULL,
                captured_at TEXT NOT NULL,
                timeframe TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_price_history_symbol_timeframe ON price_history(symbol, timeframe, captured_at DESC);
        \"\"\")
"""
    # پیدا کردن تابع init_sqlite قدیمی
    init_found = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("def init_sqlite():"):
            start = idx
            end = start
            # پیدا کردن انتهای تابع (تا خط بعدی که با def شروع شود یا به انتها برسد)
            for j in range(idx+1, total):
                if lines[j].strip().startswith("def "):
                    end = j
                    break
            if end == start:
                end = total
            # جایگزینی با تابع جدید
            lines[start:end] = new_init_sqlite.splitlines(True)
            init_found = True
            print("✅ تابع init_sqlite بازنویسی شد (بدون ALTER TABLE مستقیم).")
            break
    if not init_found:
        print("❌ تابع init_sqlite پیدا نشد! اصلاحات دیتابیس انجام نشد.")
        sys.exit(1)

    # ========== ۳. اضافه کردن توابع کمکی ==========
    new_functions = """
# ============================================================
# NEW FUNCTIONS FOR PRICE HISTORY (v11.5)
# ============================================================

def _save_price_history(symbol, price, timeframe, captured_at):
    if not symbol or price is None:
        return
    row = {"symbol": symbol.upper(), "price": price, "captured_at": captured_at, "timeframe": timeframe}
    STORE.insert("price_history", row)
    try:
        con = sqlite3.connect(DB_FILE, timeout=10)
        try:
            con.execute(
                "INSERT INTO price_history (symbol, price, captured_at, timeframe) VALUES (?,?,?,?)",
                (symbol.upper(), price, captured_at, timeframe)
            )
            con.commit()
        finally:
            con.close()
    except Exception as e:
        print(f"⚠️ Price history save error: {e}")

def _get_historical_price(symbol, timeframe_hours, captured_at):
    tolerance_hours = 1 if timeframe_hours <= 24 else 6
    try:
        rows = STORE.select(
            "price_history",
            {
                "select": "price,captured_at",
                "symbol": f"eq.{symbol.upper()}",
                "order": "captured_at.desc",
                "limit": "10"
            }
        )
        if rows:
            target = captured_at - timedelta(hours=timeframe_hours)
            for r in rows:
                try:
                    ts = datetime.fromisoformat(r["captured_at"].replace("Z", "+00:00"))
                    diff = abs((ts - target).total_seconds() / 3600)
                    if diff <= tolerance_hours:
                        return f(r["price"]), ts
                except:
                    continue
    except:
        pass
    try:
        con = sqlite3.connect(DB_FILE, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT price, captured_at FROM price_history WHERE symbol = ? ORDER BY captured_at DESC LIMIT 10",
                (symbol.upper(),)
            ).fetchall()
            target = captured_at - timedelta(hours=timeframe_hours)
            for r in rows:
                ts = datetime.fromisoformat(str(r["captured_at"]).replace("Z", "+00:00"))
                diff = abs((ts - target).total_seconds() / 3600)
                if diff <= tolerance_hours:
                    return f(r["price"]), ts
        finally:
            con.close()
    except Exception as e:
        print(f"⚠️ Historical price error: {e}")
    return None, None

def _compute_sharpe(pnls, period=20):
    if len(pnls) < period:
        return None
    recent = pnls[-period:]
    avg = safe_mean(recent)
    std = (sum((x - avg) ** 2 for x in recent) / len(recent)) ** 0.5 if len(recent) > 1 else 0
    return avg / std if std > 0 else 0
"""
    snapshot_marker = "# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT"
    for idx, line in enumerate(lines):
        if snapshot_marker in line:
            lines.insert(idx, new_functions)
            print("✅ توابع کمکی جدید اضافه شد.")
            break
    else:
        print("⚠️ نشانه SNAPSHOT پیدا نشد، توابع جدید اضافه نشد.")

    # ========== ۴. جایگزینی _get_snapshot_arrow ==========
    new_arrow_func = """
def _get_snapshot_arrow(price, previous_prices, change24=None):
    if change24 is not None:
        if abs(change24) < SNAPSHOT_24H_THRESHOLD_PCT:
            return "➡️", "24h"
        return "⬆️" if change24 > 0 else "⬇️", "24h"
    if previous_prices.get("24h") is not None:
        delta = (price - previous_prices["24h"]) / previous_prices["24h"] * 100
        if abs(delta) >= SNAPSHOT_24H_THRESHOLD_PCT:
            return "⬆️" if delta > 0 else "⬇️", "24h"
    if previous_prices.get("4h") is not None:
        delta = (price - previous_prices["4h"]) / previous_prices["4h"] * 100
        if abs(delta) >= SNAPSHOT_4H_THRESHOLD_PCT:
            return "⬆️" if delta > 0 else "⬇️", "4h"
    if previous_prices.get("current") is not None:
        delta = (price - previous_prices["current"]) / previous_prices["current"] * 100
        if abs(delta) >= SNAPSHOT_FLAT_THRESHOLD_PCT:
            return "⬆️" if delta > 0 else "⬇️", "prev"
    return "➡️", "none"
"""
    for idx, line in enumerate(lines):
        if line.strip().startswith("def _get_snapshot_arrow("):
            start = idx
            end = start
            for j in range(idx+1, total):
                if lines[j].strip().startswith("def "):
                    end = j
                    break
            if end == start:
                end = total
            lines[start:end] = new_arrow_func.splitlines(True)
            print("✅ تابع _get_snapshot_arrow جایگزین شد.")
            break

    # ========== ۵. جایگزینی build_price_snapshot ==========
    new_build_func = """
def build_price_snapshot(results, updated_at=None):
    by_coin = {str(r.get("coin") or "").upper(): r for r in (results or [])}
    dt = updated_at or now_tehran()
    captured_at_utc = dt.astimezone(timezone.utc).isoformat()

    for r in results or []:
        sym = str(r.get("coin") or "").upper()
        price = f(r.get("price"))
        if sym and price is not None and price > 0:
            _save_price_history(sym, price, "current", captured_at_utc)

    weekdays = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")
    lines = [
        f"📅 {weekdays[dt.weekday()]} | {shamsi(dt)}",
        "",
        f"⏰ آخرین بروزرسانی : {dt.strftime('%H:%M:%S')}",
        "",
        "📊 وضعیت بازار ارزهای دیجیتال (مقایسه با 4H، 24H، 7D):",
        "───────────────────",
    ]

    arrow_counts = {"⬆️": 0, "⬇️": 0, "➡️": 0}

    for sym in SNAPSHOT_SYMBOLS:
        r = by_coin.get(sym)
        if not r:
            lines.append(f"🔹 ➖{sym:<6}:   N/A")
            continue
        price = f(r.get("price"))
        if price is None:
            lines.append(f"🔹 ➖{sym:<6}:   N/A")
            continue

        hist = {}
        hist["4h"], _ = _get_historical_price(sym, 4, dt)
        hist["24h"], _ = _get_historical_price(sym, 24, dt)
        hist["7d"], _ = _get_historical_price(sym, 168, dt)

        change24 = f(r.get("change24"))
        arrow, deciding_tf = _get_snapshot_arrow(price, hist, change24)
        arrow_counts[arrow] = arrow_counts.get(arrow, 0) + 1

        line = f"🔹 {arrow}{sym:<6}:   {_snapshot_price_text(price)}"
        details = []
        for tf in ["4h", "24h", "7d"]:
            if hist.get(tf) is not None:
                delta = (price - hist[tf]) / hist[tf] * 100
                details.append(f"{tf}: {delta:+.2f}%")
            else:
                details.append(f"{tf}: N/A")
        line += f"  ({' | '.join(details)})"
        lines.append(line)

    lines.append("───────────────────")
    usdt = fetch_usdt_toman_public()
    if usdt is None:
        lines.append("💵 🟡نرخ تتر  :   در دسترس نیست")
    else:
        lines.append(f"💵 🟢نرخ تتر  :   {usdt:,.0f} تومان")
    lines.append("🔄 این پیام هر ۳ ساعت بروزرسانی می‌شود")

    session, session_label, session_multiplier = get_current_session()
    lines.append(f"🕐 سشن فعلی: {session_label} | ضریب کیفیت: {session_multiplier:.1f}x")
    return "\\n".join(lines)
"""
    for idx, line in enumerate(lines):
        if line.strip().startswith("def build_price_snapshot("):
            start = idx
            end = start
            for j in range(idx+1, total):
                if lines[j].strip().startswith("def "):
                    end = j
                    break
            if end == start:
                end = total
            lines[start:end] = new_build_func.splitlines(True)
            print("✅ تابع build_price_snapshot جایگزین شد.")
            break

    # ========== ۶. جایگزینی send_price_snapshot ==========
    new_send_func = """
def send_price_snapshot(results):
    payload = build_price_snapshot(results)
    parts, sent, errors = send_report(payload)
    return sent, errors
"""
    for idx, line in enumerate(lines):
        if line.strip().startswith("def send_price_snapshot("):
            start = idx
            end = start
            for j in range(idx+1, total):
                if lines[j].strip().startswith("def "):
                    end = j
                    break
            if end == start:
                end = total
            lines[start:end] = new_send_func.splitlines(True)
            print("✅ تابع send_price_snapshot جایگزین شد.")
            break

    # ========== ۷. جایگزینی self_diagnostic ==========
    new_self_diagnostic = """
def self_diagnostic():
    init_sqlite()
    with sqlite_conn() as c:
        rows = c.execute(\"\"\"
            SELECT s.id, s.coin, s.direction, s.outcome, s.pnl_pct, s.feature_vector, s.notes
            FROM signal_outcomes s
            LEFT JOIN self_healing_processed p ON p.signal_id = s.id
            WHERE s.status = 'CLOSED' AND p.signal_id IS NULL
            ORDER BY s.id ASC
        \"\"\").fetchall()
    if len(rows) < ATLAS_SELF_HEAL_BATCH:
        return

    batch_size = ATLAS_SELF_HEAL_BATCH
    for start_i in range(0, len(rows), batch_size):
        chunk = rows[start_i:start_i + batch_size]
        n = len(chunk)
        outcomes = [r["outcome"] for r in chunk]
        pnls = [f(r["pnl_pct"]) for r in chunk if f(r["pnl_pct"]) is not None]
        losses = sum(1 for o in outcomes if o == "SL")
        wins = sum(1 for o in outcomes if o in ("TP", "TP1", "TP2"))
        error_pct = losses / n * 100 if n else 0
        win_pct = wins / n * 100 if n else 0
        sharpe = _compute_sharpe(pnls, min(ATLAS_SHARPE_MIN_PERIOD, len(pnls)))

        loss_feature_counts = {}
        win_feature_counts = {}
        for r in chunk:
            feature_vector = r["feature_vector"]
            if feature_vector:
                try:
                    features = json.loads(feature_vector)
                    for feat, weight in features.items():
                        if r["outcome"] in ("SL", "SL"):
                            loss_feature_counts[feat] = loss_feature_counts.get(feat, 0) + weight
                        else:
                            win_feature_counts[feat] = win_feature_counts.get(feat, 0) + weight
                except:
                    pass
            else:
                text = (r["notes"] or "").lower()
                token_map = {
                    "rsi": "rsi", "macd": "macd", "sma": "higher_trend",
                    "hammer": "candle_pattern", "shooting star": "candle_pattern",
                    "engulfing": "candle_pattern", "pin bar": "candle_pattern",
                    "doji": "candle_pattern", "حجم": "volume", "واگرایی": "rsi"
                }
                for token, feat in token_map.items():
                    if token in text:
                        if r["outcome"] in ("SL", "SL"):
                            loss_feature_counts[feat] = loss_feature_counts.get(feat, 0) + 1
                        else:
                            win_feature_counts[feat] = win_feature_counts.get(feat, 0) + 1
                        break

        if error_pct > 55 and loss_feature_counts:
            feature = max(loss_feature_counts, key=loss_feature_counts.get)
            update_weight(feature, 0.85,
                f"Error rate {error_pct:.0f}% in batch of {n}; reduced weight of {feature} by 15%",
                {"samples": n, "wins": wins, "losses": losses, "error_pct": error_pct, "sharpe": sharpe})

        if win_pct > 60 and win_feature_counts and (sharpe is None or sharpe > 0.5):
            feature = max(win_feature_counts, key=win_feature_counts.get)
            update_weight(feature, 1.10,
                f"Win rate {win_pct:.0f}% and Sharpe {sharpe:.2f} in batch of {n}; increased weight of {feature} by 10%",
                {"samples": n, "wins": wins, "losses": losses, "win_pct": win_pct, "sharpe": sharpe})

        with sqlite_conn() as c:
            c.executemany(
                "INSERT OR IGNORE INTO self_healing_processed(signal_id, processed_at) VALUES (?,?)",
                [(r["id"], now_utc().isoformat()) for r in chunk]
            )
"""
    for idx, line in enumerate(lines):
        if line.strip().startswith("def self_diagnostic():"):
            start = idx
            end = start
            for j in range(idx+1, total):
                if lines[j].strip().startswith("def "):
                    end = j
                    break
            if end == start:
                end = total
            lines[start:end] = new_self_diagnostic.splitlines(True)
            print("✅ تابع self_diagnostic جایگزین شد.")
            break

    # ========== ۸. اصلاح v11_portfolio_diagnostics ==========
    new_portfolio_diag = """
def v11_portfolio_diagnostics(results):
    active = [r for r in results if r.get("executable")]
    weights = {str(r.get("coin", "")).upper(): max(0, _v11_num(r.get("opportunity_score"), 0)) for r in active}
    total = sum(weights.values())
    concentration = {k: round(v/total, 3) for k, v in weights.items()} if total else {}
    warning = "HIGH_CONCENTRATION" if any(v >= ATLAS_V11_MAX_CONCENTRATION for v in concentration.values()) else None
    return {"concentration": concentration, "warning": warning, "high_correlation_pairs": []}
"""
    for idx, line in enumerate(lines):
        if line.strip().startswith("def v11_portfolio_diagnostics("):
            start = idx
            end = start
            for j in range(idx+1, total):
                if lines[j].strip().startswith("def "):
                    end = j
                    break
            if end == start:
                end = total
            lines[start:end] = new_portfolio_diag.splitlines(True)
            print("✅ تابع v11_portfolio_diagnostics جایگزین شد.")
            break

    # ========== ۹. اصلاح v11_apply_intelligence ==========
    for idx, line in enumerate(lines):
        if line.strip().startswith("def v11_apply_intelligence(r):"):
            # اضافه کردن سه خط در ابتدای تابع
            lines.insert(idx+1, '    r["decision_confidence"] = r.get("confidence")\n')
            lines.insert(idx+2, '    r["decision_regime_trend"] = r.get("regime_trend")\n')
            lines.insert(idx+3, '    r["decision_regime_volatility"] = r.get("regime_volatility")\n')
            print("✅ تابع v11_apply_intelligence اصلاح شد.")
            break

    # ========== ۱۰. اصلاح store_signal ==========
    for idx, line in enumerate(lines):
        if line.strip().startswith("def store_signal(result):"):
            for j in range(idx, min(idx+100, total)):
                if "STORE.insert(\"atlas_signals\", row)" in lines[j]:
                    lines.insert(j, '    row["feature_vector"] = safe_json(result.get("score_components", {}))\n')
                    print("✅ feature_vector به store_signal اضافه شد.")
                    break
            break

    # ========== ۱۱. اصلاح apply_decision_engine ==========
    for idx, line in enumerate(lines):
        if line.strip().startswith("def apply_decision_engine(results, btc_regime, breadth):"):
            # اضافه کردن global
            lines.insert(idx+1, '    global _LAST_BACKTEST_OK\n')
            # پیدا کردن محل اضافه کردن کد backtest gate
            for j in range(idx, min(idx+200, total)):
                if 'reasons.append("Short crowded (negative funding rate)")' in lines[j]:
                    backtest_gate_code = '''
            # FIX: backtest gate blocks executable signals
            if not _LAST_BACKTEST_OK and state in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append("Backtest gate failed — execution frozen, watch-only")
'''
                    lines.insert(j+1, backtest_gate_code)
                    print("✅ Backtest gate به apply_decision_engine اضافه شد.")
                    break
            break

    # ========== ۱۲. اصلاح report() ==========
    for idx, line in enumerate(lines):
        if line.strip().startswith("def report():"):
            # اضافه کردن global
            lines.insert(idx+1, '    global _LAST_TOP10, _LAST_DYNAMIC30, _LAST_BACKTEST_OK, _LAST_BACKTEST_DETAILS\n')
            # پیدا کردن محل تنظیم _LAST_BACKTEST_OK
            for j in range(idx, min(idx+50, total)):
                if 'backtest_ok, bt = mandatory_backtest_gate(universe)' in lines[j]:
                    code = '    _LAST_BACKTEST_OK, _LAST_BACKTEST_DETAILS = bool(backtest_ok), (bt or {})\n'
                    lines.insert(j+1, code)
                    print("✅ report() اصلاح شد.")
                    break
            break

    # ========== ۱۳. اضافه کردن متغیرهای global ==========
    global_vars = '''
_LAST_BACKTEST_OK = True
_LAST_BACKTEST_DETAILS = {}
'''
    for idx, line in enumerate(lines):
        if '_LAST_TOP10 = []' in line:
            for j in range(idx, min(idx+5, total)):
                if '_LAST_DYNAMIC30 = []' in lines[j]:
                    lines.insert(j+1, global_vars)
                    print("✅ متغیرهای global اضافه شدند.")
                    break
            break

    # ========== نوشتن فایل جدید ==========
    output_path = file_path.replace('.py', '_updated.py')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"✅ فایل جدید با نام {output_path} ذخیره شد.")
    print("لطفاً تغییرات را بررسی کرده و در صورت تأیید، آن را جایگزین bot.py کنید.")

if __name__ == "__main__":
    target = "bot.py"
    if len(sys.argv) > 1:
        target = sys.argv[1]
    if not os.path.exists(target):
        print(f"❌ فایل {target} یافت نشد.")
        sys.exit(1)
    apply_patches(target)
