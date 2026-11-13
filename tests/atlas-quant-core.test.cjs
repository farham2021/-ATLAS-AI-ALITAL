'use strict';
const assert=require('node:assert/strict');const {test}=require('node:test');const q=require('../research/quant-core.cjs');
const rows=Array.from({length:90},(_,i)=>{const close=100+i*.3+Math.sin(i/4);return {time:new Date(Date.UTC(2026,0,1,i)).toISOString(),open:close-.1,high:close+1,low:close-1,close,volume:1000+i}});
test('OHLCV validation and chronology',()=>{assert.equal(q.normalizeCandles(rows).length,90);assert.throws(()=>q.normalizeCandles([...rows,rows[0]]));assert.throws(()=>q.normalizeCandles([{...rows[0],high:0}]))});
test('indicator warmup and RSI bounded',()=>{const p=rows.map(x=>x.close);assert.equal(q.rsi(p)[13],null);assert.ok(q.rsi(p)[89]>=0&&q.rsi(p)[89]<=100);assert.ok(q.macd(p)[89].histogram!==null);assert.ok(q.atr(rows)[89]>0)});
test('stale and observed flags',()=>{assert.equal(q.evaluate(rows,{now:Date.parse(rows.at(-1).time)+3600000}).status,'observed');assert.equal(q.evaluate(rows,{now:Date.parse(rows.at(-1).time)+72*3600000}).status,'stale')});
test('backtest costs and drawdown',()=>{const a=q.backtest(rows,{feeBps:0,slippageBps:0}),b=q.backtest(rows,{feeBps:50,slippageBps:10});assert.ok(a.equity>=b.equity);assert.ok(b.maxDrawdownPct>=0);assert.equal(b.status,'research_only')});
