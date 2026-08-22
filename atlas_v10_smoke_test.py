import ast
from pathlib import Path

source = Path('bot.py').read_text(encoding='utf-8')
tree = ast.parse(source, filename='bot.py')
names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
required = [
    'analyze_coin','btc_market_regime','market_breadth','apply_decision_engine',
    'atlas_decision_board','decision_rr','weekly_pivot','safe_float',
    'safe_mean','safe_median','rsi_series','ema_series'
]
missing = [x for x in required if x not in names]
if missing:
    raise SystemExit(f'Missing functions: {missing}')
if 'VERSION = "ATLAS v10.1"' not in source:
    raise SystemExit('Not v10.1')
if 'ATLAS_SQLITE_FILE' not in source:
    raise SystemExit('SQLite configuration missing')
if 'DATA_SYMBOL_ALIASES' not in source or '"MATIC": "POL"' not in source:
    raise SystemExit('MATIC/POL alias missing')
print('ATLAS v10.1 static smoke test: PASS')
