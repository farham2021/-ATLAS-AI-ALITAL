/* ATLAS command palette: additive, read-only, no menu mutation or API calls. */
(()=>{'use strict';
 const init=()=>{
  const main=document.getElementById('atlas-main-menu');
  const sub=document.getElementById('atlas-sub-menu');
  if(!main||!sub||document.getElementById('atlas-command-trigger'))return;
  const trigger=document.createElement('button');
  trigger.type='button';trigger.id='atlas-command-trigger';trigger.className='atlas-command-trigger';
  trigger.textContent='⌕ جستجوی سریع';trigger.setAttribute('aria-label','جستجوی بخش‌ها و دارایی‌ها');
  main.parentElement.insertBefore(trigger,main);
  const dialog=document.createElement('dialog');dialog.id='atlas-command-dialog';
  dialog.innerHTML='<div class="atlas-command-shell" dir="rtl"><label for="atlas-command-input">جستجوی سریع در ATLAS</label><input id="atlas-command-input" type="search" autocomplete="off" placeholder="BTC، طلا، صندوق، ژورنال، S&P…"><div id="atlas-command-results" role="listbox"></div><p class="atlas-command-hint">Enter برای انتخاب · Esc برای بستن</p></div>';
  document.body.append(dialog);
  const input=dialog.querySelector('input'),results=dialog.querySelector('#atlas-command-results');
  const aliases=[
   ['BTC بیت کوین bitcoin ETH اتریوم XRP SOL کریپتو ارز دیجیتال','crypto-top50-panel','کریپتو · ۵۰ ارز'],
   ['Funding OI فیوچرز مشتقات فرصت تحلیل','opportunity-lab','کریپتو · آزمایشگاه فرصت'],
   ['Quant Risk ریسک','quant-panel','کریپتو · مدیریت ریسک'],
   ['طلا سکه نقره مس gold silver copper','metals-panel','ایران · فلزات'],
   ['بورس تهران فولاد خودرو حقیقی TSETMC','iran-panel','ایران · بورس تهران'],
   ['دلار تتر ارز حباب نرخ','fx-parity-panel','ایران · ارز و حباب'],
   ['صندوق درآمد ثابت NAV ETF','funds-panel','ایران · صندوق‌ها'],
   ['S&P SPX NASDAQ آمریکا','us-panel','پژوهش · بازار آمریکا'],
   ['ژورنال معاملات trade journal','journal-panel','پژوهش · ژورنال'],
   ['انضباط adherence','discipline-panel','پژوهش · انضباط'],
   ['سبد حجم معامله position','position-panel','پژوهش · حجم معامله'],
   ['اخبار news','news-panel','پژوهش · اخبار'],
   ['ورود حساب login auth','account-panel','حساب · ورود'],
   ['نقشه بازار heatmap','market-heatmap','پیشخوان · نقشه بازار'],
   ['گزارش hourly daily','reports-panel','پیشخوان · گزارش‌ها'],
   ['زنده live terminal','live-terminal','پیشخوان · ترمینال زنده']
  ];
  const normalize=s=>String(s).toLocaleLowerCase().replace(/[ي]/g,'ی').replace(/[ك]/g,'ک').trim();
  let matches=[];
  const render=()=>{
   const q=normalize(input.value);
   matches=aliases.filter(([terms,id,label])=>document.getElementById(id)&&(!q||normalize(terms+' '+label).includes(q))).slice(0,9);
   results.replaceChildren();
   for(const [,id,label] of matches){
    const b=document.createElement('button');b.type='button';b.className='atlas-command-result';b.textContent=label;
    b.onclick=()=>navigate(id);results.append(b);
   }
   if(!matches.length){const p=document.createElement('p');p.textContent='نتیجه‌ای پیدا نشد';results.append(p)}
  };
  const navigate=id=>{dialog.close();if(location.hash==='#'+id){window.dispatchEvent(new Event('hashchange'))}else{location.hash=id}};
  const open=()=>{render();dialog.showModal();input.focus()};
  trigger.addEventListener('click',open);input.addEventListener('input',render);
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&matches[0]){e.preventDefault();navigate(matches[0][1])}});
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if(dialog.open)dialog.close();else open()}});
  dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close()});
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();