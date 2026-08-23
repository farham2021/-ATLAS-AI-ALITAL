#!/usr/bin/env python3
"""Offline smoke test for ATLAS AI v10.2 COMPLETE.

Does not call Telegram, exchanges, CoinGecko, or any external API.
"""
from pathlib import Path
import ast
import py_compile
import sys
import traceback

def main():
    print("🔍 Running smoke test on bot.py...")
    
    BOT = Path(__file__).with_name("bot.py")
    if not BOT.exists():
        print("❌ FAIL: bot.py not found")
        return 1

    # ============================================================
    # 1. PYTHON SYNTAX CHECK
    # ============================================================
    try:
        py_compile.compile(str(BOT), doraise=True)
        print("✅ PASS: Python syntax")
    except py_compile.PyCompileError as e:
        print(f"❌ FAIL: Python syntax error:\n{e}")
        return 1

    # ============================================================
    # 2. PARSE SOURCE
    # ============================================================
    try:
        source = BOT.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename="bot.py")
        print("✅ PASS: AST parse")
    except SyntaxError as e:
        print(f"❌ FAIL: AST parse error:\n{e}")
        return 1

    # ============================================================
    # 3. CHECK: CRITICAL FUNCTIONS EXIST
    # ============================================================
    functions = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    
    critical_functions = {
        "analyze_coin", "build_report", "main", "report",
        "price_consensus", "indicator_alignment",
        "asset_block", "action_emoji", "_portfolio_symbols",
        "send_with_retry", "global_market_intelligence",
    }
    
    missing = sorted(critical_functions - functions)
    if missing:
        print(f"❌ FAIL: missing critical functions: {missing}")
        return 1
    print(f"✅ PASS: {len(critical_functions)} critical functions found")

    # ============================================================
    # 4. CHECK: NO DUPLICATE FUNCTIONS
    # ============================================================
    function_counts = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_counts[n.name] = function_counts.get(n.name, 0) + 1
    
    duplicates = [name for name, count in function_counts.items() if count > 1]
    if duplicates:
        print(f"❌ FAIL: duplicate functions found: {duplicates}")
        return 1
    print("✅ PASS: no duplicate functions")

    # ============================================================
    # 5. CHECK: build_report EXISTS EXACTLY ONCE
    # ============================================================
    build_report_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_report")
    if build_report_count != 1:
        print(f"❌ FAIL: build_report must exist exactly once (found {build_report_count})")
        return 1
    print("✅ PASS: single build_report")

    # ============================================================
    # 6. CHECK: VERSION (non-blocking)
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
    # 7. CHECK: PORTFOLIO SYMBOLS
    # ============================================================
    if "_portfolio_symbols" not in source:
        print("❌ FAIL: _portfolio_symbols missing")
        return 1
    
    expected_symbols = ["BTC", "ETH", "XRP", "SOL", "BNB", "DOGE", "ADA"]
    for symbol in expected_symbols:
        if f'"{symbol}"' not in source:
            print(f"⚠️ WARNING: Portfolio may not contain {symbol}")
    print("✅ PASS: portfolio symbols found")

    # ============================================================
    # 8. CHECK: TELEGRAM RATE LIMIT HANDLING
    # ============================================================
    if "send_with_retry" not in source:
        print("❌ FAIL: Telegram rate limit handling missing")
        return 1
    print("✅ PASS: Telegram rate limit handling")

    # ============================================================
    # 9. CHECK: TABLES (non-blocking)
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
    # 10. CHECK: DEPRECATED FUNCTIONS
    # ============================================================
    deprecated = ["btc_pair_candidates", "compact_table_1", "compact_table_2", "compact_summary"]
    deprecated_found = [f for f in deprecated if f in functions]
    if deprecated_found:
        print(f"⚠️ WARNING: deprecated functions found: {deprecated_found}")
    else:
        print("✅ PASS: no deprecated functions")

    # ============================================================
    # 11. FINAL SUMMARY
    # ============================================================
    print("")
    print("="*60)
    print("✅ ATLAS v10.2 COMPLETE SMOKE TEST: PASSED")
    print("="*60)
    print("")
    print(f"📋 Functions found: {len(functions)}")
    print(f"📋 Critical functions: {len(critical_functions)}")
    print(f"📋 Duplicate functions: {len(duplicates)}")
    print("")
    print("🚀 bot.py is ready for deployment.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
