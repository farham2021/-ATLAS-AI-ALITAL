/* ATLAS progressive enhancement: no credentials, no Supabase writes, no simulated health. */
(()=>{'use strict';
if(window.__atlasUiUpgradeLoaded)return;window.__atlasUiUpgradeLoaded=true;
const SYMBOLS=['BTC','ETH','SOL','TON','SUI','LINK','XRP','ADA'];
const EXCHANGE='wss://stream.binance.com:9443/stream?streams='+SYMBOLS.map(s=>s.toLowerCase()+'usdt@miniTicker').join('/');
const state={ws:null,stopped:false,retry:0,lastSeen:0,quotes:new Map(),api:'unknown',cycles:'unknown',feed:'unknown',checkedAt:0,reconnectTimer:null,healthPending:false};
const BASE='https://onnyytvtfcvlzkagijzz.supabase.co/functions/v1/atlas-web';
const labels={fa:{ok:'سامانه: فعال',warn:'سامانه: هشدار',bad:'سامانه: خطا',unknown:'سامانه: در حال بررسی'},en:{ok:'System: healthy',warn:'System: warning',bad:'System: unavailable',unknown:'System: checking'}};
const SLA={HOURLY:2.5,DEEP4H:6,DAILY16:28,NIGHTLY23:28};
const language=()=>document.documentElement.lang==='en'?'en':'fa';
const text=(el,value)=>{if(el)el.textContent=value};
function initNavigation(){
 const nav=document.querySelector('nav[aria-label="بخش‌های برنامه"]');if(!nav||nav.dataset.atlasGrouped)return;
 const buttons=[...nav.querySelectorAll('button')];if(!buttons.length)return;
 nav.dataset.atlasGrouped='1';
 const group=document.createElement('div');group.id='atlas-ui-groups';group.setAttribute('role','group');group.setAttribute('aria-label','فیلتر بخش‌ها');
 for(const [key,label,re] of [['all','همه',null],['markets','بازارها',/رمزارز|کریپتو|بورس|طلا|آمریکا|نمودار|اخبار|فلزات|market|crypto|gold|stock/i],['lab','سبد و آزمایشگاه',/سبد|معاملات|آزمایشگاه|بروکر|portfolio|paper|lab/i],['radar','رادار هوشمند',/رادار|هشدار|گزارش|فرصت|سیگنال|risk|radar|signal|report/i]]){
 const btn=document.createElement('button');btn.type='button';btn.textContent=label;btn.setAttribute('aria-pressed',String(key==='all'));btn.onclick=()=>{for(const b of group.querySelectorAll('button'))b.setAttribute('aria-pressed',String(b===btn));for(const b of nav.querySelectorAll('button'))b.hidden=!!re&&!re.test(b.textContent);};group.append(btn);
 }nav.before(group);group.querySelector('button').click();
}
function init(){
 if(!document.body||document.getElementById('atlas-live-ticker'))return;
 const ticker=document.createElement('div');ticker.id='atlas-live-ticker';ticker.setAttribute('aria-label','Crypto reference prices, Binance backup feed');
 for(const symbol of SYMBOLS){const item=document.createElement('div');item.className='atlas-quote';const label=document.createElement('span');label.className='atlas-symbol';label.textContent=symbol;const price=document.createElement('span');price.id='atlas-quote-'+symbol;price.className='atlas-stale';price.textContent='—';item.append(label,price);ticker.append(item)}
 document.body.prepend(ticker);
 const status=document.createElement('button');status.type='button';status.id='atlas-ui-status';status.innerHTML='<span class="atlas-dot"></span><span data-atlas-status-label>سامانه: در حال بررسی</span>';status.title='وضعیت API، چرخه‌ها و جریان قیمت پشتیبان';status.setAttribute('aria-label','وضعیت سامانه؛ نمایش جزئیات');status.classList.add('notranslate');status.setAttribute('translate','no');status.onclick=()=>{const op=document.querySelector('#nav button[data-tab="operations"]');if(op)op.click();document.getElementById('opsRefresh')?.click();};document.body.append(status);
 const nav=document.querySelector('nav[aria-label="بخش‌های برنامه"]');if(nav){if(nav.querySelector('button'))initNavigation();else{const observer=new MutationObserver(()=>{if(nav.querySelector('button')){observer.disconnect();initNavigation()}});observer.observe(nav,{childList:true})}}
 connect();checkHealth();setInterval(checkHealth,60000);setInterval(renderStatus,5000);new MutationObserver(renderStatus).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
}
function renderStatus(){const el=document.getElementById('atlas-ui-status');if(!el)return;const level=state.api==='bad'?'bad':state.api==='unknown'?'unknown':state.cycles==='warn'||state.feed!=='ok'?'warn':'ok';const palette={ok:'#10b981',warn:'#f59e0b',bad:'#ef4444',unknown:'#94a3b8'};el.dataset.level=level;el.querySelector('.atlas-dot').style.background=palette[level];const label=el.querySelector('[data-atlas-status-label]');if(label)label.textContent=labels[language()][level];el.title=(language()==='en'?'API: ':'API: ')+state.api+' | cycles: '+state.cycles+' | WebSocket: '+state.feed+' | '+(state.checkedAt?new Date(state.checkedAt).toLocaleString():'not checked');}
function evaluateCycles(cycles){
 if(!Array.isArray(cycles))return 'unknown';
 const latest=new Map();
 for(const c of cycles){const key=String(c?.cycle||'').toUpperCase(),t=Date.parse(c?.completed_at||'');if(key in SLA&&Number.isFinite(t)&&(!latest.has(key)||t>latest.get(key)))latest.set(key,t)}
 if(!latest.size)return 'unknown';
 const now=Date.now();
 return Object.entries(SLA).some(([key,h])=>!latest.has(key)||latest.get(key)>now+300000||now-latest.get(key)>h*3600000)?'warn':'ok';
}
async function checkHealth(){
 if(state.healthPending||document.hidden)return;
 state.healthPending=true;
 const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),12000);
 try{
  const response=await fetch(BASE+'/api/status',{cache:'no-store',signal:ctl.signal});
  if(!response.ok)throw Error('status HTTP '+response.status);
  const data=await response.json();state.api='ok';state.cycles=evaluateCycles(data.cycles);
 }catch(_){state.api='bad';state.cycles='unknown'}
 finally{clearTimeout(timer);state.healthPending=false;state.checkedAt=Date.now();renderStatus()}
}
function clearReconnect(){if(state.reconnectTimer!==null){clearTimeout(state.reconnectTimer);state.reconnectTimer=null}}
function markFeedStale(){state.feed='warn';renderStatus();for(const el of document.querySelectorAll('#atlas-live-ticker [id^=atlas-quote-]'))el.classList.add('atlas-stale')}
function reconnect(){clearReconnect();if(state.stopped||document.hidden)return;state.reconnectTimer=setTimeout(()=>{state.reconnectTimer=null;connect()},Math.min(30000,1000*2**Math.min(++state.retry,5)))}
function connect(){
 if(state.stopped||document.hidden||state.ws&&(state.ws.readyState===0||state.ws.readyState===1))return;
 clearReconnect();
 try{
  const ws=new WebSocket(EXCHANGE);state.ws=ws;
  ws.onopen=()=>{if(state.ws!==ws)return;state.retry=0;state.lastSeen=0;markFeedStale()};
  ws.onmessage=e=>{if(state.ws!==ws)return;try{
   const data=JSON.parse(e.data).data;if(!data?.s||!data?.c)return;
   const symbol=data.s.toUpperCase().replace(/USDT$/,'');if(!SYMBOLS.includes(symbol))return;
   const price=Number(data.c);if(!Number.isFinite(price)||price<=0)return;
   const node=document.getElementById('atlas-quote-'+symbol),prev=state.quotes.get(symbol);
   state.quotes.set(symbol,price);state.lastSeen=Date.now();state.feed='ok';renderStatus();
   if(node){node.textContent='$'+price.toLocaleString('en-US',{maximumFractionDigits:price<1?6:price<10?4:2});node.className=prev==null?'':price>prev?'atlas-up':price<prev?'atlas-down':''}
  }catch(_){}};
  ws.onerror=()=>{if(state.ws===ws)markFeedStale()};
  ws.onclose=()=>{if(state.ws!==ws)return;state.ws=null;markFeedStale();reconnect()};
 }catch(_){state.ws=null;markFeedStale();reconnect()}
}
document.addEventListener('visibilitychange',()=>{if(document.hidden){clearReconnect();if(state.ws){const ws=state.ws;state.ws=null;ws.close()}markFeedStale()}else{connect();checkHealth()}});
window.addEventListener('beforeunload',()=>{state.stopped=true;clearReconnect();if(state.ws)state.ws.close()});
setInterval(()=>{if(state.lastSeen&&Date.now()-state.lastSeen>60000)markFeedStale()},15000);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
