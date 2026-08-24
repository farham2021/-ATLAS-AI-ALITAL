#!/usr/bin/env python3
from pathlib import Path
import ast,re,sys
BOT=Path('bot.py')
def fail(m): print('FAIL:',m); raise SystemExit(1)
if not BOT.exists(): fail('bot.py not found')
s=BOT.read_text(encoding='utf-8')
try: t=ast.parse(s,filename=str(BOT))
except SyntaxError as e: fail(f'bot.py syntax error: {e}')
funcs=[n.name for n in t.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
if funcs.count('build_report')!=1: fail(f'build_report must exist exactly once; found {funcs.count("build_report")}')
required=['build_report','build_personal_report','build_two_engine_reports','atlas_engine_mode','analyze_coin','main','tradingview_chart_url','build_price_snapshot','send_price_snapshot','fetch_usdt_toman_public']
missing=[x for x in required if x not in funcs]
if missing: fail('missing required functions: '+', '.join(missing))
checks={
 'version v11.0': bool(re.search(r'^VERSION\s*=\s*["\']ATLAS v11\.0',s,re.M)),
 'no stale v10 markers': not bool(re.search(r'ATLAS v10|v10\.[0-9]|10\.2',s)),
 'single build_report': funcs.count('build_report') == 1,
 'single build_personal_report': funcs.count('build_personal_report') == 1,
 'single build_two_engine_reports': funcs.count('build_two_engine_reports') == 1,
 'two-engine': all(x in s for x in ('MARKET','PERSONAL','BOTH')),
 'personal portfolio': 'ATLAS_PERSONAL_ASSETS' in s,
 'metals': 'ATLAS_METALS' in s and all(x in s for x in ('GOLD','SILVER','COPPER')),
 'TradingView links': 'tradingview.com/chart/?symbol=' in s,
 'separate 3h snapshot': 'send_price_snapshot' in s and '۳ ساعت' in s,
 'public Iranian USDT sources': all(x in s.lower() for x in ('wallex.ir','excoino.com','nobitex.ir')),
 'closed-candle logic': 'strip_incomplete' in s or 'candle_is_closed' in s or 'closed' in s.lower(),
}
for k,v in checks.items():
 if not v: fail(k)
compile(s,str(BOT),'exec')
print('PASS: ATLAS v11.0 unified two-engine smoke test')
for k in checks: print('  OK:',k)
