import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,copyFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
test('public dashboard loads without removed link and initializes movement filters to 0–5%',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'public-dashboard-'));const savedDocument=globalThis.document,savedFetch=globalThis.fetch;
 try{
 for(const file of ['filters.mjs','csv-report.mjs'])await copyFile('lib/'+file,join(dir,file));await copyFile('github-pages/app.js',join(dir,'app.mjs'));
 const nodes=new Map();for(const id of ['minCap','maxCap','minMove','maxMove','days','rows','newsRows','status','details','count','empty','topCsv','allCsv','filters'])nodes.set(id,{value:'',textContent:'',children:[],replaceChildren(){this.children=[]},append(x){this.children.push(x)}});
 globalThis.document={getElementById:id=>nodes.get(id)||null,createElement:()=>({children:[],append(x){this.children.push(x)}})};
 globalThis.fetch=async()=>({ok:true,json:async()=>({report:{filters:{minMarketCap:20e9,maxMarketCap:100e9,minAverage:5,maxAverage:null,lookbackDays:30},end:'2026-10-06',createdAt:'2026-10-06T20:00:00Z',scanned:2,total:2,errors:[],sources:['fixture'],complete:true},stocks:[{symbol:'LOW',name:'Low movement',marketCap:30e9,history:[['2026-10-05',100,2]]},{symbol:'HIGH',name:'High movement',marketCap:30e9,history:[['2026-10-05',100,6]]}]})});
 await import(pathToFileURL(join(dir,'app.mjs')).href);
 assert.equal(nodes.get('minMove').value,0);assert.equal(nodes.get('maxMove').value,5);assert.equal(nodes.get('rows').children.length,1);assert.match(nodes.get('status').textContent,/Scan complete/);
 nodes.get('minMove').value='3';nodes.get('filters').onsubmit({preventDefault(){}});assert.equal(nodes.get('rows').children.length,0);
 const html=await readFile('github-pages/index.html','utf8');assert.match(html,/app\.js\?v=/);
 }finally{globalThis.document=savedDocument;globalThis.fetch=savedFetch;await rm(dir,{recursive:true,force:true})}
});
