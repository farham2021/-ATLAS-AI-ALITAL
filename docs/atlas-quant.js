/* ATLAS Quant Risk v3 — read-only, client-side, closed candles, no orders. */
(()=>{'use strict';
const $=id=>document.getElementById(id), allowed=new Set(['BTC','ETH','SOL','SUI','BNB','XRP','LINK','TON','ADA','DOGE','AVAX','TRX']);
const finite=x=>Number.isFinite(x), clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
function indicators(rows){
 const c=rows.map(x=>x.close),h=rows.map(x=>x.high),l=rows.map(x=>x.low),n=c.length;
 if(n<250||rows.some(x=>![x.close,x.high,x.low].every(finite)))throw Error('حداقل ۲۵۰ کندل معتبر لازم است');
 let ema=c.slice(0,200).reduce((a,b)=>a+b,0)/200;
 for(let i=200;i<n;i++)ema+=2/201*(c[i]-ema);
 const rsiValues=[],tr=[];
 for(let i=1;i<n;i++){const d=c[i]-c[i-1];rsiValues.push([Math.max(0,d),Math.max(0,-d)]);tr.push(Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])))}
 let gain=0,loss=0,atr=0;for(let i=0;i<14;i++){gain+=rsiValues[i][0];loss+=rsiValues[i][1];atr+=tr[i]}gain/=14;loss/=14;atr/=14;
 for(let i=14;i<rsiValues.length;i++){gain=(gain*13+rsiValues[i][0])/14;loss=(loss*13+rsiValues[i][1])/14;atr=(atr*13+tr[i])/14}
 const rsi=loss===0?(gain===0?50:100):100-100/(1+gain/loss);
 const price=c[n-1],mean=c.slice(-20).reduce((a,b)=>a+b,0)/20;
 const std=Math.sqrt(c.slice(-20).reduce((a,b)=>a+(b-mean)**2,0)/20);
 const band=std?clamp((price-(mean-2*std))/(4*std),0,1):.5;
 const dist=(price/ema-1)*100,vol=atr/price*100;
 // Composite is a heuristic exposure-risk index, not a probability or buy signal.
 const trend=clamp(Math.abs(dist)/20,0,1), momentum=clamp(Math.abs(rsi-50)/50,0,1);
 const score=Math.round(100*(.30*momentum+.40*trend+.20*clamp(vol/8,0,1)+.10*Math.abs(band-.5)*2));
 return {price,rsi,ema,dist,atr,vol,band,score};
}
async function load(symbol,tf){
 if(!allowed.has(symbol)||!['4h','1d'].includes(tf))throw Error('نماد یا بازه نامعتبر');
 const pair=symbol+'USDT', now=Date.now(),ms=tf==='4h'?14400000:86400000;
 const ids={BTC:'bitcoin',ETH:'ethereum',SOL:'solana',SUI:'sui',BNB:'binancecoin',XRP:'ripple',LINK:'chainlink',TON:'the-open-network',ADA:'cardano',DOGE:'dogecoin',AVAX:'avalanche-2',TRX:'tron'};
 // CoinGecko is first. Public OHLC free-tier: 30 days at 4H (insufficient EMA200);
 // 365 days at 4-day resolution (not daily). Reject unsuitable granularity.
 try{
  const days=tf==='4h'?30:365, url='https://api.coingecko.com/api/v3/coins/'+ids[symbol]+'/ohlc?vs_currency=usd&days='+days;
  const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),9000);let response;
  try{response=await fetch(url,{signal:ctrl.signal,cache:'no-store'})}finally{clearTimeout(timer)}
  if(response.ok){const raw=await response.json();if(Array.isArray(raw)){
   const series=raw.map(r=>({time:+r[0]-ms,high:+r[2],low:+r[3],close:+r[4]})).filter(r=>r.time+ms<=now).sort((a,b)=>a.time-b.time);
   const spacing=series.length>1?series[1].time-series[0].time:0;
   if(series.length>=250&&spacing===ms)return {data:indicators(series),source:'CoinGecko OHLC',asof:new Date(series.at(-1).time+ms).toISOString(),count:series.length};
  }}
 }catch(_){/* unsupported or throttled public history: continue to exchanges */ }
 const sources=[
  {name:'OKX',url:'https://www.okx.com/api/v5/market/history-candles?instId='+pair.replace('USDT','-USDT')+'&bar='+(tf==='4h'?'4H':'1D')+'&limit=300',parse:d=>{if(d.code!=='0')throw Error('OKX invalid');return d.data.filter(r=>r[8]==='1').map(r=>({time:+r[0],high:+r[2],low:+r[3],close:+r[4]}))}},
  {name:'Bybit',url:'https://api.bybit.com/v5/market/kline?category=spot&symbol='+pair+'&interval='+(tf==='4h'?'240':'D')+'&limit=350',parse:d=>{if(d.retCode!==0)throw Error('Bybit invalid');return d.result.list.map(r=>({time:+r[0],high:+r[2],low:+r[3],close:+r[4]}))}},
  {name:'Binance (backup)',url:'https://api.binance.com/api/v3/klines?symbol='+pair+'&interval='+tf+'&limit=350',parse:d=>{if(!Array.isArray(d))throw Error('Binance invalid');return d.map(r=>({time:+r[0],high:+r[2],low:+r[3],close:+r[4]}))}}
 ];
 const errors=[];
 for(const src of sources){try{const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),9000);let response;try{response=await fetch(src.url,{signal:ctrl.signal,cache:'no-store'})}finally{clearTimeout(timer)}if(!response.ok)throw Error('HTTP '+response.status);const raw=src.parse(await response.json());
 const unique=[...new Map(raw.filter(r=>r.time+ms<=now&&r.time>0&&r.high>=r.low&&r.low>0&&r.close>=r.low&&r.close<=r.high).map(r=>[r.time,r])).values()].sort((a,b)=>a.time-b.time);
 if(unique.length<250)throw Error('insufficient closed candles: '+unique.length);
 return {data:indicators(unique),source:src.name,asof:new Date(unique.at(-1).time+ms).toISOString(),count:unique.length};
 }catch(e){errors.push(src.name+': '+e.message)}}
 throw Error('داده کافی نیست ('+errors.join('; ')+')');
}
function render(d,symbol,tf){const el=$('atlas-quant-live');if(!el)return;const x=d.data,fmt=n=>n.toLocaleString('en-US',{maximumFractionDigits:4});
 el.replaceChildren();const title=document.createElement('strong');title.textContent=symbol+' '+tf+' — ریسک نوسان/روند: '+x.score+'/100';el.append(title);
 const bar=document.createElement('div');bar.style='height:9px;border-radius:8px;background:#29394b;margin:10px 0';const fill=document.createElement('div');fill.style='height:100%;width:'+x.score+'%;background:'+(x.score>=70?'#ef4444':x.score>=40?'#f59e0b':'#10b981')+';border-radius:8px';bar.append(fill);el.append(bar);
 const p=document.createElement('p');p.textContent='قیمت $'+fmt(x.price)+' | RSI14 '+x.rsi.toFixed(1)+' | EMA200 $'+fmt(x.ema)+' | فاصله '+x.dist.toFixed(2)+'% | ATR14 '+x.vol.toFixed(2)+'% | Bollinger %B '+x.band.toFixed(2);el.append(p);
 const foot=document.createElement('small');foot.textContent='منبع کندل: '+d.source+' | آخرین کندل بسته‌شده: '+d.asof+' | '+d.count+' کندل. شاخص اکتشافی؛ توصیه خرید/فروش یا احتمال زیان نیست.';el.append(foot);
}
function init(){const anchor=$('quantRiskOutput');if(!anchor||$('atlas-quant-live'))return;
 const wrap=document.createElement('section');wrap.className='card';wrap.style.marginTop='12px';wrap.innerHTML='<h3>ATLAS Client-Side Quant Risk (آزمایشی)</h3><label>بازه <select id="atlas-quant-tf"><option value="4h">4H</option><option value="1d">1D</option></select></label> <button type="button" id="atlas-quant-refresh">محاسبه با کندل بسته‌شده</button><div id="atlas-quant-live" role="status" aria-live="polite">منتظر دریافت داده</div>';
 anchor.after(wrap);const select=$('quantRiskSymbol'),run=async()=>{const symbol=select.value,tf=$('atlas-quant-tf').value,el=$('atlas-quant-live');el.textContent='در حال دریافت داده…';try{const result=await load(symbol,tf);if(select.value===symbol&&$('atlas-quant-tf').value===tf)render(result,symbol,tf)}catch(e){el.textContent=e.message+'؛ این نماد بدون امتیاز باقی می‌ماند.'}};
 $('atlas-quant-refresh').onclick=run;$('atlas-quant-tf').onchange=run;select.addEventListener('change',run);run();
}
window.ATLASQuant={indicators,load};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();