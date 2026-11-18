/* Research-only calculators. No trade execution, persistence or synthetic market observations. */
(()=>{'use strict';
 const ready=()=>{
 const pos=document.getElementById('position-panel'),lab=document.getElementById('opportunity-lab');
 if(pos&&!document.getElementById('atlas-allocation')){
 const box=document.createElement('section');box.id='atlas-allocation';box.className='atlas-research-tool';
 box.innerHTML='<h3>⚖️ وزن‌دهی سبد کل (محاسبه‌گر)</h3><p>ارزش هر گروه را با واحد مشترک وارد کنید. داده‌ها فقط در همین صفحه محاسبه می‌شوند و ذخیره نمی‌شوند.</p><div class="atlas-tool-grid" id="atlas-allocation-fields"></div><div id="atlas-allocation-result" aria-live="polite"></div>';
 pos.append(box);const wrap=box.querySelector('#atlas-allocation-fields'),out=box.querySelector('#atlas-allocation-result');
 const cats=['کریپتو','طلا و سکه','سهام','درآمد ثابت','نقد'];
 cats.forEach((name,i)=>{const item=document.createElement('label');item.textContent=name;const v=document.createElement('input');v.type='number';v.min='0';v.step='any';v.placeholder='ارزش';v.dataset.kind='value';v.dataset.idx=i;const t=document.createElement('input');t.type='number';t.min='0';t.max='100';t.step='0.1';t.placeholder='هدف %';t.dataset.kind='target';t.dataset.idx=i;item.append(v,t);wrap.append(item)});
 const b=document.createElement('button');b.type='button';b.textContent='محاسبه اختلاف وزن‌ها';box.append(b);
 b.onclick=()=>{const values=[...wrap.querySelectorAll('[data-kind="value"]')].map(x=>Number(x.value)),targets=[...wrap.querySelectorAll('[data-kind="target"]')].map(x=>Number(x.value));const sum=values.reduce((a,b)=>a+b,0),targetSum=targets.reduce((a,b)=>a+b,0);
 if(values.some(x=>!Number.isFinite(x)||x<0)||targets.some(x=>!Number.isFinite(x)||x<0||x>100)||sum<=0||Math.abs(targetSum-100)>.1){out.textContent='ارزش‌ها باید نامنفی، مجموع سبد مثبت و مجموع وزن‌های هدف دقیقاً ۱۰۰٪ باشد.';return}
 out.replaceChildren();cats.forEach((name,i)=>{const current=100*values[i]/sum,delta=targets[i]-current;const row=document.createElement('p');row.textContent=name+': فعلی '+current.toFixed(1)+'٪ · هدف '+targets[i].toFixed(1)+'٪ · اختلاف '+(delta>=0?'+':'')+delta.toFixed(1)+' واحد درصد';out.append(row)});const note=document.createElement('p');note.textContent='صرفاً محاسبه وزن است؛ هزینه معاملات، مالیات، نقدشوندگی و ریسک همبستگی لحاظ نشده‌اند.';out.append(note)};
 }
 if(lab&&!document.getElementById('atlas-strategy-sandbox')){
 const box=document.createElement('section');box.id='atlas-strategy-sandbox';box.className='atlas-research-tool';
 box.innerHTML='<h3>🧪 Strategy Sandbox — فیلتر پژوهشی</h3><p>آستانه‌های سناریوی پژوهشی را تغییر دهید. این ابزار بک‌تست یا تولید سیگنال واقعی نیست.</p><div class="atlas-tool-grid"><label>حداقل R:R <input id="atlas-sb-rr" type="range" min="1" max="5" step=".25" value="2"><output id="atlas-sb-rr-o">2</output></label><label>حداکثر RSI <input id="atlas-sb-rsi" type="range" min="20" max="80" step="5" value="60"><output id="atlas-sb-rsi-o">60</output></label><label>حداقل Confidence % <input id="atlas-sb-confidence" type="range" min="0" max="100" step="5" value="65"><output id="atlas-sb-confidence-o">65</output></label></div><p id="atlas-sb-state" aria-live="polite"></p>';
 lab.append(box);
 const update=()=>{for(const k of ['rr','rsi','confidence'])document.getElementById('atlas-sb-'+k+'-o').textContent=document.getElementById('atlas-sb-'+k).value;document.getElementById('atlas-sb-state').textContent='فیلترهای انتخابی ثبت شدند؛ تا اتصال به دیتاست معتبر OOS، هیچ نتیجه عملکردی یا سیگنالی محاسبه نمی‌شود.'};
 box.querySelectorAll('input').forEach(x=>x.addEventListener('input',update));update();
 }
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready,{once:true});else ready();
})();