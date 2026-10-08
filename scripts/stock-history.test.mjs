import test from 'node:test';
import assert from 'node:assert/strict';
import {stockHistory} from '../lib/stock-history.mjs';
const report={end:'2026-10-07',filters:{lookbackDays:30}};
const stock={history:[['2026-09-07',100,2,90,110],['2026-09-08',120,20,110,130],['2026-10-05',130,1,120,140],['2026-10-06',140,7,130,150],['2026-10-07',150,7,140,160]]};
test('selected calendar window controls rows, low/high values and extremes',()=>{
 const month=stockHistory(stock,report,30);assert.equal(month.start,'2026-09-08');assert.equal(month.days.length,4);assert.equal(month.minLow,110);assert.equal(month.maxHigh,160);
 const short=stockHistory(stock,report,2);assert.deepEqual(short.days.map(d=>d.date),['2026-10-06','2026-10-07']);assert.equal(short.minLow,130);assert.equal(short.days[0].high,150);assert.equal(short.days[0].change,7);
 assert.equal(stockHistory(stock,report,1).days.length,1);
});
test('legacy snapshots show missing ranges rather than fabricated close-based values',()=>{
 const legacy=stockHistory({history:[['2026-10-07',150,7]]},report,30);assert.equal(legacy.days[0].low,undefined);assert.equal(legacy.minLow,null);assert.equal(legacy.maxHigh,null);assert.equal(legacy.missingRanges,true);
});
test('local object histories and empty weekend windows are supported',()=>{
 const result=stockHistory({days:[{date:'2026-10-06',low:10,high:20,close:15,change:-2}]},report,2);assert.equal(result.days[0].close,15);assert.equal(result.days[0].low,10);
 assert.equal(stockHistory(stock,{...report,end:'2026-10-04'},1).days.length,0);
});
test('invalid or unavailable lookbacks fail with actionable messages',()=>{
 for(const days of [0,-1,366,1.5,NaN])assert.throws(()=>stockHistory(stock,report,days));
 assert.throws(()=>stockHistory(stock,report,31),/longer lookback/);
});

test('public history page renders selected sessions and keeps back-link filters',async()=>{
 const {mkdtemp,copyFile,rm}=await import('node:fs/promises');const {tmpdir}=await import('node:os');const {join}=await import('node:path');const {pathToFileURL}=await import('node:url');
 const dir=await mkdtemp(join(tmpdir(),'stock-history-page-'));const original={document:globalThis.document,location:globalThis.location,fetch:globalThis.fetch};
 try{
 await copyFile('lib/stock-history.mjs',join(dir,'stock-history.mjs'));await copyFile('github-pages/stock.js',join(dir,'stock.mjs'));
 const nodes=new Map();for(const id of ['back','title','window','status','historyRows','empty'])nodes.set(id,{textContent:'',children:[],append(...items){this.children.push(...items)}});
 globalThis.document={getElementById:id=>nodes.get(id),createElement:()=>({children:[],append(...items){this.children.push(...items)}})};
 globalThis.location={search:'?symbol=TEST&days=2&report=old&minCap=20&maxCap=100&minMove=0&maxMove=5'};
 globalThis.fetch=async()=>({ok:true,json:async()=>({report:{...report,id:'new',createdAt:'2026-10-07T22:00:00Z'},stocks:[{...stock,symbol:'TEST',name:'Test Company'}]})});
 await import(pathToFileURL(join(dir,'stock.mjs')).href);
 const rows=nodes.get('historyRows').children;assert.equal(rows.length,2);assert.equal(rows[0].children[0].textContent,'2026-10-06');assert.equal(rows[0].children[1].children[0].textContent,'$130.00');assert.equal(rows[1].children[2].children[0].textContent,'$160.00');assert.match(nodes.get('back').href,/days=2/);assert.doesNotMatch(nodes.get('back').href,/symbol=/);assert.match(nodes.get('status').textContent,/snapshot has updated/);
 }finally{globalThis.document=original.document;globalThis.location=original.location;globalThis.fetch=original.fetch;await rm(dir,{recursive:true,force:true})}
});
