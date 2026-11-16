/* ATLAS Quant Risk v4 — client-side, research-only. Input: chronologically ordered CLOSED candles. */
export const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function ema(a,n){let x=a.slice(0,n).reduce((s,v)=>s+v,0)/n;for(let i=n;i<a.length;i++)x+=(2/(n+1))*(a[i]-x);return x}
function atrWilder(c){const tr=[];for(let i=1;i<c.length;i++)tr.push(Math.max(c[i].high-c[i].low,Math.abs(c[i].high-c[i-1].close),Math.abs(c[i].low-c[i-1].close)));let x=tr.slice(0,14).reduce((a,b)=>a+b,0)/14;for(const v of tr.slice(14))x=(13*x+v)/14;return {atr:x,atrLong:tr.slice(-50).reduce((a,b)=>a+b,0)/50}}
function valid(c,n){return Array.isArray(c)&&c.length>=n&&c.every((x,i)=>["close","high","low","volume"].every(k=>Number.isFinite(x[k]))&&x.close>0&&x.high>=x.low&&x.volume>=0&&(!i||x.time==null||c[i-1].time==null||x.time>c[i-1].time))}
export function calculateImprovedRisk(c4,d1){
 if(!valid(c4,250))throw Error("250 valid closed 4H candles required");
 if(d1!=null&&!valid(d1,200))throw Error("200 valid closed daily candles required");
 const c=c4.map(x=>x.close),v=c4.map(x=>x.volume),p=c.at(-1),e=ema(c,200),oldE=ema(c.slice(0,-1),200);
 let gain=0,loss=0;for(let i=1;i<=14;i++){gain+=Math.max(c[i]-c[i-1],0);loss+=Math.max(c[i-1]-c[i],0)}gain/=14;loss/=14;
 for(let i=15;i<c.length;i++){gain=(13*gain+Math.max(c[i]-c[i-1],0))/14;loss=(13*loss+Math.max(c[i-1]-c[i],0))/14}
 const rsi=gain===0&&loss===0?50:loss===0?100:100-100/(1+gain/loss);
 const {atr,atrLong}=atrWilder(c4),volRatio=atrLong>0?atr/atrLong:1,regime=volRatio>=1.6?"High":volRatio<=.7?"Low":"Normal";
 const last=c.slice(-20),mean=last.reduce((a,b)=>a+b,0)/20,sd=Math.sqrt(last.reduce((a,b)=>a+(b-mean)**2,0)/20),pb=sd===0?.5:(p-(mean-2*sd))/(4*sd);
 const previous=v.slice(-21,-1),avg=previous.reduce((a,b)=>a+b,0)/20,volStrength=avg>0?v.at(-1)/avg:null;
 const dist=(p/e-1)*100,trend=clamp(Math.abs(dist)/12,0,1),momentum=clamp(Math.abs(rsi-50)/50,0,1);
 const dailyBias=d1?(d1.at(-1).close>ema(d1.map(x=>x.close),200)?1:-1):null;
 const mtf=dailyBias==null?.5:(dailyBias===(p>e?1:-1)?.85:.25);
 const weights={trend:.25,momentum:.20,volatility:.20,meanReversion:.15,volume:.10,mtf:.10};
 if(regime==="High"){weights.volatility=.30;weights.trend=.18;weights.momentum=.15}
 if(regime==="Low"){weights.trend=.30;weights.volatility=.12}
 const total=Object.values(weights).reduce((a,b)=>a+b,0);for(const k in weights)weights[k]/=total;
 const components={trend,momentum,volatility:clamp(volRatio/2,0,1),meanReversion:clamp(Math.abs(pb-.5)*2,0,1),volume:volStrength==null?null:clamp(Math.abs(volStrength-1),0,1),mtf:1-mtf};
 const active=Object.keys(weights).filter(k=>components[k]!=null),den=active.reduce((s,k)=>s+weights[k],0);
 const riskScore=Math.round(100*active.reduce((s,k)=>s+weights[k]*components[k],0)/den);
 const biasScore=Math.round(clamp((dist/8*.6+(rsi-50)/50*.4)*100,-100,100));
 return {status:"RESEARCH_UNVALIDATED",riskScore,biasScore,regime,price:p,ema200:e,emaSlope:e-oldE,rsi,atr,atrPercent:atr/p*100,percentB:pb,volRatio,volumeStrength:volStrength,mtfAlignment:mtf,weights,components};
}
export function calculateRR(entry,stop,target,side="long"){
 if(![entry,stop,target].every(x=>Number.isFinite(x)&&x>0)||!["long","short"].includes(side)||!(side==="long"?stop<entry&&target>entry:stop>entry&&target<entry))throw Error("Invalid directional stop or target");
 const risk=Math.abs(entry-stop),reward=Math.abs(target-entry);return {risk,reward,rr:reward/risk,isGood:reward/risk>=1.5};
}
export function calculatePositionSize({equity,riskPercent=1,entry,stop,leverage=1,side="long",feeRate=.0006,slippageRate=.0005,openRiskAmount=0,maxPortfolioRiskPercent=6}){
 if(![equity,riskPercent,entry,stop,leverage,feeRate,slippageRate,openRiskAmount,maxPortfolioRiskPercent].every(Number.isFinite)||equity<=0||riskPercent<=0||riskPercent>1.5||leverage<1||leverage>3||feeRate<0||slippageRate<0||openRiskAmount<0||!(side==="long"?stop<entry:side==="short"&&stop>entry))throw Error("Invalid risk parameters");
 const budget=Math.max(0,Math.min(equity*riskPercent/100,equity*maxPortfolioRiskPercent/100-openRiskAmount));
 const unitRisk=Math.abs(entry-stop)+2*entry*(feeRate+slippageRate);
 const qty=Math.min(budget/unitRisk,equity*leverage/entry);
 return {size:qty,notional:qty*entry,plannedRiskAmount:qty*unitRisk,actualRiskPercent:100*qty*unitRisk/equity,estimatedRoundTripCost:qty*2*entry*(feeRate+slippageRate),assumptions:{feeRate,slippageRate,notRealFill:true}};
}
export function journalStats(trades){
 const closed=trades.filter(t=>t.status==="CLOSED"&&Number.isFinite(t.netPnl)&&Number.isFinite(t.initialRisk)&&t.initialRisk>0);
 if(!closed.length)return {count:0,winRate:null,profitFactor:null,avgNetR:null,netPnl:0,maxDrawdown:null};
 const pnl=closed.map(t=>t.netPnl),wins=pnl.filter(x=>x>0).reduce((a,b)=>a+b,0),losses=-pnl.filter(x=>x<0).reduce((a,b)=>a+b,0);
 let eq=0,peak=0,dd=0;for(const x of pnl){eq+=x;peak=Math.max(peak,eq);dd=Math.max(dd,peak-eq)}
 return {count:pnl.length,winRate:pnl.filter(x=>x>0).length/pnl.length,profitFactor:losses?wins/losses:null,avgNetR:closed.reduce((s,t)=>s+t.netPnl/t.initialRisk,0)/closed.length,netPnl:eq,maxDrawdownAmount:dd};
}
