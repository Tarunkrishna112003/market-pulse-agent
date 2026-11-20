import test from 'node:test';import assert from 'node:assert/strict';import {nextScanTime,scanDue,scanPresentation} from '../lib/scan-status.mjs';
test('Pacific daily slots include summer, winter, midnight and DST changes',()=>{
 for(const [start,expected] of [
  ['2026-10-06T18:00:00Z','2026-10-06T20:00:00.000Z'],
  ['2026-10-06T20:00:00Z','2026-10-07T00:00:00.000Z'],
  ['2026-10-07T04:00:00Z','2026-10-07T12:00:00.000Z'],
  ['2026-12-06T20:00:00Z','2026-12-06T21:00:00.000Z'],
  ['2026-03-08T05:00:00Z','2026-03-08T12:00:00.000Z'],
  ['2026-11-01T04:00:00Z','2026-11-01T13:00:00.000Z']])assert.equal(nextScanTime(Date.parse(start)),expected);
 const next=nextScanTime(Date.parse('2026-10-06T18:00:00Z'));
 assert.equal(scanDue(next,Date.parse(next)-1),false);
 assert.equal(scanDue(next,Date.parse(next)),true);
 assert.equal(scanDue('bad'),false);
});
test('finished numeric scan displays results while AI continues',()=>{const display=scanPresentation({state:'running',phase:'LLM reviewing every company',discovered:3523,pricesScanned:3523},true);assert.equal(display.title,'Scan complete — results below');assert.equal(display.priceRunning,false);assert.equal(scanPresentation({state:'running',discovered:3523,pricesScanned:1,scanCompletedAt:null},true).priceRunning,true)});
