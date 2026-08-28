#!/usr/bin/env python3
#==============================================================================
# ATLAS v11.1 — smoke_atlas.py
#==============================================================================
# Lightweight health check for ATLAS core functions.
# This file should be updated whenever new core functions are added.
#==============================================================================

import sys
import os
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("🔥 ATLAS smoke test v11.1")

# ============================================================
# لیست کامل توابع مورد نیاز
# ============================================================
required_functions = [
    # ===== Core =====
    "VERSION",
    "TIMEFRAMES",
    "SIGNAL_TIMEFRAME",
    
    # ===== Helpers =====
    "now_utc",
    "now_tehran",
    "shamsi",
    "safe_float",
    "f",
    "fmt",
    "pct",
    "clamp",
    "is_stable",
    "is_ambiguous_symbol",
    "http_get",
    "safe_http_get",
    
    # ===== Database =====
    "sqlite_conn",
    "init_sqlite",
    "append_changelog",
    
    # ===== Exchange =====
    "make_exchange",
    "init_exchanges",
    "ensure_exchanges",
    "best_ohlcv",
    
    # ===== Market =====
    "build_universe",
    "analyze_coin",
    "btc_market_regime",
    "market_breadth",
    "apply_decision_engine",
    "atlas_decision_board",
    
    # ===== Weights =====
    "get_weights",
    "update_weight",
    "self_diagnostic",
    
    # ===== Backtest =====
    "backtest_coin",
    "mandatory_backtest_gate",
    
    # ===== Signals =====
    "store_signal",
    "evaluate_open_outcomes",
    
    # ===== Telegram =====
    "telegram_preflight",
    "send_with_retry",
    "send_report",
    
    # ===== Reports =====
    "build_report",
    "build_personal_report",
    "build_two_engine_reports",
    "atlas_engine_mode",
    "generate_csv_report",
    "send_csv_report",
    "tradingview_chart_url",
    
    # ===== Snapshot =====
    "build_price_snapshot",
    "send_price_snapshot",
    "fetch_usdt_toman_public",
    "fetch_snapshot_results",
    "_automatic_run_plan",
    
    # ===== Table Functions =====
    "build_full_table_report",
    "build_signal_ranking_table",
    "send_image_table",
    "_best_setup_block",
    "_compact_scenario_row",
    "_compact_section",
    "_final_market_recommendation",
    
    # ===== Text to Image =====
    "text_to_image",
    "send_report_as_image",
    
    # ===== Intelligence =====
    "v11_apply_intelligence",
    "v11_portfolio_diagnostics",
    "build_v11_intelligence_report",
    
    # ===== Portfolio =====
    "_portfolio_symbols",
    "_portfolio_rows",
    "personal_report",
]

try:
    # بارگذاری ماژول bot.py
    spec = importlib.util.spec_from_file_location("bot", "bot.py")
    if spec is None:
        print("❌ FAIL: Could not find bot.py")
        sys.exit(1)
    
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)
    
    # بررسی وجود توابع
    missing = []
    for name in required_functions:
        if not hasattr(bot, name):
            missing.append(name)
    
    if missing:
        print(f"❌ FAIL: missing required functions: {', '.join(missing)}")
        print(f"   Total: {len(missing)} missing out of {len(required_functions)}")
        sys.exit(1)
    
    print(f"✅ All {len(required_functions)} required functions present")
    
    # ===== بررسی نسخه =====
    if hasattr(bot, "VERSION"):
        print(f"✅ Version: {bot.VERSION}")
    
    # ===== بررسی توابع جدید =====
    new_functions = ["text_to_image", "send_report_as_image", "build_full_table_report"]
    for func in new_functions:
        if hasattr(bot, func):
            print(f"✅ {func} available")
    
    print("✅ smoke_atlas passed")
    sys.exit(0)
    
except ImportError as e:
    print(f"❌ FAIL: Import error - {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ FAIL: Unexpected error - {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
