/* ATLAS Futures Setup Radar v1: read-only, closed 4h candles, paper calculator only. */
(()=>{'use strict';
if(window.__atlasSetupsLoaded)return;window.__atlasSetupsLoaded=true;
const symbols=['BTC','ETH','SOL','SUI','LINK','XRP','ADA','TON'];
const $=id=>document.getElementById(id);
const N=x=>Number(x),good=x=>Number.isFinite(x),clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
function compute(raw){
 const now=Date.now(),ms=14400000;
 const rows=raw.map(r=>({t:N(r[0]),o:N(r[1]),h:N(r[2]),l:N(r[3]),c:N(r[4]),v:N(r[5])}))
  .filter(r=>[r.t,r.o,r.h,r.l,r.c,r.v].every(good)&&r.c>0&&r.l>0&&r.h>=Math.max(r.o,r.c)&&r.l<=Math.min(r.o,r.c)&&r.t+ms<=now)
  .sort((a,b)=>a.t-b.t);
 if(rows.length<250||now-(rows.at(-1).t+ms)>ms+300000||rows.slice(-250).some((r,i,a)=>i&&r.t-a[i-1].t!==ms))throw Error('stale or incomplete candles');
 const a=rows.slice(-250),c=a.map(x=>x.c),n=c.length,price=c.at(-1);
 let ema=c.slice(0,200).reduce((s,x)=>s+x,0)/200;
 for(let i=200;i<n;i++)ema+=(c[i]-ema)*2/201;
 let g=0,l=0,atr=0;
 for(let i=1;i<=14;i++){const d=c[i]-c[i-1];g+=Math.max(0,d);l+=Math.max(0,-d);atr+=Math.max(a[i].h-a[i].l,Math.abs(a[i].h-c[i-1]),Math.abs(a[i].l-c[i-1]))}
 g/=14;l/=14;atr/=14;
 for(let i=15;i<n;i++){const d=c[i]-c[i-1];g=(g*13+Math.max(0,d))/14;l=(l*13+Math.max(0,-d))/14;atr=(atr*13+Math.max(a[i].h-a[i].l,Math.abs(a[i].h-c[i-1]),Math.abs(a[i].l-c[i-1])))/14}
 const rsi=l===0?(g===0?50:100):100-100/(1+g/l);
 const mean=c.slice(-20).reduce((s,x)=>s+x,0)/20;
 const std=Math.sqrt(c.slice(-20).reduce((s,x)=>s+(x-mean)**2,0)/20);
 const percentB=std?(price-(mean-2*std))/(4*std):.5;
 const vr=a.at(-1).v/(a.slice(-21,-1).reduce((s,x)=>s+x.v,0)/20||Infinity);
 return {price,ema,rsi,atr,percentB,vr,asof:new Date(a.at(-1).t+ms).toISOString()};
}
async function load(symbol){
 const pair=symbol+'USDT',sources=[
  {name:'OKX',url:'https://www.okx.com/api/v5/market/history-candles?instId='+symbol+'-USDT&bar=4H&limit=300',parse:d=>{if(d.code!=='0')throw Error('OKX');return d.data.map(r=>[r[0],r[1],r[2],r[3],r[4],r[5]])}},
  {name:'Bybit',url:'https://api.bybit.com/v5/market/kline?category=spot&symbol='+pair+'&interval=240&limit=300',parse:d=>{if(d.retCode!==0)throw Error('Bybit');return d.result.list}},
  {name:'Binance backup',url:'https://api.binance.com/api/v3/klines?symbol='+pair+'&interval=4h&limit=300',parse:d=>d}
 ];
 for(const src of sources){try{const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),8500);
  let res;try{res=await fetch(src.url,{signal:ctrl.signal,cache:'no-store'})}finally{clearTimeout(timer)}
  if(!res.ok)continue;const d=compute(src.parse(await res.json()));return {...d,source:src.name};
 }catch(_){}}
 throw Error('No validated 4H data');
}
function setup(symbol,d){
 const {price,ema,rsi,atr,percentB,vr}=d;
 const side=price>ema&&(rsi>=35&&rsi<=55||percentB<.2)?'LONG':price<ema&&(rsi>=55&&rsi<=72||percentB>.85)?'SHORT':null;
 if(!side||!good(atr)||atr<=0||vr<.6)return null;
 const sign=side==='LONG'?1:-1,sl=price-sign*1.5*atr,tp1=price+sign*2.25*atr,tp2=price+sign*3.75*atr;
 if(Math.min(sl,tp1,tp2)<=0)return null;
 const stopPct=100*Math.abs(price-sl)/price;
 const leverage=stopPct<=1.5?3:stopPct<=3?2:1;
 return {symbol,side,entry:price,sl,tp1,tp2,leverage,stopPct,rr1:1.5,rr2:2.5,...d};
}
function apply(s){
 const nav=document.querySelector('#nav button[data-tab="futures"]');if(nav)nav.click();
 for(const [id,val] of Object.entries({fSymbol:s.symbol,fSide:s.side,fEntry:s.entry,fSl:s.sl,fTp1:s.tp1,fTp2:s.tp2,fLeverage:s.leverage})){
  const el=$(id);if(!el)continue;
  if(el.tagName==='SELECT'&&![...el.options].some(o=>o.value===String(val))){const op=document.createElement('option');op.value=String(val);op.textContent=String(val);el.append(op)}
  el.value=String(val);el.dispatchEvent(new Event('change',{bubbles:true}));
 }
 $('fCalc')?.click();
 $('fResult')?.scrollIntoView({behavior:'smooth',block:'center'});
}
async function official(){
 const list=$('atlasLiveSetupsList');
 try{
  const response=await fetch('https://onnyytvtfcvlzkagijzz.supabase.co/functions/v1/atlas-web/api/futures',{cache:'no-store'});
  if(!response.ok)throw Error('official endpoint unavailable');
  const payload=await response.json();
  const arr=Array.isArray(payload)?payload:(payload.signals||payload.futures_signals||payload.setups||[]);
  const recent=arr.filter(x=>x&&['LONG','SHORT'].includes(String(x.side||'').toUpperCase())&&x.entry&&x.sl&&x.tp1&&x.tp2&&x.signal_at&&Date.now()-Date.parse(x.signal_at)<21600000).slice(0,5);
  if(!recent.length)throw Error('No current official signals');
  list.replaceChildren();
  for(const s of recent){
   const card=document.createElement('div');card.className='row';card.style.cssText='display:flex;gap:10px;flex-wrap:wrap;margin:8px 0';
   const label=document.createElement('span');label.textContent='سرور ATLAS | '+String(s.symbol)+' '+String(s.side)+' | Entry '+s.entry+' | SL '+s.sl+' | TP1 '+s.tp1+' | TP2 '+s.tp2;
   const btn=document.createElement('button');btn.type='button';btn.textContent='ماشین‌حساب Paper';btn.onclick=()=>apply({...s,leverage:Math.min(3,Math.max(1,Number(s.suggested_leverage||s.leverage||1)))});
   card.append(label,btn);list.append(card);
  }
 }catch(_){list.textContent='سیگنال رسمی تازه در دسترس نیست؛ برای بررسی محلی، «اسکن زنده دستی» را انتخاب کنید.'}
}
let busy=false;
async function scan(){
 if(busy)return;busy=true;
 const list=$('atlasLiveSetupsList');if(!list){busy=false;return}
 list.textContent='محاسبه محلی (خارج از چرخه سرور) — بررسی کندل‌های بسته‌شده ۴ ساعته…';
 try{
 const results=await Promise.all(symbols.map(async s=>{try{return setup(s,await load(s))}catch(_){return null}}));
 const candidates=results.filter(Boolean).sort((a,b)=>b.vr-a.vr).slice(0,5);
 list.replaceChildren();
 if(!candidates.length){list.textContent='WAIT — هیچ ستاپ تازه و معتبر مطابق فیلترها پیدا نشد.';return}
 for(const s of candidates){
  const card=document.createElement('div');card.className='row';card.style.cssText='display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:8px 0';
  const info=document.createElement('div');info.style.flex='1 1 280px';
  const f=x=>Number(x).toPrecision(7);
  info.textContent=s.symbol+'/USDT '+s.side+' | Entry '+f(s.entry)+' | SL '+f(s.sl)+' | TP1 '+f(s.tp1)+' | TP2 '+f(s.tp2)+' | R:R 1.5 / 2.5 | سقف اهرم '+s.leverage+'x | RSI '+s.rsi.toFixed(1)+' | '+s.source+' | '+s.asof;
  const btn=document.createElement('button');btn.type='button';btn.textContent='انتقال به ماشین‌حساب Paper';btn.onclick=()=>apply(s);
  card.append(info,btn);list.append(card);
 }
 }finally{busy=false}
}
function mount(){
 const parent=$('opportunities');if(!parent||$('atlasLiveSetupsCard'))return;
 const card=document.createElement('article');card.className='card';card.id='atlasLiveSetupsCard';
 const title=document.createElement('h2');title.textContent='⚡ ستاپ‌های پژوهشی LONG / SHORT — کندل بسته‌شده 4H';
 const btn=document.createElement('button');btn.type='button';btn.textContent='اسکن زنده دستی (محاسبه محلی)';btn.onclick=()=>{const list=$('atlasLiveSetupsList');list.textContent='محاسبه محلی (خارج از چرخه سرور)';scan()};
 const list=document.createElement('div');list.id='atlasLiveSetupsList';
 const note=document.createElement('small');note.textContent='منبع اولیه OKX، پشتیبان Bybit و Binance. سیگنال‌ها بدون تضمین سود؛ فقط Paper Trading. اهرم تضمین‌کننده فاصله امن لیکوئیدیشن نیست.';
 card.append(title,btn,list,note);parent.prepend(card);official();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();