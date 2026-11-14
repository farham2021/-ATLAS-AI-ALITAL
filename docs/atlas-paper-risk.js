/* ATLAS isolated paper risk ledger. Never submits orders. */
(()=>{'use strict';const $=id=>document.getElementById(id),KEY='atlas-paper-risk-v3';
let ledger;try{ledger=JSON.parse(localStorage.getItem(KEY))}catch{}if(!ledger||!Array.isArray(ledger.positions))ledger={positions:[]};
const num=id=>Number($(id).value),money=n=>Number(n).toFixed(2);
function calculate(){
 const equity=num('ar-equity'),risk=num('ar-risk'),entry=num('ar-entry'),stop=num('ar-stop'),target=num('ar-target'),lev=num('ar-lev');
 const side=$('side').value==='buy'?'LONG':'SHORT';
 if(![equity,risk,entry,stop,target,lev].every(x=>Number.isFinite(x)&&x>0)||risk>1.5||lev>3||lev<1)throw Error('ورودی نامعتبر؛ سقف ریسک ۱.۵٪ و اهرم ۳ است');
 if(side==='LONG'&&!(stop<entry&&target>entry)||side==='SHORT'&&!(stop>entry&&target<entry))throw Error('جهت Stop/Target با معامله سازگار نیست');
 const unitRisk=Math.abs(entry-stop),qty=equity*risk/100/unitRisk,notional=qty*entry,margin=notional/lev;
 if(margin>equity)throw Error('مارجین موردنیاز بیشتر از سرمایه است؛ حد ضرر یا ریسک را اصلاح کنید');
 const reward=qty*Math.abs(target-entry),loss=qty*unitRisk;
 return {side,equity,risk,entry,stop,target,lev,qty,notional,margin,loss,reward,rr:reward/loss};
}
function liquidation(x){
 const mmr=num('ar-mmr')/100,fee=num('ar-fee')/100,deduction=num('ar-deduction'),extra=num('ar-extra');
 if($('ar-mmr').value===''||$('ar-fee').value==='')return null;
 if(![mmr,fee,deduction,extra].every(Number.isFinite)||mmr<0||mmr>=1||fee<0||fee>=1||deduction<0||extra<0)throw Error('Invalid maintenance/fee inputs');
 // USDT linear isolated margin; exchange tier values supplied by user, not verified.
 const numerator=x.notional*(1+(x.side==='LONG'?-1:1)/x.lev)+(x.side==='LONG'?-1:1)*(extra/(1+(x.side==='LONG'?-1:1)*fee)+deduction);
 const denominator=x.qty*(1+(x.side==='LONG'?-1:1)*mmr);
 return numerator/denominator;
}
function preview(){try{const x=calculate();$('ar-result').textContent='Qty '+x.qty.toFixed(6)+' | Notional $'+money(x.notional)+' | Margin $'+money(x.margin)+' | Max planned stop loss $'+money(x.loss)+' | R:R 1:'+x.rr.toFixed(2)+' | Liquidation: not estimated (exchange-specific maintenance margin required)';const liq=liquidation(x);if(liq!==null){$('ar-result').textContent+=' | Conditional isolated liquidation {$('ar-result').textContent=e.message;return null}}
function persist(){localStorage.setItem(KEY,JSON.stringify(ledger));render()}
function render(){const closed=ledger.positions.filter(x=>x.status==='CLOSED'),wins=closed.filter(x=>x.pnl>0).length,pnl=closed.reduce((a,x)=>a+x.pnl,0),open=ledger.positions.filter(x=>x.status==='OPEN');$('ar-stats').textContent='Open '+open.length+' | Closed '+closed.length+' | Win rate '+(closed.length?(wins/closed.length*100).toFixed(1):'—')+'% | Realized PnL $'+money(pnl)+' (fees/funding excluded)';
 const body=$('ar-positions');body.replaceChildren();for(const x of ledger.positions){const tr=document.createElement('tr');for(const value of [x.symbol,x.side,money(x.entry),x.qty.toFixed(6),money(x.stop)+' / '+money(x.target),x.status==='CLOSED'?('Manual close: $'+money(x.pnl)):x.status]){const td=document.createElement('td');td.textContent=value;tr.append(td)}
 const td=document.createElement('td');if(x.status==='OPEN'){const btn=document.createElement('button');btn.textContent='Close manually';btn.onclick=()=>{const raw=prompt('Actual simulated exit price (manual; no TP/SL execution claim):');if(raw===null)return;const price=Number(raw);if(!Number.isFinite(price)||price<=0)return alert('Invalid exit price');x.pnl=(x.side==='LONG'?price-x.entry:x.entry-price)*x.qty;x.exit=price;x.status='CLOSED';x.closedAt=new Date().toISOString();persist()};td.append(btn)}tr.append(td);body.append(tr)}}
$('ar-calc').onclick=preview;$('ar-open').onclick=()=>{const x=preview();if(!x)return;const reserved=ledger.positions.filter(p=>p.status==='OPEN').reduce((a,p)=>a+p.margin,0);if(reserved+x.margin>x.equity)return alert('Insufficient free simulated margin');ledger.positions.unshift({...x,symbol:$('symbol').value,status:'OPEN',openedAt:new Date().toISOString(),id:Date.now()});persist()};
for(const id of ['ar-equity','ar-risk','ar-entry','ar-stop','ar-target','ar-lev','ar-mmr','ar-fee','ar-deduction','ar-extra','side'])$(id).addEventListener('change',preview);
render();preview();
})();+money(liq)+' (user-supplied tier; fees/funding/mark-price may differ)'}return x}catch(e){$('ar-result').textContent=e.message;return null}}
function persist(){localStorage.setItem(KEY,JSON.stringify(ledger));render()}
function render(){const closed=ledger.positions.filter(x=>x.status==='CLOSED'),wins=closed.filter(x=>x.pnl>0).length,pnl=closed.reduce((a,x)=>a+x.pnl,0),open=ledger.positions.filter(x=>x.status==='OPEN');$('ar-stats').textContent='Open '+open.length+' | Closed '+closed.length+' | Win rate '+(closed.length?(wins/closed.length*100).toFixed(1):'—')+'% | Realized PnL $'+money(pnl)+' (fees/funding excluded)';
 const body=$('ar-positions');body.replaceChildren();for(const x of ledger.positions){const tr=document.createElement('tr');for(const value of [x.symbol,x.side,money(x.entry),x.qty.toFixed(6),money(x.stop)+' / '+money(x.target),x.status==='CLOSED'?('Manual close: $'+money(x.pnl)):x.status]){const td=document.createElement('td');td.textContent=value;tr.append(td)}
 const td=document.createElement('td');if(x.status==='OPEN'){const btn=document.createElement('button');btn.textContent='Close manually';btn.onclick=()=>{const raw=prompt('Actual simulated exit price (manual; no TP/SL execution claim):');if(raw===null)return;const price=Number(raw);if(!Number.isFinite(price)||price<=0)return alert('Invalid exit price');x.pnl=(x.side==='LONG'?price-x.entry:x.entry-price)*x.qty;x.exit=price;x.status='CLOSED';x.closedAt=new Date().toISOString();persist()};td.append(btn)}tr.append(td);body.append(tr)}}
$('ar-calc').onclick=preview;$('ar-open').onclick=()=>{const x=preview();if(!x)return;const reserved=ledger.positions.filter(p=>p.status==='OPEN').reduce((a,p)=>a+p.margin,0);if(reserved+x.margin>x.equity)return alert('Insufficient free simulated margin');ledger.positions.unshift({...x,symbol:$('symbol').value,status:'OPEN',openedAt:new Date().toISOString(),id:Date.now()});persist()};
for(const id of ['ar-equity','ar-risk','ar-entry','ar-stop','ar-target','ar-lev','side'])$(id).addEventListener('change',preview);
render();preview();
})();