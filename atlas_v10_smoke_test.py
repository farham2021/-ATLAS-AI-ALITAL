from pathlib import Path
import ast

BOT = Path("bot.py")
if not BOT.exists():
    raise SystemExit("bot.py not found")

source = BOT.read_text(encoding="utf-8")
tree = ast.parse(source)

# ============================================================
# REQUIRED FUNCTIONS - v10.2
# ============================================================
required_functions = {
    "canonical_symbol",
    "symbol_candidates",      # v10.2: replaces symbol_for for alias handling
    "symbol_for",
    "ema_series",
    "macd",
    "rsi_series",
    "strong_divergence",
    "market_breadth",
    "analyze_coin",
    "apply_decision_engine",  # v10.2: decision engine
    "filter_btc_pairs",       # v10.2: BTC pair filtering for dashboard
    "generate_dashboard_report",  # v10.2: new dashboard report
    "build_report",
    "checkpoint_sqlite",
    "main",
}

functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
missing = required_functions - functions
if missing:
    raise SystemExit(f"Missing required functions: {sorted(missing)}")

# ============================================================
# CRITICAL CHECKS
# ============================================================
checks = {
    # Version
    "VERSION 10.2": 'VERSION = "ATLAS v10.2"' in source,
    
    # Symbol handling - v10.2 uses SYMBOL_ALIASES and COINGECKO_IDS
    "MATIC/POL alias": '"MATIC": ("POL", "MATIC")' in source,
    "CoinGecko Polygon canonical ID": '"MATIC": "polygon-ecosystem-token"' in source,
    
    # Alias functions - v10.2 uses canonical_symbol and symbol_candidates
    "canonical_symbol function": 'def canonical_symbol(symbol)' in source,
    "symbol_candidates function": 'def symbol_candidates(symbol)' in source,
    
    # Stablecoin handling - explicit allow-list only
    "exact stablecoin allow-list": 'return s in STABLE_SYMBOLS' in source and 's.startswith("USD")' not in source,
    
    # Indicators
    "O(n) EMA series": 'def ema_series(values, n):' in source,
    "Wilder RSI series": 'def rsi_series(values, n=14):' in source,
    "single-pass MACD": 'def macd(values):' in source and 'Return MACD line, signal and histogram in O(n).' in source,
    
    # Gate system
    "all gate reasons": 'hard_blocks = []' in source and 'gate_reason = " | ".join(dict.fromkeys(hard_blocks))' in source,
    
    # Persistence
    "persistent SQLite v10.2": 'atlas_v102.sqlite3' in source,
    "SQLite WAL checkpoint": 'def checkpoint_sqlite()' in source and 'wal_checkpoint(TRUNCATE)' in source,
    
    # Universe building
    "dynamic Top-30 refresh": 'cg = gecko_top(60)' in source,
    
    # Breadth
    "breadth uses aligned samples": 'aligned_samples = bullish + bearish' in source,
    
    # Error observability
    "price source errors observable": 'price_source_errors' in source,
    
    # Closed-candle engine
    "closed-candle engine": 'Only CLOSED candles used for signals' in source,
    
    # v10.2 Dashboard specific checks
    "BTC pair filtering": 'def filter_btc_pairs(coin_list, min_volume_btc=1000, top_n=10)' in source,
    "dashboard report generation": 'def generate_dashboard_report(results, btc_pairs, top10, dynamic30, macro, news, market_info)' in source,
    "dashboard two-table format": 'جدول ۱: وضعیت بازار' in source and 'جدول ۲: تحلیل عمیق' in source,
    "dashboard 4-line summary": '📌 **جمع‌بندی نهایی:**' in source,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("Smoke checks failed: " + ", ".join(failed))

# ============================================================
# OPTIONAL: Check that functions have correct signatures
# ============================================================
def check_function_signatures():
    issues = []
    
    # Check for required parameters in key functions
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if node.name == "filter_btc_pairs":
                args = [arg.arg for arg in node.args.args]
                if "coin_list" not in args:
                    issues.append("filter_btc_pairs missing 'coin_list' parameter")
                if "min_volume_btc" not in args:
                    issues.append("filter_btc_pairs missing 'min_volume_btc' parameter")
                    
            elif node.name == "generate_dashboard_report":
                args = [arg.arg for arg in node.args.args]
                expected = ["results", "btc_pairs", "top10", "dynamic30", "macro", "news", "market_info"]
                for param in expected:
                    if param not in args:
                        issues.append(f"generate_dashboard_report missing '{param}' parameter")
    
    return issues

signature_issues = check_function_signatures()
if signature_issues:
    print("WARNING: Signature issues found:")
    for issue in signature_issues:
        print(f"  - {issue}")

# ============================================================
# OPTIONAL: Verify file structure
# ============================================================
def check_file_structure():
    issues = []
    
    # Check for proper section markers
    required_sections = [
        "CONFIG",
        "ATLAS RADAR",
        "SQLITE FALLBACK",
        "SUPABASE STORAGE",
        "CCXT",
        "DYNAMIC MARKET UNIVERSE",
        "TECHNICAL INDICATORS",
        "CANDLE PATTERNS",
        "DIVERGENCE",
        "MULTI-TIMEFRAME ANALYSIS",
        "SIGNAL SCORING",
        "BACKTEST ENGINE",
        "SIGNAL OUTCOME TRACKING",
        "TELEGRAM",
        "REPORT FORMAT",
        "CONTEXT PERSISTENCE",
        "MAIN",
    ]
    
    for section in required_sections:
        if f"= {section} =" not in source:
            issues.append(f"Missing section marker: {section}")
    
    return issues

structure_issues = check_file_structure()
if structure_issues:
    print("WARNING: Structure issues found:")
    for issue in structure_issues:
        print(f"  - {issue}")

# ============================================================
# FINAL RESULT
# ============================================================
print("ATLAS v10.2 SMOKE TEST: PASS")
for name in checks:
    print(f"  OK: {name}")

if signature_issues or structure_issues:
    print("\n⚠️  Smoke test passed with warnings. Review the output above.")
else:
    print("\n✅ All checks passed successfully.")
