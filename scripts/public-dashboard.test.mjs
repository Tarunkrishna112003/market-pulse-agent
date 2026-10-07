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
 const nodes=new Map();for(const id of ['minCap','maxCap','minMove','maxMove','days','rows','newsRows','status','details','count','empty','topCsv','allCsv','filters'])nodes.set(id,{value:'',textContent:'',children:[],replaceChildren(){this.children=[]},append(...items){this.children.push(...items)}});
 globalThis.document={getElementById:id=>nodes.get(id)||null,createElement:()=>({children:[],click(){},append(...items){this.children.push(...items)}})};
 globalThis.fetch=async()=>({ok:true,json:async()=>({report:{filters:{minMarketCap:20e9,maxMarketCap:100e9,minAverage:5,maxAverage:null,lookbackDays:30},end:'2026-10-06',createdAt:'2026-10-06T20:00:00Z',scanned:2,total:2,errors:[],sources:['fixture'],complete:true,marketNews:{state:'available',items:[{title:'Company announces investment',url:'https://finance.yahoo.com/news/investment',category:'Investment / funding',publishedAt:'2026-10-06T19:00:00Z'}]}},stocks:[{symbol:'LOW',name:'Low movement',marketCap:30e9,history:[['2026-10-05',100,2]]},{symbol:'HIGH',name:'High movement',marketCap:30e9,history:[['2026-10-05',100,6]]}]})});
 await import(pathToFileURL(join(dir,'app.mjs')).href);
 assert.equal(nodes.get('minMove').value,0);assert.equal(nodes.get('maxMove').value,5);assert.equal(nodes.get('rows').children.length,1);assert.match(nodes.get('status').textContent,/Scan complete/);assert.doesNotThrow(()=>nodes.get('topCsv').onclick());
 nodes.get('minMove').value='3';nodes.get('filters').onsubmit({preventDefault(){}});assert.equal(nodes.get('rows').children.length,0);assert.equal(nodes.get('newsRows').children.length,1);assert.equal(nodes.get('newsRows').children[0].children[1].children[0].textContent,'Company announces investment');
 const html=await readFile('github-pages/index.html','utf8');assert.match(html,/app\.js\?v=/);
 }finally{globalThis.document=savedDocument;globalThis.fetch=savedFetch;await rm(dir,{recursive:true,force:true})}
});
