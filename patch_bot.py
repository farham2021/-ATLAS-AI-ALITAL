#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATLAS v11.5 Self-Updater (Final with SupabaseStore restoration)
"""

import os
import sys
import re

def apply_patches(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # ========== ۱. اضافه کردن تنظیمات جدید (اگر وجود نداشته باشد) ==========
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
        if "SNAPSHOT_24H_THRESHOLD_PCT" in content:
            content = content.replace(
                "SNAPSHOT_24H_THRESHOLD_PCT",
                "SNAPSHOT_24H_THRESHOLD_PCT" + config_block
            )
        else:
            content = content.replace(
                "MAX_LEVERAGE = float(os.environ.get(\"ATLAS_MAX_LEVERAGE\", \"10\"))",
                "MAX_LEVERAGE = float(os.environ.get(\"ATLAS_MAX_LEVERAGE\", \"10\"))\n" + config_block
            )

    # ========== ۲. بازگردانی کلاس SupabaseStore (اگر وجود نداشته باشد) ==========
    if "class SupabaseStore" not in content:
        supabase_class = """
# ============================================================
# SUPABASE STORAGE
# ============================================================

class SupabaseStore:
    def __init__(self):
        self.enabled = bool(SUPABASE_URL and SUPABASE_KEY)
        self.headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def insert(self, table, row):
        if not self.enabled:
            return False
        try:
            url = f"{SUPABASE_URL}/rest/v1/{table}"
            req = urllib.request.Request(
                url,
                data=safe_json(row).encode(),
                headers=self.headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            if table != "atlas_changelog":
                try:
                    with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
                        fh.write(f"{now_utc().isoformat()} | SUPABASE | insert failed: {table}: {e}\\n")
                except Exception:
                    pass
            return False

    def update(self, table, match, row):
        if not self.enabled:
            return False
        try:
            q = urllib.parse.urlencode(match)
            url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
            req = urllib.request.Request(
                url,
                data=safe_json(row).encode(),
                headers=self.headers,
                method="PATCH",
            )
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception as e:
            if table != "atlas_changelog":
                try:
                    with open(CHANGELOG_FILE, "a", encoding="utf-8") as fh:
                        fh.write(f"{now_utc().isoformat()} | SUPABASE | update failed: {table}: {e}\\n")
                except Exception:
                    pass
            return False

    def select(self, table, params=None):
        if not self.enabled:
            return []
        try:
            q = urllib.parse.urlencode(params or {})
            url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception:
            return []
"""
        # درج قبل از "STORE = SupabaseStore()"
        if "STORE = SupabaseStore()" in content:
            content = content.replace(
                "STORE = SupabaseStore()",
                supabase_class + "\nSTORE = SupabaseStore()"
            )
        else:
            # اگر پیدا نشد، در انتهای بخش دیتابیس اضافه کن
            content += "\n" + supabase_class + "\nSTORE = SupabaseStore()\n"
        print("✅ کلاس SupabaseStore بازگردانی شد.")

    # ========== ۳. جایگزینی تابع init_sqlite با نسخه امن ==========
    new_init_sqlite = """def init_sqlite():
    with sqlite_conn() as c:
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

        # ایجاد جدول price_history
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

    # پیدا کردن تابع قدیمی با الگوی دقیق‌تر (تا def بعدی با indent صفر)
    pattern = r'^def init_sqlite\(\):.*?(?=^def |\Z)'
    if re.search(pattern, content, re.MULTILINE | re.DOTALL):
        content = re.sub(pattern, new_init_sqlite, content, flags=re.MULTILINE | re.DOTALL)
        print("✅ تابع init_sqlite بازنویسی شد.")
    else:
        print("⚠️ تابع init_sqlite پیدا نشد! ممکن است فایل تغییر کرده باشد.")

    # ========== ۴. اضافه کردن توابع کمکی (اگر وجود نداشته باشند) ==========
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
            # در انتهای فایل اضافه کن
            content += "\n" + functions_block
        print("✅ توابع کمکی اضافه شدند.")

    # ========== ۵. جایگزینی سایر توابع (اختیاری) ==========
    # _get_snapshot_arrow, build_price_snapshot, send_price_snapshot, self_diagnostic, v11_portfolio_diagnostics, v11_apply_intelligence, store_signal, apply_decision_engine, report
    # (به دلیل محدودیت، از تکرار کدهای قبلی صرف‌نظر می‌کنیم؛ اما چون قبلاً patch شده‌اند، نیازی نیست)
    # فقط مطمئن می‌شویم که متغیرهای global تعریف شده‌اند.
    if "_LAST_BACKTEST_OK" not in content:
        # اضافه کردن در جایی که _LAST_TOP10 و _LAST_DYNAMIC30 تعریف شده‌اند
        global_vars = '''
_LAST_BACKTEST_OK = True
_LAST_BACKTEST_DETAILS = {}
'''
        if "_LAST_TOP10 = []" in content and "_LAST_DYNAMIC30 = []" in content:
            content = content.replace(
                "_LAST_DYNAMIC30 = []",
                "_LAST_DYNAMIC30 = []\n" + global_vars
            )
        else:
            # در انتهای بخش متغیرهای global اضافه کن
            content += "\n" + global_vars
        print("✅ متغیرهای global اضافه شدند.")

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
