"""ATLAS Signal Opportunity Engine V2.2 — dependency-free production module.
Consumes closed OHLCV rows [timestamp, open, high, low, close, volume].
It does NOT authorize execution. Canonical execution remains in bot.py.
"""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional, Sequence
import math, urllib.parse
from datetime import datetime, timezone, time as dt_time
from zoneinfo import ZoneInfo

ENGINE_VERSION='ATLAS_SIGNAL_OPPORTUNITY_V2_3'

DEFAULT_CONFIG={
 "ema_fast":20,"ema_slow":50,"rsi_period":14,"atr_period":14,"breakout_lookback":20,"swing_lookback":12,
 "setup_confidence":54.0,"pretrigger_confidence":62.0,"confirmed_confidence":68.0,"pretrigger_atr_distance":0.45,
 "structure_atr_buffer":0.25,"fallback_sl_atr_mult":1.5,"volume_confirm_ratio":1.10,
 "tp_r_multiples":(1.0,2.0,3.0,4.0),"mtf_bonus_same":8.0,"mtf_penalty_opposite":8.0,"min_bars":80,
}
def _f(v):
 try:
  x=float(v); return x if math.isfinite(x) else None
 except (TypeError,ValueError): return None
def _ema(a,n):
 if len(a)<n:return None
 k=2/(n+1); e=sum(a[:n])/n
 for v in a[n:]:e=v*k+e*(1-k)
 return e
def _rsi(a,n=14):
 if len(a)<=n:return None
 g=[];l=[]
 for i in range(1,len(a)):
  d=a[i]-a[i-1];g.append(max(d,0));l.append(max(-d,0))
 ag=sum(g[-n:])/n;al=sum(l[-n:])/n
 return 100. if al==0 else 100-(100/(1+ag/al))
def _atr(rows,n=14):
 if len(rows)<=n:return None
 tr=[]
 for i in range(1,len(rows)):
  h,l,pc=_f(rows[i][2]),_f(rows[i][3]),_f(rows[i-1][4])
  if None not in (h,l,pc):tr.append(max(h-l,abs(h-pc),abs(l-pc)))
 return sum(tr[-n:])/n if len(tr)>=n else None
def _macd_hist(a):
 if len(a)<35:return (None,None)
 def series(n):
  k=2/(n+1);e=sum(a[:n])/n;out=[None]*(n-1)+[e]
  for v in a[n:]:e=v*k+e*(1-k);out.append(e)
  return out
 e12,e26=series(12),series(26); mac=[None if x is None or y is None else x-y for x,y in zip(e12,e26)]
 vals=[x for x in mac if x is not None]
 if len(vals)<10:return (None,None)
 k=2/10; sig=sum(vals[:9])/9; hs=[]
 for v in vals[9:]:sig=v*k+sig*(1-k);hs.append(v-sig)
 return (hs[-1],hs[-1]-hs[-2] if len(hs)>1 else None)
def tradingview_link(symbol,exchange=None):
 s=str(symbol or '').upper().replace('/','').replace('-','').replace(' ',''); tv=f"{str(exchange).upper()}:{s}" if exchange else s
 return 'https://www.tradingview.com/chart/?symbol='+urllib.parse.quote(tv,safe=':')
def _session_context(ts=None):
 """DST-safe market-session context. Boundaries are built in each market's own timezone."""
 try:
  if ts is None: dt=datetime.now(timezone.utc)
  elif isinstance(ts,(int,float)): dt=datetime.fromtimestamp(float(ts)/1000.0 if float(ts)>1e11 else float(ts),timezone.utc)
  else:
   z=str(ts).replace('Z','+00:00'); dt=datetime.fromisoformat(z)
   if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
  dt=dt.astimezone(timezone.utc); paris=dt.astimezone(ZoneInfo('Europe/Paris'))
  london=dt.astimezone(ZoneInfo('Europe/London')); ny=dt.astimezone(ZoneInfo('America/New_York')); tokyo=dt.astimezone(ZoneInfo('Asia/Tokyo'))
  lm=london.hour*60+london.minute; nm=ny.hour*60+ny.minute; tm=tokyo.hour*60+tokyo.minute
  london_open=8*60 <= lm < 16*60+30
  ny_open=9*60+30 <= nm < 16*60
  asia_open=9*60 <= tm < 15*60
  if london_open and ny_open:sess='LONDON_NY_OVERLAP'
  elif ny_open:sess='NEW_YORK'
  elif london_open:sess='EUROPE'
  elif asia_open:sess='ASIA'
  else:sess='LOW_LIQUIDITY'
  return {'name':sess,'timezone':'Europe/Paris','local_time':paris.isoformat(),'london_time':london.isoformat(),'new_york_time':ny.isoformat(),'dst_safe':True,'research_only':True}
 except Exception:return {'name':'UNKNOWN','timezone':'Europe/Paris','dst_safe':True,'research_only':True}

def _regime_context(closes,atr,ef,es):
 if not closes or not atr or not closes[-1]: return {'trend':'UNKNOWN','volatility':'UNKNOWN','research_only':True}
 px=closes[-1]; atr_pct=atr/px*100
 spread=abs(ef-es)/px*100 if ef is not None and es is not None else 0
 trend='TRENDING' if spread>=0.45 else 'RANGING'
 vol='HIGH' if atr_pct>=3.0 else 'LOW' if atr_pct<=1.2 else 'NORMAL'
 return {'trend':trend,'volatility':vol,'atr_pct':round(atr_pct,3),'ema_spread_pct':round(spread,3),'research_only':True}

def _family_score(direction,ef,es,rsi,mh,md,hv,price,ph,pl,mtf_same,mtf_opp,deriv_adj):
 long=direction=='LONG'
 trend=0
 trend += 45 if ((ef>es)==long) else -45
 if rsi is not None: trend += 20 if ((rsi>=52)==long and (rsi<75 if long else rsi>25)) else 0
 if mh is not None: trend += 20 if ((mh>0)==long) else -20
 if md is not None: trend += 15 if ((md>0)==long) else -15
 structure=70 if (price>ph if long else price<pl) else 25
 volume=70 if hv else 40
 mtf=max(-100,min(100,(mtf_same-mtf_opp)*35))
 derivatives=max(-100,min(100,deriv_adj/6*100))
 return {'TREND':round(max(-100,min(100,trend)),1),'STRUCTURE':structure,'VOLUME':volume,'MTF':round(mtf,1),'DERIVATIVES_SHADOW':round(derivatives,1)}

def analyze_rows(rows:Sequence[Sequence[Any]],symbol='',timeframe='4h',config:Optional[Mapping[str,Any]]=None,*,mtf_context=None,derivatives=None,exchange=None)->Dict[str,Any]:
 c={**DEFAULT_CONFIG,**dict(config or {})}; base={'engine':ENGINE_VERSION,'symbol':symbol,'timeframe':timeframe,'state':'NO_TRADE','signal':'WATCH','bias':'NEUTRAL','executable':False,'confidence':0.0,'trade_plan':None,'tradingview':tradingview_link(symbol,exchange)}
 clean=[]
 for r in rows or []:
  if len(r)<6:continue
  o,h,l,cl,v=map(_f,(r[1],r[2],r[3],r[4],r[5]))
  if None not in (o,h,l,cl,v):clean.append((r[0],o,h,l,cl,v))
 if len(clean)<c['min_bars']:return {**base,'reason':f"insufficient closed bars {len(clean)}/{c['min_bars']}"}
 closes=[r[4] for r in clean]; vols=[r[5] for r in clean]; price=closes[-1]; ef=_ema(closes,c['ema_fast']);es=_ema(closes,c['ema_slow']);rsi=_rsi(closes,c['rsi_period']);atr=_atr(clean,c['atr_period']);mh,md=_macd_hist(closes)
 if None in (ef,es,rsi,atr) or atr<=0:return {**base,'reason':'indicator geometry unavailable'}
 bull=bear=0.;why=[]
 if ef>es:bull+=20;why.append('EMA trend bullish')
 else:bear+=20;why.append('EMA trend bearish')
 if 52<=rsi<75:bull+=10
 elif 25<rsi<=48:bear+=10
 elif rsi>=75:bear+=3;why.append('RSI high caution')
 elif rsi<=25:bull+=3;why.append('RSI low caution')
 if mh is not None:
  if mh>0:bull+=8+(5 if md is not None and md>0 else 0);why.append('MACD bullish')
  elif mh<0:bear+=8+(5 if md is not None and md<0 else 0);why.append('MACD bearish')
 vma=sum(vols[-20:])/min(20,len(vols)); hv=vma>0 and vols[-1]/vma>=c['volume_confirm_ratio']
 if hv:
  if bull>=bear:bull+=8
  else:bear+=8
  why.append('volume confirmation')
 n=c['breakout_lookback']; prior=clean[-(n+1):-1]; ph=max(r[2] for r in prior);pl=min(r[3] for r in prior)
 if price>ph:bull+=16;why.append('closed bullish breakout')
 if price<pl:bear+=16;why.append('closed bearish breakdown')
 direction='LONG' if bull>=bear else 'SHORT'; raw,opp=(bull,bear) if direction=='LONG' else (bear,bull); conf=max(0,min(100,42+raw*.7-opp*.35))
 same=opposite=neutral=0
 for v in (mtf_context or {}).values():
  s=str(v or '').upper();good=('BULL','LONG','BUY') if direction=='LONG' else ('BEAR','SHORT','SELL');bad=('BEAR','SHORT','SELL') if direction=='LONG' else ('BULL','LONG','BUY')
  if any(k in s for k in good):same+=1
  elif any(k in s for k in bad):opposite+=1
  else:neutral+=1
 total=same+opposite+neutral
 if total:conf+=c['mtf_bonus_same']*same/total-c['mtf_penalty_opposite']*opposite/total
 # Derivatives are one confirmation family; they never create direction.
 dd=0.;e=derivatives or {};taker=_f(e.get('taker_buy_sell_ratio'));oi=_f(e.get('oi_change_pct'));fund=_f(e.get('funding_rate'))
 if oi is not None and oi>0:dd+=1.5
 if taker is not None:
  if direction=='LONG' and taker>1.03:dd+=2.5
  elif direction=='SHORT' and taker<.97:dd+=2.5
  elif direction=='LONG' and taker<.94:dd-=2.5
  elif direction=='SHORT' and taker>1.06:dd-=2.5
 if fund is not None and ((direction=='LONG' and fund>.001) or (direction=='SHORT' and fund<-.001)):dd-=2
 dd=max(-6,min(6,dd));conf=max(0,min(100,conf+dd))
 trigger=ph if direction=='LONG' else pl;crossed=price>trigger if direction=='LONG' else price<trigger;near=abs(trigger-price)<=atr*c['pretrigger_atr_distance']
 if crossed and conf>=c['confirmed_confidence']:state='CONFIRMED';confirmed=True
 elif near and conf>=c['pretrigger_confidence']:state='PRE_TRIGGER';confirmed=False
 elif conf>=c['setup_confidence']:state='SETUP';confirmed=False
 else:state='NO_TRADE';confirmed=False
 hist=clean[-(c['swing_lookback']+1):-1];sw=min(r[3] for r in hist) if direction=='LONG' else max(r[2] for r in hist);entry=price if confirmed else trigger;buf=atr*c['structure_atr_buffer']
 if direction=='LONG':sl=sw-buf if sw<entry else entry-atr*c['fallback_sl_atr_mult'];risk=entry-sl;sgn=1;inv=f"closed candle below {sl:.8f}"
 else:sl=sw+buf if sw>entry else entry+atr*c['fallback_sl_atr_mult'];risk=sl-entry;sgn=-1;inv=f"closed candle above {sl:.8f}"
 plan=None
 if risk>0:
  t=[entry+sgn*risk*x for x in c['tp_r_multiples'][:4]];plan={'direction':direction,'entry':round(entry,8),'stop_loss':round(sl,8),'tp1':round(t[0],8),'tp2':round(t[1],8),'tp3':round(t[2],8),'tp4':round(t[3],8),'risk_reward_tp2':2.0,'invalidation':inv}
 sig='BUY' if confirmed and direction=='LONG' else 'SELL' if confirmed else 'WATCH'
 return {**base,'state':state,'signal':sig,'bias':direction,'executable':confirmed,'confidence':round(conf,2),'price':round(price,8),'trigger':round(trigger,8),'trade_plan':plan,'reason':' | '.join(why+[f'MTF {same}/{opposite}/{neutral}',state]),'session_context':_session_context(clean[-1][0]),'regime_context':_regime_context(closes,atr,ef,es),'evidence_families':_family_score(direction,ef,es,rsi,mh,md,hv,price,ph,pl,same,opposite,dd),'promotion_gate':'WALK_FORWARD+ABLATION+OOS+COSTS','shadow_families':['DERIVATIVES_SHADOW','SMC_FVG_OB'],'evidence':{'bull_points':bull,'bear_points':bear,'derivatives_adjustment':dd,'derivatives_mode':'SHADOW_CONFIRMATION_ONLY','double_count_guard':True},'indicators':{'ema_fast':round(ef,8),'ema_slow':round(es,8),'rsi':round(rsi,2),'atr':round(atr,8),'macd_hist':None if mh is None else round(mh,8),'volume_ratio':round(vols[-1]/vma,3) if vma else None}}

def enrich_result(result:Dict[str,Any])->Dict[str,Any]:
 """Attach opportunity fields without overwriting canonical decision/execution fields."""
 r=result; rows=((r.get('snapshots') or {}).get('4h') or {}).get('rows') or []
 mtf={'15m':r.get('m15_trend'),'1h':r.get('h1_trend'),'4h':r.get('h4_trend'),'1d':r.get('d1_trend'),'1w':r.get('w1_trend')}
 d={'funding_rate':r.get('coinglass_funding_rate') or r.get('funding_rate'),'oi_change_pct':r.get('open_interest_change') or r.get('oi_change') or r.get('oi_change_pct'),'taker_buy_sell_ratio':r.get('taker_buy_sell_ratio') or r.get('taker_ratio')}
 o=analyze_rows(rows,str(r.get('coin') or ''),'4h',mtf_context=mtf,derivatives=d)
 p=o.get('trade_plan') or {};r['opportunity_engine']=o;r['opportunity_state']=o.get('state');r['opportunity_bias']=o.get('bias');r['opportunity_confidence']=o.get('confidence');r['opportunity_trigger']=o.get('trigger');r['opportunity_tv']=o.get('tradingview')
 # Conditional geometry is exposed for SETUP/PRE_TRIGGER; canonical Entry/SL/TP is never overwritten.
 r['opportunity_session']=o.get('session_context');r['opportunity_regime']=o.get('regime_context');r['opportunity_evidence_families']=o.get('evidence_families');r['opportunity_promotion_gate']=o.get('promotion_gate');
 r['opportunity_entry']=p.get('entry');r['opportunity_sl']=p.get('stop_loss');r['opportunity_tp1']=p.get('tp1');r['opportunity_tp2']=p.get('tp2');r['opportunity_tp3']=p.get('tp3');r['opportunity_tp4']=p.get('tp4');r['opportunity_rr']=p.get('risk_reward_tp2');r['opportunity_invalidation']=p.get('invalidation')
 r['opportunity_attribution']={'status':'PENDING_OUTCOME_REPLAY','planned_rr':p.get('risk_reward_tp2'),'mfe_r':None,'mae_r':None,'realized_r':None,'fees_r':None,'slippage_r':None,'engine':ENGINE_VERSION}
 r['opportunity_shadow_only']=True
 return r
