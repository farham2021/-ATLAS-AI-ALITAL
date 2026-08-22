from pathlib import Path
import ast

BOT = Path("bot.py")
if not BOT.exists():
    raise SystemExit("bot.py not found")

source = BOT.read_text(encoding="utf-8")
tree = ast.parse(source)

# ============================================================
# REQUIRED FUNCTIONS - v10.3
# ============================================================
required_functions = {
    "canonical_symbol",
    "symbol_candidates",
    "symbol_for",
    "symbol_for_btc",           # v10.3: جدید برای جفت‌های BTC
    "ema_series",
    "macd",
    "rsi_series",
    "strong_divergence",
    "market_breadth",
    "analyze_coin",
    "apply_decision_engine",
    "filter_btc_pairs",         # v10.3: بهبود یافته
    "get_top_market_cap_assets", # v10.3: جدید برای دریافت ۱۰ ارز برتر
    "get_top_cmc_assets",       # v10.3: جدید برای پشتیبان CoinMarketCap
    "generate_dashboard_report",
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
    "VERSION 10.3": 'VERSION = "ATLAS v10.3"' in source,
    
    # Symbol handling
    "MATIC/POL alias": '"MATIC": ("POL", "MATIC")' in source,
    "CoinGecko Polygon canonical ID": '"MATIC": "polygon-ecosystem-token"' in source,
    "canonical_symbol function": 'def canonical_symbol(symbol)' in source,
    "symbol_candidates function": 'def symbol_candidates(symbol)' in source,
    
    # BTC pair handling - v10.3 new
    "symbol_for_btc function": 'def symbol_for_btc(eid, coin)' in source,
    "filter_btc_pairs improved": 'def filter_btc_pairs(coin_list, min_volume_btc=1000, top_n=10)' in source,
    
    # Top market cap - v10.3 new
    "get_top_market_cap_assets": 'def get_top_market_cap_assets(limit=10)' in source,
    "get_top_cmc_assets": 'def get_top_cmc_assets(limit=10)' in source,
    "coingecko_headers": 'def coingecko_headers()' in source,
    
    # Stablecoin handling
    "exact stablecoin allow-list": 'return s in STABLE_SYMBOLS' in source and 's.startswith("USD")' not in source,
    
    # Indicators
    "O(n) EMA series": 'def ema_series(values, n):' in source,
    "Wilder RSI series": 'def rsi_series(values, n=14):' in source,
    "single-pass MACD": 'def macd(values):' in source and 'Return MACD line, signal and histogram in O(n).' in source,
    
    # Gate system
    "all gate reasons": 'hard_blocks = []' in source and 'gate_reason = " | ".join(dict.fromkeys(hard_blocks))' in source,
    
    # Persistence - v10.3 new SQLite file
    "persistent SQLite v10.3": 'atlas_v103.sqlite3' in source,
    "SQLite WAL checkpoint": 'def checkpoint_sqlite()' in source and 'wal_checkpoint(TRUNCATE)' in source,
    
    # Universe building - v10.3 improved
    "build_universe with top 10": 'top10_symbols' in source and 'get_top_market_cap_assets' in source,
    "dynamic Top-30 refresh": 'cg = gecko_top(60)' in source,
    
    # Breadth
    "breadth uses aligned samples": 'aligned_samples = bullish + bearish' in source,
    
    # Error observability
    "price source errors observable": 'price_source_errors' in source,
    
    # Closed-candle engine
    "closed-candle engine": 'Only CLOSED candles used for signals' in source,
    
    # v10.3 Dashboard specific checks
    "dashboard report with top 10": 'top10_symbols' in source and 'priority10' in source,
    "dashboard two-table format": 'جدول ۱: وضعیت بازار' in source and 'جدول ۲: تحلیل عمیق' in source,
    "dashboard 4-line summary": '📌 **جمع‌بندی نهایی:**' in source,
    "multi-source data": 'CoinGecko + Binance' in source,
    
    # Telegram rate limit handling - v10.3 new
    "telegram rate limit handling": 'send_with_retry(chat_id, text, max_retries=None, base_delay=None)' in source,
    "telegram exponential backoff": 'retry_after * (2 ** attempt)' in source,
    "telegram duplicate prevention": 'telegram_sent_reports' in source,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("Smoke checks failed: " + ", ".join(failed))

# ============================================================
# OPTIONAL: Check that functions have correct signatures
# ============================================================
def check_function_signatures():
    issues = []
    
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if node.name == "filter_btc_pairs":
                args = [arg.arg for arg in node.args.args]
                if "coin_list" not in args:
                    issues.append("filter_btc_pairs missing 'coin_list' parameter")
                if "min_volume_btc" not in args:
                    issues.append("filter_btc_pairs missing 'min_volume_btc' parameter")
                    
            elif node.name == "get_top_market_cap_assets":
                args = [arg.arg for arg in node.args.args]
                if "limit" not in args:
                    issues.append("get_top_market_cap_assets missing 'limit' parameter")
                    
            elif node.name == "generate_dashboard_report":
                args = [arg.arg for arg in node.args.args]
                expected = ["results", "btc_pairs", "top10_symbols", "priority10", "dynamic30", "macro", "news", "market_info"]
                for param in expected:
                    if param not in args:
                        issues.append(f"generate_dashboard_report missing '{param}' parameter")
            
            elif node.name == "send_with_retry":
                args = [arg.arg for arg in node.args.args]
                expected = ["chat_id", "text"]
                for param in expected:
                    if param not in args:
                        issues.append(f"send_with_retry missing '{param}' parameter")
    
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
# OPTIONAL: Check for new v10.3 features
# ============================================================
def check_v10_3_features():
    features = []
    
    # Check for multi-source data handling
    if "get_top_market_cap_assets" in source:
        features.append("✅ Top 10 market cap from CoinGecko")
    if "get_top_cmc_assets" in source:
        features.append("✅ CoinMarketCap fallback support")
    if "symbol_for_btc" in source:
        features.append("✅ BTC pair detection")
    if "send_with_retry" in source and "429" in source:
        features.append("✅ Telegram rate limit handling")
    if "telegram_sent_reports" in source:
        features.append("✅ Telegram duplicate prevention")
    
    return features

v10_3_features = check_v10_3_features()
if v10_3_features:
    print("\n📌 v10.3 Features detected:")
    for feature in v10_3_features:
        print(f"  {feature}")

# ============================================================
# FINAL RESULT
# ============================================================
print("\n" + "="*50)
print("ATLAS v10.3 SMOKE TEST: PASS")
print("="*50)
for name in checks:
    print(f"  OK: {name}")

if signature_issues or structure_issues:
    print("\n⚠️  Smoke test passed with warnings. Review the output above.")
else:
    print("\n✅ All checks passed successfully.")

print("="*50)
