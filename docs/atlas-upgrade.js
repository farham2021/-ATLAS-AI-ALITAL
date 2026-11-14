/* ATLAS progressive enhancement: no credentials, no Supabase writes, no simulated health. */
(()=>{'use strict';
if(window.__atlasUiUpgradeLoaded)return;window.__atlasUiUpgradeLoaded=true;
const SYMBOLS=['BTC','ETH','SOL','TON','SUI','LINK','XRP','ADA'];
const EXCHANGE='wss://stream.binance.com:9443/stream?streams='+SYMBOLS.map(s=>s.toLowerCase()+'usdt@miniTicker').join('/');
const state={ws:null,stopped:false,retry:0,lastSeen:0,quotes:new Map(),api:'unknown',cycles:'unknown',feed:'unknown',checkedAt:0};
const BASE='https://onnyytvtfcvlzkagijzz.supabase.co/functions/v1/atlas-web';
const labels={fa:{ok:'سامانه: فعال',warn:'سامانه: هشدار',bad:'سامانه: خطا',unknown:'سامانه: در حال بررسی'},en:{ok:'System: healthy',warn:'System: warning',bad:'System: unavailable',unknown:'System: checking'}};
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
 const status=document.createElement('button');status.type='button';status.id='atlas-ui-status';status.innerHTML='<span class="atlas-dot"></span><span data-atlas-status-label>سامانه: در حال بررسی</span>';status.title='وضعیت API، چرخه‌ها و جریان قیمت پشتیبان';status.setAttribute('aria-label','وضعیت سامانه؛ نمایش جزئیات');status.onclick=()=>{if(typeof window.switchTab==='function')window.switchTab('operations');else{const original=[...document.querySelectorAll('#nav button')].find(b=>b.dataset.tab==='operations');if(original)original.click()}};document.body.append(status);
 const nav=document.querySelector('nav[aria-label="بخش‌های برنامه"]');if(nav){if(nav.querySelector('button'))initNavigation();else{const observer=new MutationObserver(()=>{if(nav.querySelector('button')){observer.disconnect();initNavigation()}});observer.observe(nav,{childList:true})}}
 connect();checkHealth();setInterval(checkHealth,60000);setInterval(renderStatus,5000);
}
function renderStatus(){const el=document.getElementById('atlas-ui-status');if(!el)return;const level=state.api==='bad'?'bad':state.api==='unknown'?'unknown':state.cycles==='warn'||state.feed!=='ok'?'warn':'ok';const palette={ok:'#10b981',warn:'#f59e0b',bad:'#ef4444',unknown:'#94a3b8'};el.dataset.level=level;el.querySelector('.atlas-dot').style.background=palette[level];const label=el.querySelector('[data-atlas-status-label]');if(label)label.textContent=labels[language()][level];el.title=(language()==='en'?'API: ':'API: ')+state.api+' | cycles: '+state.cycles+' | WebSocket: '+state.feed+' | '+(state.checkedAt?new Date(state.checkedAt).toLocaleString():'not checked');}
async function checkHealth(){try{const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),12000);let results;try{results=await Promise.all(['status','overview'].map(async endpoint=>{const response=await fetch(BASE+'/api/'+endpoint,{cache:'no-store',signal:ctl.signal});if(!response.ok)throw Error(endpoint+' HTTP '+response.status);return response.json()}))}finally{clearTimeout(timer)}const [status,overview]=results;if(!Array.isArray(status.cycles)||!Array.isArray(overview.cycles))throw Error('missing cycles');state.api='ok';const completed=status.cycles.map(c=>Date.parse(c.completed_at)).filter(Number.isFinite);const latest=completed.length?Math.max(...completed):0;state.cycles=latest&&Date.now()-latest<=3*60*60*1000?'ok':'warn';state.checkedAt=Date.now()}catch(_){state.api='bad';state.cycles='unknown';state.checkedAt=Date.now()}renderStatus()}
function connect(){if(state.stopped||document.hidden)return;try{const ws=new WebSocket(EXCHANGE);state.ws=ws;ws.onopen=()=>{state.retry=0;state.feed='warn';renderStatus()};ws.onmessage=e=>{try{const data=JSON.parse(e.data).data;if(!data||!data.s||!data.c)return;const symbol=data.s.toUpperCase().replace(/USDT$/,'');if(!SYMBOLS.includes(symbol))return;const price=Number(data.c);if(!Number.isFinite(price)||price<=0)return;const node=document.getElementById('atlas-quote-'+symbol);const prev=state.quotes.get(symbol);state.quotes.set(symbol,price);state.lastSeen=Date.now();state.feed='ok';renderStatus();if(node){node.textContent='$'+price.toLocaleString('en-US',{maximumFractionDigits:price<1?6:price<10?4:2});node.className=prev==null?'':price>prev?'atlas-up':price<prev?'atlas-down':''}}catch(_){}};ws.onerror=()=>{state.feed='warn';renderStatus()};ws.onclose=()=>{state.feed='warn';renderStatus();if(!state.stopped&&!document.hidden)setTimeout(connect,Math.min(30000,1000*2**Math.min(++state.retry,5)))}}catch(_){state.feed='warn';renderStatus()}}
document.addEventListener('visibilitychange',()=>{if(document.hidden){if(state.ws)state.ws.close()}else if(!state.ws||state.ws.readyState>1)connect()});
setInterval(()=>{if(state.lastSeen&&Date.now()-state.lastSeen>60000){state.feed='warn';renderStatus();for(const el of document.querySelectorAll('#atlas-live-ticker [id^=atlas-quote-]'))el.classList.add('atlas-stale')}},15000);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
