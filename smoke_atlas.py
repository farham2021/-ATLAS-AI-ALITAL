#!/usr/bin/env python3
from pathlib import Path
import ast

BOT = Path(__file__).with_name("bot.py")

def fail(msg):
    print("FAIL:", msg)
    raise SystemExit(1)

if not BOT.exists(): fail("bot.py not found")
s = BOT.read_text(encoding="utf-8")
try: tree = ast.parse(s)
except SyntaxError as e: fail(e)
funcs=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
required=("build_report","build_personal_report","build_two_engine_reports","atlas_engine_mode","asset_block","action_emoji","tradingview_chart_url","top5_opportunities","metals_report","calculate_levels","_ensure_candidate_plan","main")
for name in required:
    if funcs.count(name)!=1: fail(f"{name} must exist exactly once")
for token in ("ATLAS_PERSONAL_ASSETS","ATLAS_METALS","TOP 5 OPPORTUNITIES","DYNAMIC TOP 30","TradingView","Chart:","TP1","TP2","TP3","TP4","MARKET","PERSONAL","BOTH","shamsi","CONDITIONAL BUY","CONDITIONAL SELL","stablecoin","AMBIGUOUS_DYNAMIC_SYMBOLS"):
    if token not in s: fail(f"missing token: {token}")
if 'if __name__ == "__main__":' not in s: fail("missing executable entrypoint")
entry=s.index('if __name__ == "__main__":')
if s.find('def build_two_engine_reports')>entry: fail("two-engine dispatcher defined after entrypoint")
if s.find('def build_personal_report')>entry: fail("personal engine defined after entrypoint")
compile(s,str(BOT),"exec")
print("PASS: ATLAS v10.2 TWO-ENGINE V3 smoke test")
