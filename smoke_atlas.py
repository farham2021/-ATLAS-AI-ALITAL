#!/usr/bin/env python3
from pathlib import Path
import ast, py_compile, re

ROOT=Path(__file__).resolve().parent
BOT=ROOT/"bot.py"
if not BOT.exists(): raise SystemExit("FAIL: bot.py not found")
src=BOT.read_text(encoding="utf-8")
py_compile.compile(str(BOT), doraise=True)
tree=ast.parse(src)
funcs={n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
required={"asset_block","action_emoji","build_report","build_personal_report","personal_report","report",
          "main","calculate_levels","decision_rr","_conditional_trade_plan","apply_decision_engine",
          "analyze_coin","market_breadth","checkpoint_sqlite","multi_source_validation",
          "coinmarketcap_quote","coingecko_quote","coinglass_context","tradingview_confirmation"}
missing=sorted(required-funcs)
if missing: raise SystemExit(f"FAIL: missing functions: {missing}")
if 'ATLAS_ENGINE' not in src or 'os.getenv("ATLAS_ENGINE"' not in src: raise SystemExit("FAIL: two-engine selector missing")
if 'for eid in ("binance"' in src: raise SystemExit("FAIL: Binance must not be in exchange roster")
for eid in ("lbank","xt","okx","bybit","kucoin","gateio","bitget","mexc","kraken"):
    if eid not in src: raise SystemExit(f"FAIL: exchange adapter missing: {eid}")
for x in ("COINGECKO_API_KEY","CMC_API_KEY","COINGLASS_API_KEY","TRADINGVIEW_CONFIRMATION_URL",
          "CRYPTOBUBBLES_API_URL","EASYTRADER_API_URL","OMPFINEX_API_URL","BITUNIX_API_URL",
          "TABTRADER_API_URL","KCEX_API_URL"):
    if x not in src: raise SystemExit(f"FAIL: source config missing: {x}")
if "candidate_levels = calculate_levels" not in src: raise SystemExit("FAIL: candidate TP/SL plan missing")
if 'levels = candidate_levels' not in src: raise SystemExit("FAIL: candidate plan not exposed")
print("PASS: ATLAS two-engine multi-source structural smoke test")
print("PASS: no Binance adapter")
print("PASS: candidate Entry/SL/TP calculation enabled for complete personal report")
