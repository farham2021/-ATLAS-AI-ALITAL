#!/usr/bin/env python3
from pathlib import Path
import ast, re, sys

BOT = Path("bot.py")

def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)

if not BOT.exists():
    fail("bot.py not found")

s = BOT.read_text(encoding="utf-8")
try:
    tree = ast.parse(s, filename=str(BOT))
except SyntaxError as e:
    fail(f"bot.py syntax error: {e}")

funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

required = [
    "build_report", "build_personal_report", "build_two_engine_reports",
    "atlas_engine_mode", "analyze_coin", "main",
    "tradingview_chart_url", "build_price_snapshot",
    "_compact_scenario_row", "_compact_section", "_final_market_recommendation",
    "send_price_snapshot", "fetch_usdt_toman_public",
    "fetch_snapshot_results", "_automatic_run_plan", "generate_csv_report", "send_csv_report", "_best_setup_block",
    # Voice functions
    "generate_voice_summary", "text_to_speech_persian", "generate_audio_report", "send_audio_report",
    # Session functions
    "get_current_session",
]
missing = [x for x in required if x not in funcs]
if missing:
    fail("missing required functions: " + ", ".join(missing))

# Check for MARKET_SESSIONS variable (not a function)
if "MARKET_SESSIONS" not in s:
    fail("MARKET_SESSIONS dictionary not found")

checks = {
    "version v11.1": bool(re.search(r'^VERSION\s*=\s*["\']ATLAS v11\.1', s, re.M)),
    "no stale v10 markers": not bool(re.search(r'ATLAS v10|v10\.[0-9]|10\.2', s)),
    "single build_report": funcs.count("build_report") == 1,
    "single build_personal_report": funcs.count("build_personal_report") == 1,
    "single build_two_engine_reports": funcs.count("build_two_engine_reports") == 1,
    "single personal_report alias": funcs.count("personal_report") == 1,
    "two-engine": all(x in s for x in ("MARKET", "PERSONAL", "BOTH")),
    "personal portfolio": "ATLAS_PERSONAL_ASSETS" in s,
    "market excludes personal": "market_results" in s and "not in personal_symbols" in s,
    "metals": "ATLAS_METALS" in s and all(x in s for x in ("GOLD", "SILVER", "COPPER")),
    "TradingView links": "tradingview.com/chart/?symbol=" in s,
    "separate 3h snapshot": "send_price_snapshot" in s and "این پیام هر ۳ ساعت" in s,
    "snapshot-only path": "fetch_snapshot_results" in s and 'run_mode == "SNAPSHOT"' in s,
    "automatic 3h/4h scheduler": "_automatic_run_plan" in s and "dt.hour % 3 == 0" in s and "dt.hour % 4 == 0" in s,
    "public Iranian USDT sources": all(x in s.lower() for x in ("wallex.ir", "excoino.com", "nobitex.ir")),
    "KCEX CCXT source": '"kcex"' in s,
    "closed-candle logic": "strip_incomplete" in s and "candle_is_closed" in s,
    "compact table output": all(x in s for x in ("_compact_scenario_row", "کلیدی:", "🟢 صعودی:", "🔴 نزولی:")),
    "no verbose market headings": "TOP 5 OPPORTUNITIES" not in s[s.index("def build_report"):s.index("def build_personal_report")],
    "no verbose personal headings": "🧠 ATLAS MEMORY / CALIBRATION" not in s[s.index("def build_personal_report"):s.index("def personal_report")],
    "all dynamic30 output": "dyn30_rows" in s and "DYNAMIC TOP 30" in s and "خارج از Top 10 و Personal" in s,
    "metals in compact market output": "ATLAS METALS — GOLD / SILVER / COPPER" in s,
    "trade geometry gate": "_validate_trade_geometry" in s and "invalid LONG geometry" in s and "invalid SHORT geometry" in s,
    "negative/contradictory TP blocked": "non-positive trade level" in s and "Trade geometry blocked" in s,
    "snapshot compares previous price": "_snapshot_previous_prices" in s and "_snapshot_direction" in s and "SNAPSHOT_FLAT_THRESHOLD_PCT" in s,
    "snapshot persists after successful send": "if sent == parts and sent > 0" in s and "_save_snapshot_prices" in s,
    "dashboard table": "build_dashboard_table" in s and "ATLAS AI — DASHBOARD TABLE" in s and "PERSONAL PORTFOLIO" in s,
    "dynamic30 compact output capped": "dyn30_all_rows" in s and "dynamic_top8(" in s,
    "no duplicate portfolio function": s.count("def _portfolio_rows(") == 1,
    "dynamic CSV export": "CSV_COLUMNS" in s and "def generate_csv_report(" in s and "def send_csv_report(" in s,
    "CSV includes all universes": all(x in s for x in ("MARKET_TOP10", "DYNAMIC_TOP30", "PERSONAL_PORTFOLIO")),
    "best setup validation": "def _best_setup_block(" in s and "MIN_EXECUTABLE_RR" in s and "repeat_signal" in s,
    "CSV invalid geometry suppressed": "_csv_safe_plan" in s and "_validate_trade_geometry" in s,
    "snapshot arrows": "⬆️" in s and "⬇️" in s and "SNAPSHOT_FLAT_THRESHOLD_PCT" in s,
    # Voice checks
    "voice summary": "generate_voice_summary" in s,
    "voice output": "send_audio_report" in s and "ATLAS_ENABLE_VOICE" in s,
    "session support": "get_current_session" in s and "MARKET_SESSIONS" in s and "multiplier" in s,
    "session in snapshot": "سشن فعلی" in s and "ضریب کیفیت" in s,
    # New confidence and volume ratio checks
    "min confidence 55": "MIN_CONFIDENCE = float(os.environ.get(\"ATLAS_MIN_CONFIDENCE\", \"55\"))" in s,
    "min volume ratio 0.60": "MIN_VOLUME_RATIO = float(os.environ.get(\"ATLAS_MIN_VOLUME_RATIO\", \"0.60\"))" in s,
    # Invalidation & No-Trade checks (checking for import and usage, not functions)
    "signal lifecycle import": "from core.invalidation import" in s or "import core.invalidation" in s,
    "signal id in results": "signal_id" in s and "create_signal" in s,
    "no-trade in results": "no_trade_reasons" in s and "should_trade" in s,
    "contradiction in results": "contradictions" in s and "HIGH_CONTRADICTION" in s,
}
for name, ok in checks.items():
    if not ok:
        fail(name)

compile(s, str(BOT), "exec")
print("PASS: ATLAS v11.1 unified two-engine + metals + snapshot + voice + session + invalidation smoke test")
for name in checks:
    print("  OK:", name)
