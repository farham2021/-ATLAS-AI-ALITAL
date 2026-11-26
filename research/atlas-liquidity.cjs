'use strict';
// Independent OHLCV liquidity proxy, shadow only. time denotes candle CLOSE.
const q=require('./quant-core.cjs');
const finite=Number.isFinite;
function radar(rows,{asOf,intervalMs,lookback=20,riskPct=1.5,equity=1000,feeBps=10,slippageBps=5}={}){
 const unavailable=reason=>({status:'unavailable',reason,mode:'shadow'});
 if(!finite(asOf)||!Number.isInteger(intervalMs)||intervalMs<=0||!Number.isInteger(lookback)||lookback<14||![riskPct,equity,feeBps,slippageBps].every(finite)||riskPct<=0||riskPct>1.5||equity<=0||feeBps<0||slippageBps<0)return unavailable('invalid_configuration');
 let c;try{if(!Array.isArray(rows)||rows.some(r=>!r||['open','high','low','close','volume'].some(k=>r[k]===null||r[k]===undefined||r[k]==='')))return unavailable('invalid_candles');c=q.normalizeCandles(rows).filter(r=>Date.parse(r.time)<=asOf)}catch{return unavailable('invalid_candles')}
 if(c.length<lookback+15)return unavailable('insufficient_history');
 c=c.slice(-(lookback+15));const last=c.at(-1),prev=c.at(-2);
 if(asOf-Date.parse(last.time)>=intervalMs||c.some((r,i)=>i&&Date.parse(r.time)-Date.parse(c[i-1].time)!==intervalMs))return unavailable('stale_or_gapped');
 const hist=c.slice(-lookback-1,-1),upper=Math.max(...hist.map(r=>r.high)),lower=Math.min(...hist.map(r=>r.low));
 const atr=q.atr(c.slice(0,-1)).at(-1);if(!(atr>0))return unavailable('zero_volatility');
 const up=last.low<lower&&last.close>lower,down=last.high>upper&&last.close<upper;
 const nearUp=Math.abs(last.close-lower)<=.5*atr,nearDown=Math.abs(last.close-upper)<=.5*atr;
 const vol=hist.reduce((s,r)=>s+r.volume,0)/hist.length,relativeVolume=vol>0?last.volume/vol:null;
 const fvg=last.low>c.at(-3).high?'bullish':last.high<c.at(-3).low?'bearish':null;
 const base={mode:'shadow',as_of:new Date(asOf).toISOString(),candle_close:last.time,upper,lower,atr,relativeVolume,fvg,liquidity_type:'OHLCV proxy',score:null,probability:null};
 if(up&&down)return {...base,status:'INVALIDATED',reason:'ambiguous_dual_sweep'};
 const direction=up?'LONG':down?'SHORT':nearUp&&!nearDown?'LONG':nearDown&&!nearUp?'SHORT':null;
 if(!direction)return {...base,status:'WATCH',direction:null};
 const confirmed=(up||down)&&relativeVolume!==null&&relativeVolume>=1.2;
 if(!confirmed)return {...base,status:up||down?'EARLY_WARNING':'WATCH',direction,reason:up||down?'sweep_without_volume_confirmation':'near_liquidity'};
 const sign=direction==='LONG'?1:-1,entry=last.close,stop=sign===1?last.low-.25*atr:last.high+.25*atr;
 const cost=entry*(feeBps+slippageBps)/10000*2,unitRisk=Math.abs(entry-stop)+cost;
 const target=entry+sign*(2*unitRisk+cost);
 if(stop<=0||target<=0||!finite(unitRisk)||unitRisk<=0)return {...base,status:'INVALIDATED',reason:'invalid_risk'};
 const quantity=Math.min(equity*riskPct/100/unitRisk,equity/entry);
 return {...base,status:'CONFIRMED',direction,entry_reference:entry,stop,target,quantity,net_rr:2,planned_loss:quantity*unitRisk,execution:'next executable quote; reprice and revalidate',live_orders:false};
}
module.exports={radar};
