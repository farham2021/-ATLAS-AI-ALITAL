'use strict';const {test}=require('node:test'),a=require('node:assert/strict'),x=require('../research/atlas-intelligence.cjs');
test('score evidence gate',()=>{a.equal(x.signalScore({technical:80,volume:70,macro:50,news:60,quality:90}).status,'research_only');a.equal(x.signalScore({technical:80}).status,'insufficient_evidence')});
test('early warning requires observable horizon',()=>{const s=[{id:'1',symbol:'BTC',time:'2026-01-01T00:00:00Z',direction:'up'}],p=[{symbol:'BTC',time:'2026-01-01T00:00:00Z',price:100},{symbol:'BTC',time:'2026-01-02T00:00:00Z',price:105}];a.equal(x.earlyWarningAudit(s,p).hitRate,1);a.equal(x.earlyWarningAudit(s,p,{horizonHours:48}).pending,1)});
test('correlation and portfolio metrics',()=>{a.ok(x.correlation([1,2,3],[2,4,6])>.99);a.equal(x.performance([.01,-.02,.03]).status,'research_only');a.equal(x.performance([]).status,'insufficient_data')});
test('no invented provider fallback',async()=>{const r=x.providerRegistry([{id:'broken',fetch:async()=>{throw Error('offline')}}]);a.equal((await r.get('BTC')).status,'unavailable')});
test('strategy tournament insufficient data',()=>a.equal(x.strategyTournament([],[]).status,'insufficient_out_of_sample'));
