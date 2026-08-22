from pathlib import Path
import ast

BOT = Path('bot.py')
if not BOT.exists():
    raise SystemExit('bot.py not found')
source = BOT.read_text(encoding='utf-8')
tree = ast.parse(source)
functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
required = {
    'canonical_symbol', 'symbol_for', 'ema_series', 'macd', 'rsi_series',
    'strong_divergence', 'market_breadth', 'analyze_coin',
    'apply_decision_engine', 'build_report', 'checkpoint_sqlite', 'main'
}
missing = required - functions
if missing:
    raise SystemExit(f'Missing required functions: {sorted(missing)}')

checks = [
    ('VERSION 10.2', 'VERSION = "ATLAS v10.2"' in source),
    ('MATIC/POL alias', '"MATIC": ("MATIC", "POL")' in source),
    ('CoinGecko Polygon canonical ID', 'polygon-ecosystem-token' in source),
    ('exact stablecoin allow-list', 's in STABLE_SYMBOLS' in source and 's.startswith("USD")' not in source),
    ('O(n) EMA series', 'def ema_series(values, n):' in source),
    ('single-pass MACD', 'def macd(values):' in source and 'Return MACD line, signal and histogram in O(n).' in source),
    ('all gate reasons', 'hard_blocks = []' in source and ' | ".join(dict.fromkeys(hard_blocks))' in source),
    ('persistent SQLite v10.2', 'atlas_v102.sqlite3' in source),
    ('SQLite WAL checkpoint', 'def checkpoint_sqlite()' in source and 'wal_checkpoint(TRUNCATE)' in source),
    ('dynamic Top-30 refresh', 'cg = gecko_top(60)' in source),
    ('breadth uses aligned samples', 'aligned_samples = bullish + bearish' in source),
    ('decision board watches', 'WATCH — صعود' in source and 'WATCH — ریزش' in source),
    ('price source errors observable', 'PRICE SOURCES:' in source and 'price_source_errors' in source),
    ('closed-candle engine', 'Only CLOSED candles used for signals' in source),
]
failed = [name for name, ok in checks if not ok]
if failed:
    raise SystemExit('Smoke checks failed: ' + ', '.join(failed))

ast.parse(source)
print('ATLAS v10.2 SMOKE TEST: PASS')
for name, _ in checks:
    print('  OK:', name)
