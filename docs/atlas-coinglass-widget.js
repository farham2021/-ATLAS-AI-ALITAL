/* Read-only derivatives context for the standalone ATLAS desk. */
(()=>{'use strict';
const lang=()=>document.documentElement.lang==='en'?'en':'fa';
const text=(el,value)=>{if(el)el.textContent=String(value??'—')};
const fmt=(v,d=2)=>v!==null&&v!==undefined&&Number.isFinite(Number(v))?Number(v).toLocaleString(lang()==='en'?'en-US':'fa-IR',{maximumFractionDigits:d}):'—';
const node=(tag,value,cls)=>{const n=document.createElement(tag);n.textContent=String(value??'—');if(cls)n.className=cls;return n};
const FALLBACK_SYMBOLS=['BTC','ETH','SOL','XRP'];
async function loadOKXFallback(rows,en){
 const get=async url=>{const r=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(9000)});if(!r.ok)throw Error('HTTP_'+r.status);const d=await r.json();if(d.code!=='0')throw Error('OKX_'+d.code);return d.data||[]};
 try{
  const oiRows=await get('https://www.okx.com/api/v5/public/open-interest?instType=SWAP');
  const oiBySymbol=new Map();
  for(const x of oiRows){const m=String(x.instId||'').match(/^([A-Z0-9]+)-USDT-SWAP$/);if(m&&FALLBACK_SYMBOLS.includes(m[1])&&(!oiBySymbol.has(m[1])||Number(x.ts)>Number(oiBySymbol.get(m[1]).ts)))oiBySymbol.set(m[1],x)}
  const fundingRows=await Promise.all(FALLBACK_SYMBOLS.map(async s=>{try{return [s,(await get('https://www.okx.com/api/v5/public/funding-rate?instId='+s+'-USDT-SWAP'))[0]||null]}catch{return [s,null]}}));
  const fundingBySymbol=new Map(fundingRows),valid=[];
  for(const symbol of FALLBACK_SYMBOLS){
   const oi=oiBySymbol.get(symbol),funding=fundingBySymbol.get(symbol),oiUsd=Number(oi?.oiUsd),rate=Number(funding?.fundingRate),oiTs=Number(oi?.ts),captured=Date.now();
   const validOi=Number.isFinite(oiUsd)&&oiUsd>0&&Number.isFinite(oiTs)&&captured-oiTs<300000&&captured>=oiTs-60000;
   const validRate=Number.isFinite(rate)&&Number.isFinite(Number(funding?.fundingTime))&&Math.abs(captured-Number(funding.fundingTime))<86400000;
   if(!validOi&&!validRate)continue;
   const card=node('article','');card.className='row';card.style.cssText='display:block;padding:12px 0';
   card.append(node('strong',symbol+' · OKX SWAP'));
   if(validOi)card.append(node('div',(en?'Open interest (OKX only): ':'موقعیت باز (فقط OKX): ')+fmt(oiUsd,0)+' USD'));
   if(validRate)card.append(node('div',(en?'Current funding: ':'فاندینگ فعلی: ')+(rate*100).toLocaleString(en?'en-US':'fa-IR',{maximumFractionDigits:6})+'%'));
   card.append(node('small',en?'Exchange-specific snapshot; not CoinGlass aggregate. No 1h/24h change estimated.':'دادهٔ مختص OKX است و تجمیع CoinGlass نیست؛ تغییر ۱ساعته/۲۴ساعته تخمین زده نشده.'));
   rows.append(card);valid.push(symbol);
  }
  return valid.length;
 }catch(_){return 0}
}
async function refresh(){
 const status=document.getElementById('atlas-coinglass-status'),rows=document.getElementById('atlas-coinglass-rows');if(!status||!rows)return;
 try{
  const response=await fetch('../coinglass_snapshot.json?t='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw Error('HTTP_'+response.status);
  const data=await response.json(),en=lang()==='en';
  status.textContent=(en?'Updated UTC: ':'دریافت UTC: ')+(data.fetched_at_utc||'—')+' · '+(data.status||'UNAVAILABLE');
  rows.replaceChildren();
  const entries=Object.entries(data.symbols||{});
  if(!entries.length){
   rows.replaceChildren();
   const count=await loadOKXFallback(rows,en);
   if(count){status.textContent=(en?'CoinGlass unavailable · Public exchange fallback: OKX · ':'CoinGlass ناموجود · منبع عمومی پشتیبان: OKX · ')+count+' '+(en?'markets':'بازار')+' · '+new Date().toISOString();return}
  }
  for(const [symbol,item] of entries){
   const card=node('article','');card.className='row';card.style.cssText='display:block;padding:12px 0';
   card.append(node('strong',symbol+' · '+(item.status||'UNAVAILABLE')));
   card.append(node('div',(en?'Market-wide OI: ':'مجموع OI بازار: ')+fmt(item.open_interest_usd,0)+' USD · '+(en?'1h Δ ':'تغییر ۱ساعته ')+fmt(item.open_interest_change_1h_pct)+'% · '+(en?'24h Δ ':'تغییر ۲۴ساعته ')+fmt(item.open_interest_change_24h_pct)+'%'));
   const rates=Object.entries(item.funding_by_exchange||{}).map(([venue,x])=>venue+': '+fmt(x.rate_pct,4)+'% / '+fmt(x.settlement_interval_hours,0)+'h');
   card.append(node('div',(en?'Current funding: ':'فاندینگ فعلی: ')+(rates.length?rates.join(' · '):(en?'unavailable':'ناموجود'))));
   rows.append(card);
  }
  if(!entries.length){rows.append(node('p',en?'CoinGlass and public exchange fallback unavailable; no values estimated.':'دادهٔ CoinGlass و منبع عمومی پشتیبان در دسترس نیست؛ عددی تخمین زده نشده است.','empty'));if(data.error){const code=String(data.error);const friendly=code.includes('401')?(en?'CoinGlass rejected the request (HTTP 401). A valid API key and plan are required; no derivatives values are available.':'دسترسی CoinGlass رد شد (HTTP 401). برای دریافت دادهٔ مشتقات، کلید و سطح دسترسی معتبر لازم است؛ فعلاً عددی در دسترس نیست.'):(en?'Provider status: ':'وضعیت منبع: ')+code;rows.append(node('small',friendly,'warn'))}}
 }catch(error){text(status,(lang()==='en'?'Data unavailable: ':'داده در دسترس نیست: ')+String(error.message||error));rows.replaceChildren(node('p',lang()==='en'?'No verified CoinGlass snapshot.':'دادهٔ معتبر CoinGlass در دسترس نیست.','empty'))}
}
document.addEventListener('DOMContentLoaded',()=>{refresh();setInterval(()=>{if(!document.hidden)refresh()},90000)});
})();
