import test from 'node:test';
import assert from 'node:assert/strict';
import {updateLedger,validationSummary,MODEL_VERSION} from '../lib/prediction.mjs';
import {nextTradingDay,sessionExpired,nextForecastSession} from '../lib/trading-calendar.mjs';
import {parseNews,companyMatches,gatherPredictionNews} from '../lib/prediction-news.mjs';
function stock(change=1){let close=100;const days=[];for(let date='2026-08-31';date<='2026-10-09';date=nextTradingDay(date)){close*=1+change/100;days.push({date,close,change})}return {symbol:'ALAB',name:'Astera Labs, Inc. Common Stock',price:close,priceAsOf:'2026-10-12T14:00:00Z',days}}
const now=new Date('2026-10-12T15:00:00Z');
const news=polarity=>({state:'available',headlines:[{title:'Astera Labs funding announcement',url:'https://example.com/news',publishedAt:'2026-10-12T14:00:00Z',sentiment:polarity}]});
function forecast(lookback=20){return {state:'estimated',forecastModel:'supervised',returnBasis:'open-to-close',validationPassed:true,lookback,sessions:20,baseDate:'2026-10-09',baseClose:100,quotePrice:100,quoteAsOf:'2026-10-12T14:00:00Z',targetDate:'2026-10-13',generatedAt:now.toISOString(),estimatedPercent:1,estimatedDollar:1,projectedClose:101,direction:'positive',priceOnlyPercent:0.5,newsContributionPoints:0.5,newsLabel:'learned news features',remainingPercent:1,interval:{level:0.8,lowerPercent:-5,upperPercent:6}}}
test('trading session calendar handles weekends and scheduled holidays and early closes',()=>{
 assert.equal(nextTradingDay('2026-07-02'),'2026-07-06');assert.equal(nextTradingDay('2026-04-02'),'2026-04-06');assert.equal(nextTradingDay('2027-12-31'),'2028-01-03');assert.equal(sessionExpired('2026-11-27',new Date('2026-11-27T18:00:00Z')),true);
});
test('ledger scores only previously recorded forecasts and retains first forecast per session',()=>{
 const s=stock(),f=forecast(20),rows=[{symbol:s.symbol,forecasts:[f]}];let ledger=updateLedger([], [s],rows,now);assert.equal(ledger.length,1);assert.equal(ledger[0].modelVersion,MODEL_VERSION);assert.equal(updateLedger(ledger,[s],rows,now).length,1);
 const actual={...s,days:[...s.days,{date:'2026-10-13',open:200,close:204,change:2}]};ledger=updateLedger(ledger,[actual],[],new Date('2026-10-13T21:00:00Z'));assert.ok(Math.abs(ledger[0].actualPercent-2)<1e-9);assert.equal(validationSummary(ledger,20).samples,1);assert.equal(validationSummary(ledger,10).samples,0);
 const tooLate=[{...ledger[0],actualPercent:null,generatedAt:'2026-10-13T21:00:00Z'}];assert.equal(updateLedger(tooLate,[actual],[],new Date('2026-10-13T12:00:00Z'))[0].actualPercent,null);
});
test('open-to-close ledger waits for closing data and does not score a missing open',()=>{
 const f=forecast(),row={symbol:'ALAB',forecasts:[f]};const previous=updateLedger([],[],[row],now);
 const bars=[{symbol:'ALAB',history:[['2026-10-13',204,2,195,205,200]]}];
 assert.equal(updateLedger(previous,bars,[],new Date('2026-10-13T17:00:00Z'))[0].actualPercent,undefined);
 assert.ok(Math.abs(updateLedger(previous,bars,[],new Date('2026-10-13T21:00:00Z'))[0].actualPercent-2)<1e-9);
 const missing=[{symbol:'ALAB',history:[['2026-10-13',204,2,195,205]]}];
 assert.equal(updateLedger(previous,missing,[],new Date('2026-10-13T21:00:00Z'))[0].actualPercent,undefined);
 const legacy=[{...previous[0],returnBasis:'scan-to-close',baseClose:100}];
 assert.equal(updateLedger(legacy,bars,[],new Date('2026-10-13T21:00:00Z'))[0].actualPercent,104);
});
test('RSS parsing ignores future articles, stale items, duplicates and unsafe URLs',()=>{
 const item=(title,date='Mon, 12 Oct 2026 14:00:00 GMT',url='https://example.com/a')=>`<item><title>${title}</title><link>${url}</link><pubDate>${date}</pubDate></item>`;const xml='<rss>'+item('Astera Labs wins contract')+item('Astera Labs wins contract')+item('Astera Labs news','Tue, 13 Oct 2026 14:00:00 GMT')+item('Astera Labs old news','Mon, 01 Jun 2026 14:00:00 GMT')+item('Astera Labs funding',undefined,'javascript:alert(1)')+'</rss>';const parsed=parseNews(xml,'CNBC',now);assert.equal(parsed.length,1);assert.equal(parsed[0].source,'CNBC');assert.equal(companyMatches(stock(),parsed[0].title),true);assert.equal(companyMatches(stock(),'Another company gets funding'),false);assert.equal(companyMatches({symbol:'ON',name:'ON Semiconductor Corporation'},'On Monday another company raised funds'),false);
});
test('free company news sources disclose individual failures',async()=>{
 const result=await gatherPredictionNews([stock()],{now,fetchImpl:async url=>String(url).includes('finance.yahoo')?{ok:true,text:async()=>'<rss><item><title>Astera Labs receives new investment</title><link>https://finance.yahoo.com/news/investment</link><pubDate>Mon, 12 Oct 2026 14:00:00 GMT</pubDate></item></rss>'}:{ok:false,status:503}});assert.equal(result.companies[0].headlines.length,1);assert.equal(result.errors.length,3);
});

test('forecast target is an unstarted session and crosses market holidays',()=>{
 assert.equal(nextForecastSession(new Date('2026-10-12T12:00:00Z')),'2026-10-12');assert.equal(nextForecastSession(new Date('2026-10-12T13:30:00Z')),'2026-10-13');assert.equal(nextForecastSession(new Date('2026-07-02T15:00:00Z')),'2026-07-06');
});
