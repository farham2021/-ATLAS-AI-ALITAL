/* Read-only CoinGlass snapshot; the API key stays on the Actions runner. */
(()=>{'use strict';
const fmt=(v,d=2)=>v!==null&&v!==undefined&&Number.isFinite(Number(v))?Number(v).toLocaleString(document.documentElement.lang==='en'?'en-US':'fa-IR',{maximumFractionDigits:d}):'—';
const node=(tag,value,cls)=>{const n=document.createElement(tag);n.textContent=String(value??'—');if(cls)n.className=cls;return n};
async function refresh(){
 const host=document.getElementById('live-terminal');if(!host)return;
 let box=document.getElementById('atlas-coinglass-panel');
 if(!box){box=document.createElement('section');box.id='atlas-coinglass-panel';box.className='card';box.style.marginTop='14px';box.append(node('h3','🧭 CoinGlass · وضعیت مشتقات بازار'));box.append(node('p','در انتظار داده معتبر…','muted'));const rows=document.createElement('div');rows.id='atlas-coinglass-rows';box.append(rows);host.append(box)}
 const status=box.querySelector('p'),rows=document.getElementById('atlas-coinglass-rows'),en=document.documentElement.lang==='en';
 try{
  const res=await fetch('./coinglass_snapshot.json?t='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(10000)});
  if(!res.ok)throw new Error('HTTP_'+res.status);
  const data=await res.json();status.textContent=(en?'Updated UTC: ':'دریافت UTC: ')+(data.fetched_at_utc||'—')+' · '+(data.status||'UNAVAILABLE');
  rows.replaceChildren();
  const entries=Object.entries(data.symbols||{});
  for(const [symbol,item] of entries){
   const card=document.createElement('article');card.className='web3-record';
   card.append(node('strong',symbol+' · '+(item.status||'UNAVAILABLE')));
   card.append(node('p',(en?'Market-wide OI: ':'مجموع OI بازار: ')+fmt(item.open_interest_usd,0)+' USD · '+(en?'1h Δ ':'تغییر ۱ساعته ')+fmt(item.open_interest_change_1h_pct)+'% · '+(en?'24h Δ ':'تغییر ۲۴ساعته ')+fmt(item.open_interest_change_24h_pct)+'%'));
   const rates=Object.entries(item.funding_by_exchange||{}).map(([venue,x])=>venue+': '+fmt(x.rate_pct,4)+'% / '+fmt(x.settlement_interval_hours,0)+'h');
   card.append(node('p',(en?'Current stablecoin-perpetual funding: ':'فاندینگ فعلی پرپچوال استیبل‌کوینی: ')+(rates.length?rates.join(' · '):(en?'unavailable':'ناموجود'))));
   rows.append(card);
  }
  if(!entries.length)rows.append(node('p',en?'No verified CoinGlass snapshot; no values estimated.':'دادهٔ معتبر CoinGlass موجود نیست؛ عددی تخمین زده نشده است.','muted'));
  rows.append(node('small',en?'Current funding is sentiment context, not settled historical cost.':'فاندینگ فعلی صرفاً زمینهٔ بازار است و جایگزین نرخ تسویه‌شدهٔ تاریخی برای هزینهٔ بک‌تست نیست.','muted'));
 }catch(e){status.textContent=(en?'Data unavailable: ':'داده در دسترس نیست: ')+String(e.message||e);rows.replaceChildren(node('p','CoinGlass: no verified snapshot.','muted'))}
}
document.addEventListener('DOMContentLoaded',()=>{refresh();setInterval(()=>{if(!document.hidden)refresh()},90000)});
})();
