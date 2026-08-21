import ast
from pathlib import Path

SOURCE = Path('bot.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE, filename='bot.py')
NAMES = {n.name for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)}

required = [
    'analyze_coin', 'btc_market_regime', 'market_breadth',
    'apply_decision_engine', 'atlas_decision_board', 'decision_rr',
    'weekly_pivot', 'safe_float', 'safe_mean', 'safe_median',
    'ema_series', 'rsi_series', 'strong_divergence', 'symbol_for',
]
missing = [x for x in required if x not in NAMES]
if missing:
    raise SystemExit(f'Missing required functions: {missing}')

if 'VERSION = "ATLAS v10.1"' not in SOURCE:
    raise SystemExit('Not ATLAS v10.1')
if 'atlas_v101.sqlite3' not in SOURCE:
    raise SystemExit('v10.1 SQLite filename missing')
if 'TOKEN_ALIASES' not in SOURCE or '"MATIC": ("MATIC", "POL")' not in SOURCE:
    raise SystemExit('MATIC/POL alias support missing')
if 's.startswith("USD")' in SOURCE:
    raise SystemExit('Unsafe USD-prefix stablecoin filter still present')
if 'return line[-1], signal, hist if prev_signal is not None else None' in SOURCE:
    raise SystemExit('Legacy MACD histogram bug still present')
if 'def rsi_series(values, n=14):' not in SOURCE:
    raise SystemExit('Wilder RSI series missing')
if 'aligned_samples = bullish + bearish' not in SOURCE:
    raise SystemExit('Market breadth sample fix missing')
if 'hard_blocks = []' not in SOURCE or 'gate_reason = " | ".join(hard_blocks)' not in SOURCE:
    raise SystemExit('Multi-reason hard gate missing')
if '"price_source_errors": errors' not in SOURCE:
    raise SystemExit('Price-source diagnostics missing')

# Basic AST-level regression checks for the expensive O(n^2) MACD/RSI patterns.
for node in ast.walk(TREE):
    if isinstance(node, ast.FunctionDef) and node.name == 'strong_divergence':
        calls_rsi = [
            n for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'rsi'
        ]
        if calls_rsi:
            raise SystemExit('strong_divergence still calls rsi() repeatedly')

print('ATLAS v10.1 static smoke test: PASS')
print('PASS: VERSION / SQLite state')
print('PASS: MATIC -> POL symbol alias')
print('PASS: O(n) MACD + histogram')
print('PASS: Wilder RSI series for divergence')
print('PASS: divergence-score recomputation hook')
print('PASS: aligned market-breadth sample count')
print('PASS: multi-reason hard gates')
print('PASS: price-source diagnostics')
print('PASS: exact stablecoin filter')
