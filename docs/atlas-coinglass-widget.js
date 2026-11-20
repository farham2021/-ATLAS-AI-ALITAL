/* Read-only derivatives context for the standalone ATLAS desk. */
(()=>{'use strict';
const lang=()=>document.documentElement.lang==='en'?'en':'fa';
const text=(el,value)=>{if(el)el.textContent=String(value??'—')};
const fmt=(v,d=2)=>v!==null&&v!==undefined&&Number.isFinite(Number(v))?Number(v).toLocaleString(lang()==='en'?'en-US':'fa-IR',{maximumFractionDigits:d}):'—';
const node=(tag,value,cls)=>{const n=document.createElement(tag);n.textContent=String(value??'—');if(cls)n.className=cls;return n};
async function refresh(){
 const status=document.getElementById('atlas-coinglass-status'),rows=document.getElementById('atlas-coinglass-rows');if(!status||!rows)return;
 try{
  const response=await fetch('../coinglass_snapshot.json?t='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw Error('HTTP_'+response.status);
  const data=await response.json(),en=lang()==='en';
  status.textContent=(en?'Updated UTC: ':'دریافت UTC: ')+(data.fetched_at_utc||'—')+' · '+(data.status||'UNAVAILABLE');
  rows.replaceChildren();
  const entries=Object.entries(data.symbols||{});
  for(const [symbol,item] of entries){
   const card=node('article','');card.className='row';card.style.cssText='display:block;padding:12px 0';
   card.append(node('strong',symbol+' · '+(item.status||'UNAVAILABLE')));
   card.append(node('div',(en?'Market-wide OI: ':'مجموع OI بازار: ')+fmt(item.open_interest_usd,0)+' USD · '+(en?'1h Δ ':'تغییر ۱ساعته ')+fmt(item.open_interest_change_1h_pct)+'% · '+(en?'24h Δ ':'تغییر ۲۴ساعته ')+fmt(item.open_interest_change_24h_pct)+'%'));
   const rates=Object.entries(item.funding_by_exchange||{}).map(([venue,x])=>venue+': '+fmt(x.rate_pct,4)+'% / '+fmt(x.settlement_interval_hours,0)+'h');
   card.append(node('div',(en?'Current funding: ':'فاندینگ فعلی: ')+(rates.length?rates.join(' · '):(en?'unavailable':'ناموجود'))));
   rows.append(card);
  }
  if(!entries.length){rows.append(node('p',en?'No verified CoinGlass data; no values estimated.':'دادهٔ معتبر CoinGlass موجود نیست؛ عددی تخمین زده نشده است.','empty'));if(data.error)rows.append(node('small',(en?'Provider status: ':'وضعیت منبع: ')+data.error,'warn'))}
 }catch(error){text(status,(lang()==='en'?'Data unavailable: ':'داده در دسترس نیست: ')+String(error.message||error));rows.replaceChildren(node('p',lang()==='en'?'No verified CoinGlass snapshot.':'دادهٔ معتبر CoinGlass در دسترس نیست.','empty'))}
}
document.addEventListener('DOMContentLoaded',()=>{refresh();setInterval(()=>{if(!document.hidden)refresh()},90000)});
})();
