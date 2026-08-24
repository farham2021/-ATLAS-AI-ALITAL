#!/usr/bin/env python3
"""Offline smoke test for ATLAS AI v10.2.

Does not call Telegram, exchanges, CoinGecko, or any external API.
"""
from pathlib import Path
import ast
import py_compile

BOT = Path(__file__).with_name("bot.py")
if not BOT.exists():
    raise SystemExit("FAIL: bot.py not found")

py_compile.compile(str(BOT), doraise=True)
source = BOT.read_text(encoding="utf-8-sig")
tree = ast.parse(source, filename="bot.py")
functions = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
required = {
    "asset_block", "action_emoji", "btc_pair_candidates",
    "compact_table_1", "compact_table_2", "compact_summary",
    "build_report", "main"
}
missing = sorted(required - functions)
if missing:
    raise SystemExit(f"FAIL: missing functions: {missing}")

if sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_report") != 1:
    raise SystemExit("FAIL: build_report must exist exactly once")

for token in ("TP1", "TP2", "TP3", "TP4", "SL", "R/R", "BUY", "SELL", "WAIT"):
    if token not in source.upper():
        raise SystemExit(f"FAIL: required token missing: {token}")

if "ATLAS_PRIORITY_TOP10" not in source:
    raise SystemExit("FAIL: market leader universe missing")

print("PASS: bot.py syntax")
print("PASS: asset_block/action_emoji")
print("PASS: compact renderer")
print("PASS: single build_report")
print("PASS: TP1-TP4 / SL / R/R")
print("PASS: market-leader Top 10 architecture")
print("PASS: offline smoke test")
