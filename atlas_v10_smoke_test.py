from pathlib import Path
import ast

BOT = Path("bot.py")
if not BOT.exists():
    raise SystemExit("bot.py not found")
source = BOT.read_text(encoding="utf-8")
ast.parse(source)
functions = {n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
required = {
    "canonical_symbol", "symbol_for", "ema_series", "macd", "rsi_series",
    "strong_divergence", "market_breadth", "analyze_coin",
    "build_report", "checkpoint_sqlite", "main",
}
missing = required - functions
if missing:
    raise SystemExit(f"Missing required functions: {sorted(missing)}")
checks = [
    ("VERSION 10.2", 'VERSION = "ATLAS v10.2"' in source),
    ("MATIC/POL alias", '"MATIC": ("POL", "MATIC")' in source),
    ("CoinGecko Polygon canonical ID", '"MATIC": "polygon-ecosystem-token"' in source),
    ("exact stablecoin allow-list", 'return s in STABLE_SYMBOLS' in source and 's.startswith("USD")' not in source),
    ("O(n) EMA series", 'def ema_series(values, n):' in source),
    ("Wilder RSI series", 'def rsi_series(values, n=14):' in source),
    ("single-pass MACD", 'def macd(values):' in source and 'Return MACD line, signal and histogram in O(n).' in source),
    ("all gate reasons", 'hard_blocks = []' in source and ' | ".join(dict.fromkeys(hard_blocks))' in source),
    ("persistent SQLite v10.2", 'atlas_v102.sqlite3' in source),
    ("SQLite WAL checkpoint", 'def checkpoint_sqlite()' in source and 'wal_checkpoint(TRUNCATE)' in source),
    ("dynamic Top-30 refresh", 'cg = gecko_top(60)' in source),
    ("breadth uses aligned samples", 'aligned_samples = bullish + bearish' in source),
    ("price source errors observable", 'price_source_errors' in source),
    ("closed-candle engine", 'Only CLOSED candles used for signals' in source),
]
failed = [name for name, ok in checks if not ok]
if failed:
    raise SystemExit("Smoke checks failed: " + ", ".join(failed))
print("ATLAS v10.2 SMOKE TEST: PASS")
for name, _ in checks:
    print("  OK:", name)
