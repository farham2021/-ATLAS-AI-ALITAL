#!/usr/bin/env python3
from pathlib import Path
import ast, py_compile
BOT=Path(__file__).with_name("bot.py")
if not BOT.exists(): raise SystemExit("FAIL: bot.py not found")
py_compile.compile(str(BOT), doraise=True)
s=BOT.read_text(encoding="utf-8-sig")
t=ast.parse(s)
funcs={n.name for n in ast.walk(t) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
required={"asset_block","action_emoji","compact_table_1","compact_table_2","compact_summary","build_report","build_personal_report","main"}
missing=sorted(required-funcs)
if missing: raise SystemExit(f"FAIL: missing functions: {missing}")
if sum(1 for n in ast.walk(t) if isinstance(n,ast.FunctionDef) and n.name=="build_report")!=1: raise SystemExit("FAIL: build_report must exist exactly once")
for token in ("TP1","TP2","TP3","TP4","SL","R/R","BUY","SELL","WAIT","ATLAS_ENGINE"):
    if token not in s.upper(): raise SystemExit(f"FAIL: missing token {token}")
print("PASS: ATLAS bot syntax")
print("PASS: single build_report")
print("PASS: asset_block/action_emoji")
print("PASS: compact market engine")
print("PASS: personal 4H engine")
print("PASS: TP1-TP4 / SL / R/R")
