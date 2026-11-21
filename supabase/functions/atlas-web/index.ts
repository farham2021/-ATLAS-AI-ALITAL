import { COIN_SPECS, fairValueToman, bubbleToman, normalizeUsdIrr, normalizeTomanMarket, normalizeUsdMetal, quoteFreshness } from "./relative-value.mjs";
// ATLAS public read-only PWA. No private portfolios, credentials, or trading operations.
const HTML = `<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#101b32"><meta name="description" content="ATLAS AI &#8212; &#1583;&#1575;&#1588;&#1576;&#1608;&#1585;&#1583; &#1608;&#1590;&#1593;&#1740;&#1578; &#1578;&#1581;&#1604;&#1740;&#1604; &#1608; &#1607;&#1588;&#1583;&#1575;&#1585;&#1607;&#1575;&#1740; &#1576;&#1575;&#1586;&#1575;&#1585;"><link rel="manifest" href="/functions/v1/atlas-web/manifest.webmanifest"><title>ATLAS AI | Dashboard</title><style>
:root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#e9f2ff;background:#091324;font-synthesis:none}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0%,#1b3861 0%,#091324 50%);min-height:100vh}main{max-width:1080px;margin:auto;padding:24px 16px 70px}header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}h1{font-size:28px;margin:8px 0}h2{font-size:19px;margin:0 0 16px}.muted{color:#a5b7d1}.brand{font-weight:800;letter-spacing:2px;color:#77d3ff}.pill{border:1px solid #355271;border-radius:30px;padding:7px 12px;font-size:12px;color:#b8d3ed}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:14px;margin:24px 0}.card{background:#13243b;border:1px solid #2b4564;border-radius:18px;padding:20px;box-shadow:0 12px 30px #0002}.value{font-size:25px;font-weight:750;margin:12px 0 4px;direction:ltr;text-align:right}.row{display:flex;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid #2b4564;align-items:center}.row:last-child{border:0}.tag{border-radius:8px;padding:4px 8px;background:#1e3a54;color:#b9e4f8;font-size:12px}button{background:#2a86bf;color:white;border:0;border-radius:10px;padding:11px 16px;cursor:pointer;font:inherit}button:focus-visible{outline:3px solid white}a{color:#7bd8ff}footer{margin-top:24px;font-size:13px;line-height:1.8}#error{color:#ffbdad}#alerts{overflow-wrap:anywhere}@media(min-width:760px){.panels{display:grid;grid-template-columns:1fr 1fr;gap:16px}}@media(max-width:500px){h1{font-size:23px}.value{font-size:20px}}
</style></head><body><main><header><div><div class="brand">ATLAS AI</div><h1>&#1583;&#1575;&#1588;&#1576;&#1608;&#1585;&#1583; &#1607;&#1608;&#1588;&#1605;&#1606;&#1583; &#1576;&#1575;&#1586;&#1575;&#1585;</h1><div class="muted">&#1606;&#1605;&#1575;&#1740; &#1593;&#1605;&#1608;&#1605;&#1740; &#1608; &#1601;&#1602;&#1591;&#8204;&#1582;&#1608;&#1575;&#1606;&#1583;&#1606;&#1740; &#1575;&#1586; &#1608;&#1590;&#1593;&#1740;&#1578; &#1605;&#1608;&#1578;&#1608;&#1585; &#1608; &#1607;&#1588;&#1583;&#1575;&#1585;&#1607;&#1575;&#1740; &#1579;&#1576;&#1578;&#8204;&#1588;&#1583;&#1607;</div></div><button id="refresh">&#8635; &#1576;&#1585;&#1608;&#1586;&#1585;&#1587;&#1575;&#1606;&#1740;</button></header><div class="grid"><section class="card"><div class="muted">&#1608;&#1590;&#1593;&#1740;&#1578; &#1587;&#1585;&#1608;&#1740;&#1587;</div><div class="value" id="service">&#1583;&#1585; &#1581;&#1575;&#1604; &#1576;&#1585;&#1585;&#1587;&#1740;</div><div class="muted" id="updated">&#8212;</div></section><section class="card"><div class="muted">&#1607;&#1588;&#1583;&#1575;&#1585;&#1607;&#1575;&#1740; &#1575;&#1582;&#1740;&#1585;</div><div class="value" id="count">&#8212;</div><div class="muted">&#1581;&#1583;&#1575;&#1705;&#1579;&#1585; &#1777;&#1778; &#1585;&#1705;&#1608;&#1585;&#1583; &#1570;&#1582;&#1585;</div></section><section class="card"><div class="muted">&#1670;&#1585;&#1582;&#1607;&#8204;&#1607;&#1575;&#1740; &#1578;&#1581;&#1604;&#1740;&#1604;</div><div class="value">&#1780;</div><div class="muted">HOURLY &#183; DEEP4H &#183; DAILY16 &#183; NIGHTLY23</div></section></div><div id="error" role="alert"></div><div class="panels"><section class="card"><h2>&#1570;&#1582;&#1585;&#1740;&#1606; &#1575;&#1580;&#1585;&#1575;&#1740; &#1670;&#1585;&#1582;&#1607;&#8204;&#1607;&#1575;</h2><div id="runs" aria-live="polite">&#1583;&#1585; &#1581;&#1575;&#1604; &#1583;&#1585;&#1740;&#1575;&#1601;&#1578;...</div></section><section class="card"><h2>&#1570;&#1582;&#1585;&#1740;&#1606; &#1607;&#1588;&#1583;&#1575;&#1585;&#1607;&#1575;&#1740; &#1579;&#1576;&#1578;&#8204;&#1588;&#1583;&#1607;</h2><div id="alerts" aria-live="polite">&#1583;&#1585; &#1581;&#1575;&#1604; &#1583;&#1585;&#1740;&#1575;&#1601;&#1578;...</div></section></div><section class="card" id="research-panel"><h2>اعتبارسنجی معاملات Futures</h2><div class="muted">بک‌تست ۱۸ ماهه BTC / ETH / SOL: Funding سناریویی؛ سودآوری تأیید نشده است.</div><div class="muted">Paper Trading صرفاً شبیه‌سازی است؛ سفارش واقعی ارسال نمی‌شود.</div><a href="https://github.com/farham2021/-ATLAS-AI-ALITAL/actions/workflows/atlas-futures-18m-backtest.yml" target="_blank" rel="noopener noreferrer">گزارش بک‌تست</a></section><footer class="muted">&#1586;&#1605;&#1575;&#1606;&#8204;&#1607;&#1575; UTC &#1607;&#1587;&#1578;&#1606;&#1583;. &#1575;&#1740;&#1606; &#1583;&#1575;&#1588;&#1576;&#1608;&#1585;&#1583; &#1583;&#1575;&#1583;&#1607;&#8204;&#1607;&#1575;&#1740; &#1579;&#1576;&#1578;&#8204;&#1588;&#1583;&#1607; &#1585;&#1575; &#1606;&#1605;&#1575;&#1740;&#1588; &#1605;&#1740;&#8204;&#1583;&#1607;&#1583;&#1548; &#1606;&#1607; &#1602;&#1740;&#1605;&#1578; &#1604;&#1581;&#1592;&#1607;&#8204;&#1575;&#1740; &#1740;&#1575; &#1578;&#1608;&#1589;&#1740;&#1607; &#1602;&#1591;&#1593;&#1740; &#1605;&#1593;&#1575;&#1605;&#1604;&#1607;. &#1608;&#1590;&#1593;&#1740;&#1578; SENT &#1579;&#1576;&#1578; &#1575;&#1585;&#1587;&#1575;&#1604; &#1575;&#1587;&#1578; &#1608; &#1578;&#1581;&#1608;&#1740;&#1604; &#1576;&#1607; &#1711;&#1740;&#1585;&#1606;&#1583;&#1607; &#1585;&#1575; &#1575;&#1579;&#1576;&#1575;&#1578; &#1606;&#1605;&#1740;&#8204;&#1705;&#1606;&#1583;. &#1575;&#1591;&#1604;&#1575;&#1593;&#1575;&#1578; &#1582;&#1589;&#1608;&#1589;&#1740; &#1587;&#1576;&#1583; &#1705;&#1575;&#1585;&#1576;&#1585;&#1575;&#1606; &#1583;&#1585; &#1575;&#1740;&#1606; &#1589;&#1601;&#1581;&#1607; &#1606;&#1605;&#1575;&#1740;&#1588; &#1583;&#1575;&#1583;&#1607; &#1606;&#1605;&#1740;&#8204;&#1588;&#1608;&#1583;.</footer></main><script>
const el=id=>document.getElementById(id);const fmt=x=>x?new Date(x).toLocaleString('fa-IR',{timeZone:'Asia/Tehran'}):'\u062b\u0628\u062a \u0646\u0634\u062f\u0647';
function line(left,right){const d=document.createElement('div');d.className='row';const a=document.createElement('span');a.textContent=left;const b=document.createElement('span');b.className='tag';b.textContent=right;d.append(a,b);return d}
async function load(){el('error').textContent='';try{const r=await fetch('/functions/v1/atlas-web/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json();el('service').textContent='\u0641\u0639\u0627\u0644';el('updated').textContent=fmt(d.checked_at);el('count').textContent=String(d.alerts.length);el('runs').replaceChildren(...d.cycles.map(x=>line(x.cycle,x.completed_at?fmt(x.completed_at):'\u0628\u062f\u0648\u0646 \u0627\u062c\u0631\u0627\u06cc \u062b\u0628\u062a\u200c\u0634\u062f\u0647')));el('alerts').replaceChildren(...(d.alerts.length?d.alerts.map(x=>line([x.symbol,x.direction,x.timeframe].filter(Boolean).join(' | '),fmt(x.timestamp))):[document.createTextNode('\u0647\u0646\u0648\u0632 \u0647\u0634\u062f\u0627\u0631\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647 \u0627\u0633\u062a')]));}catch(e){el('service').textContent='\u0646\u0627\u0645\u0634\u062e\u0635';el('error').textContent='\u062f\u0631\u06cc\u0627\u0641\u062a \u062f\u0627\u062f\u0647 \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f: '+String(e.message||e)}}el('refresh').onclick=load;load();
</script><section class="card" style="margin:16px auto;max-width:1080px"><h2>ATLAS Quant Risk V4 — محاسبه پژوهشی</h2><p class="muted">ورودی: آرایه JSON از حداقل ۲۵۰ کندل بسته‌شده 4H شامل close/high/low/volume. بدون داده معتبر، هیچ امتیازی تولید نمی‌شود.</p><textarea id="quant-candles" rows="4" style="width:100%;background:#0c1930;color:white;border:1px solid #456;border-radius:8px" placeholder='[{"close":100,"high":101,"low":99,"volume":500}, ...]'></textarea><button id="quant-calc" type="button">محاسبه ریسک</button><div id="quant-result" class="muted" aria-live="polite">هنوز محاسبه نشده</div><h3>ماشین‌حساب حجم و R:R</h3><div style="display:flex;gap:8px;flex-wrap:wrap"><input id="q-equity" type="number" value="10000" min="1" placeholder="Equity"><input id="q-entry" type="number" value="100" min=".000001" step="any" placeholder="Entry"><input id="q-stop" type="number" value="95" min=".000001" step="any" placeholder="SL"><input id="q-target" type="number" value="110" min=".000001" step="any" placeholder="TP"><select id="q-side"><option value="long">LONG</option><option value="short">SHORT</option></select><button id="q-size" type="button">محاسبه حجم</button></div><div id="q-size-result" class="muted" aria-live="polite"></div><p class="muted">ریسک هر معامله ۱٪، اهرم حداکثر ۳، کارمزد و لغزش تخمینی؛ سفارش واقعی ارسال نمی‌شود.</p></section><script>
const qnum=id=>Number(document.getElementById(id).value);
document.getElementById('q-calc-placeholder')?.remove();
document.getElementById('q-size').onclick=()=>{const out=document.getElementById('q-size-result');try{const eq=qnum('q-equity'),entry=qnum('q-entry'),stop=qnum('q-stop'),tp=qnum('q-target'),side=document.getElementById('q-side').value;const ok=[eq,entry,stop,tp].every(x=>Number.isFinite(x)&&x>0)&&(side==='long'?stop<entry&&entry<tp:tp<entry&&entry<stop);if(!ok)throw Error('جهت استاپ یا تارگت نامعتبر است');const unit=Math.abs(entry-stop)+2*entry*.0011,qty=Math.min(eq*.01/unit,eq*3/entry),rr=Math.abs(tp-entry)/Math.abs(entry-stop);out.textContent='حجم: '+qty.toFixed(6)+' | ارزش: '+(qty*entry).toFixed(2)+' USDT | R:R = '+rr.toFixed(2)+' | ریسک با هزینه تخمینی: '+(qty*unit).toFixed(2)+' USDT';}catch(e){out.textContent=String(e.message)}};
document.getElementById('quant-calc').onclick=()=>{const out=document.getElementById('quant-result');try{const a=JSON.parse(document.getElementById('quant-candles').value);if(!Array.isArray(a)||a.length<250||!a.every(c=>['close','high','low','volume'].every(k=>Number.isFinite(c[k]))&&c.close>0&&c.high>=c.low&&c.volume>=0))throw Error('حداقل ۲۵۰ کندل معتبر لازم است');const c=a.map(x=>x.close),p=c.at(-1),ema=(v,n)=>{let e=v.slice(0,n).reduce((s,x)=>s+x,0)/n;for(let i=n;i<v.length;i++)e+=2/(n+1)*(v[i]-e);return e};const e=ema(c,200),dist=(p/e-1)*100;let g=0,loss=0;for(let i=1;i<=14;i++){g+=Math.max(0,c[i]-c[i-1]);loss+=Math.max(0,c[i-1]-c[i])}g/=14;loss/=14;for(let i=15;i<c.length;i++){g=(g*13+Math.max(0,c[i]-c[i-1]))/14;loss=(loss*13+Math.max(0,c[i-1]-c[i]))/14}const rsi=g===0&&loss===0?50:loss===0?100:100-100/(1+g/loss);const tr=[];for(let i=1;i<a.length;i++)tr.push(Math.max(a[i].high-a[i].low,Math.abs(a[i].high-c[i-1]),Math.abs(a[i].low-c[i-1])));let atr=tr.slice(0,14).reduce((x,y)=>x+y,0)/14;for(const v of tr.slice(14))atr=(atr*13+v)/14;const long=tr.slice(-50).reduce((x,y)=>x+y,0)/50,ratio=long?atr/long:1,regime=ratio>=1.6?'High':ratio<=.7?'Low':'Normal';const bb=c.slice(-20),m=bb.reduce((x,y)=>x+y,0)/20,sd=Math.sqrt(bb.reduce((x,y)=>x+(y-m)**2,0)/20),pb=sd?(p-(m-2*sd))/(4*sd):.5;const vol=a.slice(-21,-1).reduce((x,y)=>x+y.volume,0)/20,vs=vol?a.at(-1).volume/vol:null;const w={trend:.25,mom:.2,vol:.2,bb:.15,volume:.1,mtf:.1};if(regime==='High'){w.vol=.3;w.trend=.18;w.mom=.15}if(regime==='Low'){w.trend=.3;w.vol=.12}const comps={trend:Math.min(Math.abs(dist)/12,1),mom:Math.min(Math.abs(rsi-50)/50,1),vol:Math.min(ratio/2,1),bb:Math.min(Math.abs(pb-.5)*2,1),volume:vs===null?null:Math.min(Math.abs(vs-1),1),mtf:.5};const keys=Object.keys(w).filter(k=>comps[k]!==null),den=keys.reduce((x,k)=>x+w[k],0),risk=Math.round(100*keys.reduce((x,k)=>x+w[k]*comps[k],0)/den),bias=Math.round(Math.max(-100,Math.min(100,(dist/8*.6+(rsi-50)/50*.4)*100)));out.textContent='Risk: '+risk+'/100 | Bias: '+bias+' | Regime: '+regime+' | RSI: '+rsi.toFixed(1)+' | فقط Research؛ MTF بدون داده روزانه خنثی است';}catch(e){out.textContent='خطای داده: '+String(e.message)}};
const textarea=document.getElementById('quant-candles');textarea.style.display='none';const qbutton=document.getElementById('quant-calc');qbutton.insertAdjacentHTML('beforebegin','<input id="q-symbol-search" type="search" placeholder="جستجوی ارز" style="max-width:170px"><select id="q-symbol" aria-label="Asset"><option>BTC</option></select><span id="q-symbol-count"></span>');qbutton.textContent='دریافت و محاسبه خودکار';const qp=document.querySelector('#quant-candles').previousElementSibling;if(qp)qp.textContent='داده 4H و 1D مستقیماً از حافظه کندل‌های بسته‌شده ATLAS دریافت می‌شود؛ ورود دستی لازم نیست.';qbutton.onclick=async()=>{const out=document.getElementById('quant-result'),symbol=document.getElementById('q-symbol').value;out.textContent='در حال دریافت '+symbol+' ...';try{const r=await fetch('/functions/v1/atlas-web/api/quant-v4?symbol='+encodeURIComponent(symbol),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const v=await r.json();out.textContent=v.status==='INSUFFICIENT_DATA'?'داده کافی نیست: 4H='+v.available_4h+' 1D='+v.available_1d:'Status: '+v.status+' | '+symbol+' | Risk: '+v.riskScore+'/100 | Bias: '+v.biasScore+' | Regime: '+v.regime+' | RSI: '+v.rsi+' | age: '+v.age_hours+'h';}catch(e){out.textContent='خطا: '+String(e.message)}};async function loadQuantSymbols(){try{const r=await fetch('/functions/v1/atlas-web/api/quant-symbols',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json(),sel=document.getElementById('q-symbol');sel.replaceChildren(...d.symbols.map(x=>{const o=document.createElement('option');o.value=x.symbol;o.textContent=x.symbol+(x.has4h&&x.has1d?'':' · ناقص');return o}));if(d.symbols.some(x=>x.symbol==='BTC'))sel.value='BTC';document.getElementById('q-symbol-count').textContent=d.count+' نماد';document.getElementById('q-symbol-search').oninput=()=>{const q=document.getElementById('q-symbol-search').value.toUpperCase();for(const o of sel.options)o.hidden=!o.value.includes(q);const first=[...sel.options].find(o=>!o.hidden);if(first)sel.value=first.value};}catch(e){document.getElementById('q-symbol-count').textContent='خطای فهرست: '+e.message}}loadQuantSymbols().then(()=>qbutton.click());
</script><section class="card" style="margin:16px auto;max-width:1080px"><h2>ژورنال معاملات مجازی — حساب تلگرام</h2><p class="muted">اطلاعات فقط با هویت تأییدشده Telegram WebApp نمایش داده می‌شود. سفارش‌های قدیمی بدون خروجی ثبت‌شده، در سود و زیان شمرده نمی‌شوند.</p><button id="journal-refresh">بارگذاری ژورنال خصوصی</button><div id="journal-stats" class="muted" aria-live="polite">برای مشاهده داخل Telegram WebApp وارد شوید.</div><div id="journal-orders"></div></section><script>
document.getElementById('journal-refresh').onclick=async()=>{const out=document.getElementById('journal-stats'),list=document.getElementById('journal-orders');const init=window.Telegram?.WebApp?.initData;if(!init){out.textContent='برای دسترسی به ژورنال خصوصی، صفحه را از دکمه WebApp داخل بات باز کنید.';return}out.textContent='در حال دریافت...';try{const r=await fetch('/functions/v1/atlas-web/api/private',{headers:{'X-Telegram-Init-Data':init},cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json(),orders=d.paper_orders||[],counts={};for(const x of orders)counts[x.status]=(counts[x.status]||0)+1;out.textContent='سفارش‌های ثبت‌شده: '+orders.length+' | '+Object.entries(counts).map(([k,v])=>k+': '+v).join(' | ')+' | Win Rate / Net R: داده بسته‌شده و سود تحقق‌یافته کافی نیست';list.replaceChildren(...orders.slice(0,20).map(x=>{const div=document.createElement('div');div.className='row';div.textContent=[x.symbol,x.side,x.status,'Entry: '+x.entry,'SL: '+x.stop_loss].join(' | ');return div}));}catch(e){out.textContent='خطای دسترسی ژورنال: '+String(e.message)}};if(window.Telegram?.WebApp?.initData)document.getElementById('journal-refresh').click();
</script><section class="card" style="margin:16px auto;max-width:1100px;line-height:2"><h2>ATLAS Quant / Paper Research V2</h2><p>Six-factor Quant Risk, Bias Score, Bar Replay and Journal research modules are in GitHub. Not validated trading signals.</p><p>Paper API v3 supports authenticated virtual account, pending orders and private journal readout. Automated fills and browser login are NOT yet enabled. No live trades.</p><p><a href="https://github.com/farham2021/-ATLAS-AI-ALITAL/actions/workflows/atlas-quant-paper-v2.yml" target="_blank" rel="noopener noreferrer">Quant / Paper CI test results</a></p></section></body></html>`;
// Use ASCII-safe HTML entities and JS Unicode escapes to prevent intermediary Latin-1 mojibake.
const HEAD={"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Access-Control-Allow-Origin":"https://farham2021.github.io","Access-Control-Allow-Methods":"GET, POST, OPTIONS","Access-Control-Allow-Headers":"X-Telegram-Init-Data, Content-Type, Authorization","Vary":"Origin"};
const corsHeaders=(origin:string|null)=>{const allowed=origin==="https://farham2021.github.io"||origin==="http://127.0.0.1:8765"||origin==="http://localhost:8765";return {...HEAD,...(allowed&&origin?{"Access-Control-Allow-Origin":origin}:{})};};
const json=(v:unknown,status=200,origin:string|null=null)=>new Response(JSON.stringify(v),{status,headers:corsHeaders(origin)});
async function readTable(url:string,key:string,path:string){
 const res=await fetch(url+"/rest/v1/"+path,{headers:{"apikey":key,"Authorization":"Bearer "+key},signal:AbortSignal.timeout(8500)});
 if(!res.ok)throw Error("database HTTP "+res.status);
 return await res.json();
}

async function validateTelegram(initData:string):Promise<string|null>{
 const token=Deno.env.get("TELEGRAM_TOKEN")||"";
 if(!token||!initData||initData.length>4096)return null;
 const params=new URLSearchParams(initData),hash=params.get("hash"),auth=Number(params.get("auth_date"));
 if(!hash||!/^[0-9a-f]{64}$/i.test(hash)||!Number.isFinite(auth)||Math.abs(Date.now()/1000-auth)>3600)return null;
 params.delete("hash");params.delete("signature");
 const data=[...params.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>k+"="+v).join("\n");
 const enc=new TextEncoder();
 const secret=await crypto.subtle.sign("HMAC",await crypto.subtle.importKey("raw",enc.encode("WebAppData"),{name:"HMAC",hash:"SHA-256"},false,["sign"]),enc.encode(token));
 const signature=await crypto.subtle.sign("HMAC",await crypto.subtle.importKey("raw",secret,{name:"HMAC",hash:"SHA-256"},false,["sign"]),enc.encode(data));
 const expected=new Uint8Array(signature),actual=Uint8Array.from(hash.match(/../g)!.map(h=>parseInt(h,16)));
 let diff=0;for(let i=0;i<32;i++)diff|=expected[i]^actual[i];if(diff!==0)return null;
 try{const user=JSON.parse(params.get("user")||"{}");return Number.isSafeInteger(user.id)&&user.id>0?String(user.id):null}catch{return null}
}
async function dbWrite(base:string,key:string,table:string,method:string,payload:unknown,query=""){
 const res=await fetch(base+"/rest/v1/"+table+query,{method,headers:{"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=representation"},body:JSON.stringify(payload),signal:AbortSignal.timeout(9000)});
 if(!res.ok)throw Error("database write unavailable");return res.json();
}
async function privateRoute(req:Request,url:URL){
 const userId=await validateTelegram(req.headers.get("X-Telegram-Init-Data")||"");
 if(!userId)return json({error:"telegram_auth_required",hint:"Telegram Mini App initData could not be verified; check bot token and auth_date. No private data exposed."},401);
 const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
 if(!base||!key)return json({error:"service_unavailable"},503);
 const get=(table:string,query:string)=>readTable(base,key,table+"?"+query);
 const filter="user_id=eq."+encodeURIComponent(userId);
 if(req.method==="GET"){
  const [holdings,basis,trades,prefs,referrals,memberships,opening,language,paperOrders]=await Promise.all([
   get("atlas_desk_holdings",filter+"&select=coin,qty"),
   get("atlas_desk_purchase_basis",filter+"&select=coin,average_buy_price,buy_date,quote_currency"),
   get("atlas_desk_trades",filter+"&select=id,coin,side,qty,unit_price,fee,traded_at&order=traded_at.desc&limit=200"),
   get("atlas_desk_alert_preferences",filter+"&select=symbol,rise_pct,fall_pct,enabled"),
   get("atlas_desk_referrals","inviter_user_id=eq."+encodeURIComponent(userId)+"&select=invited_user_id&limit=200"),
   get("atlas_desk_memberships",filter+"&select=status,plan,expires_at"),
   get("atlas_desk_trade_opening",filter+"&select=coin,opening_qty,opening_cost"),
   get("atlas_desk_language_preferences",filter+"&select=language"),
   get("atlas_futures_paper_orders",filter+"&select=id,symbol,side,entry,stop_loss,take_profit_1,take_profit_2,leverage,risk_pct,equity_usdt,quantity,status,created_at&order=created_at.desc&limit=40")
  ]);
  return json({user_id:userId,holdings,basis,trades,prefs,opening,membership:memberships[0]||{status:"trial",plan:"free"},language:language[0]?.language||"fa",paper_orders:paperOrders,referral_count:referrals.length});
 }
 if(req.method!=="POST")return json({error:"method_not_allowed"},405);
 let body:any;try{body=await req.json()}catch{return json({error:"invalid_json"},400)}
 const action=String(body?.action||""),coin=String(body?.coin||"").toUpperCase();
 if(!/^[A-Z0-9]{2,20}$/.test(coin)&&!["referral","language"].includes(action))return json({error:"invalid_symbol"},400);
 
 if(action==="paper_order"){
  const symbol=String(body.symbol||"").toUpperCase().trim(),side=String(body.side||"").toUpperCase();
  const entry=Number(body.entry),sl=Number(body.sl),tp1=Number(body.tp1);
  const tp2=body.tp2===null||body.tp2===undefined||body.tp2===""?null:Number(body.tp2);
  const equity=Number(body.equity_usdt),risk=Number(body.risk_pct),leverage=Number(body.leverage);
  const valid=[entry,sl,tp1,equity,risk,leverage].every(x=>Number.isFinite(x)&&x>0)&&
   (tp2===null||(Number.isFinite(tp2)&&tp2>0))&&/^[A-Z0-9]{2,20}$/.test(symbol)&&
   ["LONG","SHORT"].includes(side)&&risk<=2&&Number.isInteger(leverage)&&leverage<=3&&
   (side==="LONG"?(sl<entry&&tp1>entry&&(tp2===null||tp2>tp1)):(sl>entry&&tp1<entry&&(tp2===null||tp2<tp1)));
  if(!valid)return json({error:"invalid_paper_trade_levels_or_limits"},400);
  const quantity=equity*risk/100/Math.abs(entry-sl);
  if(!Number.isFinite(quantity)||quantity<=0||quantity*entry>equity*leverage)return json({error:"insufficient_margin_for_risk_sizing"},400);
  const order={user_id:userId,symbol,side,entry,stop_loss:sl,take_profit_1:tp1,take_profit_2:tp2,
   leverage,risk_pct:risk,equity_usdt:equity,quantity,status:"paper_open"};
  await dbWrite(base,key,"atlas_futures_paper_orders","POST",order);
  return json({ok:true,mode:"paper_only",order});
 }
 if(action==="language"){
  const language=String(body.language||"");
  if(!["fa","en"].includes(language))return json({error:"invalid_language"},400);
  await dbWrite(base,key,"atlas_desk_language_preferences","POST",{user_id:userId,language,updated_at:new Date().toISOString()},"?on_conflict=user_id");
  return json({ok:true,language});
 }
 if(action==="basis"){
  const price=Number(body.price),date=body.date===null||body.date===""?null:String(body.date||"");
  if(!(price>0&&price<1e12)||date&&!/^\d{4}-\d{2}-\d{2}$/.test(date))return json({error:"invalid_basis"},400);
  await dbWrite(base,key,"atlas_desk_purchase_basis","POST",{user_id:userId,coin,average_buy_price:price,buy_date:date,quote_currency:"USD"},"?on_conflict=user_id,coin");
  return json({ok:true});
 }
 if(action==="alert"){
  const rise=body.rise===null?null:Number(body.rise),fall=body.fall===null?null:Number(body.fall);
  if((rise!==null&&!(rise>0&&rise<=100))||(fall!==null&&!(fall>0&&fall<=100)))return json({error:"invalid_threshold"},400);
  await dbWrite(base,key,"atlas_desk_alert_preferences","POST",{user_id:userId,symbol:coin,rise_pct:rise,fall_pct:fall,enabled:body.enabled!==false},"?on_conflict=user_id,symbol");
  return json({ok:true,delivery_automated:false});
 }
 if(action==="trade"){
  const qty=Number(body.qty),price=Number(body.price),fee=Number(body.fee||0),side=String(body.side||"").toUpperCase();
  if(!["BUY","SELL"].includes(side)||!(qty>0&&qty<=1e12)||!(price>0&&price<1e12)||!(fee>=0&&fee<=1e9))return json({error:"invalid_trade"},400);
  const response=await fetch(base+"/rest/v1/rpc/atlas_desk_record_trade",{method:"POST",headers:{"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json"},body:JSON.stringify({p_user_id:userId,p_coin:coin,p_side:side,p_qty:qty,p_unit_price:price,p_fee:fee}),signal:AbortSignal.timeout(9000)});
  if(!response.ok)return json({error:"trade_rejected",detail:response.status===400?"insufficient_quantity_or_invalid_trade":"transaction_unavailable"},400);
  const id=await response.json();
  return json({ok:true,trade_id:id,holdings_sync:"atomic"});
 }
 if(action==="referral"){
  const inviter=String(body.inviter||"");
  if(!/^\d{1,20}$/.test(inviter)||inviter===userId)return json({error:"invalid_inviter"},400);
  const existing=await get("atlas_desk_referrals","invited_user_id=eq."+encodeURIComponent(userId)+"&select=invited_user_id");
  if(existing.length)return json({ok:true,already_registered:true});
  await dbWrite(base,key,"atlas_desk_referrals","POST",{invited_user_id:userId,inviter_user_id:inviter});
  return json({ok:true});
 }
 return json({error:"unknown_action"},400);
}

Deno.serve(async(req:Request)=>{
 const origin=req.headers.get("origin");
 const url=new URL(req.url);
 if(req.method==="OPTIONS")return new Response(null,{status:204,headers:{...corsHeaders(origin),"Access-Control-Allow-Headers":"X-Telegram-Init-Data, Content-Type"}});
 if(url.pathname.endsWith("/api/account")){
  const auth=req.headers.get("Authorization")||"";
  const match=/^Bearer ([A-Za-z0-9_.-]+)$/.exec(auth);
  if(req.method!=="GET")return json({error:"method_not_allowed"},405,origin);
  if(!match)return json({error:"authentication_required"},401,origin);
  try{
   const base=Deno.env.get("SUPABASE_URL")||"";
   const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
   if(!base||!key)return json({error:"auth_unavailable"},503,origin);
   const response=await fetch(base+"/auth/v1/user",{headers:{"Authorization":"Bearer "+match[1],"apikey":key},signal:AbortSignal.timeout(9000)});
   if(!response.ok)return json({error:"invalid_session"},401,origin);
   const user=await response.json();
   if(!user?.id)return json({error:"invalid_session"},401,origin);
   return json({authenticated:true,user_id:user.id,email:user.email||null,role:"research",private_journal_linked:false},200,origin);
  }catch(e){console.error("account-auth",String(e));return json({error:"auth_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/discipline")){
  const headers={...corsHeaders(origin),"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"};
  const respond=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status,headers});
  if(!["GET","POST"].includes(req.method))return respond({error:"method_not_allowed"},405);
  const uid=await validateTelegram(req.headers.get("X-Telegram-Init-Data")||"");
  if(!uid)return respond({error:"telegram_auth_required"},401);
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return respond({error:"service_unavailable"},503);
  const auth={"apikey":key,"Authorization":"Bearer "+key};
  try{
    if(req.method==="GET"){
      const rows=await readTable(base,key,"atlas_plan_adherence?select=id,symbol,trade_ref,trade_date,entry_followed,stop_followed,sizing_followed,exit_followed,reviewed,score,created_at&telegram_user_id=eq."+encodeURIComponent(uid)+"&order=created_at.desc&limit=100");
      const complete=rows.filter((x:any)=>x.score!==null);
      return respond({rows,complete:complete.length,average_score:complete.length?Math.round(complete.reduce((a:number,x:any)=>a+Number(x.score),0)/complete.length*10)/10:null});
    }
    const body=await req.json();
    const symbol=String(body.symbol||"").trim().toUpperCase(),trade_ref=String(body.trade_ref||"").trim();
    if(!/^[A-Z0-9]{2,15}$/.test(symbol)||trade_ref.length>100||String(body.notes||"").length>1000)return respond({error:"invalid_input"},400);
    const fields=["entry_followed","stop_followed","sizing_followed","exit_followed","reviewed"];
    if(fields.some(f=>typeof body[f]!=="boolean"))return respond({error:"five_boolean_answers_required"},400);
    const payload:any={telegram_user_id:uid,symbol,trade_ref:trade_ref||null,notes:String(body.notes||""),...Object.fromEntries(fields.map(f=>[f,body[f]]))};
    const res=await fetch(base+"/rest/v1/atlas_plan_adherence",{method:"POST",headers:{...auth,"Content-Type":"application/json","Prefer":"return=representation"},body:JSON.stringify(payload)});
    if(!res.ok)return respond({error:"save_failed"},res.status===409?409:503);
    const rows=await res.json();return respond({saved:true,row:rows[0]},201);
  }catch(e){console.error("discipline",String(e));return respond({error:"discipline_unavailable"},503)}
 }
 if(url.pathname.endsWith("/api/private")){try{return await privateRoute(req,url)}catch(e){console.error("private ATLAS route error",String(e));return json({error:"private_data_unavailable"},503)}}
 if(req.method!=="GET"&&req.method!=="HEAD")return json({error:"method_not_allowed"},405);
 if(url.pathname.endsWith("/manifest.webmanifest"))return new Response(JSON.stringify({name:"ATLAS AI Dashboard",short_name:"ATLAS",start_url:"./",scope:"./",display:"standalone",background_color:"#091324",theme_color:"#101b32",lang:"fa",dir:"rtl"}),{headers:{"Content-Type":"application/manifest+json","Cache-Control":"public, max-age=3600"}});






 if(url.pathname.endsWith("/api/market-heatmap")){
  if(req.method!=="GET"&&req.method!=="HEAD")return json({error:"method_not_allowed"},405,origin);
  const tf=url.searchParams.get("timeframe")||"24h";
  const spans:Record<string,number>={"1h":3600,"4h":14400,"24h":86400,"7d":604800};
  if(!(tf in spans))return json({error:"invalid_timeframe"},400,origin);
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503,origin);
  try{
   const now=Date.now(),cutoff=new Date(now-(spans[tf]+86400)*1000).toISOString();
   const rows=await readTable(base,key,"atlas_market_snapshots?select=symbol,price,captured_at&price=gt.0&captured_at=gte."+encodeURIComponent(cutoff)+"&order=captured_at.desc&limit=5000");
   const grouped=new Map<string,any[]>();
   for(const x of rows){const symbol=String(x.symbol||"").toUpperCase();if(!/^[A-Z0-9]{2,15}$/.test(symbol))continue;if(!grouped.has(symbol))grouped.set(symbol,[]);grouped.get(symbol)!.push(x)}
   const items=[...grouped.entries()].map(([symbol,bars])=>{
    const latest=bars[0],last=Date.parse(latest.captured_at),target=last-spans[tf]*1000;
    const eligible=bars.filter(x=>Date.parse(x.captured_at)<=target);
    const prev=eligible.length?eligible.reduce((best,x)=>Math.abs(Date.parse(x.captured_at)-target)<Math.abs(Date.parse(best.captured_at)-target)?x:best):null;
    const age=now-last,lag=prev?target-Date.parse(prev.captured_at):Infinity;
    const tolerance:Record<string,number>={"1h":5400000,"4h":10800000,"24h":28800000,"7d":129600000};
    const valid=age<=21600000&&prev&&lag<=tolerance[tf];
    return {symbol,price:Number(latest.price),change_pct:valid?Math.round((Number(latest.price)/Number(prev.price)-1)*10000)/100:null,timeframe:tf,source:"ATLAS Supabase market snapshots (upstream unverified)",updated_at:latest.captured_at,status:valid?"OK":age>3600000?"STALE":"INSUFFICIENT_DATA"};
   }).sort((a,b)=>a.symbol.localeCompare(b.symbol));
   return json({items,count:items.length,timeframe:tf,source:"atlas_market_snapshots",truncated:rows.length===5000,as_of:new Date(now).toISOString()},200,origin);
  }catch(e){console.error("market-heatmap",String(e));return json({error:"heatmap_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/quant-symbols")){
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503,origin);
  try{
    const rows=await readTable(base,key,"atlas_ohlcv_closed_cache?select=symbol,timeframe&timeframe=in.(4h,1d)&limit=5000");
    const map=new Map<string,Set<string>>();
    for(const row of rows){const sym=String(row.symbol||"").toUpperCase();if(!/^[A-Z0-9]{2,12}$/.test(sym))continue;if(!map.has(sym))map.set(sym,new Set());map.get(sym)!.add(String(row.timeframe).toLowerCase())}
    const symbols=[...map.entries()].map(([symbol,tfs])=>({symbol,has4h:tfs.has("4h"),has1d:tfs.has("1d")})).sort((a,b)=>a.symbol.localeCompare(b.symbol));
    return json({symbols,count:symbols.length,source:"atlas_ohlcv_closed_cache",note:"Availability does not guarantee sufficient fresh closed candles."},200,origin);
  }catch(e){console.error("quant-symbols",String(e));return json({error:"symbol_catalog_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/quant-v4")){
  const symbol=String(url.searchParams.get("symbol")||"BTC").toUpperCase();
  if(!/^[A-Z0-9]{2,12}$/.test(symbol))return json({error:"invalid_symbol"},400,origin);
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503,origin);
  try{
   const qs="select=rows_json,last_closed_ts,updated_at,provider&symbol=eq."+encodeURIComponent(symbol)+"&order=updated_at.desc&limit=5";
   const [h,d]=await Promise.all([readTable(base,key,"atlas_ohlcv_closed_cache?"+qs+"&timeframe=eq.4h"),readTable(base,key,"atlas_ohlcv_closed_cache?"+qs+"&timeframe=eq.1d")]);
   function bars(rows:any[],ms:number){for(const r of rows){try{const a=typeof r.rows_json==="string"?JSON.parse(r.rows_json):r.rows_json;if(!Array.isArray(a))continue;const out=a.map((x:any)=>({t:Number(x[0]),close:Number(x[4]),high:Number(x[2]),low:Number(x[3]),volume:Number(x[5])})).filter((x:any)=>Number.isFinite(x.t)&&x.t+ms<=Date.now()&&x.close>0&&x.high>=x.low&&x.volume>=0).sort((a:any,b:any)=>a.t-b.t);const unique=out.filter((x:any,i:number)=>!i||x.t!==out[i-1].t);if(unique.length>=250)return {data:unique,provider:r.provider,updated_at:r.updated_at};}catch(_e){}}return null}
   const h4=bars(h,14400000),daily=bars(d,86400000);
   if(!h4||!daily)return json({status:"INSUFFICIENT_DATA",symbol,reason:"minimum_250_closed_bars_each_timeframe",required_closed_candles:250,available_4h:h4?.data.length??0,available_1d:daily?.data.length??0,cache_4h:h[0]?{provider:h[0].provider,updated_at:h[0].updated_at,last_closed_ts:h[0].last_closed_ts,stored_bytes:String(h[0].rows_json||"").length}:null,cache_1d:d[0]?{provider:d[0].provider,updated_at:d[0].updated_at,last_closed_ts:d[0].last_closed_ts,stored_bytes:String(d[0].rows_json||"").length}:null},200,origin);
   const x=h4.data,y=daily.data,c=x.map((v:any)=>v.close),p=c.at(-1),ema=(a:number[],n:number)=>{let v=a.slice(0,n).reduce((s:number,z:number)=>s+z,0)/n;for(let i=n;i<a.length;i++)v+=2/(n+1)*(a[i]-v);return v};
   const e=ema(c,200),dist=(p/e-1)*100;
   let gain=0,loss=0;for(let i=1;i<=14;i++){gain+=Math.max(0,c[i]-c[i-1]);loss+=Math.max(0,c[i-1]-c[i])}gain/=14;loss/=14;for(let i=15;i<c.length;i++){gain=(13*gain+Math.max(0,c[i]-c[i-1]))/14;loss=(13*loss+Math.max(0,c[i-1]-c[i]))/14}
   const rsi=gain===0&&loss===0?50:loss===0?100:100-100/(1+gain/loss);
   const tr=[];for(let i=1;i<x.length;i++)tr.push(Math.max(x[i].high-x[i].low,Math.abs(x[i].high-c[i-1]),Math.abs(x[i].low-c[i-1])));
   let atr=tr.slice(0,14).reduce((a:number,b:number)=>a+b,0)/14;for(const z of tr.slice(14))atr=(13*atr+z)/14;
   const al=tr.slice(-50).reduce((a:number,b:number)=>a+b,0)/50,vr=al?atr/al:1,regime=vr>=1.6?"High":vr<=.7?"Low":"Normal";
   const bb=c.slice(-20),m=bb.reduce((a:number,b:number)=>a+b,0)/20,sd=Math.sqrt(bb.reduce((a:number,b:number)=>a+(b-m)**2,0)/20),pb=sd?(p-m+2*sd)/(4*sd):.5;
   const vv=x.slice(-21,-1).reduce((a:number,b:any)=>a+b.volume,0)/20,vol=vv?x.at(-1).volume/vv:null;
   const dailyE=ema(y.map((z:any)=>z.close),200),mtf=(p>e)===(y.at(-1).close>dailyE)?.85:.25;
   const w:any={trend:.25,momentum:.20,volatility:.20,meanReversion:.15,volume:.10,mtf:.10};if(regime==="High"){w.trend=.18;w.momentum=.15;w.volatility=.30}if(regime==="Low"){w.trend=.30;w.volatility=.12}
   const z:any={trend:Math.min(Math.abs(dist)/12,1),momentum:Math.min(Math.abs(rsi-50)/50,1),volatility:Math.min(vr/2,1),meanReversion:Math.min(Math.abs(pb-.5)*2,1),volume:vol===null?null:Math.min(Math.abs(vol-1),1),mtf:1-mtf};
   const keys=Object.keys(w).filter(k=>z[k]!==null),den=keys.reduce((a:number,k:string)=>a+w[k],0),risk=Math.round(100*keys.reduce((a:number,k:string)=>a+w[k]*z[k],0)/den),bias=Math.round(Math.max(-100,Math.min(100,(dist/8*.6+(rsi-50)/50*.4)*100)));
   const ageHours=(Date.now()-(x.at(-1).t+14400000))/3600000;
   const dailyAgeHours=(Date.now()-(y.at(-1).t+86400000))/3600000;
   return json({status:ageHours>12||dailyAgeHours>48?"STALE_RESEARCH":"RESEARCH_UNVALIDATED",symbol,riskScore:risk,biasScore:bias,regime,rsi:+rsi.toFixed(2),atr:+atr.toFixed(4),price:p,mtfAlignment:mtf,volumeStrength:vol,closed_4h:x.length,closed_1d:y.length,latest_closed_4h:new Date(x.at(-1).t+14400000).toISOString(),age_hours:+ageHours.toFixed(2),daily_age_hours:+dailyAgeHours.toFixed(2),provider_4h:h4.provider,provider_1d:daily.provider,real_order:false,signal:false},200,origin);
  }catch(e){console.error("quant-v4",String(e));return json({error:"quant_v4_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/quant-risk")){
  const symbol=String(url.searchParams.get("symbol")||"BTC").toUpperCase();
  if(!/^[A-Z0-9_]{2,18}$/.test(symbol))return json({error:"invalid_symbol"},400,origin);
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503,origin);
  try{
   const [raw,signals]=await Promise.all([
    readTable(base,key,"atlas_market_snapshots?select=captured_at,price,value&symbol=eq."+encodeURIComponent(symbol)+"&order=captured_at.desc&limit=400"),
    readTable(base,key,"atlas_signal_audit?select=signal_at,direction,return_pct,directional_hit,status,horizon_hours&symbol=eq."+encodeURIComponent(symbol)+"&order=signal_at.desc&limit=200")
   ]);
   const seen=new Set<string>(),prices=raw.filter((x:any)=>{const v=Number(x.price??x.value),t=Date.parse(x.captured_at);if(!Number.isFinite(v)||v<=0||!Number.isFinite(t)||seen.has(x.captured_at))return false;seen.add(x.captured_at);return true}).reverse();
   const rets=prices.slice(1).map((x:any,i:number)=>Number(x.price??x.value)/Number(prices[i].price??prices[i].value)-1).filter((v:number)=>Number.isFinite(v)&&v>-1);
   const last=prices.at(-1),ageHours=last?(Date.now()-Date.parse(last.captured_at))/3600000:null;
   const audited=signals.filter((x:any)=>x.status==="evaluated"&&typeof x.directional_hit==="boolean");
   const hitRate=audited.length?audited.filter((x:any)=>x.directional_hit).length/audited.length:null;
   let var95=null,cvar95=null,drawdown=null;
   if(rets.length>=30&&ageHours!==null&&ageHours>=0&&ageHours<=48){
    const sorted=[...rets].sort((a:number,b:number)=>a-b),idx=Math.floor((sorted.length-1)*.05),q=sorted[idx],tail=sorted.filter((x:number)=>x<=q);
    var95=Math.max(0,-q);cvar95=Math.max(0,-tail.reduce((a:number,b:number)=>a+b,0)/tail.length);
    let peak=1,equity=1,dd=0;for(const ret of rets){equity*=1+ret;peak=Math.max(peak,equity);dd=Math.max(dd,1-equity/peak)}drawdown=dd;
   }
   return json({status:rets.length>=30&&ageHours!==null&&ageHours>=0&&ageHours<=48?"observed":"insufficient_or_stale",symbol,source:"atlas_market_snapshots",price_points:prices.length,return_observations:rets.length,latest_at:last?.captured_at??null,age_hours:ageHours,var95,cvar95,max_drawdown:drawdown,signal_audit:{evaluated:audited.length,directional_hit_rate:hitRate},limitations:"Snapshot returns are irregularly spaced; VaR/CVaR not comparable with fixed-interval candles. Not OHLCV, not a predictive signal, no execution or alert automation."},200,origin);
  }catch(e){console.error("quant risk unavailable",String(e));return json({error:"quant_risk_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/metals-analysis")){
  const symbol=String(url.searchParams.get("symbol")||"XAUUSD").toUpperCase();
  if(!["XAUUSD","XAGUSD","COPPER","SILVER999_FAIR","GOLD18","COIN_EMAMI"].includes(symbol))return json({error:"unsupported_metal"},400,origin);
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503,origin);
  try{
   const filter="symbol=eq."+encodeURIComponent(symbol);
   const [market,mtf]=await Promise.all([
    readTable(base,key,"atlas_market_snapshots?select=symbol,price,captured_at&"+filter+"&order=captured_at.desc&limit=250"),
    readTable(base,key,"atlas_mtf_snapshots?select=symbol,timestamp,direction,h1,h4,d1,w1,agreement_pct&"+filter+"&order=timestamp.desc&limit=1")
   ]);
   const points=market.filter((r:any)=>Number.isFinite(Number(r.price))&&Number(r.price)>0).map((r:any)=>({price:Number(r.price),time:Date.parse(r.captured_at)})).filter((r:any)=>Number.isFinite(r.time));
   const newest=points[0],oldest=points.at(-1),hours=points.length>1?(newest.time-oldest.time)/3600000:0;
   const changes=[1,4,12,24,168].map(h=>{
    if(!newest)return {hours:h,status:"no_data"};
    const target=newest.time-h*3600000;
    const candidate=points.filter((r:any)=>r.time<=target).sort((a:any,b:any)=>b.time-a.time)[0];
    if(!candidate||newest.time-candidate.time>h*3600000+Math.max(3600000,h*3600000*.35))return {hours:h,status:"insufficient_history"};
    const changePct=(newest.price/candidate.price-1)*100;
    return {hours:h,status:"observed",change_pct:Math.round(changePct*1000)/1000,
      direction:changePct>.15?"up":changePct<-.15?"down":"flat",reference_at:new Date(candidate.time).toISOString()};
   });
   const lastMtf=mtf[0]||null;
   return json({symbol,latest_price:newest?.price??null,latest_at:newest?new Date(newest.time).toISOString():null,
    sample_count:points.length,coverage_hours:Math.round(hours*10)/10,changes,mtf:lastMtf,
    stale:!newest||Date.now()-newest.time>4*3600000,method:"Observed price changes, not a technical-indicator forecast",
    unit:symbol==="COPPER"?"USD/lb (futures proxy)":symbol==="XAUUSD"?"USD/troy oz":symbol==="XAGUSD"?"USD/troy oz":symbol==="SILVER999_FAIR"?"IRR or Toman per stored source metadata (verify source)": "source-dependent",
    disclaimer:"Insufficient time-series history is never replaced by fabricated multi-timeframe indicators."},200,origin);
  }catch(e){console.error("metal analysis unavailable",String(e));return json({error:"metals_analysis_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/us-markets")){
  const groups={indices:["TVC:SPX","NASDAQ:NDX","TVC:DJI","TVC:VIX","TVC:DXY"],mega_cap:["NASDAQ:AAPL","NASDAQ:MSFT","NASDAQ:NVDA","NASDAQ:AMZN","NASDAQ:GOOGL","NASDAQ:META","NASDAQ:TSLA","NASDAQ:AVGO","NASDAQ:AMD","NYSE:BRK.B","NYSE:JPM","NYSE:V","NYSE:UNH"],etfs:["AMEX:SPY","NASDAQ:QQQ","AMEX:DIA","AMEX:IWM","AMEX:GLD","AMEX:SLV","NASDAQ:TLT","AMEX:XLF","AMEX:XLK","AMEX:XLE","AMEX:XLV"],futures:["CME_MINI:ES1!","CME_MINI:NQ1!","CBOT_MINI:YM1!"]};const symbols=Object.values(groups).flat();
  return json({market:"US",source:"TradingView external charts",symbols,groups,session_timezone:"America/New_York",regular_session:"09:30–16:00 ET, weekdays excluding exchange holidays",quotes:"provider-dependent, may be delayed",mode:"external_chart",notice:"Quotes and trading hours are provided by the external chart provider, not ATLAS."});
 }
 if(url.pathname.endsWith("/api/crypto-news")){
 const symbol=String(url.searchParams.get("symbol")||"").toUpperCase().trim();
 if(symbol&&!/^[A-Z0-9]{2,15}$/.test(symbol))return json({error:"invalid_symbol"},400);
 const feeds=[["Crypto News","https://cryptocurrency.cv/api/news?limit=70","json"],["Cointelegraph","https://cointelegraph.com/rss","rss"],["CoinDesk","https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml","rss"],["Decrypt","https://decrypt.co/feed","rss"]];
 const decode=(s:string)=>s.replace(/<!\[CDATA\[|\]\]>/g,"").replace(/&amp;/g,"&").replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&lt;/g,"<").replace(/&gt;/g,">").trim();
 const tag=(s:string,k:string)=>decode(s.match(new RegExp("<"+k+"[^>]*>([\\s\\S]*?)</"+k+">","i"))?.[1]||"");
 const link=(s:unknown)=>{try{const u=new URL(String(s||""));return u.protocol==="https:"?u.href:null}catch{return null}};
 const results=await Promise.allSettled(feeds.map(async ([name,url,kind])=>{
  const res=await fetch(url,{headers:{"User-Agent":"ATLAS-NewsReader/2.0"},signal:AbortSignal.timeout(7000)});
  if(!res.ok)throw Error("HTTP "+res.status);
  if(kind==="json"){const d=await res.json(),rows=Array.isArray(d)?d:Array.isArray(d.articles)?d.articles:Array.isArray(d.news)?d.news:[];
   return rows.slice(0,80).map((x:any)=>({title:String(x.title||""),link:link(x.link||x.url),published:String(x.pubDate||x.publishedAt||x.published||""),source:typeof x.source==="string"?x.source:String(x.source?.name||name)}))}
  const xml=await res.text(),matches=[...xml.matchAll(new RegExp("<item(?:\\s[^>]*)?>([\\s\\S]*?)</item>","gi"))];
  return matches.slice(0,40).map(m=>({title:tag(m[1],"title"),link:link(tag(m[1],"link")),published:tag(m[1],"pubDate"),source:name}));
 }));
 const rows:any[]=[],ok:string[]=[],failed:string[]=[];
 for(let i=0;i<results.length;i++){const r=results[i];if(r.status==="fulfilled"){ok.push(feeds[i][0]);rows.push(...r.value)}else failed.push(feeds[i][0])}
 const names:Record<string,string[]>={BTC:["bitcoin","btc"],ETH:["ethereum","ether","eth"],SOL:["solana","sol"],XRP:["ripple","xrp"],BNB:["binance","bnb"],DOGE:["dogecoin","doge"],ADA:["cardano","ada"],TRX:["tron","trx"],LINK:["chainlink"],AVAX:["avalanche","avax"]};
 const words=names[symbol]||[symbol.toLowerCase()];
 const seen=new Set<string>();
 const items=rows.filter(x=>x.title&&x.link&&(!symbol||words.some(w=>new RegExp("(^|[^a-z0-9])"+w+"([^a-z0-9]|$)","i").test(x.title)))).filter(x=>{if(seen.has(x.link))return false;seen.add(x.link);return true}).sort((a,b)=>(Date.parse(b.published)||0)-(Date.parse(a.published)||0)).slice(0,25).map(x=>({...x,impact:"unverified",language:"en"}));
 return json({symbol:symbol||null,source:ok.join(", "),sources_ok:ok,sources_failed:failed,items,degraded:ok.length===0,fetched_at:new Date().toISOString(),impact_note:"News impact not verified."});
 }
 if(url.pathname.endsWith("/api/futures")){
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503);
  try{
   const rows=await readTable(base,key,"atlas_signal_lifecycle?select=symbol,direction,entry,sl,tp1,tp2,confidence,updated_at,lifecycle_state&order=updated_at.desc&limit=150");
   const valid=rows.filter((x:any)=>{
    const side=String(x.direction||"").toUpperCase(),e=Number(x.entry),sl=Number(x.sl),tp=Number(x.tp1);
    return ["LONG","SHORT"].includes(side)&&[e,sl,tp].every(n=>Number.isFinite(n)&&n>0)&&
      (side==="LONG"?(sl<e&&tp>e):(sl>e&&tp<e));
   }).map((x:any)=>{
    const side=String(x.direction).toUpperCase(),e=Number(x.entry),sl=Number(x.sl),tp=Number(x.tp1),tp2=Number(x.tp2);
    const second=Number.isFinite(tp2)&&tp2>0&&(side==="LONG"?tp2>tp:tp2<tp)?tp2:null;
    return {symbol:x.symbol,side,entry:e,sl,tp1:tp,tp2:second,
      rr1:Math.round(Math.abs(tp-e)/Math.abs(e-sl)*100)/100,confidence:x.confidence,
      updated_at:x.updated_at,lifecycle_state:x.lifecycle_state,mode:"paper_only"};
   });
   return json({mode:"paper_only",max_leverage:3,max_risk_pct:2,signals:valid.slice(0,60),
    warning:"Historical indicative levels, not executable quotes. Verify data freshness; no real broker connection."});
  }catch(e){console.error("futures unavailable",String(e));return json({error:"futures_unavailable"},503)}
 }
 if(url.pathname.endsWith("/api/intelligence")){
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503);
  try{
   const [radar,latest,audits]=await Promise.all([
    readTable(base,key,"atlas_risk_radar_snapshots?select=symbol,asset_group,captured_at,price,change_1h_pct,volatility_24h_pct,risk_score,alert_level,model_version&order=captured_at.desc&limit=400"),
    readTable(base,key,"atlas_signal_audit?select=source,symbol,direction,score,signal_at,return_pct,directional_hit,status&order=signal_at.desc&limit=300"),
    readTable(base,key,"atlas_signal_audit?select=directional_hit,return_pct&status=eq.evaluated&limit=1000")
   ]);
   const seen=new Set<string>();const unique=radar.filter((r:any)=>{if(seen.has(r.symbol))return false;seen.add(r.symbol);return true}).slice(0,100);
   const valid=audits.filter((r:any)=>r.directional_hit!==null);
   const hits=valid.filter((r:any)=>r.directional_hit===true).length;
   return json({checked_at:new Date().toISOString(),mode:"shadow",radar:unique,signals:latest.slice(0,80),
    performance:{evaluated:audits.length,directional_evaluable:valid.length,hits,hit_rate:valid.length?hits/valid.length:null},
    disclaimer:"Heuristic risk scores are not calibrated probabilities; historical outcomes do not guarantee future results."});
  }catch(e){console.error("ATLAS intelligence unavailable",String(e));return json({error:"intelligence_unavailable"},503)}
 }
 if(url.pathname.endsWith("/api/reports")){
  const cycle=String(url.searchParams.get("cycle")||"").toUpperCase();
  if(!["HOURLY","DEEP4H","DAILY16","NIGHTLY23"].includes(cycle))return json({error:"invalid_cycle"},400);
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503);
  try{
   const runs=await readTable(base,key,"atlas_scheduler_runs?select=cycle,completed_at,status&cycle=eq."+cycle+"&status=eq.DONE&order=completed_at.desc&limit=1");
   const run=runs[0];if(!run?.completed_at)return json({cycle,run:null,rows:[],source:null});
   const end=new Date(run.completed_at),start=new Date(end.getTime()-90*60*1000);
   const table=cycle==="DEEP4H"?"atlas_deep_4h_snapshots":"atlas_hourly_signal_snapshots";
   const query=table+"?select=symbol,asset_group,direction,confidence,price,captured_at,public_signal,decision_state,opportunity_score&captured_at=gte."+encodeURIComponent(start.toISOString())+"&captured_at=lte."+encodeURIComponent(new Date(end.getTime()+5*60*1000).toISOString())+"&order=captured_at.desc&limit=200";
   const records=await readTable(base,key,query),seen=new Set<string>();
   const rows=records.filter((r:any)=>{if(seen.has(r.symbol))return false;seen.add(r.symbol);return true}).slice(0,50);
   return json({cycle,run,rows,source:table,disclaimer:cycle==="DAILY16"||cycle==="NIGHTLY23"?"snapshot_near_cycle_not_full_report":null});
  }catch(e){console.error("cycle report unavailable",String(e));return json({error:"report_unavailable"},503)}
 }
 if(url.pathname.endsWith("/api/live-terminal")){
 const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
 if(!base||!key)return json({error:"service_unavailable"},503);
 try{
  const qs=[
   "atlas_signal_lifecycle?select=symbol,signal_id,lifecycle_state,direction,entry,sl,tp1,tp2,confidence,updated_at&order=updated_at.desc&limit=60",
   "atlas_free_alert_events?select=alert_key,timestamp,symbol,timeframe,event_type,direction,severity,rsi_value,confidence,telegram_status&order=timestamp.desc&limit=60",
   "atlas_market_guard_events?select=event_key,captured_at,event_type,symbol,pct_1h,reference_level,telegram_sent&order=captured_at.desc&limit=50",
   "atlas_hourly_signal_snapshots?select=symbol,asset_group,price,captured_at,public_signal&order=captured_at.desc&limit=300",
   "atlas_market_snapshots?select=symbol,price,captured_at&order=captured_at.desc&limit=120",
   "atlas_tse_snapshots?select=symbol,price,captured_at&order=captured_at.desc&limit=120"
  ];
  const [signals,alerts,guards,crypto,metals,iran]=await Promise.all(qs.map(q=>readTable(base,key,q)));
  const fresh=(t:any,h=24)=>!!t&&Date.now()-new Date(t).getTime()<h*3600000&&Date.now()>=new Date(t).getTime()-300000;
  const dedup=(rows:any[],limit=30)=>{const seen=new Set();return rows.filter(x=>{if(!x.symbol||seen.has(x.symbol))return false;seen.add(x.symbol);return true}).slice(0,limit)};
  const safeSignals=signals.map((x:any)=>({symbol:x.symbol,signal_id:x.signal_id,state:x.lifecycle_state,direction:x.direction,entry:x.entry,sl:x.sl,tp1:x.tp1,tp2:x.tp2,confidence:x.confidence,updated_at:x.updated_at,stale:!fresh(x.updated_at,24)}));
  const safeAlerts=[...alerts.map((x:any)=>({id:x.alert_key,at:x.timestamp,symbol:x.symbol,type:x.event_type,direction:x.direction,severity:x.severity,timeframe:x.timeframe,rsi:x.rsi_value,delivery:x.telegram_status,stale:!fresh(x.timestamp,12)})),...guards.map((x:any)=>({id:x.event_key,at:x.captured_at,symbol:x.symbol,type:x.event_type,severity:"GUARD",change_1h:x.pct_1h,reference_level:x.reference_level,delivery:x.telegram_sent?"SENT":"NOT_CONFIRMED",stale:!fresh(x.captured_at,12)}))].sort((a:any,b:any)=>String(b.at).localeCompare(String(a.at))).slice(0,80);
  const summarize=(rows:any[],limit=20)=>{const list=dedup(rows,limit);return {count:list.length,updated_at:list[0]?.captured_at||null,status:!list.length?"INSUFFICIENT_DATA":fresh(list[0].captured_at,6)?"FRESH":"DELAYED",items:list.map((x:any)=>({symbol:x.symbol,price:x.price,at:x.captured_at,signal:x.public_signal||null}))}};
  const c=summarize(crypto.filter((x:any)=>x.asset_group==="CRYPTO"),30);
  const m=summarize(metals,20),i=summarize(iran,20);
  return json({checked_at:new Date().toISOString(),refresh_seconds:90,public_read_only:true,signals:safeSignals,alerts:safeAlerts,markets:{crypto:c,metals:m,iran:i,us:{count:0,updated_at:null,status:"EXTERNAL_CHART_ONLY",items:[]}},disclaimer:"Historical or delayed signals are not live orders. No verified OOS performance implied."});
 }catch(e){console.error("live-terminal unavailable",String(e));return json({error:"live_terminal_unavailable"},503)}
 }
 if(url.pathname.endsWith("/api/iran-relative-value") && url.searchParams.get("schema")==="2"){
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503,origin);
  try{
   const marketSymbols=["XAUUSD","XAGUSD","COPPER"];
   const fxSymbols=["USD_IRR","GOLD18",...COIN_SPECS.map((x:any)=>x.source_symbol)];
   const inFilter=(symbols:string[])=>"in.("+symbols.map(x=>encodeURIComponent(x)).join(",")+")";
   const [marketRows,fxRows]=await Promise.all([
    readTable(base,key,"atlas_market_snapshots?select=symbol,price,captured_at,payload&symbol="+inFilter(marketSymbols)+"&order=captured_at.desc&limit=100"),
    readTable(base,key,"atlas_iran_fx_snapshots?select=symbol,price,captured_at,payload&symbol="+inFilter(fxSymbols)+"&order=captured_at.desc&limit=100")
   ]);
   const latest=(rows:any[],symbol:string)=>rows.find((r:any)=>r.symbol===symbol)||null;
   const xau=latest(marketRows,"XAUUSD"),usd=latest(fxRows,"USD_IRR");
   const xauUsd=normalizeUsdMetal(xau,"USD_PER_TROY_OZ"),usdIrr=normalizeUsdIrr(usd);
   const globalInputs=[xau,usd].filter(Boolean);
   const globalFresh=globalInputs.length===2&&globalInputs.every((r:any)=>Date.parse(r.captured_at)<=Date.now())?quoteFreshness(globalInputs):{ok:false,reason:"missing_global_input"};
   const quote=(symbol:string,row:any,unit:string,normalized:number|null)=>({
    symbol,price:normalized,unit,source:row?.payload?.provider||null,source_unit:row?.payload?.unit_canonical||row?.payload?.unit||row?.payload?.unit_raw||null,
    captured_at:row?.captured_at||null,status:!row?"unavailable":normalized===null?"invalid_unit":!(Date.parse(row.captured_at)<=Date.now())?"invalid_time":Date.now()-Date.parse(row.captured_at)>15*60*1000?"delayed":"recorded"
   });
   const usdToman=usdIrr===null?null:usdIrr/10;
   const quotes=[
    quote("USD_FREE",usd,"IRR_PER_USD",usdIrr),
    quote("XAUUSD",xau,"USD_PER_TROY_OZ",xauUsd),
    quote("XAGUSD",latest(marketRows,"XAGUSD"),"USD_PER_TROY_OZ",normalizeUsdMetal(latest(marketRows,"XAGUSD"),"USD_PER_TROY_OZ")),
    quote("COPPER",latest(marketRows,"COPPER"),"USD_PER_LB",normalizeUsdMetal(latest(marketRows,"COPPER"),"USD_PER_LB"))
   ];
   const comparisons:any[]=[];
   const goldRow=latest(fxRows,"GOLD18"),goldMarket=normalizeTomanMarket(goldRow);
   const globalReady=globalFresh.ok&&xauUsd!==null&&usdIrr!==null;
   const goldFair=globalReady?fairValueToman({weightG:1,purity:.75,xauUsd,usdIrr}):null;
   const goldFresh=Boolean(globalReady&&goldRow&&goldMarket!==null&&Date.parse(goldRow.captured_at)<=Date.now()&&quoteFreshness([xau,usd,goldRow]).ok);
   comparisons.push({
    symbol:"GOLD18",name_fa:"طلای ۱۸ عیار",weight_g:1,purity:.75,
    spot_usd_oz:xauUsd,fair_toman_per_gram:goldFair===null?null:Math.round(goldFair),
    market_toman_per_gram:goldMarket===null?null:Math.round(goldMarket),
    ...(goldFresh?bubbleToman(goldMarket,Number(goldFair)):{bubble_toman:null,bubble_pct:null}),
    status:!globalReady?"unavailable_inputs":!goldRow?"market_unavailable":goldMarket===null?"market_unit_unverified":!goldFresh?"stale_or_time_skew":"observed",
    formula:"(XAU_USD_per_troy_oz × 0.75 × USD_IRR_per_USD / 31.1034768) / 10",
    captured_at:goldRow?.captured_at||null,market_unit:"TOMAN_PER_GRAM"
   });
   for(const spec of COIN_SPECS){
    const row=latest(fxRows,spec.source_symbol),market=row?.payload?.unit_canonical==='TOMAN_PROVIDER_QUOTE'?null:normalizeTomanMarket(row);
    const fair=globalReady?fairValueToman({weightG:spec.weight_g,purity:spec.purity,xauUsd,usdIrr}):null;
    const ready=globalReady&&row&&market!==null&&Date.parse(row.captured_at)<=Date.now()&&quoteFreshness([xau,usd,row]).ok;
    comparisons.push({
     symbol:spec.symbol,name_fa:spec.name_fa,weight_g:spec.weight_g,purity:spec.purity,
     spot_usd_oz:xauUsd,fair_toman:fair===null?null:Math.round(fair),
     market_toman:market===null?null:Math.round(market),
     ...(ready?bubbleToman(market,Number(fair)):{bubble_toman:null,bubble_pct:null}),
     status:!globalReady?"unavailable_inputs":!row?"market_unavailable":market===null?"market_unit_unverified":!ready?"stale_or_time_skew":"observed",
     formula:"(weight_g × purity × XAU_USD_per_troy_oz × USD_IRR_per_USD / 31.1034768) / 10",
     captured_at:row?.captured_at||null,market_unit:"TOMAN_PER_COIN"
    });
   }
   const newest=[...globalInputs].map((r:any)=>Date.parse(r?.captured_at)).filter(Number.isFinite).sort((a:number,b:number)=>a-b)[0];
   const ageMs=newest?Date.now()-newest:Infinity;
   return json({status:globalReady?(ageMs>15*60*1000?"delayed":"recorded"):"unavailable",updated_at:newest?new Date(newest).toISOString():null,
    units:{usd_free:"IRR_PER_USD",usd_free_toman:usdToman,xau:"USD_PER_TROY_OZ",iran_market:"TOMAN",fair_value:"TOMAN"},
    freshness:{max_age_minutes:360,max_source_skew_minutes:30,global_inputs:globalFresh},
    sources:{usd_free:usd?.payload?.provider||null,xau:xau?.payload?.provider||null,iran_market:"atlas_iran_fx_snapshots"},
    quotes,comparisons,note:"Computed from stored provider quotes. Missing, stale, future-dated, or unit-unknown inputs do not produce a bubble value. This is intrinsic metal parity, not a guaranteed executable market price."},200,origin);
  }catch(e){console.error("Iran relative value unavailable",String(e));return json({error:"iran_relative_value_unavailable",status:"unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/iran-relative-value")){
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503,origin);
  try{
   const [fx,metal]=await Promise.all([
    readTable(base,key,"atlas_iran_fx_snapshots?select=symbol,price,captured_at,payload&order=captured_at.desc&limit=1200"),
    readTable(base,key,"atlas_market_snapshots?select=symbol,price,captured_at,payload&order=captured_at.desc&limit=1200")]);
   const pick=(rows:any[],symbol:string)=>rows.find((x:any)=>x.symbol===symbol);
   const rows:any[]=[];const maxAge=36*3600000;
   const age=(x:any)=>x?.captured_at?Date.now()-Date.parse(x.captured_at):Infinity;
   const price=(x:any)=>Number(x?.price)>0?Number(x.price):null;
   const usd=pick(fx,"USD_IRR"),usdt=pick(fx,"USDT_IRR"),eur=pick(fx,"EUR_IRR"),aed=pick(fx,"AED_IRR"),gold=pick(fx,"GOLD18"),silver=pick(metal,"SILVER999"),xau=pick(metal,"XAUUSD"),xag=pick(metal,"XAGUSD");
   const toman=(x:any)=>{const u=x?.payload?.unit_canonical;if(u==="IRR")return price(x)/10;if(u==="TOMAN_PER_GRAM"||u==="TOMAN_PROVIDER_QUOTE")return price(x);return null};
   for(const [label,x] of [["USDT",usdt],["USD",usd],["EUR",eur],["AED",aed],["GOLD18",gold],["SILVER999_9",silver]]){
    const v=toman(x);rows.push({symbol:label,toman:v,at:x?.captured_at||null,source:x?.payload?.provider||null,status:!x?"MISSING":age(x)>maxAge?"STALE":v===null?"UNIT_UNVERIFIED":"RECENT",unit:x?.payload?.unit_canonical||null})}
   const u=toman(usd),oz=31.1034768;
   const fairGold=price(xau)&&u?price(xau)*u/oz*.75:null;
   const fairSilver=price(xag)&&u?price(xag)*u/oz*.9999:null;
   const goldMarket=toman(gold),silverMarket=toman(silver);
   const compare=(name:string,spot:any,fair:number|null,market:number|null,marketObj:any)=>{const ok=!!(fair&&market&&age(usd)<maxAge&&age(spot)<maxAge&&age(marketObj)<maxAge&&Math.abs(Date.parse(spot.captured_at)-Date.parse(marketObj.captured_at))<6*3600000);return {symbol:name,spot_usd_oz:price(spot),fair_toman_per_gram:fair,market_toman_per_gram:market,premium_pct:ok?(market!/fair!-1)*100:null,status:ok?"COMPARABLE":"INSUFFICIENT_OR_NONCOMPARABLE",formula:name==="GOLD18"?"XAUUSD * USD_TOMAN / 31.1034768 * 0.75":"XAGUSD * USD_TOMAN / 31.1034768 * 0.9999",at:spot?.captured_at||null}};
   return json({checked_at:new Date().toISOString(),quotes:rows,comparisons:[compare("GOLD18",xau,fairGold,goldMarket,gold),compare("SILVER999_9",xag,fairSilver,silverMarket,silver)],note:"Spot parity excludes taxes, fabrication, dealer spreads and local premiums. Stale/missing/unit-ambiguous prices block premium."},200,origin);
  }catch(e){console.error("iran-relative-value",String(e));return json({error:"relative_value_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/crypto-top50-levels")){
  if(req.method!=="GET")return json({error:"method_not_allowed"},405,origin);
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503,origin);
  try{
   let coins:any[]=[],rankingSource="CoinGecko";
   try{
    const cg=await fetch("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1&sparkline=false",{signal:AbortSignal.timeout(5000),headers:{accept:"application/json"}});
    if(cg.ok){const result=await cg.json();if(Array.isArray(result)&&result.length>=40)coins=result}
    else console.warn("CoinGecko top50 HTTP",cg.status);
   }catch(e){console.warn("CoinGecko top50",String(e))}
   if(coins.length<40){
    try{
     const cp=await fetch("https://api.coinpaprika.com/v1/tickers?quotes=USD",{signal:AbortSignal.timeout(11000),headers:{accept:"application/json"}});
     if(cp.ok){const data=await cp.json();if(Array.isArray(data)){
      coins=data.filter((x:any)=>Number.isInteger(x.rank)&&x.rank>0&&x.quotes?.USD?.price>0).sort((a:any,b:any)=>a.rank-b.rank).slice(0,50).map((x:any)=>({symbol:x.symbol,name:x.name,current_price:x.quotes.USD.price,market_cap_rank:x.rank,price_change_percentage_24h:x.quotes.USD.percent_change_24h}));
      rankingSource="CoinPaprika (CoinGecko unavailable)";
     }}
    }catch(e){console.warn("CoinPaprika top50",String(e))}
   }
   if(coins.length<40)return json({error:"top50_price_providers_unavailable",sources_tried:["CoinGecko","CoinPaprika"],items:[]},503,origin);
   let rows:any[]=[];let signalDataAvailable=true;
   try{rows=await readTable(base,key,"atlas_deep_4h_snapshots?select=symbol,asset_group,public_signal,decision_state,direction,confidence,price,captured_at,payload&order=captured_at.desc&limit=500")}
   catch(e){signalDataAvailable=false;console.warn("top50 signal database unavailable",String(e))}
   const bySymbol=new Map();for(const x of rows){const k=String(x.symbol||"").toUpperCase().replace(/USDT$/,"");if(!bySymbol.has(k)&&["CRYPTO","COIN"].some(y=>String(x.asset_group||"").toUpperCase().includes(y)))bySymbol.set(k,x)}
   const num=(x:any)=>Number.isFinite(Number(x))&&Number(x)>0?Number(x):null;
   const items=coins.slice(0,50).map((coin:any,i:number)=>{
    const symbol=String(coin.symbol||"").toUpperCase(),x=bySymbol.get(symbol),p=x?.payload||{},entry=num(p.entry),sl=num(p.sl),tp1=num(p.tp1),tp2=num(p.tp2),signal=String(x?.public_signal||"WAIT").toUpperCase(),direction=String(x?.direction||p.direction||"").toUpperCase();
    const recent=x?.captured_at&&Date.now()-Date.parse(x.captured_at)<8*3600000;
    const long=["BUY","ACCUMULATE","LONG"].includes(signal)&&direction==="LONG",short=["SELL","REDUCE","SHORT"].includes(signal)&&direction==="SHORT";
    const geometry=entry&&sl&&tp1&&tp2&&(long?sl<entry&&entry<tp1&&tp1<=tp2:short?sl>entry&&entry>tp1&&tp1>=tp2:false);
    const rr=geometry?Math.abs(tp2-entry)/Math.abs(entry-sl):null;
    const verified=!!(recent&&geometry&&rr>=2);
    const reasons=verified?[String(p.reason||"ATLAS 4H technical model"),"Validated level order and R:R ≥ 2"]:[signalDataAvailable?"No fresh eligible public ATLAS signal with valid positive TP/SL and R:R ≥ 2":"ATLAS signal database temporarily unavailable; WAIT (no fabricated levels)"];
    return {rank:i+1,symbol,name:coin.name,price_usd:num(coin.current_price),market_cap_rank:coin.market_cap_rank,price_change_24h:coin.price_change_percentage_24h??null,decision:verified?signal:"WAIT",direction:verified?direction:null,entry:verified?entry:null,sl:verified?sl:null,tp1:verified?tp1:null,tp2:verified?tp2:null,rr:verified?rr:null,reasons,signal_at:x?.captured_at||null,price_source:"CoinGecko",signal_source:verified?"ATLAS deep4h public snapshot":null,chart:"https://www.tradingview.com/chart/?symbol=BINANCE%3A"+encodeURIComponent(symbol+"USDT")};
   });
   return json({checked_at:new Date().toISOString(),ranking_source:rankingSource,timeframe:"4h",signal_data_available:signalDataAvailable,items,eligible:items.filter((x:any)=>x.decision!=="WAIT").length,method:"Public ATLAS signals only; positive ordered TP/SL; minimum RR 2; 8h freshness; no levels for WAIT",paper_only:true},200,origin);
  }catch(e){console.error("top50",String(e));return json({error:"crypto_top50_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/opportunity-lab")){
 if(req.method!=="GET")return json({error:"method_not_allowed"},405,origin);
 const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
 if(!base||!key)return json({error:"service_unavailable"},503,origin);
 try{
  const queries=[
   "atlas_deep_4h_snapshots?select=symbol,asset_group,public_signal,decision_state,direction,confidence,opportunity_score,price,captured_at&order=captured_at.desc&limit=1500",
   "atlas_tse_snapshots?select=symbol,price,value,captured_at&order=captured_at.desc&limit=2500",
   "atlas_fund_snapshots?select=symbol,name,fund_type,price,nav,captured_at&order=captured_at.desc&limit=1500",
   "atlas_market_snapshots?select=symbol,asset,price,captured_at&order=captured_at.desc&limit=350",
   "atlas_iran_fx_snapshots?select=symbol,price,captured_at&order=captured_at.desc&limit=250"
  ];
  const [deep,tse,funds,metals,fx]=await Promise.all(queries.map(q=>readTable(base,key,q)));
  const recent=(x:any,h:number)=>x?.captured_at&&Date.now()-Date.parse(x.captured_at)<h*3600000&&Date.now()>=Date.parse(x.captured_at)-300000;
  const latest=(rows:any[])=>{const seen=new Set(),out:any[]=[];for(const x of rows){if(!x.symbol||seen.has(x.symbol))continue;seen.add(x.symbol);out.push(x)}return out};
  const scores=latest(deep.filter((x:any)=>String(x.asset_group).toUpperCase().includes("CRYPTO")&&Number.isFinite(Number(x.opportunity_score))&&recent(x,36))).filter((x:any)=>!["WAIT","INSUFFICIENT_DATA"].includes(String(x.decision_state).toUpperCase()));
  const crypto=scores.sort((a:any,b:any)=>Number(b.opportunity_score)-Number(a.opportunity_score)).slice(0,5).map((x:any)=>({symbol:x.symbol,decision:x.decision_state,signal:x.public_signal,score:Number(x.opportunity_score),confidence:x.confidence,price:x.price,at:x.captured_at,metric:"existing_atlas_opportunity_score",validated_performance:false}));
  const stocks=latest(tse).filter((x:any)=>recent(x,96)&&Number(x.price)>0).slice(0,5).map((x:any)=>({symbol:x.symbol,price:x.price,at:x.captured_at,decision:"UNRANKED",reason:"No validated stock-growth model or fundamental filter"}));
  const fundItems=latest(funds).filter((x:any)=>recent(x,96)&&/درآمد ثابت|fixed|income/i.test(String(x.fund_type||"")+" "+String(x.name||""))).map((x:any)=>({...x,discount_pct:Number(x.nav)>0&&Number(x.price)>0?(Number(x.price)/Number(x.nav)-1)*100:null})).sort((a:any,b:any)=>(a.discount_pct??Infinity)-(b.discount_pct??Infinity)).slice(0,20).map((x:any)=>({symbol:x.symbol,name:x.name,fund_type:x.fund_type,price:x.price,nav:x.nav,discount_pct:x.discount_pct,at:x.captured_at,yield_rank:null}));
  const m=latest(metals),f=latest(fx);
  const bubbles=[...m,...f].filter((x:any)=>/GOLD|SILVER|XAU|XAG|COIN|USD|USDT|سکه|طلا|نقره/i.test(x.symbol||"")).slice(0,35).map((x:any)=>({symbol:x.symbol,price:x.price,at:x.captured_at,bubble_pct:null,decision:"WAIT",reason:"Comparable spot, FX, purity, premium and unit conversions not independently verified"}));
  return json({checked_at:new Date().toISOString(),read_only:true,crypto:{items:crypto,eligible:scores.length,method:"Existing ATLAS scores; not a verified win-rate"},iran_stocks:{items:stocks,ranking_status:"UNAVAILABLE",reason:"No defensible growth ranking until price history, liquidity and fundamentals validated"},fixed_income:{items:fundItems,method:"NAV discount ascending; NOT yield ranking",yield_ranking_status:"UNAVAILABLE"},relative_value:{items:bubbles,method:"Raw quotes only; no inferred bubble without normalized units and verified cross-market prices"},disclaimer:"Research only; missing rankings and fair values are intentionally withheld."},200,origin);
 }catch(e){console.error("opportunity-lab",String(e));return json({error:"opportunity_lab_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/iran-funds")){
 if(req.method!=="GET")return json({error:"method_not_allowed"},405,origin);
 const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
 if(!base||!key)return json({error:"service_unavailable"},503,origin);
 try{
  const rows=await readTable(base,key,"atlas_fund_snapshots?select=symbol,name,fund_type,price,nav,captured_at&order=captured_at.desc&limit=1500");
  const seen=new Set(),items:any[]=[];
  for(const x of rows){if(!x.symbol||seen.has(x.symbol))continue;seen.add(x.symbol);items.push({symbol:x.symbol,name:x.name,fund_type:x.fund_type,price:x.price,nav:x.nav,captured_at:x.captured_at})}
  const latest=items[0]?.captured_at||null;
  return json({items:items.slice(0,350),returned:items.length,latest_at:latest,status:!latest?"INSUFFICIENT_DATA":Date.now()-Date.parse(latest)>36*3600000?"DELAYED":"RECENT",source:"atlas_fund_snapshots",read_only:true},200,origin);
 }catch(e){console.error("iran-funds",String(e));return json({error:"funds_unavailable"},503,origin)}
 }
 if(url.pathname.endsWith("/api/overview")){
  const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503);
  try{
   const queries=[
    "atlas_scheduler_runs?select=cycle,completed_at&status=eq.DONE&order=completed_at.desc&limit=120",
    "atlas_free_alert_events?select=symbol,direction,timeframe,severity,confidence,timestamp&telegram_status=eq.SENT&order=timestamp.desc&limit=30",
    "atlas_hourly_signal_snapshots?select=symbol,price,captured_at&order=captured_at.desc&limit=200",
    "atlas_tse_snapshots?select=symbol,price,captured_at&order=captured_at.desc&limit=200",
    "atlas_mtf_snapshots?select=symbol,timestamp,direction,h1,h4,d1,w1,agreement_pct&order=timestamp.desc&limit=200",
    "atlas_signal_lifecycle?select=symbol,direction,lifecycle_state,confidence,entry,sl,tp1,updated_at&order=updated_at.desc&limit=20",
    "atlas_market_snapshots?select=symbol,price,captured_at,payload&symbol=in.(XAUUSD,XAGUSD,COPPER,SILVER999_FAIR)&order=captured_at.desc&limit=100",
    "atlas_iran_fx_snapshots?select=symbol,price,captured_at,payload&symbol=in.(GOLD18,COIN_EMAMI,USD_IRR,USDT_IRR)&order=captured_at.desc&limit=100",
    "atlas_deep_4h_snapshots?select=symbol,asset_group,direction,confidence,price,captured_at,public_signal,decision_state&order=captured_at.desc&limit=40"
   ];
   const [runs,alerts,cryptorows,iranrows,mtfrows,opportunities,metalrows,fxrows,deepRows]=await Promise.all(queries.map(q=>readTable(base,key,q)));
   const unique=(rows:any[],limit:number)=>{const seen=new Set<string>();return rows.filter((x:any)=>{const k=String(x.symbol||"");if(!k||seen.has(k))return false;seen.add(k);return true}).slice(0,limit)};
   const cycles=["HOURLY","DEEP4H","DAILY16","NIGHTLY23"].map(cycle=>({cycle,completed_at:runs.find((r:any)=>r.cycle===cycle)?.completed_at||null}));
   return json({checked_at:new Date().toISOString(),cycles,alerts,crypto:unique(cryptorows,100),iran:unique(iranrows,100),mtf:unique(mtfrows,100),metals:unique([...metalrows,...fxrows].filter((x:any)=>!(x.symbol==='COIN_EMAMI'&&x.payload?.unit_canonical==='TOMAN_PROVIDER_QUOTE')).map((x:any)=>({symbol:x.symbol,price:x.price,captured_at:x.captured_at,unit:x.payload?.unit_canonical||x.payload?.unit||null})).sort((a:any,b:any)=>String(b.captured_at).localeCompare(String(a.captured_at))),40),deep:deepRows,opportunities});
  }catch(e){console.error("ATLAS overview unavailable",String(e));return json({error:"data_unavailable"},503)}
 }
 if(url.pathname.endsWith("/api/status")){
  const base=Deno.env.get("SUPABASE_URL")||"";const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
  if(!base||!key)return json({error:"service_unavailable"},503);
  try{
   const [runs,alerts]=await Promise.all([
    readTable(base,key,"atlas_scheduler_runs?select=cycle,status,completed_at&status=eq.DONE&order=completed_at.desc&limit=120"),
    readTable(base,key,"atlas_free_alert_events?select=symbol,direction,timeframe,severity,confidence,timestamp&telegram_status=eq.SENT&order=timestamp.desc&limit=12")
   ]);
   const cycles=["HOURLY","DEEP4H","DAILY16","NIGHTLY23"].map(cycle=>({cycle,completed_at:runs.find((r:any)=>r.cycle===cycle)?.completed_at||null}));
   return json({checked_at:new Date().toISOString(),cycles,alerts:alerts.map((r:any)=>({symbol:r.symbol,direction:r.direction,timeframe:r.timeframe,severity:r.severity,confidence:r.confidence,timestamp:r.timestamp}))});
  }catch(e){console.error("ATLAS web data unavailable",String(e));return json({error:"data_unavailable"},503)}
 }
 return new Response(new TextEncoder().encode(HTML),{status:200,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store, no-cache, must-revalidate","x-atlas-web-version":"50-utf8-bytes","Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}});
});
