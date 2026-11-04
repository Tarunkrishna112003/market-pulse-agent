import test,{after} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,copyFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const dir=await mkdtemp(join(tmpdir(),'market-dashboard-data-'));
for(const [source,name] of [['github-pages/dashboard-data.mjs','dashboard-data.mjs'],['github-pages/exchange.mjs','exchange.mjs'],['lib/filters.mjs','filters.mjs'],['lib/stock-history.mjs','stock-history.mjs'],['lib/trading-calendar.mjs','trading-calendar.mjs']])await copyFile(source,join(dir,name));
const {parseRanges,movementRows,predictionRows,searchStocks,indexSearchResult,historyView,testDayView,csvText,stockPredictionView,exchangeLabel,tickerLabel}=await import(pathToFileURL(join(dir,'dashboard-data.mjs')).href);
after(()=>rm(dir,{recursive:true,force:true}));
const report={id:'fixture',end:'2026-10-30',filters:{lookbackDays:365}};
const stocks=[{symbol:'APP',name:'AppLovin Corporation',marketCap:30e9,price:110,change:2,history:[['2026-10-29',105,-4,103,108,104,1200],['2026-10-30',110,2,105,112,106,1500]]},
 {symbol:'AAPL',name:'Apple Inc.',marketCap:3e12,price:200,change:-1,history:[['2026-10-30',200,-1,199,202,201,2000]]},
 {symbol:'SMALL',name:'Small Stock',marketCap:1e9,price:10,change:3,history:[['2026-10-30',10,3,9,11,9,100]]}];
const data={report,stocks};

test('volatility uses inclusive cap and movement ranges, absolute returns and the selected calendar window',()=>{
 const filters=parseRanges({minCap:20,maxCap:200,minMove:3,maxMove:3,days:30});const rows=movementRows(data,filters);
 assert.equal(rows.length,1);assert.equal(rows[0].symbol,'APP');assert.equal(rows[0].average,3);assert.equal(rows[0].sessions,2);
 assert.equal(movementRows(data,parseRanges({minCap:20,maxCap:200,minMove:3,maxMove:3,days:1})).length,0);
 assert.equal(stocks[0].average,undefined);assert.throws(()=>parseRanges({minCap:200,maxCap:20}));
});

test('prediction filters retain independent ranges and preserve saved completed-session forecasts',()=>{
 const now=new Date('2026-10-30T12:00:00Z');
 const make=(percent,date='2026-10-30')=>({state:'estimated',forecastModel:'supervised',returnBasis:'open-to-close',targetDate:date,estimatedPercent:percent});
 const forecasts=new Map([['APP',make(-.18)],['AAPL',make(.5)],['SMALL',make(2,'2026-10-29')]]);
 const options={minCap:0,maxCap:4000,minMove:0,maxMove:'',days:30,direction:'negative',minPrediction:-1,maxPrediction:0,availableOnly:true};
 assert.deepEqual(predictionRows(data,forecasts,options,now).map(s=>s.symbol),['APP']);
 assert.deepEqual(predictionRows(data,forecasts,{...options,direction:'all',minPrediction:'',maxPrediction:''},now).map(s=>s.symbol),['SMALL','AAPL','APP']);
 assert.equal(predictionRows(data,forecasts,{...options,direction:'all',minPrediction:'',maxPrediction:'',availableOnly:false},now).length,3);
 assert.throws(()=>predictionRows(data,forecasts,{...options,minPrediction:2,maxPrediction:1},now),/valid minimum/);
});

test('market close keeps today’s forecast visible and stock details retain it without a top-25 ledger record',()=>{
 const now=new Date('2026-10-30T22:00:00Z');
 const forecast={state:'estimated',forecastModel:'supervised',returnBasis:'open-to-close',targetDate:'2026-10-30',estimatedPercent:-.18,generatedAt:'2026-10-30T17:00:00Z'};
 const map=new Map([['APP',forecast]]),options={minCap:0,maxCap:4000,minMove:0,maxMove:'',days:30,availableOnly:true};
 const rows=predictionRows(data,map,options,now);
 assert.equal(rows.length,1);assert.equal(rows[0].completed,true);assert.equal(rows[0].current,false);
 const view=stockPredictionView('APP',map,null,null,now);
 assert.equal(view.current,forecast);assert.equal(view.currentClosed,true);assert.equal(view.next,null);
 assert.equal(view.records[0].percent,-.18);assert.equal(view.records[0].actual,null);
 const absent={symbol:'APP',targetDate:'2026-10-30',lookback:365,returnBasis:'open-to-close',state:'no-signal',reason:'Historical prices unavailable',estimatedPercent:null,generatedAt:forecast.generatedAt};
 const missing=stockPredictionView('APP',new Map([['APP',absent]]),null,{records:[absent]},now);
 assert.equal(missing.latestAttempt.reason,'Historical prices unavailable');assert.equal(missing.records[0].percent,null);assert.equal(missing.records[0].directionCorrect,null);
});

test('explore searches all scanned stocks by ticker or company, independent of screener filters',()=>{
 assert.deepEqual(searchStocks(stocks,'apple').map(s=>s.symbol),['AAPL']);
 assert.equal(searchStocks(stocks,'APP')[0].symbol,'APP');
 assert.equal(searchStocks(stocks,'small stock')[0].symbol,'SMALL');
 assert.deepEqual(searchStocks(stocks,'','watchlist',new Set(['SMALL'])).map(s=>s.symbol),['SMALL']);
 assert.deepEqual(searchStocks(stocks,'','decliners').map(s=>s.symbol),['AAPL']);
 assert.equal(searchStocks(stocks,'no-such-stock').length,0);
 assert.equal(searchStocks([{symbol:'SPGI',name:'S&P Global Inc.'}],'S and P Global')[0].symbol,'SPGI');
 assert.equal(searchStocks([{symbol:'BRK.B',name:'Berkshire Hathaway Inc.'}],'brk-b')[0].symbol,'BRK.B');
 assert.equal(indexSearchResult('S and P 500').symbol,'^GSPC');
 assert.equal(indexSearchResult('S&P500').symbol,'^GSPC');
 assert.equal(indexSearchResult('Apple'),null);
});

test('range return uses the known preceding close and preserves volume and missing ranges',()=>{
 const stock={...stocks[0],predictionBaseline:[['2026-10-28',100,0,99,101,100,900]]};
 const view=historyView(stock,report,2);assert.ok(Math.abs(view.returnPercent-10)<1e-10);
 assert.equal(view.baselineDate,'2026-10-28');assert.equal(view.days[0].volume,1200);assert.equal(view.days.length,2);
 assert.equal(historyView({...stock,history:[['2026-10-30',110,2]]},report,1).missingRanges,true);
});

test('testing shows all 25 original stocks and keeps after-open scores separate',()=>{
 const cohort=Array.from({length:25},(_,i)=>({symbol:'S'+i,name:'Stock '+i}));
 const saved={stocks:cohort,entries:[{date:'2026-10-30',symbol:'S0',prediction:{percent:2},actual:{percent:-1},lateForecasts:[{percent:-1,generatedAt:'2026-10-30T16:00:00Z'}]}]};
 const morning=testDayView(saved,'2026-10-30'),late=testDayView(saved,'2026-10-30','late');
 assert.equal(morning.rows.length,25);assert.equal(late.rows.length,25);assert.equal(morning.compared,1);assert.equal(morning.correct,0);assert.equal(morning.mae,3);
 assert.equal(late.correct,1);assert.equal(late.mae,0);assert.equal(morning.rows[1].prediction,undefined);assert.equal(saved.entries[0].prediction.percent,2);
});

test('CSV preserves numeric returns and escapes spreadsheet formulas in external strings',()=>{
 const value=csvText(['Ticker','Return'],[['=BAD()',-.18],['Name "quoted"',.09]]);
 assert.ok(value.includes('"\'=BAD()"'));assert.ok(value.includes('"-0.18"'));assert.ok(value.includes('Name ""quoted""'));
});

test('dashboard exposes four separate accessible sections and a complete explore/history route',async()=>{
 const html=await readFile('github-pages/index.html','utf8');
 for(const section of ['volatility','predictions','explore','testing'])assert.match(html,new RegExp('id="panel-'+section+'"'));
 assert.match(html,/id="volatilityFilters"/);assert.match(html,/id="predictionFilters"/);assert.match(html,/id="stockSearch" type="search"/);assert.match(html,/id="testVariant"/);
 assert.match(html,/href="#testing"/);assert.match(html,/Skip to content/);
 const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,ids.length);
});

test('stock details use saved history, separate late records, and require the exact next-session forecast',()=>{
 const now=new Date('2026-11-01T18:00:00Z'),forecast={symbol:'APP',state:'estimated',returnBasis:'open-to-close',forecastModel:'supervised',sessionMode:'current-or-next',targetDate:'2026-11-02',estimatedPercent:1.2};
 const prediction={percent:-2,generatedAt:'2026-10-30T12:00:00Z',modelVersion:'v10'};
 const testing={entries:[{symbol:'APP',date:'2026-10-30',prediction,actual:{percent:-1},lateForecasts:[{percent:0.5,generatedAt:'2026-10-30T17:00:00Z',modelVersion:'v10'}]}]};
 const ledger={records:[{symbol:'APP',targetDate:'2026-10-30',lookback:365,returnBasis:'open-to-close',estimatedPercent:-2,actualPercent:-1,generatedAt:prediction.generatedAt,modelVersion:'v10'},
 {symbol:'APP',targetDate:'2026-10-29',lookback:365,returnBasis:'open-to-close',estimatedPercent:0,actualPercent:null},
 {symbol:'APP',targetDate:'2026-10-28',lookback:30,returnBasis:'scan-to-close',estimatedPercent:9},
 {symbol:'OTHER',targetDate:'2026-10-30',lookback:365,returnBasis:'open-to-close',estimatedPercent:9}]};
 const view=stockPredictionView('APP',new Map([['APP',forecast]]),testing,ledger,now);
 assert.equal(view.targetDate,'2026-11-02');assert.equal(view.next,forecast);assert.equal(view.records.length,3);
 assert.equal(view.records.find(r=>r.record==='Frozen morning test').error,1);
 assert.equal(view.records.find(r=>r.afterOpen).directionCorrect,false);assert.equal(view.records.find(r=>r.date==='2026-10-29').actual,null);
 assert.equal(stockPredictionView('APP',new Map([['APP',{...forecast,targetDate:'2026-10-30'}]]),null,null,now).next,null);
 assert.equal(stockPredictionView('UNKNOWN',new Map(),testing,ledger,now).records.length,0);
 const duringSession=stockPredictionView('APP',new Map([['APP',forecast]]),null,null,new Date('2026-11-02T17:00:00Z'));
 assert.equal(duringSession.targetDate,'2026-11-03');assert.equal(duringSession.next,null);assert.equal(duringSession.current,forecast);
 const nextDay={...forecast,targetDate:'2026-11-03'};
 const savedToday={records:[{symbol:'APP',targetDate:'2026-11-02',lookback:365,returnBasis:'open-to-close',estimatedPercent:-.7,actualPercent:-1,generatedAt:'2026-11-02T17:00:00Z'}]};
 const afterClose=stockPredictionView('APP',new Map([['APP',nextDay]]),null,savedToday,new Date('2026-11-02T23:00:00Z'));
 assert.equal(afterClose.next,nextDay);assert.equal(afterClose.current.estimatedPercent,-.7);assert.equal(afterClose.currentClosed,true);assert.equal(afterClose.records[0].actual,-1);
});

test('exchange labels use recorded listing metadata and distinguish NASDAQ from NYSE',()=>{
 for(const name of ['NASDAQ','NASDAQGS','NMS','NGM','NCM'])assert.equal(exchangeLabel({exchange:name}),'NASDAQ');
 for(const name of ['NYSE','NYQ','New York Stock Exchange'])assert.equal(exchangeLabel({exchange:name}),'NYSE');
 assert.equal(tickerLabel({symbol:'AAPL',exchange:'NMS'}),'AAPL · NASDAQ');
 assert.equal(tickerLabel({symbol:'IBM',exchange:'NYSE'}),'IBM · NYSE');
 assert.equal(exchangeLabel({symbol:'UNKNOWN'}),'Exchange unavailable');
});
