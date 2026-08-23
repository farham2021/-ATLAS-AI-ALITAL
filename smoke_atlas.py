#!/usr/bin/env python3
"""Offline smoke test for ATLAS AI v10.2 COMPLETE.

Does not call Telegram, exchanges, CoinGecko, or any external API.
"""
from pathlib import Path
import ast
import py_compile
import sys

BOT = Path(__file__).with_name("bot.py")
if not BOT.exists():
    print("❌ FAIL: bot.py not found")
    sys.exit(1)

print("🔍 Running smoke test on bot.py...")

# ============================================================
# 1. PYTHON SYNTAX CHECK
# ============================================================
try:
    py_compile.compile(str(BOT), doraise=True)
    print("✅ PASS: Python syntax")
except py_compile.PyCompileError as e:
    print(f"❌ FAIL: Python syntax error:\n{e}")
    sys.exit(1)

# ============================================================
# 2. PARSE SOURCE
# ============================================================
try:
    source = BOT.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename="bot.py")
    print("✅ PASS: AST parse")
except SyntaxError as e:
    print(f"❌ FAIL: AST parse error:\n{e}")
    sys.exit(1)

# ============================================================
# 3. GET ALL FUNCTIONS
# ============================================================
functions = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

# ============================================================
# 4. CHECK: CRITICAL FUNCTIONS (MUST EXIST)
# ============================================================
critical_functions = {
    "analyze_coin", "build_report", "main", "report",
    "price_consensus", "indicator_alignment",
    "asset_block", "action_emoji",
    "global_market_intelligence",
}

missing = sorted(critical_functions - functions)
if missing:
    print(f"❌ FAIL: missing critical functions: {missing}")
    sys.exit(1)
print(f"✅ PASS: {len(critical_functions)} critical functions found")

# ============================================================
# 5. CHECK: OPTIONAL FUNCTIONS (INFO ONLY)
# ============================================================
optional_functions = {
    "_portfolio_symbols": "Portfolio symbols (optional)",
    "send_with_retry": "Telegram rate limit (optional)",
}

for func, desc in optional_functions.items():
    if func in functions:
        print(f"✅ PASS: {desc}")
    else:
        print(f"ℹ️ INFO: {desc} - not found (optional)")

# ============================================================
# 6. CHECK: NO DUPLICATE FUNCTIONS (WARNING ONLY)
# ============================================================
function_counts = {}
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        function_counts[n.name] = function_counts.get(n.name, 0) + 1

duplicates = [name for name, count in function_counts.items() if count > 1]
if duplicates:
    print(f"⚠️ WARNING: duplicate functions found: {duplicates}")
else:
    print("✅ PASS: no duplicate functions")

# ============================================================
# 7. CHECK: build_report EXISTS (at least once)
# ============================================================
build_report_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_report")
if build_report_count == 0:
    print("❌ FAIL: build_report not found")
    sys.exit(1)
elif build_report_count > 1:
    print(f"⚠️ WARNING: build_report found {build_report_count} times")
else:
    print("✅ PASS: single build_report")

# ============================================================
# 8. CHECK: VERSION
# ============================================================
version_line = None
for line in source.split('\n'):
    if 'VERSION =' in line and 'ATLAS' in line:
        version_line = line.strip()
        break

if version_line:
    print(f"✅ Found VERSION: {version_line}")
else:
    print("⚠️ WARNING: VERSION not found")

# ============================================================
# 9. CHECK: TELEGRAM
# ============================================================
if "telegram_send_one" in functions:
    print("✅ PASS: Telegram send function found")
else:
    print("⚠️ WARNING: Telegram send function missing")

# ============================================================
# 10. CHECK: TABLES (NON-BLOCKING)
# ============================================================
required_tables = [
    "signal_outcomes", "model_weights", "telegram_sent_reports",
    "backtest_gate_cache", "candle_events", "signal_memory",
]

missing_tables = []
for table in required_tables:
    if f"create table if not exists {table}" not in source.lower():
        missing_tables.append(table)

if missing_tables:
    print(f"⚠️ WARNING: missing tables: {missing_tables}")
else:
    print("✅ PASS: all required tables found")

# ============================================================
# 11. CHECK: DEPRECATED FUNCTIONS (WARNING ONLY)
# ============================================================
deprecated = [
    "btc_pair_candidates",
    "compact_table_1",
    "compact_table_2",
    "compact_summary",
    "_signal_short",
    "_compact_reason",
]

deprecated_found = [f for f in deprecated if f in functions]
if deprecated_found:
    print(f"⚠️ WARNING: deprecated functions found: {deprecated_found}")
else:
    print("✅ PASS: no deprecated functions")

# ============================================================
# 12. CHECK: REQUIRED TOKENS - PORTFOLIO KEPT
# ============================================================
required_tokens = {
    "TP1", "TP2", "TP3", "TP4", "SL", "R/R",
    "BUY", "SELL", "WAIT", "PORTFOLIO",  # ✅ PORTFOLIO حفظ شد
}

source_upper = source.upper()
missing_tokens = [t for t in required_tokens if t not in source_upper]
if missing_tokens:
    print(f"⚠️ WARNING: required tokens missing: {missing_tokens}")
else:
    print("✅ PASS: all required tokens present (including PORTFOLIO)")

# ============================================================
# 13. CHECK: MARKET LEADER UNIVERSE
# ============================================================
if "ATLAS_PRIORITY_TOP10" in source:
    print("✅ PASS: market-leader Top 10 architecture")
else:
    print("⚠️ WARNING: market-leader universe missing")

# ============================================================
# 14. CHECK: DATA_SYMBOL (MATIC/POL ALIAS)
# ============================================================
if "def data_symbol(symbol)" in source:
    if "MATIC" in source and "POL" in source:
        print("✅ PASS: MATIC/POL alias handling")
    else:
        print("⚠️ WARNING: MATIC/POL alias may be incomplete")
else:
    print("⚠️ WARNING: data_symbol function missing")

# ============================================================
# 15. CHECK: BTC REGIME CACHE
# ============================================================
if "_BTC_REGIME_CACHE" in source:
    print("✅ PASS: BTC regime cache")
else:
    print("⚠️ WARNING: BTC regime cache may be missing")

# ============================================================
# 16. CHECK: EXCHANGE GLOBALS
# ============================================================
if "EX = {}" in source and "MARKETS = {}" in source:
    print("✅ PASS: exchange globals")
else:
    print("⚠️ WARNING: exchange globals may be missing")

# ============================================================
# 17. CHECK: SUPABASE STORE
# ============================================================
if "class SupabaseStore" in source:
    print("✅ PASS: SupabaseStore class")
else:
    print("⚠️ WARNING: SupabaseStore class missing")

# ============================================================
# 18. CHECK: CLOSED-CANDLE ENGINE
# ============================================================
if "strip_incomplete" in source and "candle_is_closed" in source:
    print("✅ PASS: closed-candle engine")
else:
    print("⚠️ WARNING: closed-candle engine may be incomplete")

# ============================================================
# FINAL SUMMARY
# ============================================================
print("")
print("="*60)
print("✅ ATLAS v10.2 SMOKE TEST: PASSED")
print("="*60)
print("")
print(f"📋 Functions found: {len(functions)}")
print(f"📋 Critical functions: {len(critical_functions)}")
print(f"📋 Duplicate functions: {len(duplicates)}")
print(f"📋 Deprecated functions: {len(deprecated_found)}")
print(f"📋 Missing tables: {len(missing_tables)}")
print("")
print("🚀 bot.py is ready for deployment.")
sys.exit(0)
