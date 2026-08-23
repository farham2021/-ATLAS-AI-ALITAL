# ============================================================
# ATLAS AI v10.3 — TWO ENGINE
# ============================================================
import os, math, json
from datetime import datetime, timezone, timedelta
ENGINE=os.getenv('ATLAS_ENGINE','PERSONAL').upper(); MIN_CONF=float(os.getenv('ATLAS_MIN_CONFIDENCE','60')); MIN_RR=float(os.getenv('ATLAS_MIN_EXECUTABLE_RR','2.0'))
PERSONAL_ASSETS=['BTC','ETH','BNB','XRP','SOL','TRX','DOGE','ADA','LINK','XLM','SUI','AVAX','LTC','SHIB','HBAR','DOT','BCH','XMR','NEAR','UNI','AAVE']
def _num(v):
 try:
  x=float(v); return x if math.isfinite(x) else None
 except: return None
def fmt(v,n=6):
 x=_num(v); return 'N/A' if x is None else f'{x:.{n}f}'
def action_emoji(a): return {'BUY':'🟢 BUY','SELL':'🔴 SELL','WATCH':'👀 WATCH'}.get((a or 'WAIT').upper(),'⚪ WAIT')
def _levels(price,support,resistance,side='LONG'):
 p,s,r=map(_num,(price,support,resistance)); o={'entry':None,'sl':None,'tp1':None,'tp2':None,'tp3':None,'tp4':None,'rr':None}
 if p is None or p<=0:return o
 o['entry']=p
 if side=='SHORT':
  if r is None or r<=p:return o
  o['sl']=r; risk=r-p; t=[p-risk,p-2*risk,p-3*risk,p-4*risk]
 else:
  if s is None or s>=p:return o
  o['sl']=s*.98; risk=p-o['sl']; t=[p+risk,p+2*risk,p+3*risk,p+4*risk]
  if r is not None and r>p:t[0]=min(t[0],r)
 for k,v in zip(('tp1','tp2','tp3','tp4'),t):o[k]=v
 o['rr']=abs(p-o['tp2'])/abs(p-o['sl']) if o['tp2'] is not None and o['sl'] is not None and p!=o['sl'] else None
 return o
def asset_block(a):
 p=_num(a.get('price')); sig=str(a.get('signal','WAIT')).upper(); conf=_num(a.get('confidence')) or 0; plan=_levels(p,a.get('support'),a.get('resistance'),'SHORT' if sig=='SELL' else 'LONG'); exe=sig in ('BUY','SELL') and conf>=MIN_CONF and plan['rr'] is not None and plan['rr']>=MIN_RR; shown=sig if exe else 'WAIT'
 return '\n'.join([f"🔹 {a.get('symbol','?')} | {action_emoji(shown)} | اطمینان: {conf:.0f}%",f"قیمت: ${fmt(p,8)} | 24H: {a.get('change24','N/A')}",f"H4/D1/W1: {a.get('h4','UNKNOWN')} / {a.get('d1','UNKNOWN')} / {a.get('w1','UNKNOWN')}",f"RSI: {fmt(a.get('rsi'),2)} | MACD: {a.get('macd','N/A')}",f"Entry: {fmt(plan['entry'],8)} | SL: {fmt(plan['sl'],8)}",f"TP1: {fmt(plan['tp1'],8)} | TP2: {fmt(plan['tp2'],8)} | TP3: {fmt(plan['tp3'],8)} | TP4: {fmt(plan['tp4'],8)}",f"R/R(TP2): {fmt(plan['rr'],2)} | حمایت: {fmt(a.get('support'),8)} | مقاومت: {fmt(a.get('resistance'),8)}",'دلیل: ستاپ اجرایی فقط با تأیید همزمان روند، مومنتوم، اطمینان و R/R فعال می‌شود.'])
def _assets():
 try:
  x=json.loads(os.getenv('ATLAS_ASSETS_JSON','[]')); return x if isinstance(x,list) else []
 except:return []
def _time():return (datetime.now(timezone.utc)+timedelta(hours=3,minutes=30)).strftime('%Y-%m-%d %H:%M:%S Asia/Tehran')
def build_personal_report(assets=None):
 d={str(x.get('symbol','')).upper():x for x in (assets if assets is not None else _assets())}; rows=[asset_block(d[s]) for s in PERSONAL_ASSETS if s in d]; return '🤖 ATLAS AI — گزارش کامل 4H\n━━━━━━━━━━━━━━━━━━\nتاریخ/ساعت: '+_time()+'\n\n📊 سبد شخصی تحت پایش\n\n'+('\n\n'.join(rows) if rows else 'داده بازار برای سبد شخصی در این اجرا در دسترس نیست.')
def build_market_report(assets=None):
 a=assets if assets is not None else _assets(); rows=sorted([x for x in a if _num(x.get('change24')) is not None],key=lambda x:abs(_num(x.get('change24'))),reverse=True)[:10]; return '🤖 ATLAS AI — MARKET COMPACT\n━━━━━━━━━━━━━━━━━━\n'+ ('\n\n'.join(asset_block(x) for x in rows) if rows else 'داده بازار در دسترس نیست.')
def build_report(mode=None,assets=None):
 m=(mode or ENGINE).upper(); return build_market_report(assets) if m=='MARKET' else build_market_report(assets)+'\n\n'+build_personal_report(assets) if m=='BOTH' else build_personal_report(assets)
if __name__=='__main__':print(build_report())
