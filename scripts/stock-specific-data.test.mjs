import test from 'node:test';
import assert from 'node:assert/strict';
import {collectStockSpecificData,completedDaily} from '../lib/stock-specific-data.mjs';
import {currentOrNextForecastSession,forecastSessionForModel} from '../lib/trading-calendar.mjs';

test('new model can forecast the active session without changing legacy targets',()=>{
 const now=new Date('2026-10-29T16:35:00Z');
 assert.equal(currentOrNextForecastSession(now),'2026-10-29');
 assert.equal(forecastSessionForModel({sessionMode:'current-or-next'},now),'2026-10-29');
 assert.equal(forecastSessionForModel({},now),'2026-10-30');
 assert.equal(currentOrNextForecastSession(new Date('2026-10-29T22:00:00Z')),'2026-10-30');
});

test('stock-specific collection requests split-aware daily history and excludes unfinished sessions',async()=>{
 const now=new Date('2026-10-28T22:00:00Z'),requests=[];
 const fetchImpl=async url=>{const u=new URL(url);requests.push(u);return {ok:true,json:async()=>({chart:{result:[{
  timestamp:[Date.parse('2026-10-27T13:30:00Z')/1000,Date.parse('2026-10-28T13:30:00Z')/1000],
  indicators:{quote:[{open:[100,101],close:[101,102],low:[99,100],high:[102,103],volume:[1000,1100]}]}
 }]}})}};
 const data={report:{id:'switch',top25:[{symbol:'A'}],filters:{lookbackDays:17}},stocks:[{symbol:'A',name:'A',sector:'Technology'},{symbol:'B',name:'B',sector:'Healthcare'}]};
 const result=await collectStockSpecificData(data,{now,fetchImpl,historyDays:800});
 assert.equal(result.reportId,'switch');assert.equal(result.companies.length,2);assert.equal(result.availableLookback,17);
 assert.equal(result.companies.find(c=>c.symbol==='A').sectorETF,'XLK');assert.equal(result.companies.find(c=>c.symbol==='B').sectorETF,'XLV');
 assert.equal(result.companies[0].forecastContext.targetDate,'2026-10-29');assert.equal(result.companies[0].forecastContext.baseDate,'2026-10-28');
 assert.equal(result.companies[0].forecastContext.state,'ready');assert.equal(Object.keys(result.context).length,13);
 assert.ok(requests.every(u=>u.searchParams.get('interval')==='1d'&&u.searchParams.get('events')==='splits'));
 const bars=[{date:'2026-10-27'},{date:'2026-10-28'}];assert.equal(completedDaily(bars,new Date('2026-10-28T20:05:00Z')).length,1);
 assert.equal(completedDaily(bars,new Date('2026-10-28T20:16:00Z')).length,2);
});
