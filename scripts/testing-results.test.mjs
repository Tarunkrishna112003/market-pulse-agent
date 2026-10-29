import test from 'node:test';
import assert from 'node:assert/strict';
import {createTest,extendTest,restoreSavedPredictions,updateTest,cutoffAt} from '../lib/testing-results.mjs';
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

test('October 20 switch uses exact frozen candidate values, preserves October 19 and prior predictions',async()=>{
 const {readFile}=await import('node:fs/promises');
 const {useFrozenOctober20}=await import('../lib/frozen-forecast-migration.mjs');
 const raw=await readFile('data/frozen-forecasts/2026-10-20.json','utf8'),frozen=JSON.parse(raw);
 const state=createTest({sessionDate:'2026-10-16',rows:frozen.entries.map(r=>({symbol:r.symbol,name:r.symbol}))});
 state.entries[0].prediction={percent:1};state.entries[0].actual={percent:2};
 state.entries[25].prediction={percent:.2312,modelVersion:'v7'};
 const migrated=useFrozenOctober20(state,raw,new Date('2026-10-20T19:00:00Z'));
 assert.deepEqual(migrated.entries.slice(0,25),state.entries.slice(0,25));
 assert.equal(migrated.entries[25].prediction.percent,frozen.entries[0].candidatePercent);
 assert.equal(migrated.entries[25].prediction.generatedAt,frozen.generatedAt);
 assert.equal(migrated.entries[25].previousPredictions[0].percent,.2312);
 assert.equal(migrated.entries[25].prediction.originallyPublic,false);
 assert.deepEqual(useFrozenOctober20(migrated,raw,new Date('2026-10-21T19:00:00Z')),migrated);
 assert.throws(()=>useFrozenOctober20(state,raw+' '),/integrity/);
});

test('second week preserves all prior entries and extension is idempotent',()=>{
 const prior=createTest(cohort);prior.entries[0].prediction={percent:3};prior.entries[0].actual={percent:2};
 const extended=extendTest(prior);
 assert.deepEqual(extended.entries.slice(0,125),prior.entries);assert.equal(extended.entries.length,250);
 assert.deepEqual(extended.dates.slice(5),['2026-10-26','2026-10-27','2026-10-28','2026-10-29','2026-10-30']);
 assert.deepEqual(extendTest(extended),extended);assert.equal(prior.entries.length,125);
});
test('history recovery uses saved pre-cutoff forecasts and preserves frozen values',()=>{
 const state=extendTest(createTest(cohort));const row={id:'saved',symbol:'S0',targetDate:'2026-10-26',lookback:365,returnBasis:'open-to-close',generatedAt:'2026-10-23T15:00:00Z',estimatedPercent:2,modelVersion:'existing'};
 const history={records:[{...row,generatedAt:'2026-10-26T12:55:00Z',estimatedPercent:9},row,{...row,symbol:'S1',generatedAt:'2026-10-26T13:00:00Z'},{...row,symbol:'S2',lookback:30},{...row,symbol:'S3',returnBasis:'scan-to-close'}]};
 const now=new Date('2026-10-27T22:00:00Z'),recovered=restoreSavedPredictions(state,history,now);
 assert.equal(restoreSavedPredictions(state,history,new Date('2026-10-26T12:00:00Z')).entries[125].prediction,null);
 assert.equal(recovered.entries[125].prediction.percent,2);assert.equal(recovered.entries[125].prediction.historyId,'saved');
 for(const i of [126,127,128])assert.equal(recovered.entries[i].prediction,null);
 assert.deepEqual(recovered.entries.slice(0,125),state.entries.slice(0,125));
 assert.deepEqual(restoreSavedPredictions(recovered,{records:[{...row,estimatedPercent:99}]},now),recovered);
 const scored=updateTest(recovered,{rows:[]},[{symbol:'S0',daily:[{date:'2026-10-26',open:100,close:103}]}],now);
 assert.equal(scored.entries[125].status,'compared');assert.ok(Math.abs(scored.entries[125].errorPoints-1)<1e-9);
 assert.equal(scored.entries[126].status,'missed-cutoff');
});

test('model activation preserves past records and cannot recover the old model for new dates',()=>{
 const state=extendTest(createTest(cohort)),selection={version:'new-model',activationDate:'2026-10-29'};
 state.entries[0].prediction={percent:3,modelVersion:'original'};
 const row={id:'old',symbol:'S0',targetDate:'2026-10-29',lookback:365,returnBasis:'open-to-close',generatedAt:'2026-10-28T21:00:00Z',estimatedPercent:2,modelVersion:'old-model'};
 const result=restoreSavedPredictions(state,{records:[row,{...row,id:'new',modelVersion:'new-model',estimatedPercent:-1,generatedAt:'2026-10-29T12:00:00Z'}]},new Date('2026-10-29T21:00:00Z'),selection);
 assert.deepEqual(result.entries[0],state.entries[0]);assert.equal(result.entries.find(e=>e.date==='2026-10-29'&&e.symbol==='S0').prediction.percent,-1);
 const oldSnapshot={lookback:365,generatedAt:'2026-10-29T12:00:00Z',modelVersion:'old-model',rows:[{symbol:'S0',state:'estimated',lookback:365,returnBasis:'open-to-close',targetDate:'2026-10-29',estimatedPercent:9}]};
 const capture=updateTest(state,oldSnapshot,[],new Date('2026-10-29T12:30:00Z'),selection);
 assert.equal(capture.entries.find(e=>e.date==='2026-10-29'&&e.symbol==='S0').prediction,null);
});

test('after-open model forecast is separate from the frozen morning test',()=>{
 const state=extendTest(createTest(cohort));const entry=state.entries.find(e=>e.date==='2026-10-29'&&e.symbol==='S0');entry.prediction={percent:2,modelVersion:'old-morning'};
 const source={lookback:365,generatedAt:'2026-10-29T16:00:00Z',modelVersion:'new',rows:[{symbol:'S0',state:'estimated',lookback:365,returnBasis:'open-to-close',targetDate:'2026-10-29',estimatedPercent:-1,modelVersion:'new',generatedAfterOpen:true}]};
 const first=updateTest(state,source,[],new Date('2026-10-29T16:05:00Z'));const row=first.entries.find(e=>e.date==='2026-10-29'&&e.symbol==='S0');
 assert.deepEqual(row.prediction,entry.prediction);assert.equal(row.lateForecasts[0].percent,-1);assert.equal(row.status,'awaiting-close');
 const second=updateTest(first,{...source,rows:[{...source.rows[0],estimatedPercent:9}]},[{symbol:'S0',daily:[{date:'2026-10-29',open:100,close:99}]}],new Date('2026-10-29T22:00:00Z'));
 const scored=second.entries.find(e=>e.date==='2026-10-29'&&e.symbol==='S0');assert.equal(scored.prediction.percent,2);assert.ok(Math.abs(scored.errorPoints-3)<1e-8);assert.ok(scored.lateForecasts[0].errorPoints<1e-8);
});
