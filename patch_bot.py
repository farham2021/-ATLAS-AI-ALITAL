#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATLAS v11.5 Ultimate Patcher
این اسکریپت تمام مشکلات bot.py را برطرف می‌کند.
"""

import os
import sys
import re

def apply_patches(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # ========== ۱. اضافه کردن تنظیمات جدید (اگر وجود نداشته باشند) ==========
    if "SNAPSHOT_4H_THRESHOLD_PCT" not in content:
        config_block = """
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
        # درج بعد از SNAPSHOT_24H_THRESHOLD_PCT
        if "SNAPSHOT_24H_THRESHOLD_PCT" in content:
            content = content.replace(
                "SNAPSHOT_24H_THRESHOLD_PCT",
                "SNAPSHOT_24H_THRESHOLD_PCT" + config_block
            )
        else:
            # در غیر این صورت، در انتهای بخش CONFIG اضافه کن
            content = content.replace(
                "MAX_LEVERAGE = float(os.environ.get(\"ATLAS_MAX_LEVERAGE\", \"10\"))",
                "MAX_LEVERAGE = float(os.environ.get(\"ATLAS_MAX_LEVERAGE\", \"10\"))\n" + config_block
            )
        print("✅ تنظیمات جدید اضافه شد.")

    # ========== ۲. تعریف متغیرهای _LAST_BACKTEST_* (اگر وجود نداشته باشند) ==========
    if "_LAST_BACKTEST_OK" not in content:
        global_vars = """
_LAST_BACKTEST_OK = True
_LAST_BACKTEST_DETAILS = {}
"""
        # پیدا کردن محل _LAST_TOP10 و _LAST_DYNAMIC30
        if "_LAST_TOP10 = []" in content and "_LAST_DYNAMIC30 = []" in content:
            content = content.replace(
                "_LAST_DYNAMIC30 = []",
                "_LAST_DYNAMIC30 = []\n" + global_vars
            )
        else:
            content += "\n" + global_vars
        print("✅ متغیرهای _LAST_BACKTEST_* اضافه شدند.")

    # ========== ۳. جایگزینی تابع `self_diagnostic` با نسخه v11.5 ==========
    # این نسخه از بچ ۱۵، پاداش برنده و Sharpe استفاده می‌کند
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
    # جایگزینی تابع قدیمی
    pattern = r'^def self_diagnostic\(\):.*?(?=^def |\Z)'
    if re.search(pattern, content, re.MULTILINE | re.DOTALL):
        content = re.sub(pattern, new_self_diagnostic, content, flags=re.MULTILINE | re.DOTALL)
        print("✅ تابع self_diagnostic به‌روز شد.")
    else:
        print("⚠️ تابع self_diagnostic پیدا نشد.")

    # ========== ۴. اضافه کردن توابع کمکی جدید (اگر وجود نداشته باشند) ==========
    if "_save_price_history" not in content:
        functions_block = """
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
        # درج قبل از "# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT"
        if "# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT" in content:
            content = content.replace(
                "# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT",
                functions_block + "\n# ATLAS v11.0 — SEPARATE 3H PRICE SNAPSHOT"
            )
        else:
            content += "\n" + functions_block
        print("✅ توابع کمکی اضافه شدند.")

    # ========== ۵. اصلاح تابع v11_apply_intelligence (نگهداری نسخه v11.4) ==========
    # اگر نسخه v11.1 وجود دارد، آن را با نسخه v11.4 جایگزین کنیم
    # برای سادگی، فقط مطمئن می‌شویم که تابع v11_apply_intelligence از فیلدهای decision_* استفاده کند
    # ولی چون در فایل فعلی دو نسخه وجود دارد، بهتر است نسخه v11.4 را نگه داریم.
    # ما در اینجا یک پچ کوچک اضافه می‌کنیم که در ابتدای تابع، decision_* را حفظ کند.
    # ولی چون ممکن است تداخل ایجاد شود، بهتر است کاربر یکی از نسخه‌ها را حذف کند.
    # در اینجا اخطار می‌دهیم.
    if "def v11_apply_intelligence(r):" in content:
        # بررسی اینکه آیا decision_* در ابتدا اضافه شده یا نه
        if "decision_confidence" not in content:
            # اضافه کردن سه خط در ابتدای تابع
            pattern_func = r'(def v11_apply_intelligence\(r\):.*?)(?=\n    )'
            replacement = r'\1\n    r["decision_confidence"] = r.get("confidence")\n    r["decision_regime_trend"] = r.get("regime_trend")\n    r["decision_regime_volatility"] = r.get("regime_volatility")\n    '
            content = re.sub(pattern_func, replacement, content, flags=re.DOTALL)
            print("✅ decision_* به v11_apply_intelligence اضافه شد.")
        else:
            print("ℹ️ decision_* قبلاً در v11_apply_intelligence وجود دارد.")
    else:
        print("⚠️ تابع v11_apply_intelligence پیدا نشد.")

    # ========== ۶. اصلاح تابع store_signal برای اضافه کردن feature_vector ==========
    if "row[\"feature_vector\"]" not in content:
        # پیدا کردن محل STORE.insert و قبل از آن feature_vector را اضافه کنیم
        if "STORE.insert(\"atlas_signals\", row)" in content:
            content = content.replace(
                "STORE.insert(\"atlas_signals\", row)",
                '    row["feature_vector"] = safe_json(result.get("score_components", {}))\n    STORE.insert("atlas_signals", row)'
            )
            print("✅ feature_vector به store_signal اضافه شد.")
        else:
            print("⚠️ STORE.insert(\"atlas_signals\") پیدا نشد.")

    # ========== ۷. اصلاح تابع apply_decision_engine برای اضافه کردن global و backtest gate ==========
    if "global _LAST_BACKTEST_OK" not in content:
        # پیدا کردن def apply_decision_engine
        if "def apply_decision_engine(results, btc_regime, breadth):" in content:
            content = content.replace(
                "def apply_decision_engine(results, btc_regime, breadth):",
                "def apply_decision_engine(results, btc_regime, breadth):\n    global _LAST_BACKTEST_OK"
            )
            # اضافه کردن کد backtest gate
            # پیدا کردن "reasons.append(\"Short crowded (negative funding rate)\")"
            if 'reasons.append("Short crowded (negative funding rate)")' in content:
                content = content.replace(
                    'reasons.append("Short crowded (negative funding rate)")',
                    'reasons.append("Short crowded (negative funding rate)")\n            # FIX: backtest gate blocks executable signals\n            if not _LAST_BACKTEST_OK and state in ("BUY CONFIRMATION", "SELL CONFIRMATION"):\n                state = "BULLISH WATCH" if direction == "LONG" else "BEARISH WATCH"\n                reasons.append("Backtest gate failed — execution frozen, watch-only")'
                )
            print("✅ apply_decision_engine اصلاح شد.")
        else:
            print("⚠️ apply_decision_engine پیدا نشد.")

    # ========== ۸. اصلاح تابع report() برای تنظیم _LAST_BACKTEST_OK ==========
    if "_LAST_BACKTEST_OK" in content and "backtest_ok, bt = mandatory_backtest_gate(universe)" in content:
        # پیدا کردن خط و اضافه کردن کد تنظیم
        content = content.replace(
            "backtest_ok, bt = mandatory_backtest_gate(universe)",
            "backtest_ok, bt = mandatory_backtest_gate(universe)\n    _LAST_BACKTEST_OK, _LAST_BACKTEST_DETAILS = bool(backtest_ok), (bt or {})"
        )
        print("✅ report() اصلاح شد.")
    else:
        print("⚠️ report() اصلاح نشد (خط mandatory_backtest_gate پیدا نشد).")

    # ========== نوشتن فایل جدید ==========
    output_path = file_path.replace('.py', '_updated.py')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ فایل جدید با نام {output_path} ذخیره شد.")

if __name__ == "__main__":
    target = "bot.py"
    if len(sys.argv) > 1:
        target = sys.argv[1]
    if not os.path.exists(target):
        print(f"❌ فایل {target} یافت نشد.")
        sys.exit(1)
    apply_patches(target)
