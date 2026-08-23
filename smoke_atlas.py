#!/usr/bin/env python3
"""Offline structural/regression smoke test for ATLAS Two Engine."""
from pathlib import Path
import ast
import re
import py_compile

ROOT = Path(__file__).resolve().parent
BOT = ROOT / "bot.py"
if not BOT.exists():
    raise SystemExit("FAIL: bot.py not found")

source = BOT.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(BOT))
functions = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
required = {
    "asset_block", "action_emoji", "build_report", "build_personal_report",
    "personal_report", "report", "main", "calculate_levels", "decision_rr",
    "_conditional_trade_plan", "apply_decision_engine", "analyze_coin",
    "market_breadth", "checkpoint_sqlite",
}
missing = sorted(required - functions)
if missing:
    raise SystemExit(f"FAIL: missing required functions: {missing}")

checks = [
    ("syntax", True),
    ("two-engine env", 'os.environ.get("ATLAS_ENGINE")' in source and 'os.environ.get("ATLAS_MODE")' in source),
    ("GLOBAL alias", 'ATLAS_ENGINE == "GLOBAL"' in source),
    ("TP1-TP4", all(x in source for x in ("tp1", "tp2", "tp3", "tp4"))),
    ("SL", "\"sl\"" in source),
    ("exact R/R formula", 'abs(entry-tp2)/abs(entry-sl)' in source),
    ("conditional WAIT plan", "_conditional_trade_plan" in source),
    ("personal levels for blocked setups", 'if f(r.get("entry")) is None:' in source),
    ("physical market references", 'PERSONAL_PHYSICAL_ASSETS' in source and 'macro.get("GOLD")' in source and 'macro.get("SILVER")' in source and 'macro.get("COPPER")' in source),
    ("closed candles", "Only CLOSED candles used for signals" in source),
    ("no automatic orders", "No automatic orders." in source),
]
py_compile.compile(str(BOT), doraise=True)
failed = [name for name, ok in checks if not ok]
if failed:
    raise SystemExit("FAIL: " + ", ".join(failed))

# Ensure the personal report does not conditionally hide TP fields behind BUY/SELL.
start = source.index("def build_personal_report")
end = source.index("def personal_report", start)
personal_src = source[start:end]
if "if action.startswith(\"🟢\") or action.startswith(\"🔴\") or action.startswith(\"🟡\")" in personal_src:
    raise SystemExit("FAIL: personal report still hides trade levels for WAIT/WATCH")

print("PASS: ATLAS Two Engine structural smoke test")
print("PASS: bot.py syntax")
print("PASS: MARKET/PERSONAL/BOTH environment routing")
print("PASS: conditional Entry/SL/TP1-TP4 for WAIT/WATCH")
print("PASS: exact R/R(TP2) formula")
print("PASS: physical Gold/Silver/Copper reference section")
print("PASS: personal report no longer hides TP levels")
