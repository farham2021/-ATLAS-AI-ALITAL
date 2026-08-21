import ast, os, tempfile
from pathlib import Path
source = Path('bot.py').read_text(encoding='utf-8')
ast.parse(source, filename='bot.py')
required = ['analyze_coin','btc_market_regime','market_breadth','apply_decision_engine','atlas_decision_board','decision_rr','weekly_pivot']
names = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}
missing = [x for x in required if x not in names]
if missing: raise SystemExit(f'Missing: {missing}')
if 'VERSION = "ATLAS v9.0"' not in source: raise SystemExit('Not v9.0')
print('ATLAS v9 static smoke test: PASS')
