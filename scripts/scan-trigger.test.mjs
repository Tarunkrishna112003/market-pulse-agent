import test from 'node:test';
import assert from 'node:assert/strict';
import {scanTriggerDecision,triggerDueScan} from '../lib/github-scan-trigger.mjs';
const completed='2026-10-08T19:10:19Z';
const success={status:'completed',conclusion:'success',updated_at:completed};
const threeHours=3*60*60*1000;
test('trigger waits exactly three hours after successful completion',()=>{
 const due=Date.parse(completed)+threeHours;
 assert.equal(scanTriggerDecision([success],due-1).due,false);
 assert.equal(scanTriggerDecision([success],due).due,true);
 assert.equal(scanTriggerDecision([success],due+2*threeHours).due,true);
 assert.equal(scanTriggerDecision([success],due-1).nextScanAt,'2026-10-08T22:10:19.000Z');
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
 assert.equal(result.triggered,true);assert.equal(calls.length,2);assert.match(calls[1].url,/scan-and-publish.yml\/dispatches$/);assert.equal(calls[1].options.method,'POST');assert.deepEqual(JSON.parse(calls[1].options.body),{ref:'main',inputs:{lookback_days:'30',min_cap_b:'20',max_cap_b:'100',min_move:'0',max_move:'5'}});
});
test('not-due check never dispatches and API errors do not start blind scans',async()=>{
 let calls=0;
 const result=await triggerDueScan({repository:'owner/repo',token:'fixture',now:Date.parse(completed)+60000,fetchImpl:async()=>{calls++;return {ok:true,json:async()=>({workflow_runs:[success]})}}});assert.equal(result.due,false);assert.equal(calls,1);
 await assert.rejects(triggerDueScan({repository:'owner/repo',token:'fixture',fetchImpl:async()=>({ok:false,status:403})}),/history/);
 let requests=0;await assert.rejects(triggerDueScan({repository:'owner/repo',token:'fixture',fetchImpl:async()=>++requests===1?{ok:true,json:async()=>({workflow_runs:[]})}:{ok:false,status:403}}),/trigger/);
});
