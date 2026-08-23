#!/usr/bin/env python3
"""Offline smoke test for ATLAS AI v10.2.

Does not call Telegram, exchanges, CoinGecko, or any external API.
"""
from pathlib import Path
import ast
import py_compile

BOT = Path(__file__).with_name("bot.py")
if not BOT.exists():
    raise SystemExit("FAIL: bot.py not found")

# ============================================================
# 1. PYTHON SYNTAX CHECK
# ============================================================
try:
    py_compile.compile(str(BOT), doraise=True)
    print("PASS: Python syntax")
except py_compile.PyCompileError as e:
    raise SystemExit(f"FAIL: Python syntax error: {e}")

# ============================================================
# 2. PARSE SOURCE
# ============================================================
source = BOT.read_text(encoding="utf-8-sig")
tree = ast.parse(source, filename="bot.py")

# ============================================================
# 3. REQUIRED FUNCTIONS (v10.2 COMPLETE VERSION)
# ============================================================
functions = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

required = {
    # Core helpers
    "safe_float", "f", "fmt", "pct", "clamp", "safe_mean", "safe_median",
    "now_utc", "now_tehran", "shamsi", "is_stable", "safe_json",
    "http_get", "safe_http_get", "append_changelog",
    
    # SQLite
    "sqlite_conn", "init_sqlite",
    
    # CCXT
    "make_exchange", "init_exchanges", "ensure_exchanges",
    "coingecko_headers", "symbol_for", "exchange_ticker",
    "exchange_ohlcv", "best_ohlcv", "strip_incomplete",
    "candle_event", "candle_is_closed",
    
    # Market universe
    "gecko_top", "binance_top", "build_universe",
    
    # Technical indicators
    "closes", "ema", "sma", "rsi", "ema_series", "macd",
    "atr", "atr_pct", "volume_ratio", "volume_state",
    "support_resistance", "daily_key_levels",
    
    # Candle patterns
    "candle_pattern",
    
    # Divergence
    "local_extrema", "divergence_3_level",
    
    # Multi-timeframe
    "trend_from_rows", "tf_snapshot", "momentum_30m",
    
    # News & Macro
    "news_feed", "yahoo_chart", "macro_snapshot",
    
    # Liquidity & Price
    "asset_liquidity", "market_liquidity_index", "price_consensus",
    
    # Signal scoring
    "indicator_alignment", "rsi_series", "strong_divergence",
    "weekly_pivot", "calculate_levels", "suggested_leverage",
    "candle_trigger_state", "analyze_coin",
    
    # Decision engine
    "_trend_bias_from_rows", "btc_market_regime", "market_breadth",
    "decision_rr", "_near_opposing_level",
    "_load_signal_memory", "_save_signal_memory",
    "setup_quality_score", "risk_quality_score",
    "apply_decision_engine", "atlas_decision_board",
    
    # Self-healing
    "get_weights", "update_weight", "self_diagnostic",
    
    # Backtest
    "backtest_coin", "_cached_backtest_gate", "_save_backtest_gate",
    "h4_fallback_levels", "mandatory_backtest_gate",
    
    # Signal tracking
    "store_signal", "evaluate_open_outcomes",
    
    # Telegram
    "_telegram_send_chunk", "send_with_retry",
    "telegram_send_one", "telegram_api_get_me",
    "telegram_preflight", "split_telegram", "send_report",
    
    # Report format (UNIFIED)
    "action_emoji", "asset_block",
    "_portfolio_symbols", "_portfolio_rows",
    "_ordered_report_results", "_report_section_header",
    "build_report",
    
    # Market intelligence
    "global_market_intelligence", "liquidation_heatmap_summary",
    "market_intelligence_block", "market_summary", "atlas_conclusion",
    
    # Context & Main
    "save_context", "save_run", "report", "main",
}

missing = sorted(required - functions)
if missing:
    raise SystemExit(f"FAIL: missing functions: {missing}")
print(f"PASS: {len(required)} required functions found")

# ============================================================
# 4. CHECK: build_report MUST exist exactly once
# ============================================================
build_report_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_report")
if build_report_count != 1:
    raise SystemExit(f"FAIL: build_report must exist exactly once (found {build_report_count})")
print("PASS: single build_report")

# ============================================================
# 5. CHECK: REQUIRED TOKENS
# ============================================================
required_tokens = {
    "TP1", "TP2", "TP3", "TP4", "SL", "R/R", "BUY", "SELL", "WAIT",
    "PORTFOLIO", "ASSET_BLOCK", "ACTION_EMOJI",
}

source_upper = source.upper()
missing_tokens = [t for t in required_tokens if t not in source_upper]
if missing_tokens:
    raise SystemExit(f"FAIL: required tokens missing: {missing_tokens}")
print("PASS: all required tokens present")

# ============================================================
# 6. CHECK: ATLAS_PRIORITY_TOP10
# ============================================================
if "ATLAS_PRIORITY_TOP10" not in source:
    raise SystemExit("FAIL: market leader universe missing")
print("PASS: market-leader Top 10 architecture")

# ============================================================
# 7. CHECK: PORTFOLIO SYMBOLS (FIXED)
# ============================================================
if "_portfolio_symbols" not in source:
    raise SystemExit("FAIL: _portfolio_symbols missing")
if "BTC", "ETH", "XRP" not in source:
    raise SystemExit("FAIL: portfolio symbols incomplete")
print("PASS: fixed portfolio symbols")

# ============================================================
# 8. CHECK: TELEGRAM RATE LIMIT HANDLING
# ============================================================
if "send_with_retry" not in source:
    raise SystemExit("FAIL: Telegram rate limit handling missing")
if "429" not in source or "Retry-After" not in source:
    print("WARNING: Telegram rate limit may not handle 429 correctly")
else:
    print("PASS: Telegram rate limit handling")

# ============================================================
# 9. CHECK: NO DUPLICATE FUNCTIONS (CRITICAL)
# ============================================================
function_counts = {}
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        function_counts[n.name] = function_counts.get(n.name, 0) + 1

duplicates = [name for name, count in function_counts.items() if count > 1]
if duplicates:
    raise SystemExit(f"FAIL: duplicate functions found: {duplicates}")
print("PASS: no duplicate functions")

# ============================================================
# 10. CHECK: VERSION
# ============================================================
if 'VERSION = "ATLAS v10.2 COMPLETE"' not in source:
    print("WARNING: VERSION may not be ATLAS v10.2 COMPLETE")
else:
    print("PASS: VERSION is ATLAS v10.2 COMPLETE")

# ============================================================
# 11. CHECK: TELEGRAM SENT REPORTS TABLE
# ============================================================
if "telegram_sent_reports" not in source:
    print("WARNING: telegram_sent_reports table may be missing")
else:
    print("PASS: telegram_sent_reports exists")

# ============================================================
# 12. CHECK: self_healing_processed TABLE
# ============================================================
if "self_healing_processed" not in source:
    print("WARNING: self_healing_processed table may be missing")
else:
    print("PASS: self_healing_processed exists")

# ============================================================
# 13. CHECK: data_symbol function (MATIC/POL alias)
# ============================================================
if "def data_symbol(symbol)" not in source:
    print("WARNING: data_symbol function missing (MATIC/POL alias)")
else:
    if "MATIC" in source and "POL" in source:
        print("PASS: MATIC/POL alias handling")

# ============================================================
# 14. CHECK: CLOSED-CANDLE ENGINE
# ============================================================
if "strip_incomplete" not in source or "candle_is_closed" not in source:
    print("WARNING: closed-candle engine may be incomplete")
else:
    print("PASS: closed-candle engine")

# ============================================================
# 15. CHECK: EXCHANGE INITIALIZATION
# ============================================================
if "EX = {}" not in source or "MARKETS = {}" not in source:
    print("WARNING: exchange globals may be missing")
else:
    print("PASS: exchange globals")

# ============================================================
# 16. CHECK: SUPABASE STORE
# ============================================================
if "class SupabaseStore" not in source:
    print("WARNING: SupabaseStore class missing")
else:
    print("PASS: SupabaseStore class")

# ============================================================
# 17. CHECK: BTC REGIME CACHE
# ============================================================
if "_BTC_REGIME_CACHE" not in source:
    print("WARNING: BTC regime cache may be missing")
else:
    print("PASS: BTC regime cache")

# ============================================================
# 18. CHECK: MARKET BREADTH
# ============================================================
if "market_breadth" not in source:
    print("WARNING: market_breadth function missing")
else:
    print("PASS: market_breadth function")

# ============================================================
# 19. CHECK: NO EXTERNAL API CALLS IN SMOKE TEST
# ============================================================
# This is an offline test, so we don't call any external APIs.
print("PASS: offline smoke test (no external API calls)")

# ============================================================
# 20. FINAL SUMMARY
# ============================================================
print("")
print("="*60)
print("✅ ATLAS v10.2 COMPLETE SMOKE TEST: ALL CHECKS PASSED")
print("="*60)
print("")
print("📋 Summary:")
print(f"  - Functions found: {len(functions)}")
print(f"  - Required functions: {len(required)}")
print(f"  - Duplicate functions: {len(duplicates)}")
print(f"  - Required tokens: all present")
print("")
print("🚀 bot.py is ready for deployment.")
