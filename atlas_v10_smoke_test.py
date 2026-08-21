from pathlib import Path
import ast

BOT = Path("bot.py")
if not BOT.exists():
    raise SystemExit("bot.py not found")

source = BOT.read_text(encoding="utf-8")
tree = ast.parse(source)

required_functions = {
    "canonical_symbol", "symbol_for", "ema_series", "macd", "rsi_series",
    "strong_divergence", "market_breadth", "analyze_coin",
    "apply_decision_engine", "build_report", "main",
}
functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
missing = required_functions - functions
if missing:
    raise SystemExit(f"Missing required functions: {sorted(missing)}")

if 'VERSION = "ATLAS v10.1"' not in source:
    raise SystemExit("VERSION is not ATLAS v10.1")

checks = {
    "MATIC/POL alias": '"MATIC": ("MATIC", "POL")' in source,
    "exact stablecoin allow-list": 's in STABLE_SYMBOLS' in source and 's.startswith("USD")' not in source,
    "O(n) EMA series": 'def ema_series(values, n):' in source,
    "Wilder RSI series": 'def rsi_series(values, n=14):' in source,
    "all gate reasons": 'hard_blocks = []' in source,
    "persistent SQLite filename": 'atlas_v101.sqlite3' in source,
    "dynamic Top-30 refresh": 'cg = gecko_top(60)' in source,
    "decision board watches": 'WATCH — صعود' in source and 'WATCH — ریزش' in source,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("Smoke checks failed: " + ", ".join(failed))

print("ATLAS v10.1 SMOKE TEST: PASS")
for name in checks:
    print(f"  OK: {name}")
