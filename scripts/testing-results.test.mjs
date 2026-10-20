import test from 'node:test';
import assert from 'node:assert/strict';
import {createTest,updateTest,cutoffAt} from '../lib/testing-results.mjs';
const cohort={sessionDate:'2026-10-16',rows:Array.from({length:25},(_,i)=>({symbol:'S'+i,name:'Stock '+i}))};
const snapshot=(percent=2)=>({reportId:'published',modelVersion:'annual',generatedAt:'2026-10-19T11:30:00Z',lookback:365,rows:[{symbol:'S0',state:'estimated',lookback:365,returnBasis:'open-to-close',targetDate:'2026-10-19',estimatedPercent:percent}]});
test('test keeps a fixed set of 25 for the requested week, even if deployment is late',()=>{
 const state=createTest(cohort,new Date('2026-10-18T20:00:00Z'));
 assert.deepEqual(state.dates,['2026-10-19','2026-10-20','2026-10-21','2026-10-22','2026-10-23']);assert.equal(state.entries.length,125);
 assert.deepEqual(createTest(cohort,new Date('2026-10-20T20:00:00Z')).dates,state.dates);
 assert.throws(()=>createTest({...cohort,rows:cohort.rows.slice(0,24)}),/25 stocks/);
});
test('first published morning prediction is frozen and cannot be overwritten or backfilled',()=>{
 let state=createTest(cohort,new Date('2026-10-18T20:00:00Z'));
 state=updateTest(state,snapshot(),[],new Date('2026-10-19T12:05:00Z'));
 assert.equal(state.entries[0].prediction.percent,2);assert.equal(state.entries[0].prediction.observedAt,'2026-10-19T12:05:00.000Z');
 state=updateTest(state,snapshot(9),[],new Date('2026-10-19T12:40:00Z'));assert.equal(state.entries[0].prediction.percent,2);
 const late={...snapshot(),rows:[...snapshot().rows,{...snapshot().rows[0],symbol:'S1'}]};
 state=updateTest(state,late,[],new Date('2026-10-19T13:00:00Z'));
 assert.equal(state.entries[1].prediction,null);assert.equal(state.entries[1].status,'missed-cutoff');
});
test('only target-day, one-year, published-before-cutoff values qualify',()=>{
 const state=createTest(cohort);let result=updateTest(state,snapshot(),[],new Date('2026-10-18T20:00:00Z'));assert.equal(result.entries[0].prediction,null);
 result=updateTest(state,{...snapshot(),generatedAt:'2026-10-19T14:00:00Z'},[],new Date('2026-10-19T12:05:00Z'));assert.equal(result.entries[0].prediction,null);
 result=updateTest(state,{...snapshot(),lookback:30},[],new Date('2026-10-19T12:05:00Z'));assert.equal(result.entries[0].prediction,null);
});
test('actual comparison waits for close and uses close divided by open, not latest quote',()=>{
 let state=updateTest(createTest(cohort),snapshot(),[],new Date('2026-10-19T12:05:00Z'));
 const prices=[{symbol:'S0',daily:[{date:'2026-10-19',open:200,close:206}]}];
 state=updateTest(state,snapshot(9),prices,new Date('2026-10-19T18:00:00Z'));assert.equal(state.entries[0].actual,null);
 state=updateTest(state,snapshot(9),prices,new Date('2026-10-19T21:55:00Z'));
 assert.ok(Math.abs(state.entries[0].actual.percent-3)<1e-9);assert.ok(Math.abs(state.entries[0].errorPoints-1)<1e-9);assert.equal(state.entries[0].directionCorrect,true);assert.equal(state.entries[0].prediction.percent,2);
});
test('6 AM Pacific cutoff follows daylight and standard time',()=>{
 assert.equal(cutoffAt('2026-10-19'),'2026-10-19T13:00:00.000Z');assert.equal(cutoffAt('2026-11-02'),'2026-11-02T14:00:00.000Z');
});
test('testing page shows the saved number beside actual change and bottom button opens it',async()=>{
 const {mkdtemp,copyFile,readFile,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path'),{pathToFileURL}=await import('node:url');
 const dir=await mkdtemp(join(tmpdir(),'testing-page-'));const savedDocument=globalThis.document,savedFetch=globalThis.fetch;
 try{
  await copyFile('github-pages/testing.js',join(dir,'testing.mjs'));
  let state=updateTest(createTest(cohort),snapshot(),[],new Date('2026-10-19T12:05:00Z'));
  state=updateTest(state,snapshot(9),[{symbol:'S0',daily:[{date:'2026-10-19',open:200,close:206}]}],new Date('2026-10-19T21:55:00Z'));
  const nodes=new Map();for(const id of ['week','testDay','testStatus','testRows'])nodes.set(id,{value:'',children:[],append(...items){this.children.push(...items)},replaceChildren(){this.children=[]}});
  globalThis.document={getElementById:id=>nodes.get(id),createElement:()=>({children:[],append(...items){this.children.push(...items)}})};globalThis.fetch=async()=>({ok:true,json:async()=>state});
  await import(pathToFileURL(join(dir,'testing.mjs')).href);nodes.get('testDay').value='2026-10-19';nodes.get('testDay').onchange();
  assert.equal(nodes.get('testRows').children.length,25);const row=nodes.get('testRows').children[0];assert.equal(row.children[1].textContent,'+2.00%');assert.equal(row.children[2].textContent,'+3.00%');assert.equal(row.children[3].textContent,'1.00');assert.equal(row.children[4].textContent,'Correct direction');
  const html=await readFile('github-pages/index.html','utf8');assert.match(html,/href="testing.html">Testing results/);assert.ok(html.indexOf('Testing results')>html.indexOf('Report details'));
 }finally{globalThis.document=savedDocument;globalThis.fetch=savedFetch;await rm(dir,{recursive:true,force:true})}
});
