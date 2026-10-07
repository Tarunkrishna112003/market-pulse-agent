import test from 'node:test';
import assert from 'node:assert/strict';
import {calculate,dates,makeReport} from '../lib/screener.mjs';
import {publicUniverse,publicStock} from '../lib/public-market.mjs';
import {attachStockNews} from '../lib/stock-news.mjs';
import {csv,summaryRows} from '../lib/csv-report.mjs';

test('30-day intraday range stays independent of a short movement window',()=>{
 const w=dates(new Date('2026-10-07T22:00:00Z'),2);
 assert.equal(w.baseline,'2026-08-29');
 const r=calculate({symbol:'TEST',companyName:'Test',marketCap:30e9,exchangeShortName:'NYSE'},[
  {date:'2026-09-07',close:50,low:1,high:1000},
  {date:'2026-09-08',close:90,low:80,high:140},
  {date:'2026-10-05',close:100,low:95,high:105},
  {date:'2026-10-06',close:110,low:100,high:115},
  {date:'2026-10-07',close:120,low:110,high:125},
 ],w);
 assert.equal(r.low30,80);assert.equal(r.high30,140);assert.equal(r.days.length,2);assert.equal(r.price,120);assert.equal(r.exchange,'NYSE');
 const report=makeReport([r],[],w,1,{minAverage:0});
 assert.deepEqual(report.exchanges,['NASDAQ','NYSE']);
 const exported=csv(summaryRows([r],report));assert.match(exported,/Low_30_day_USD/);assert.doesNotMatch(exported,/Days_with_move_at_least_5_percent/);
 const missing=calculate({symbol:'TEST'},[{date:'2026-10-05',close:100},{date:'2026-10-06',close:110}],w);
 assert.equal(missing.low30,null);assert.equal(missing.high30,null);
});

test('discovery merges exchanges and NYSE history accepts latest quote and trading range',async()=>{
 const original=globalThis.fetch;const requested=[];
 try{
 globalThis.fetch=async url=>{const u=String(url);requested.push(u);if(u.includes('screener/stocks')){const nyse=u.includes('exchange=nyse');return {ok:true,json:async()=>({data:{totalrecords:1,table:{rows:[{symbol:nyse?'NY':'NAS',name:'Company',marketCap:'30000000000'}]}}})}}return {ok:true,json:async()=>({chart:{result:[{meta:{instrumentType:'EQUITY',exchangeName:'NYQ',regularMarketPrice:123,regularMarketTime:1791316800},timestamp:[Date.parse('2026-09-06T17:00:00Z')/1000,Date.parse('2026-09-08T17:00:00Z')/1000],indicators:{quote:[{close:[100,110],low:[95,105],high:[105,115]}]}}]}})}};
 const list=await publicUniverse({all:true});assert.deepEqual(list.map(s=>s.exchangeShortName),['NASDAQ','NYSE']);assert.equal(requested.filter(u=>u.includes('screener/stocks')).length,2);
 const r=await publicStock(list[1],{baseline:'2026-08-29',start:'2026-09-07',end:'2026-10-06'});assert.equal(r.price,123);assert.equal(r.low30,105);assert.equal(r.high30,115);assert.equal(r.priceKind,'Latest quote');
 }finally{globalThis.fetch=original}
});

test('news uses sourced titles and a failed feed preserves calculated report',async()=>{
 const original=globalThis.fetch;
 try{globalThis.fetch=async url=>String(url).includes('s=FAIL')?{ok:false}:{ok:true,text:async()=>'<rss><item><title>Company &amp; results</title><link>https://example.com/news</link><pubDate>today</pubDate></item></rss>'};
 const report={newsStocks:[{symbol:'OK'},{symbol:'FAIL'}]};await attachStockNews(report);
 assert.equal(report.newsStocks[0].headlines[0].title,'Company & results');assert.equal(report.newsStocks[1].headlines.length,0);assert.match(report.newsStocks[1].newsStatus,/unavailable/);
 }finally{globalThis.fetch=original}
});
