import test from 'node:test';import assert from 'node:assert/strict';import {calculate,dates,makeReport} from '../lib/screener.mjs';
const s={symbol:'TEST',companyName:'Test',marketCap:20e9},w={start:'2026-09-01',end:'2026-09-30'};
test('opposing moves do not cancel and pre-window close is used',()=>{const r=calculate(s,[{date:'2026-08-31',close:100},{date:'2026-09-01',close:110},{date:'2026-09-02',close:99}],w);assert.ok(Math.abs(r.average-10)<1e-9);assert.ok(Math.abs(r.signedAverage)<1e-9);assert.equal(r.largeDays,2)});
test('30 calendar days across month boundary',()=>assert.deepEqual(dates(new Date('2026-10-05T22:00:00Z')),{start:'2026-09-06',end:'2026-10-05',baseline:'2026-08-27'}));
test('missing baseline is rejected',()=>assert.throws(()=>calculate(s,[{date:'2026-09-01',close:100},{date:'2026-09-02',close:105}],w)));
test('rank and threshold return only top 25 and flag incomplete coverage',()=>{const a=Array.from({length:30},(_,i)=>({symbol:'T'+i,average:i}));const r=makeReport(a,[{symbol:'FAIL'}],w,31);assert.equal(r.stocks.length,25);assert.equal(r.stocks[0].average,29);assert.equal(r.qualifying,25);assert.equal(r.complete,false);assert.equal(r.scanned,30)});
