import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,copyFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {nextForecastSession} from '../lib/trading-calendar.mjs';
test('public dashboard loads without removed link and initializes movement filters to 0–5%',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'public-dashboard-'));const savedDocument=globalThis.document,savedFetch=globalThis.fetch;
 try{
 for(const file of ['filters.mjs','csv-report.mjs','trading-calendar.mjs'])await copyFile('lib/'+file,join(dir,file));await copyFile('github-pages/app.js',join(dir,'app.mjs'));
 const nodes=new Map();for(const id of ['minCap','maxCap','minMove','maxMove','days','rows','newsRows','status','details','count','empty','topCsv','allCsv','filters'])nodes.set(id,{value:'',textContent:'',children:[],replaceChildren(){this.children=[]},append(...items){this.children.push(...items)}});
 globalThis.document={getElementById:id=>nodes.get(id)||null,createElement:()=>({children:[],click(){},append(...items){this.children.push(...items)}})};
 globalThis.fetch=async url=>String(url)==='predictions.json'?{ok:true,json:async()=>({reportId:'fixture',rows:[{symbol:'OUTSIDE',forecasts:[{lookback:365,state:'estimated',forecastModel:'supervised',returnBasis:'open-to-close',targetDate:nextForecastSession(),estimatedPercent:0.81}]},{symbol:'LOW',forecasts:[{lookback:18,state:'estimated',forecastModel:'supervised',returnBasis:'scan-to-close',validationPassed:true,targetDate:nextForecastSession(),estimatedPercent:9},{lookback:17,state:'estimated',forecastModel:'supervised',returnBasis:'open-to-close',validationPassed:false,targetDate:nextForecastSession(),estimatedPercent:-0.73},{lookback:365,state:'estimated',forecastModel:'supervised',returnBasis:'open-to-close',validationPassed:true,targetDate:nextForecastSession(),estimatedPercent:1.23}]}]})}:({ok:true,json:async()=>({report:{id:'fixture',filters:{minMarketCap:20e9,maxMarketCap:100e9,minAverage:5,maxAverage:null,lookbackDays:30},end:'2026-10-06',createdAt:'2026-10-06T20:00:00Z',scanned:2,total:2,errors:[],sources:['fixture'],complete:true,marketNews:{state:'available',items:[{title:'Company announces investment',url:'https://finance.yahoo.com/news/investment',category:'Investment / funding',publishedAt:'2026-10-06T19:00:00Z'}]}},stocks:[{symbol:'OUTSIDE',name:'Outside original cap range',marketCap:1e9,price:10,history:[['2026-10-05',10,1]]},{symbol:'LOW',name:'Low movement',marketCap:30e9,price:100,history:[['2026-10-05',100,2]]},{symbol:'HIGH',name:'High movement',marketCap:30e9,price:100,history:[['2026-10-05',100,6]]}]})});
 await import(pathToFileURL(join(dir,'app.mjs')).href);
 assert.equal(nodes.get('minMove').value,0);assert.equal(nodes.get('maxMove').value,5);assert.equal(nodes.get('rows').children.length,1);assert.equal(nodes.get('rows').children[0].children[4].children[0].textContent,'+1.23%');assert.equal(nodes.get('rows').children[0].children[4].children[1].textContent,nextForecastSession());assert.match(nodes.get('rows').children[0].children[0].children[0].href,/stock.html\?symbol=LOW&days=30/);assert.equal(nodes.get('rows').children[0].children[1].textContent,'$100.00');assert.equal(nodes.get('rows').children[0].children[5].textContent,'$30.00B');assert.match(nodes.get('status').textContent,/Scan complete/);assert.doesNotThrow(()=>nodes.get('topCsv').onclick());
 nodes.get('days').value='17';nodes.get('filters').onsubmit({preventDefault(){}});assert.equal(nodes.get('rows').children[0].children[4].children[0].textContent,'+1.23%');assert.match(nodes.get('rows').children[0].children[4].children[0].title,/365 calendar days/);assert.equal(nodes.get('rows').children[0].children[4].children.length,2);assert.equal(nodes.get('rows').children[0].children[4].children[0].href,undefined);nodes.get('days').value='18';nodes.get('filters').onsubmit({preventDefault(){}});assert.equal(nodes.get('rows').children[0].children[4].children[0].textContent,'+1.23%');nodes.get('days').value='30';nodes.get('minCap').value='0';nodes.get('filters').onsubmit({preventDefault(){}});assert.equal(nodes.get('rows').children.length,2);assert.equal(nodes.get('rows').children[1].children[4].children[0].textContent,'+0.81%');nodes.get('minMove').value='3';nodes.get('filters').onsubmit({preventDefault(){}});assert.equal(nodes.get('rows').children.length,0);assert.equal(nodes.get('newsRows').children.length,1);assert.equal(nodes.get('newsRows').children[0].children[1].children[0].textContent,'Company announces investment');
 const html=await readFile('github-pages/index.html','utf8');assert.match(html,/app\.js\?v=/);assert.match(html,/<th>Company \/ ticker<\/th><th>Current price<\/th>/);assert.doesNotMatch(html,/predictionLink|prediction\.html/);assert.doesNotMatch(html,/<th>#<\/th>/);assert.match(html,/<th>Avg\. daily move ↓<\/th><th>Session open → close<\/th>/);
 }finally{globalThis.document=savedDocument;globalThis.fetch=savedFetch;await rm(dir,{recursive:true,force:true})}
});

test('dashboard always loads annual forecasts while displayed movement filters change',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'full-universe-forecasts-'));const savedDocument=globalThis.document,savedFetch=globalThis.fetch;
 try{
  for(const file of ['filters.mjs','csv-report.mjs','trading-calendar.mjs'])await copyFile('lib/'+file,join(dir,file));await copyFile('github-pages/app.js',join(dir,'app.mjs'));
  const nodes=new Map();for(const id of ['minCap','maxCap','minMove','maxMove','days','rows','newsRows','status','details','count','empty','topCsv','allCsv','filters'])nodes.set(id,{value:'',children:[],replaceChildren(){this.children=[]},append(...items){this.children.push(...items)}});
  globalThis.document={getElementById:id=>nodes.get(id)||null,createElement:()=>({children:[],append(...items){this.children.push(...items)}})};
  const requested=[];
  globalThis.fetch=async url=>{requested.push(String(url));let value;
   if(url==='predictions.json')value={reportId:'universe',tableFiles:[365],rows:[]};
   else if(String(url).startsWith('predictions/')){const period=Number(String(url).match(/\/(\d+)\./)[1]);value={reportId:period===13?'wrong-scan':'universe',lookback:period,rows:[{symbol:'SMALL',lookback:period,state:'estimated',forecastModel:'supervised',returnBasis:'open-to-close',targetDate:nextForecastSession(),estimatedPercent:1.81,estimates:{openToClose:{state:'estimated',estimatedPercent:1.81,targetDate:nextForecastSession()},closeToClose:{state:'estimated',estimatedPercent:-2.41,targetDate:nextForecastSession()}},confidenceStatus:'experimental',validationPassed:false}]}}
   else value={report:{id:'universe',filters:{minMarketCap:0,maxMarketCap:100e9,minAverage:0,maxAverage:5,lookbackDays:17},end:'2026-10-06',createdAt:'2026-10-06T20:00:00Z',scanned:1,total:1,errors:[],sources:['fixture']},stocks:[{symbol:'SMALL',name:'Outside training cohort',marketCap:1e9,price:10,history:[['2026-10-05',10,1]]}]};
   return {ok:true,json:async()=>value};
  };
  await import(pathToFileURL(join(dir,'app.mjs')).href);
  assert.ok(requested.includes('predictions/365.json'));assert.equal(nodes.get('rows').children[0].children[4].children[2].textContent,'Close → close: -2.41%');assert.equal(nodes.get('rows').children[0].children[4].children.length,3);assert.equal(nodes.get('rows').children[0].children[4].children[0].textContent,'+1.81%');
  nodes.get('days').value='13';nodes.get('filters').onsubmit({preventDefault(){}});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(nodes.get('rows').children[0].children[4].children[0].textContent,'+1.81%');assert.equal(requested.filter(url=>url==='predictions/365.json').length,1);assert.ok(!requested.includes('predictions/13.json'));
 }finally{globalThis.document=savedDocument;globalThis.fetch=savedFetch;await rm(dir,{recursive:true,force:true})}
});
