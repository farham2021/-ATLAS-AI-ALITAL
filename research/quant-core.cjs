'use strict';
// Research-only analytics: no trading, no live alerts, no fabricated OHLCV.
function normalizeCandles(rows){
 if(!Array.isArray(rows))throw Error('candles must be an array');
 const seen=new Set();
 return rows.map(r=>{
  const t=Date.parse(r.time??r.timestamp??r.captured_at);
  const c=Number(r.close),o=Number(r.open),h=Number(r.high),l=Number(r.low),v=Number(r.volume);
  if(!Number.isFinite(t)||![c,o,h,l,v].every(Number.isFinite)||l<=0||v<0||h<Math.max(o,c,l)||l>Math.min(o,c)||seen.has(t))throw Error('invalid or duplicate OHLCV candle');
  seen.add(t);return {time:new Date(t).toISOString(),open:o,high:h,low:l,close:c,volume:v};
 }).sort((a,b)=>a.time.localeCompare(b.time));
}
function sma(a,n){if(!Number.isInteger(n)||n<1)throw Error('invalid period');return a.map((_,i)=>i+1<n?null:a.slice(i+1-n,i+1).reduce((s,x)=>s+x,0)/n)}
function ema(a,n){if(!Number.isInteger(n)||n<1)throw Error('invalid period');const out=Array(a.length).fill(null);if(a.length<n)return out;let e=a.slice(0,n).reduce((s,x)=>s+x,0)/n;out[n-1]=e;for(let i=n;i<a.length;i++){e=(a[i]-e)*2/(n+1)+e;out[i]=e}return out}
function rsi(a,n=14){const out=Array(a.length).fill(null);if(a.length<=n)return out;let gain=0,loss=0;for(let i=1;i<=n;i++){const d=a[i]-a[i-1];gain+=Math.max(0,d);loss+=Math.max(0,-d)}gain/=n;loss/=n;const value=()=>loss===0?(gain===0?50:100):100-100/(1+gain/loss);out[n]=value();for(let i=n+1;i<a.length;i++){const d=a[i]-a[i-1];gain=(gain*(n-1)+Math.max(0,d))/n;loss=(loss*(n-1)+Math.max(0,-d))/n;out[i]=value()}return out}
function macd(a,fast=12,slow=26,signal=9){const ef=ema(a,fast),es=ema(a,slow),line=a.map((_,i)=>ef[i]===null||es[i]===null?null:ef[i]-es[i]);const valid=line.filter(x=>x!==null),sig=ema(valid,signal),offset=line.length-valid.length;return line.map((x,i)=>({line:x,signal:i<offset?null:sig[i-offset],histogram:x===null||i<offset||sig[i-offset]===null?null:x-sig[i-offset]}))}
function atr(c,n=14){const tr=c.map((x,i)=>i===0?x.high-x.low:Math.max(x.high-x.low,Math.abs(x.high-c[i-1].close),Math.abs(x.low-c[i-1].close)));const out=Array(c.length).fill(null);if(c.length<n)return out;let a=tr.slice(0,n).reduce((s,x)=>s+x,0)/n;out[n-1]=a;for(let i=n;i<c.length;i++){a=(a*(n-1)+tr[i])/n;out[i]=a}return out}
function evaluate(rows,{maxAgeHours=48,now=Date.now()}={}){const c=normalizeCandles(rows);if(!c.length)return {status:'no_data',count:0};const ageHours=(now-Date.parse(c.at(-1).time))/3600000;if(ageHours>maxAgeHours||ageHours< -0.1)return {status:'stale',count:c.length,ageHours};if(c.length<35)return {status:'insufficient_history',count:c.length,required:35};const p=c.map(x=>x.close),i=p.length-1;return {status:'observed',count:c.length,latest_at:c[i].time,close:p[i],indicators:{rsi14:rsi(p)[i],ema12:ema(p,12)[i],ema26:ema(p,26)[i],macd:macd(p)[i],atr14:atr(c)[i]},provenance:'provided OHLCV; no predictive claim'}}
function backtest(rows,{feeBps=10,slippageBps=5}={}){const c=normalizeCandles(rows);if(c.length<40)return {status:'insufficient_history',count:c.length};const p=c.map(x=>x.close),f=ema(p,12),s=ema(p,26);let equity=1,peak=1,maxDrawdown=0,position=0,trades=0;const curve=[];for(let i=27;i<c.length;i++){const desired=f[i-1]>s[i-1]?1:0;if(desired!==position){equity*=1-(feeBps+slippageBps)/10000;trades++;position=desired}equity*=1+position*(p[i]/p[i-1]-1);peak=Math.max(peak,equity);maxDrawdown=Math.max(maxDrawdown,1-equity/peak);curve.push({time:c[i].time,equity})}return {status:'research_only',equity,returnPct:(equity-1)*100,maxDrawdownPct:maxDrawdown*100,trades,curve,assumptions:{feeBps,slippageBps,execution:'previous closed candle signal; next close-to-close return; no funding, spread or market impact'},warning:'Not a validated trading signal; test out-of-sample before use'}}
module.exports={normalizeCandles,sma,ema,rsi,macd,atr,evaluate,backtest};
