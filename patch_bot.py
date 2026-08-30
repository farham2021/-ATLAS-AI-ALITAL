#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATLAS v11.5 Self-Updater
این اسکریپت تمام اصلاحات مورد نیاز را روی bot.py اعمال می‌کند.
استفاده: python patch_bot.py
"""

import os
import re
import shutil
from datetime import datetime

# ============================================================
# 1. لیست تغییرات (به صورت توابع)
# ============================================================

def apply_patches(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # تبدیل به لیست برای ویرایش
    new_lines = []
    i = 0
    total = len(lines)

    # ========== تغییر ۱: اضافه کردن تنظیمات جدید (بعد از SNAPSHOT_24H_THRESHOLD_PCT) ==========
    # جستجوی خط حاوی SNAPSHOT_24H_THRESHOLD_PCT
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
    # پیدا کردن خط SNAPSHOT_24H_THRESHOLD_PCT
    found = False
    for idx, line in enumerate(lines):
        if "SNAPSHOT_24H_THRESHOLD_PCT" in line:
            # درج بعد از این خط
            lines.insert(idx+1, config_insert)
            found = True
            break
    if not found:
        print("⚠️ خط SNAPSHOT_24H_THRESHOLD_PCT پیدا نشد. تنظیمات جدید اضافه نشد.")
    else:
        print("✅ تنظیمات جدید اضافه شد.")

    # ========== تغییر ۲: به‌روزرسانی تابع init_sqlite ==========
    # جستجوی create table if not exists signal_outcomes و اضافه کردن feature_vector
    # همچنین ایجاد جدول price_history
    new_sql = """
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
            notes text,
            feature_vector text
        );
"""
    # جستجوی خط create table signal_outcomes و جایگزینی با نسخه جدید
    # ساده‌تر: پیدا کردن خط حاوی "create table if not exists signal_outcomes" و سپس جایگزینی کل بلوک تا ");"
    # پیاده‌سازی ساده‌تر: با استفاده از regex کل CREATE TABLE را بیابیم و جایگزین کنیم.
    # اما برای اطمینان، ما یک تابع کمکی برای جایگزینی بلوک می‌نویسیم.
    # به دلیل پیچیدگی، بهتر است که به‌جای جایگزینی، دستور ALTER TABLE را اضافه کنیم.
    # اما SQLite از ALTER TABLE برای اضافه کردن ستون پشتیبانی می‌کند.
    # بنابراین در انتهای init_sqlite، بعد از executescript، دستورات ALTER را اضافه می‌کنیم.
    # همچنین جدول price_history را اضافه می‌کنیم.

    alter_commands = """
        -- اضافه کردن ستون feature_vector به signal_outcomes
        ALTER TABLE signal_outcomes ADD COLUMN feature_vector text;
        -- ایجاد جدول price_history
        CREATE TABLE IF NOT EXISTS price_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            captured_at TEXT NOT NULL,
            timeframe TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_price_history_symbol_timeframe ON price_history(symbol, timeframe, captured_at DESC);
"""
    # پیدا کردن انتهای تابع init_sqlite (با جستجوی "def init_sqlite():" و سپس "with sqlite_conn() as c:")
    # و سپس درج alter_commands قبل از closing of with.
    # ساده‌تر: بعد از c.executescript(""" ... """)، یک c.executescript دیگر با alter_commands اضافه کنیم.
    # جستجوی خطی که شامل "c.executescript(""" است و بعد از آن یک c.executescript دیگر درج کنیم.
    init_found = False
    for idx, line in enumerate(lines):
        if "def init_sqlite():" in line:
            # پیدا کردن خطی که شامل "c.executescript(\"\"\"" است
            for j in range(idx, min(idx+50, total)):
                if 'c.executescript("""' in lines[j]:
                    # درج بعد از خطی که با """ بسته می‌شود (پیدا کردن خط بعد از """)
                    for k in range(j, min(j+200, total)):
                        if '""")' in lines[k] and '"""' in lines[k]:
                            # درج کد جدید بعد از این خط
                            lines.insert(k+1, f'        c.executescript("""{alter_commands}""")')
                            init_found = True
                            break
                    break
            break
    if not init_found:
        print("⚠️ نتوانستیم init_sqlite را پیدا کنیم. تغییرات دیتابیس اعمال نشد.")
    else:
        print("✅ تغییرات دیتابیس اعمال شد.")

    # ========== تغییر ۳: اضافه کردن توابع کمکی جدید (قبل از build_price_snapshot) ==========
    # ما یک نشانه‌گذاری داریم: "# ============================================================\n# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT"
    # قبل از آن، توابع جدید را اضافه می‌کنیم.
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
    # پیدا کردن خطی که شامل "# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT" است
    snapshot_marker = "# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT"
    for idx, line in enumerate(lines):
        if snapshot_marker in line:
            # درج توابع جدید قبل از این خط
            lines.insert(idx, new_functions)
            print("✅ توابع کمکی جدید اضافه شد.")
            break
    else:
        print("⚠️ نشانه SNAPSHOT پیدا نشد. توابع جدید اضافه نشد.")

    # ========== تغییر ۴: جایگزینی تابع _get_snapshot_arrow ==========
    # یافتن تعریف تابع و جایگزینی با کد جدید
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
    # پیدا کردن خط "def _get_snapshot_arrow"
    arrow_found = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("def _get_snapshot_arrow("):
            # پیدا کردن انتهای تابع (تا خط بعدی که با def شروع شود یا به انتها برسد)
            start = idx
            end = start
            for j in range(idx+1, total):
                if lines[j].strip().startswith("def "):
                    end = j
                    break
            if end == start:
                end = total
            # جایگزینی با تابع جدید
            lines[start:end] = new_arrow_func.splitlines(True)
            arrow_found = True
            print("✅ تابع _get_snapshot_arrow جایگزین شد.")
            break
    if not arrow_found:
        print("⚠️ تابع _get_snapshot_arrow پیدا نشد.")

    # ========== تغییر ۵: جایگزینی تابع build_price_snapshot ==========
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
    # پیدا کردن تابع build_price_snapshot
    build_found = False
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
            build_found = True
            print("✅ تابع build_price_snapshot جایگزین شد.")
            break
    if not build_found:
        print("⚠️ تابع build_price_snapshot پیدا نشد.")

    # ========== تغییر ۶: جایگزینی تابع send_price_snapshot ==========
    new_send_func = """
def send_price_snapshot(results):
    payload = build_price_snapshot(results)
    parts, sent, errors = send_report(payload)
    return sent, errors
"""
    send_found = False
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
            send_found = True
            print("✅ تابع send_price_snapshot جایگزین شد.")
            break
    if not send_found:
        print("⚠️ تابع send_price_snapshot پیدا نشد.")

    # ========== تغییر ۷: جایگزینی تابع self_diagnostic ==========
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
    self_diag_found = False
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
            self_diag_found = True
            print("✅ تابع self_diagnostic جایگزین شد.")
            break
    if not self_diag_found:
        print("⚠️ تابع self_diagnostic پیدا نشد.")

    # ========== تغییر ۸: جایگزینی تابع v11_portfolio_diagnostics ==========
    new_portfolio_diag = """
def v11_portfolio_diagnostics(results):
    active = [r for r in results if r.get("executable")]
    weights = {str(r.get("coin", "")).upper(): max(0, _v11_num(r.get("opportunity_score"), 0)) for r in active}
    total = sum(weights.values())
    concentration = {k: round(v/total, 3) for k, v in weights.items()} if total else {}
    warning = "HIGH_CONCENTRATION" if any(v >= ATLAS_V11_MAX_CONCENTRATION for v in concentration.values()) else None
    return {"concentration": concentration, "warning": warning, "high_correlation_pairs": []}
"""
    port_found = False
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
            port_found = True
            print("✅ تابع v11_portfolio_diagnostics جایگزین شد.")
            break
    if not port_found:
        print("⚠️ تابع v11_portfolio_diagnostics پیدا نشد.")

    # ========== تغییر ۹: اصلاح تابع v11_apply_intelligence ==========
    # اضافه کردن دو خط در ابتدای تابع
    v11_apply_found = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("def v11_apply_intelligence(r):"):
            # درج بعد از خط بعدی (بعد از def)
            lines.insert(idx+1, '    r["decision_confidence"] = r.get("confidence")\n')
            lines.insert(idx+2, '    r["decision_regime_trend"] = r.get("regime_trend")\n')
            lines.insert(idx+3, '    r["decision_regime_volatility"] = r.get("regime_volatility")\n')
            v11_apply_found = True
            print("✅ تابع v11_apply_intelligence اصلاح شد (اضافه کردن decision_*).")
            break
    if not v11_apply_found:
        print("⚠️ تابع v11_apply_intelligence پیدا نشد.")

    # ========== تغییر ۱۰: اصلاح تابع store_signal ==========
    # اضافه کردن feature_vector
    store_found = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("def store_signal(result):"):
            # پیدا کردن جایی که row = { ... } تعریف شده و feature_vector را اضافه کنیم
            # ساده‌تر: بعد از تعریف row، یک خط اضافه کنیم که feature_vector بسازد
            # و در dictionary insert آن را اضافه کنیم
            # ما به دنبال خطی هستیم که شامل "STORE.insert("atlas_signals", row)" است و قبل از آن feature_vector را به row اضافه کنیم.
            for j in range(idx, min(idx+100, total)):
                if "STORE.insert(\"atlas_signals\", row)" in lines[j]:
                    # قبل از این خط، feature_vector را به row اضافه کنیم
                    lines.insert(j, '    row["feature_vector"] = safe_json(result.get("score_components", {}))\n')
                    store_found = True
                    break
            break
    if not store_found:
        print("⚠️ تابع store_signal پیدا نشد یا feature_vector اضافه نشد.")
    else:
        print("✅ feature_vector به store_signal اضافه شد.")

    # ========== تغییر ۱۱: اصلاح تابع apply_decision_engine ==========
    # اضافه کردن global _LAST_BACKTEST_OK در ابتدا و کد backtest gate
    apply_found = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("def apply_decision_engine(results, btc_regime, breadth):"):
            # بعد از خط def، global اضافه کنیم
            lines.insert(idx+1, '    global _LAST_BACKTEST_OK\n')
            # پیدا کردن جایی که بعد از بخش derivatives، کد backtest gate را اضافه کنیم
            # جستجوی "if r.get(\"regime_derivatives\") == \"SHORT_CROWDED\""
            for j in range(idx, min(idx+200, total)):
                if 'if r.get("regime_derivatives") == "SHORT_CROWDED"' in lines[j]:
                    # بعد از این بلوک (پیدا کردن خط بعدی که با if شروع نشود) کد جدید را اضافه کنیم
                    # برای سادگی، بعد از خط j+1 (که احتمالاً "if state == \"SELL CONFIRMATION\"" است) اضافه می‌کنیم.
                    # بهتر است بعد از کل بلوک derivatives
                    # من یک نشانه‌گذاری می‌کنم: بعد از "reasons.append(\"Short crowded (negative funding rate)\")" اضافه کنم.
                    for k in range(j, min(j+20, total)):
                        if 'reasons.append("Short crowded (negative funding rate)")' in lines[k]:
                            # بعد از این خط، کد backtest gate را درج کنیم
                            backtest_gate_code = '''
            # FIX: backtest gate blocks executable signals
            if not _LAST_BACKTEST_OK and state in ("BUY CONFIRMATION", "SELL CONFIRMATION"):
                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"
                reasons.append("Backtest gate failed — execution frozen, watch-only")
'''
                            lines.insert(k+1, backtest_gate_code)
                            apply_found = True
                            break
                    break
            break
    if not apply_found:
        print("⚠️ تابع apply_decision_engine اصلاح نشد (Backtest gate اضافه نشد).")
    else:
        print("✅ Backtest gate به apply_decision_engine اضافه شد.")

    # ========== تغییر ۱۲: اصلاح تابع report() ==========
    # اضافه کردن global _LAST_BACKTEST_OK, _LAST_BACKTEST_DETAILS
    report_found = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("def report():"):
            # بعد از خط def، global اضافه کنیم
            lines.insert(idx+1, '    global _LAST_TOP10, _LAST_DYNAMIC30, _LAST_BACKTEST_OK, _LAST_BACKTEST_DETAILS\n')
            # پیدا کردن خط "backtest_ok, bt = mandatory_backtest_gate(universe)"
            for j in range(idx, min(idx+50, total)):
                if 'backtest_ok, bt = mandatory_backtest_gate(universe)' in lines[j]:
                    # بعد از این خط، کد تنظیم _LAST_BACKTEST_OK را اضافه کنیم
                    code = '    _LAST_BACKTEST_OK, _LAST_BACKTEST_DETAILS = bool(backtest_ok), (bt or {})\n'
                    lines.insert(j+1, code)
                    report_found = True
                    break
            break
    if not report_found:
        print("⚠️ تابع report() اصلاح نشد.")
    else:
        print("✅ report() اصلاح شد.")

    # ========== تغییر ۱۳: اضافه کردن متغیرهای global در ابتدای فایل (بعد از بخش DATABASE) ==========
    # جستجوی جایی که _LAST_TOP10 و _LAST_DYNAMIC30 تعریف شده‌اند و بعد از آنها اضافه کنیم
    global_vars = '''
_LAST_BACKTEST_OK = True
_LAST_BACKTEST_DETAILS = {}
'''
    for idx, line in enumerate(lines):
        if '_LAST_TOP10 = []' in line:
            # بعد از این خط و خط بعدی که _LAST_DYNAMIC30 = [] است، اضافه کنیم
            # پیدا کردن خط بعدی که شامل _LAST_DYNAMIC30 باشد
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
    import sys
    target = "bot.py"
    if len(sys.argv) > 1:
        target = sys.argv[1]
    if not os.path.exists(target):
        print(f"❌ فایل {target} یافت نشد.")
        sys.exit(1)
    apply_patches(target)
