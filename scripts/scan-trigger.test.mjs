import test from 'node:test';
import assert from 'node:assert/strict';
import {morningForecastDate,scanTriggerDecision,triggerDueScan,afterCloseWindow,needsClosingRefresh} from '../lib/github-scan-trigger.mjs';
const completed='2026-10-08T19:10:19Z';
const success={status:'completed',conclusion:'success',display_title:'Scan 2026-10-08T12:00:00.000Z',updated_at:completed};
const threeHours=3*60*60*1000;
test('trigger follows fixed Pacific slots rather than completion intervals',()=>{
 const due=Date.parse('2026-10-08T20:00:00Z');
 assert.equal(scanTriggerDecision([success],due-1).due,false);
 assert.equal(scanTriggerDecision([success],due).due,true);
 assert.equal(scanTriggerDecision([success],due-1).nextScanAt,'2026-10-08T20:00:00.000Z');
 const overlapping={...success,created_at:'2026-10-08T19:00:00Z',updated_at:'2026-10-08T20:30:00Z'};
 assert.equal(scanTriggerDecision([overlapping],Date.parse('2026-10-08T20:31:00Z')).due,true);
 const onTime={...success,display_title:'Scan 2026-10-08T20:00:00.000Z',created_at:'2026-10-08T20:00:00Z',updated_at:'2026-10-08T20:30:00Z'};
 assert.equal(scanTriggerDecision([onTime],Date.parse('2026-10-08T20:31:00Z')).due,false);
});
test('running, pending and queued scans prevent duplicate dispatch',()=>{
 for(const status of ['queued','pending','waiting','requested','in_progress'])assert.equal(scanTriggerDecision([success,{status}],Date.parse(completed)+threeHours*2).due,false);
});
test('unsuccessful scans have a 30-minute retry cooldown',()=>{
 const failed={status:'completed',conclusion:'failure',updated_at:'2026-10-08T23:00:00Z'};
 assert.equal(scanTriggerDecision([success,failed],Date.parse(failed.updated_at)+29*60000).due,false);
 assert.equal(scanTriggerDecision([success,failed],Date.parse(failed.updated_at)+30*60000).due,true);
});
test('no history triggers initial scan and malformed timestamps fail explicitly',()=>{
 assert.equal(scanTriggerDecision([]).due,true);
 assert.throws(()=>scanTriggerDecision([{...success,updated_at:'invalid'}]),/timestamp/);
 assert.throws(()=>scanTriggerDecision([{...success,updated_at:'2100-01-01'}]),/timestamp/);
});
test('due check dispatches the real scanner with public filters',async()=>{
 const calls=[];
 const result=await triggerDueScan({repository:'owner/repo',token:'fixture',now:Date.parse(completed)+threeHours,fetchImpl:async(url,options)=>{calls.push({url,options});return calls.length===1?{ok:true,json:async()=>({workflow_runs:[success]})}:{ok:true,status:204}}});
 assert.equal(result.triggered,true);assert.equal(calls.length,2);assert.match(calls[1].url,/scan-and-publish.yml\/dispatches$/);assert.equal(calls[1].options.method,'POST');assert.deepEqual(JSON.parse(calls[1].options.body),{ref:'main',inputs:{lookback_days:'365',min_cap_b:'20',max_cap_b:'200',min_move:'0',max_move:'5',scheduled_at:'2026-10-08T20:00:00.000Z'}});
});
test('not-due check never dispatches and API errors do not start blind scans',async()=>{
 let calls=0;
 const result=await triggerDueScan({repository:'owner/repo',token:'fixture',now:Date.parse(completed)+60000,fetchImpl:async()=>{calls++;return {ok:true,json:async()=>({workflow_runs:[success]})}}});assert.equal(result.due,false);assert.equal(calls,1);
 await assert.rejects(triggerDueScan({repository:'owner/repo',token:'fixture',fetchImpl:async()=>({ok:false,status:403})}),/history/);
 let requests=0;await assert.rejects(triggerDueScan({repository:'owner/repo',token:'fixture',fetchImpl:async()=>++requests===1?{ok:true,json:async()=>({workflow_runs:[]})}:{ok:false,status:403}}),/trigger/);
});

test('closing freshness follows actual close, DST, holidays and completed training labels',()=>{
 const stale={trainedModels:[{trainingTargetEnd:'2026-11-02'}],rows:[{forecasts:[{state:'estimated',targetDate:'2026-11-03',estimatedPercent:1}]}]};
 const fresh={trainedModels:[{trainingTargetEnd:'2026-11-03'}],rows:[{forecasts:[{state:'estimated',targetDate:'2026-11-04',estimatedPercent:1}]}]};
 assert.equal(afterCloseWindow(Date.parse('2026-11-03T21:14:00Z')),false);
 assert.equal(needsClosingRefresh(stale,Date.parse('2026-11-03T21:17:00Z')),true);
 assert.equal(needsClosingRefresh(fresh,Date.parse('2026-11-03T21:17:00Z')),false);
 assert.equal(afterCloseWindow(Date.parse('2026-10-30T20:17:00Z')),true);
 assert.equal(afterCloseWindow(Date.parse('2026-11-26T21:17:00Z')),false);
 assert.equal(afterCloseWindow(Date.parse('2026-11-27T18:17:00Z')),true);
});

test('stale closing forecasts trigger a guarded retry without exposing GitHub credentials',async()=>{
 const now=Date.parse('2026-11-03T21:47:00Z');
 const early={status:'completed',conclusion:'success',created_at:'2026-11-03T21:00:00Z',updated_at:'2026-11-03T21:05:00Z'};
 const calls=[];
 const result=await triggerDueScan({repository:'owner/repo',token:'fixture',now,checkAfterClose:true,fetchImpl:async(url,options)=>{
  calls.push({url,options});
  if(calls.length===1)return {ok:true,json:async()=>({workflow_runs:[early]})};
  if(calls.length===2)return {ok:true,json:async()=>({rows:[],trainedModels:[]})};
  return {ok:true,status:204};
 }});
 assert.equal(result.triggered,true);assert.equal(calls.length,3);
 assert.match(calls[1].url,/owner.github.io\/repo\/predictions.json/);
 assert.equal(calls[1].options.headers,undefined);
 let requests=0;
 const active=await triggerDueScan({repository:'owner/repo',token:'fixture',now,checkAfterClose:true,fetchImpl:async()=>{requests++;return {ok:true,json:async()=>({workflow_runs:[{status:'in_progress'}]})}}});
 assert.equal(active.triggered,undefined);assert.equal(requests,1);
});

test('the 5 AM Pacific trading scan starts November 19 and qualifies only before the market opens',()=>{
 assert.equal(morningForecastDate('2026-11-18T13:00:00.000Z',Date.parse('2026-11-18T13:05:00Z')),'');
 for(const slot of ['2026-11-19T13:00:00.000Z','2027-03-15T12:00:00.000Z']){
  const time=Date.parse(slot);
  assert.equal(morningForecastDate(slot,time+60000),slot.slice(0,10));
  assert.equal(morningForecastDate(slot,time+90*60000),'');
  assert.equal(morningForecastDate('',time),'');
 }
});

test('the missed morning slot is retried before open and caught up without replacing the afternoon slot',()=>{
 const slot='2026-11-19T13:00:00.000Z';
 const failed={display_title:'Scan '+slot,status:'completed',conclusion:'failure',created_at:slot,updated_at:'2026-11-19T13:10:00Z'};
 assert.equal(scanTriggerDecision([failed],Date.parse('2026-11-19T13:14:59Z')).due,false);
 assert.equal(scanTriggerDecision([failed],Date.parse('2026-11-19T13:15:00Z')).scheduledAt,slot);
 const afternoon=Date.parse('2026-11-19T21:15:00Z');
 assert.equal(scanTriggerDecision([],afternoon).scheduledAt,slot);
 assert.equal(morningForecastDate(slot,afternoon),'');
 const caughtUp={...failed,conclusion:'success',created_at:'2026-11-19T21:03:00Z',updated_at:'2026-11-19T21:14:00Z'};
 assert.equal(scanTriggerDecision([caughtUp],afternoon).scheduledAt,'2026-11-19T21:00:00.000Z');
});
