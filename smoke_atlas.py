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
    "send_price_snapshot", "fetch_usdt_toman_public",
    "fetch_snapshot_results", "_automatic_run_plan",
]
missing = [x for x in required if x not in funcs]
if missing:
    fail("missing required functions: " + ", ".join(missing))

checks = {
    "version v11.0": bool(re.search(r'^VERSION\s*=\s*["\']ATLAS v11\.0', s, re.M)),
    "no stale v10 markers": not bool(re.search(r'ATLAS v10|v10\.[0-9]|10\.2', s)),
    "single build_report": funcs.count("build_report") == 1,
    "single build_personal_report": funcs.count("build_personal_report") == 1,
    "single build_two_engine_reports": funcs.count("build_two_engine_reports") == 1,
    "single personal_report alias": funcs.count("personal_report") == 1,
    "two-engine": all(x in s for x in ("MARKET", "PERSONAL", "BOTH")),
    "personal portfolio": "ATLAS_PERSONAL_ASSETS" in s,
    "market excludes personal": "market_results" in s and "exclude_symbols=personal_symbols" in s,
    "metals": "ATLAS_METALS" in s and all(x in s for x in ("GOLD", "SILVER", "COPPER")),
    "TradingView links": "tradingview.com/chart/?symbol=" in s,
    "separate 3h snapshot": "send_price_snapshot" in s and "این پیام هر ۳ ساعت" in s,
    "snapshot-only path": "fetch_snapshot_results" in s and 'run_mode == "SNAPSHOT"' in s,
    "automatic 3h/4h scheduler": "_automatic_run_plan" in s and "dt.hour % 3 == 0" in s and "dt.hour % 4 == 0" in s,
    "public Iranian USDT sources": all(x in s.lower() for x in ("wallex.ir", "excoino.com", "nobitex.ir")),
    "KCEX CCXT source": '"kcex"' in s,
    "closed-candle logic": "strip_incomplete" in s and "candle_is_closed" in s,
}
for name, ok in checks.items():
    if not ok:
        fail(name)

compile(s, str(BOT), "exec")
print("PASS: ATLAS v11.0 unified two-engine + metals + snapshot smoke test")
for name in checks:
    print("  OK:", name)
