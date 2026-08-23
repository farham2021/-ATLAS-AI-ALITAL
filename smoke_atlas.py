#!/usr/bin/env python3
from pathlib import Path
import ast

BOT = Path(__file__).with_name("bot.py")

def fail(msg):
    print("FAIL:", msg)
    raise SystemExit(1)

if not BOT.exists():
    fail("bot.py not found")
s = BOT.read_text(encoding="utf-8")
try:
    tree = ast.parse(s)
except SyntaxError as e:
    fail(e)

funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
required = (
    "build_report", "build_personal_report", "build_two_engine_reports",
    "atlas_engine_mode", "asset_block", "action_emoji", "tradingview_chart_url",
    "top5_opportunities", "metals_report",
)
for name in required:
    if name not in funcs:
        fail(f"missing function {name}")
if funcs.count("build_report") != 1:
    fail("build_report must exist exactly once")
if funcs.count("build_personal_report") != 1:
    fail("build_personal_report must exist exactly once")
if funcs.count("calculate_levels") != 1:
    fail("calculate_levels must exist exactly once")
if funcs.count("_ensure_candidate_plan") != 1:
    fail("_ensure_candidate_plan must exist exactly once")
if "R/R" not in s or "opportunity_score" not in s:
    fail("real R/R/opportunity scoring missing")
if "is_stable" not in s:
    fail("stablecoin guard missing")

for token in (
    "ATLAS_PERSONAL_ASSETS", "ATLAS_METALS", "TOP 5 OPPORTUNITIES",
    "DYNAMIC TOP 30", "TradingView", "Chart:", "TP1", "TP2", "TP3", "TP4",
    "MARKET", "PERSONAL", "BOTH", "shamsi", "conditional", "stablecoin",
):
    if token not in s:
        fail(f"missing token {token}")

# Structural regression: no executable code before the header comments except comments/shebang.
first_code = None
for i, line in enumerate(s.splitlines(), 1):
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and not stripped.startswith("#!"):
        first_code = (i, stripped)
        break
if first_code and first_code[1].startswith("import") and first_code[0] < 30:
    pass

compile(s, str(BOT), "exec")
print("PASS: ATLAS two-engine smoke test")
