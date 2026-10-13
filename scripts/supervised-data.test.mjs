import test from 'node:test';
import assert from 'node:assert/strict';
import {parseToneTimeline,trainingPrices} from '../lib/supervised-data.mjs';
test('historical news buckets become available only after their complete UTC day',()=>{
 const data={timeline:[{series:'Average Tone',data:[{date:'20261011T000000Z',value:-2},{date:'20261012T000000Z',value:9},{date:'invalid',value:3}]}]};const parsed=parseToneTimeline(data,new Date('2026-10-12T14:00:00Z'));assert.equal(parsed.length,1);assert.equal(parsed[0].tone,-2);assert.equal(parsed[0].availableAt,'2026-10-12T00:00:00.000Z');assert.throws(()=>parseToneTimeline({}),/unavailable/);
});
test('training fetches longer daily prices and intraday observations from free chart feeds',async()=>{
 const requested=[];const result=await trainingPrices('ALAB',{now:new Date('2026-10-12T22:00:00Z'),fetchImpl:async url=>{requested.push(String(url));return {ok:true,json:async()=>({chart:{result:[{timestamp:[Date.parse('2026-10-09T14:30:00Z')/1000],indicators:{quote:[{close:[100],low:[95],high:[105],volume:[5000]}]}}]}})}}});assert.equal(result.daily[0].close,100);assert.equal(result.daily[0].nextSession,'2026-10-12');assert.equal(result.hourly[0].volume,5000);assert.ok(requested.some(u=>u.includes('interval=1d')));assert.ok(requested.some(u=>u.includes('interval=1h')));
});
