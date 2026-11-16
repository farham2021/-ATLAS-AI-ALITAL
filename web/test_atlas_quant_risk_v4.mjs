import assert from "node:assert/strict";
import {calculateImprovedRisk,calculateRR,calculatePositionSize,journalStats} from "./atlas_quant_risk_v4.mjs";
const bars=Array.from({length:260},(_,i)=>({time:i,close:100+i*.1,high:101+i*.1,low:99+i*.1,volume:100+i%10}));
const r=calculateImprovedRisk(bars,bars);assert.equal(r.status,"RESEARCH_UNVALIDATED");assert.ok(r.riskScore>=0&&r.riskScore<=100);assert.ok(r.biasScore>=-100&&r.biasScore<=100);assert.ok(Math.abs(Object.values(r.weights).reduce((a,b)=>a+b,0)-1)<1e-10);
assert.throws(()=>calculateRR(100,110,120,"long"));assert.equal(calculateRR(100,95,110,"long").rr,2);
const p=calculatePositionSize({equity:10000,entry:100,stop:95,side:"long",riskPercent:1,leverage:3});assert.ok(p.plannedRiskAmount<=100.00001);assert.ok(p.notional<=30000);
assert.throws(()=>calculatePositionSize({equity:10000,entry:100,stop:95,side:"long",riskPercent:2}));
const j=journalStats([{status:"CLOSED",netPnl:10,initialRisk:5},{status:"CLOSED",netPnl:-5,initialRisk:5}]);assert.equal(j.profitFactor,2);assert.equal(j.avgNetR,.5);
console.log("ATLAS Quant Risk V4 JS tests passed");
