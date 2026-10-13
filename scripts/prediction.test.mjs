import test from 'node:test';
import assert from 'node:assert/strict';
import {predictStock,priceBacktest,updateLedger,validationSummary,MODEL_VERSION} from '../lib/prediction.mjs';
import {nextTradingDay,sessionExpired,nextForecastSession} from '../lib/trading-calendar.mjs';
import {parseNews,companyMatches,gatherPredictionNews} from '../lib/prediction-news.mjs';
function stock(change=1){let close=100;const days=[];for(let date='2026-08-31';date<='2026-10-09';date=nextTradingDay(date)){close*=1+change/100;days.push({date,close,change})}return {symbol:'ALAB',name:'Astera Labs, Inc. Common Stock',price:close,priceAsOf:'2026-10-12T14:00:00Z',days}}
const now=new Date('2026-10-12T15:00:00Z');
const news=polarity=>({state:'available',headlines:[{title:'Astera Labs funding announcement',url:'https://example.com/news',publishedAt:'2026-10-12T14:00:00Z',sentiment:polarity}]});
test('window uses historical calendar days and forecasts the next session from the current quote',()=>{
 const s=stock();const a=predictStock(s,10,null,now),b=predictStock(s,30,null,now);assert.equal(a.targetDate,'2026-10-13');assert.ok(a.sessions<b.sessions);assert.ok(a.estimatedPercent>0);assert.equal(a.direction,'positive');assert.ok(a.interval.lowerPercent<=a.estimatedPercent&&a.interval.upperPercent>=a.estimatedPercent);assert.equal(a.newsLabel,'not assessed');assert.equal(predictStock(stock(-1),20,null,now).direction,'negative');assert.equal(predictStock(stock(0),20,null,now).direction,'neutral');
 assert.equal(predictStock(s,10,null,new Date('2026-10-12T21:00:00Z')).state,'stale');
});
test('positive and negative assessed headlines shift a volatile forecast with capped influence',()=>{
 const s=stock();s.days=s.days.map((d,i)=>({...d,change:i%2?5:-3}));const base=predictStock(s,20,null,now),positive=predictStock(s,20,news({positive:0.95,negative:0.01,neutral:0.04}),now),negative=predictStock(s,20,news({positive:0.01,negative:0.95,neutral:0.04}),now);assert.ok(positive.estimatedPercent>base.estimatedPercent);assert.ok(negative.estimatedPercent<base.estimatedPercent);assert.ok(Math.abs(Math.log(positive.projectedClose/base.projectedClose))<=0.00500001);assert.equal(positive.newsCount,1);assert.equal(positive.newsLabel,'positive');
 const future=news({positive:1,negative:0,neutral:0});future.headlines[0].publishedAt='2026-10-13T14:00:00Z';assert.equal(predictStock(s,20,future,now).newsCount,0);assert.throws(()=>predictStock(s,20,news({positive:9,negative:0,neutral:0}),now),/sentiment/);
});
test('short or invalid history cannot fabricate an estimate',()=>{
 assert.equal(predictStock({days:stock().days.slice(-2)},10,null,now).state,'insufficient-history');assert.throws(()=>predictStock(stock(),11,null,now));assert.throws(()=>predictStock({days:[{date:'2026-10-09',close:0}]},10,null,now));
});
test('trading session calendar handles weekends and scheduled holidays and early closes',()=>{
 assert.equal(nextTradingDay('2026-07-02'),'2026-07-06');assert.equal(nextTradingDay('2026-04-02'),'2026-04-06');assert.equal(nextTradingDay('2027-12-31'),'2028-01-03');assert.equal(sessionExpired('2026-11-27',new Date('2026-11-27T18:00:00Z')),true);
});
test('ledger scores only previously recorded forecasts and retains first forecast per session',()=>{
 const s=stock(),f=predictStock(s,20,null,now),rows=[{symbol:s.symbol,forecasts:[f]}];let ledger=updateLedger([], [s],rows,now);assert.equal(ledger.length,1);assert.equal(ledger[0].modelVersion,MODEL_VERSION);assert.equal(updateLedger(ledger,[s],rows,now).length,1);
 const actual={...s,days:[...s.days,{date:'2026-10-13',close:f.baseClose*1.02,change:2}]};ledger=updateLedger(ledger,[actual],[],new Date('2026-10-13T21:00:00Z'));assert.ok(Math.abs(ledger[0].actualPercent-2)<1e-9);assert.equal(validationSummary(ledger,20).samples,1);assert.equal(validationSummary(ledger,10).samples,0);
 const tooLate=[{...ledger[0],actualPercent:null,generatedAt:'2026-10-13T21:00:00Z'}];assert.equal(updateLedger(tooLate,[actual],[],new Date('2026-10-13T12:00:00Z'))[0].actualPercent,null);
});
test('rolling backtest compares price-only model to a no-change baseline',()=>{
 const results=priceBacktest(stock(),10);assert.ok(results.samples>0);assert.ok(results.meanAbsoluteError<results.naiveMeanAbsoluteError);assert.equal(results.priceOnly,true);
});
test('RSS parsing ignores future articles, stale items, duplicates and unsafe URLs',()=>{
 const item=(title,date='Mon, 12 Oct 2026 14:00:00 GMT',url='https://example.com/a')=>`<item><title>${title}</title><link>${url}</link><pubDate>${date}</pubDate></item>`;const xml='<rss>'+item('Astera Labs wins contract')+item('Astera Labs wins contract')+item('Astera Labs news','Tue, 13 Oct 2026 14:00:00 GMT')+item('Astera Labs old news','Mon, 01 Jun 2026 14:00:00 GMT')+item('Astera Labs funding',undefined,'javascript:alert(1)')+'</rss>';const parsed=parseNews(xml,'CNBC',now);assert.equal(parsed.length,1);assert.equal(parsed[0].source,'CNBC');assert.equal(companyMatches(stock(),parsed[0].title),true);assert.equal(companyMatches(stock(),'Another company gets funding'),false);assert.equal(companyMatches({symbol:'ON',name:'ON Semiconductor Corporation'},'On Monday another company raised funds'),false);
});
test('free company news sources disclose individual failures',async()=>{
 const result=await gatherPredictionNews([stock()],{now,fetchImpl:async url=>String(url).includes('finance.yahoo')?{ok:true,text:async()=>'<rss><item><title>Astera Labs receives new investment</title><link>https://finance.yahoo.com/news/investment</link><pubDate>Mon, 12 Oct 2026 14:00:00 GMT</pubDate></item></rss>'}:{ok:false,status:503}});assert.equal(result.companies[0].headlines.length,1);assert.equal(result.errors.length,3);
});

test('Prediction page changes historical window and displays sourced evidence and validation',async()=>{
 const {mkdtemp,copyFile,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path'),{pathToFileURL}=await import('node:url');const dir=await mkdtemp(join(tmpdir(),'prediction-page-'));const original={document:globalThis.document,fetch:globalThis.fetch,location:globalThis.location};
 try{await copyFile('github-pages/prediction.js',join(dir,'prediction.mjs'));await copyFile('lib/trading-calendar.mjs',join(dir,'trading-calendar.mjs'));const nodes=new Map();for(const id of ['historyWindow','predictionRows','predictionEvidence','predictionEmpty','validationSummary','predictionStatus'])nodes.set(id,{value:'30',children:[],append(...items){this.children.push(...items)},replaceChildren(){this.children=[]}});globalThis.document={getElementById:id=>nodes.get(id),createElement:()=>({children:[],append(...items){this.children.push(...items)}})};globalThis.location={search:'?history=10'};
 const base={...predictStock(stock(),20,null,now),targetDate:nextForecastSession()};globalThis.fetch=async()=>({ok:true,json:async()=>({state:'experimental',generatedAt:now.toISOString(),scanCreatedAt:now.toISOString(),newsModelState:'available',rows:[{symbol:'ALAB',name:'Astera Labs',headlines:[{title:'Funding story',url:'https://example.com/news',source:'CNBC',publishedAt:now.toISOString(),sentiment:{positive:0.9,negative:0.05,neutral:0.05}}],forecasts:[{...base,lookback:10,estimatedPercent:1},{...base,lookback:30,estimatedPercent:2}]}],validation:[]})});
 await import(pathToFileURL(join(dir,'prediction.mjs')).href);assert.equal(nodes.get('historyWindow').value,'10');assert.equal(nodes.get('predictionRows').children[0].children[4].textContent,'+1.00%');nodes.get('historyWindow').value='30';nodes.get('historyWindow').onchange();assert.equal(nodes.get('predictionRows').children[0].children[4].textContent,'+2.00%');assert.equal(nodes.get('predictionEvidence').children[0].children[2].children[0].textContent,'Funding story');assert.match(nodes.get('validationSummary').textContent,/No completed/);
 }finally{globalThis.document=original.document;globalThis.fetch=original.fetch;globalThis.location=original.location;await rm(dir,{recursive:true,force:true})}
});

test('pre-open predicts upcoming session, open-session forecasts following session, and baseline uses quote',()=>{
 const s=stock();s.price*=1.1;const open=predictStock(s,20,null,now);assert.equal(open.targetDate,'2026-10-13');assert.equal(open.baseClose,s.price);assert.ok(Math.abs(open.projectedClose/s.price-1-open.estimatedPercent/100)<1e-10);assert.ok(open.horizonSessions>1);
 assert.equal(nextForecastSession(new Date('2026-10-12T12:00:00Z')),'2026-10-12');assert.equal(nextForecastSession(new Date('2026-10-12T13:30:00Z')),'2026-10-13');assert.equal(nextForecastSession(new Date('2026-07-02T15:00:00Z')),'2026-07-06');
 const old={...s,priceAsOf:'2026-10-09T20:00:00Z'};assert.equal(predictStock(old,20,null,now).state,'stale');
});
