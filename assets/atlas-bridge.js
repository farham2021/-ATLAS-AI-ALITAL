/* ATLAS asset bridge v1 — UI only, no orders or invented trade levels. */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const finite=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x))&&Number(x)>0;
const symbolOf=x=>String(x.symbol||'').trim().toUpperCase();
const allowed=s=>/^[A-Z0-9]{2,18}$/.test(s);
const show=(id)=>{const node=$(id);if(!node)return;location.hash=id;node.scrollIntoView({behavior:'smooth',block:'start'});};
window.addEventListener('atlas:selectAsset',event=>{
 const x=event.detail||{},symbol=symbolOf(x);if(!allowed(symbol))return;
 const chart=$('chart-symbol');
 if(chart){if(![...chart.options].some(o=>o.value===symbol))chart.add(new Option(symbol,symbol));chart.value=symbol;$('chart-open')?.click();}
 const quant=$('symbol');if(quant&&[...quant.options].some(o=>o.value===symbol))quant.value=symbol;
 const discipline=$('discipline-symbol');if(discipline)discipline.value=symbol;
 const direction=String(x.direction||x.side||'').toUpperCase();
 const decision=String(x.decision||'').toUpperCase();
 const validDecision=['BUY','ACCUMULATE','HOLD','REDUCE','SELL','LONG','SHORT'].includes(decision);
 const valid=validDecision&&['LONG','SHORT'].includes(direction)&&finite(x.entry)&&finite(x.sl)&&finite(x.tp1)&&
 (direction==='LONG'?Number(x.sl)<Number(x.entry)&&Number(x.tp1)>Number(x.entry):Number(x.sl)>Number(x.entry)&&Number(x.tp1)<Number(x.entry))&&
 x.stale!==true&&x.status!=='STALE';
 const notice=$('atlas-bridge-status');
 if(valid){
  $('entry').value=x.entry;$('sl').value=x.sl;$('tp').value=x.tp1;$('side').value=direction;
  $('size-btn')?.click();if(notice)notice.textContent=symbol+' · ستاپ دریافت شد؛ حجم صرفاً محاسباتی است و سفارش ارسال نشده است.';
  show('position-panel');
 }else{
  for(const id of ['entry','sl','tp'])if($(id))$(id).value='';
  if($('size-result'))$('size-result').textContent='برای '+symbol+' ستاپ معتبر و کامل وجود ندارد؛ محاسبه حجم انجام نشد.';
  if(notice)notice.textContent=symbol+' · فقط نمودار؛ Entry و SL معتبر موجود نیست.';
  show('chart-panel');
 }
});
document.addEventListener('DOMContentLoaded',()=>{
 const host=$('position-panel');if(host&&!$('atlas-bridge-status')){const p=document.createElement('p');p.id='atlas-bridge-status';p.className='muted';p.setAttribute('aria-live','polite');p.textContent='یک نماد را از جدول انتخاب کنید.';host.insertBefore(p,host.firstElementChild?.nextSibling||null);}
});
})();