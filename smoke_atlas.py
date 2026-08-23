!/usr/bin/env python3
from pathlib import Path
import ast
BOT=Path(__file__).with_name("ATLAS_bot_two_engine.py")
def fail(x): print("FAIL:",x); raise SystemExit(1)
if not BOT.exists(): fail("ATLAS_bot_two_engine.py not found")
s=BOT.read_text(encoding="utf-8")
try: t=ast.parse(s)
except SyntaxError as e: fail(e)
f=[n.name for n in t.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
for x in ("build_report","build_personal_report","build_two_engine_reports","atlas_engine_mode"):
    if x not in f: fail("missing "+x)
if f.count("build_report")!=1: fail("build_report must exist exactly once")
for x in ("MARKET","PERSONAL","BOTH","ATLAS_PERSONAL_ASSETS","TP1","TP2","TP3","TP4"):
    if x not in s: fail("missing token "+x)
compile(s,str(BOT),"exec")
print("PASS: ATLAS two-engine smoke test")
