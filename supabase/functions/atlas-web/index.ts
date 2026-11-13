// ATLAS public read-only PWA. No private portfolios, credentials, or trading operations.
const HTML = `<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#101b32"><meta name="description" content="ATLAS AI &#8212; &#1583;&#1575;&#1588;&#1576;&#1608;&#1585;&#1583; &#1608;&#1590;&#1593;&#1740;&#1578; &#1578;&#1581;&#1604;&#1740;&#1604; &#1608; &#1607;&#1588;&#1583;&#1575;&#1585;&#1607;&#1575;&#1740; &#1576;&#1575;&#1586;&#1575;&#1585;"><link rel="manifest" href="/functions/v1/atlas-web/manifest.webmanifest"><title>ATLAS AI | Dashboard</title><style>
:root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#e9f2ff;background:#091324;font-synthesis:none}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0%,#1b3861 0%,#091324 50%);min-height:100vh}main{max-width:1080px;margin:auto;padding:24px 16px 70px}header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}h1{font-size:28px;margin:8px 0}h2{font-size:19px;margin:0 0 16px}.muted{color:#a5b7d1}.brand{font-weight:800;letter-spacing:2px;color:#77d3ff}.pill{border:1px solid #355271;border-radius:30px;padding:7px 12px;font-size:12px;color:#b8d3ed}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:14px;margin:24px 0}.card{background:#13243b;border:1px solid #2b4564;border-radius:18px;padding:20px;box-shadow:0 12px 30px #0002}.value{font-size:25px;font-weight:750;margin:12px 0 4px;direction:ltr;text-align:right}.row{display:flex;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid #2b4564;align-items:center}.row:last-child{border:0}.tag{border-radius:8px;padding:4px 8px;background:#1e3a54;color:#b9e4f8;font-size:12px}button{background:#2a86bf;color:white;border:0;border-radius:10px;padding:11px 16px;cursor:pointer;font:inherit}button:focus-visible{outline:3px solid white}a{color:#7bd8ff}footer{margin-top:24px;font-size:13px;line-height:1.8}#error{color:#ffbdad}#alerts{overflow-wrap:anywhere}@media(min-width:760px){.panels{display:grid;grid-template-columns:1fr 1fr;gap:16px}}@media(max-width:500px){h1{font-size:23px}.value{font-size:20px}}
</style></head><body><main><header><div><div class="brand">ATLAS AI</div><h1>&#1583;&#1575;&#1588;&#1576;&#1608;&#1585;&#1583; &#1607;&#1608;&#1588;&#1605;&#1606;&#1583; &#1576;&#1575;&#1586;&#1575;&#1585;</h1><div class="muted">&#1606;&#1605;&#1575;&#1740; &#1593;&#1605;&#1608;&#1605;&#1740; &#1608; &#1601;&#1602;&#1591;&#8204;&#1582;&#1608;&#1575;&#1606;&#1583;&#1606;&#1740; &#1575;&#1586; &#1608;&#1590;&#1593;&#1740;&#1578; &#1605;&#1608;&#1578;&#1608;&#1585; &#1608; &#1607;&#1588;&#1583;&#1575;&#1585;&#1607;&#1575;&#1740; &#1579;&#1576;&#1578;&#8204;&#1588;&#1583;&#1607;</div></div><button id="refresh">&#8635; &#1576;&#1585;&#1608;&#1586;&#1585;&#1587;&#1575;&#1606;&#1740;</button></header><div class="grid"><section class="card"><div class="muted">&#1608;&#1590;&#1593;&#1740;&#1578; &#1587;&#1585;&#1608;&#1740;&#1587;</div><div class="value" id="service">&#1583;&#1585; &#1581;&#1575;&#1604; &#1576;&#1585;&#1585;&#1587;&#1740;</div><div class="muted" id="updated">&#8212;</div></section><section class="card"><div class="muted">&#1607;&#1588;&#1583;&#1575;&#1585;&#1607;&#1575;&#1740; &#1575;&#1582;&#1740;&#1585;</div><div class="value" id="count">&#8212;</div><div class="muted">&#1581;&#1583;&#1575;&#1705;&#1579;&#1585; &#1777;&#1778; &#1585;&#1705;&#1608;&#1585;&#1583; &#1570;&#1582;&#1585;</div></section><section class="card"><div class="muted">&#1670;&#1585;&#1582;&#1607;&#8204;&#1607;&#1575;&#1740; &#1578;&#1581;&#1604;&#1740;&#1604;</div><div class="value">&#1780;</div><div class="muted">HOURLY &#183; DEEP4H &#183; DAILY16 &#183; NIGHTLY23</div></section></div><div id="error" role="alert"></div><div class="panels"><section class="card"><h2>&#1570;&#1582;&#1585;&#1740;&#1606; &#1575;&#1580;&#1585;&#1575;&#1740; &#1670;&#1585;&#1582;&#1607;&#8204;&#1607;&#1575;</h2><div id="runs" aria-live="polite">&#1583;&#1585; &#1581;&#1575;&#1604; &#1583;&#1585;&#1740;&#1575;&#1601;&#1578;...</div></section><section class="card"><h2>&#1570;&#1582;&#1585;&#1740;&#1606; &#1607;&#1588;&#1583;&#1575;&#1585;&#1607;&#1575;&#1740; &#1579;&#1576;&#1578;&#8204;&#1588;&#1583;&#1607;</h2><div id="alerts" aria-live="polite">&#1583;&#1585; &#1581;&#1575;&#1604; &#1583;&#1585;&#1740;&#1575;&#1601;&#1578;...</div></section></div><footer class="muted">&#1586;&#1605;&#1575;&#1606;&#8204;&#1607;&#1575; UTC &#1607;&#1587;&#1578;&#1606;&#1583;. &#1575;&#1740;&#1606; &#1583;&#1575;&#1588;&#1576;&#1608;&#1585;&#1583; &#1583;&#1575;&#1583;&#1607;&#8204;&#1607;&#1575;&#1740; &#1579;&#1576;&#1578;&#8204;&#1588;&#1583;&#1607; &#1585;&#1575; &#1606;&#1605;&#1575;&#1740;&#1588; &#1605;&#1740;&#8204;&#1583;&#1607;&#1583;&#1548; &#1606;&#1607; &#1602;&#1740;&#1605;&#1578; &#1604;&#1581;&#1592;&#1607;&#8204;&#1575;&#1740; &#1740;&#1575; &#1578;&#1608;&#1589;&#1740;&#1607; &#1602;&#1591;&#1593;&#1740; &#1605;&#1593;&#1575;&#1605;&#1604;&#1607;. &#1608;&#1590;&#1593;&#1740;&#1578; SENT &#1579;&#1576;&#1578; &#1575;&#1585;&#1587;&#1575;&#1604; &#1575;&#1587;&#1578; &#1608; &#1578;&#1581;&#1608;&#1740;&#1604; &#1576;&#1607; &#1711;&#1740;&#1585;&#1606;&#1583;&#1607; &#1585;&#1575; &#1575;&#1579;&#1576;&#1575;&#1578; &#1606;&#1605;&#1740;&#8204;&#1705;&#1606;&#1583;. &#1575;&#1591;&#1604;&#1575;&#1593;&#1575;&#1578; &#1582;&#1589;&#1608;&#1589;&#1740; &#1587;&#1576;&#1583; &#1705;&#1575;&#1585;&#1576;&#1585;&#1575;&#1606; &#1583;&#1585; &#1575;&#1740;&#1606; &#1589;&#1601;&#1581;&#1607; &#1606;&#1605;&#1575;&#1740;&#1588; &#1583;&#1575;&#1583;&#1607; &#1606;&#1605;&#1740;&#8204;&#1588;&#1608;&#1583;.</footer></main><script>
const el=id=>document.getElementById(id);const fmt=x=>x?new Date(x).toLocaleString('fa-IR',{timeZone:'Asia/Tehran'}):'\u062b\u0628\u062a \u0646\u0634\u062f\u0647';
function line(left,right){const d=document.createElement('div');d.className='row';const a=document.createElement('span');a.textContent=left;const b=document.createElement('span');b.className='tag';b.textContent=right;d.append(a,b);return d}
async function load(){el('error').textContent='';try{const r=await fetch('/functions/v1/atlas-web/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json();el('service').textContent='\u0641\u0639\u0627\u0644';el('updated').textContent=fmt(d.checked_at);el('count').textContent=String(d.alerts.length);el('runs').replaceChildren(...d.cycles.map(x=>line(x.cycle,x.completed_at?fmt(x.completed_at):'\u0628\u062f\u0648\u0646 \u0627\u062c\u0631\u0627\u06cc \u062b\u0628\u062a\u200c\u0634\u062f\u0647')));el('alerts').replaceChildren(...(d.alerts.length?d.alerts.map(x=>line([x.symbol,x.direction,x.timeframe].filter(Boolean).join(' | '),fmt(x.timestamp))):[document.createTextNode('\u0647\u0646\u0648\u0632 \u0647\u0634\u062f\u0627\u0631\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647 \u0627\u0633\u062a')]));}catch(e){el('service').textContent='\u0646\u0627\u0645\u0634\u062e\u0635';el('error').textContent='\u062f\u0631\u06cc\u0627\u0641\u062a \u062f\u0627\u062f\u0647 \u0645\u0645\u06a9\u0646 \u0646\u0634\u062f: '+String(e.message||e)}}el('refresh').onclick=load;load();
</script></body></html>`;
// Use ASCII-safe HTML entities and JS Unicode escapes to prevent intermediary Latin-1 mojibake.
const HEAD={"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Access-Control-Allow-Origin":"https://farham2021.github.io","Access-Control-Allow-Methods":"GET, POST, OPTIONS","Access-Control-Allow-Headers":"X-Telegram-Init-Data, Content-Type","Vary":"Origin"};
const json=(v:unknown,status=200)=>new Response(JSON.stringify(v),{status,headers:HEAD});
async function readTable(url:string,key:string,path:string){
 const res=await fetch(url+"/rest/v1/"+path,{headers:{"apikey":key,"Authorization":"Bearer "+key},signal:AbortSignal.timeout(9000)});
 if(!res.ok)throw Error("database unavailable");
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
 if(!userId)return json({error:"telegram_auth_required"},401);
 const base=Deno.env.get("SUPABASE_URL")||"",key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
 if(!base||!key)return json({error:"service_unavailable"},503);
 const get=(table:string,query:string)=>readTable(base,key,table+"?"+query);
 const filter="user_id=eq."+encodeURIComponent(userId);
 if(req.method==="GET"){
  const [holdings,basis,trades,prefs,referrals,memberships,opening,language]=await Promise.all([
   get("atlas_desk_holdings",filter+"&select=coin,qty"),
   get("atlas_desk_purchase_basis",filter+"&select=coin,average_buy_price,buy_date,quote_currency"),
   get("atlas_desk_trades",filter+"&select=id,coin,side,qty,unit_price,fee,traded_at&order=traded_at.desc&limit=200"),
   get("atlas_desk_alert_preferences",filter+"&select=symbol,rise_pct,fall_pct,enabled"),
   get("atlas_desk_referrals","inviter_user_id=eq."+encodeURIComponent(userId)+"&select=invited_user_id&limit=200"),
   get("atlas_desk_memberships",filter+"&select=status,plan,expires_at"),
   get("atlas_desk_trade_opening",filter+"&select=coin,opening_qty,opening_cost"),
   get("atlas_desk_language_preferences",filter+"&select=language")
  ]);
  return json({user_id:userId,holdings,basis,trades,prefs,opening,membership:memberships[0]||{status:"trial",plan:"free"},language:language[0]?.language||"fa",referral_count:referrals.length});
 }
 if(req.method!=="POST")return json({error:"method_not_allowed"},405);
 let body:any;try{body=await req.json()}catch{return json({error:"invalid_json"},400)}
 const action=String(body?.action||""),coin=String(body?.coin||"").toUpperCase();
 if(!/^[A-Z0-9]{2,20}$/.test(coin)&&!["referral","language"].includes(action))return json({error:"invalid_symbol"},400);
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
 const url=new URL(req.url);
 if(req.method==="OPTIONS")return new Response(null,{status:204,headers:{...HEAD,"Access-Control-Allow-Headers":"X-Telegram-Init-Data, Content-Type"}});
 if(url.pathname.endsWith("/api/private")){try{return await privateRoute(req,url)}catch(e){console.error("private ATLAS route error",String(e));return json({error:"private_data_unavailable"},503)}}
 if(req.method!=="GET"&&req.method!=="HEAD")return json({error:"method_not_allowed"},405);
 if(url.pathname.endsWith("/manifest.webmanifest"))return new Response(JSON.stringify({name:"ATLAS AI Dashboard",short_name:"ATLAS",start_url:"./",scope:"./",display:"standalone",background_color:"#091324",theme_color:"#101b32",lang:"fa",dir:"rtl"}),{headers:{"Content-Type":"application/manifest+json","Cache-Control":"public, max-age=3600"}});



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
    "atlas_market_snapshots?select=symbol,price,captured_at&order=captured_at.desc&limit=100",
    "atlas_iran_fx_snapshots?select=symbol,price,captured_at&order=captured_at.desc&limit=100",
    "atlas_deep_4h_snapshots?select=symbol,asset_group,direction,confidence,price,captured_at,public_signal,decision_state&order=captured_at.desc&limit=40"
   ];
   const [runs,alerts,cryptorows,iranrows,mtfrows,opportunities,metalrows,fxrows,deepRows]=await Promise.all(queries.map(q=>readTable(base,key,q)));
   const unique=(rows:any[],limit:number)=>{const seen=new Set<string>();return rows.filter((x:any)=>{const k=String(x.symbol||"");if(!k||seen.has(k))return false;seen.add(k);return true}).slice(0,limit)};
   const cycles=["HOURLY","DEEP4H","DAILY16","NIGHTLY23"].map(cycle=>({cycle,completed_at:runs.find((r:any)=>r.cycle===cycle)?.completed_at||null}));
   return json({checked_at:new Date().toISOString(),cycles,alerts,crypto:unique(cryptorows,100),iran:unique(iranrows,100),mtf:unique(mtfrows,100),metals:unique([...metalrows,...fxrows].sort((a:any,b:any)=>String(b.captured_at).localeCompare(String(a.captured_at))),40),deep:deepRows,opportunities});
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
 return new Response(HTML,{headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"public, max-age=120","X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}});
});
