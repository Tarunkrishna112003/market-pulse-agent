import test from 'node:test';
import assert from 'node:assert/strict';
import {buildDailyReport,completedSession,dailyReportCSV,dailyReportMarkdown} from '../lib/daily-report.mjs';

function fixture(){
 const stock=(symbol,marketCap,move)=>{const history=[];for(let t=Date.parse('2025-10-01T00:00:00Z');t<=Date.parse('2026-10-16T00:00:00Z');t+=86400000){const date=new Date(t);if(![0,6].includes(date.getUTCDay()))history.push([date.toISOString().slice(0,10),100,move,99,101,99,1000])}return {symbol,name:symbol+' Company',marketCap,history}};
 const stocks=Array.from({length:35},(_,i)=>stock('T'+String(i).padStart(2,'0'),25e9+i*4e9,i/10));
 stocks.push(stock('MIN',20e9,0),stock('MAX',200e9,5),stock('TOO_SMALL',19.9e9,1),stock('TOO_LARGE',200.1e9,1),stock('TOO_VOLATILE',50e9,5.1));
 const data={report:{id:'closing',createdAt:'2026-10-16T22:00:00Z',end:'2026-10-16',filters:{lookbackDays:365},errors:[{symbol:'FAILED'}]},stocks};
 const forecasts={reportId:'closing',lookback:365,rows:stocks.filter(s=>s.symbol!=='T33').map(s=>({symbol:s.symbol,state:'estimated',returnBasis:'open-to-close',targetDate:'2026-10-19',estimatedPercent:0.3}))};
 return {data,forecasts};
}
test('closing report applies inclusive 20–200B and 0–5 bounds, ranks and limits to 25 with annual forecasts',()=>{
 const {data,forecasts}=fixture();const report=buildDailyReport(data,forecasts,new Date('2026-10-17T19:00:00Z'));
 assert.equal(report.sessionDate,'2026-10-16');assert.equal(report.targetDate,'2026-10-19');assert.equal(report.historyDays,365);assert.equal(report.matchingStocks,37);assert.equal(report.rows.length,25);assert.equal(report.rows[0].symbol,'MAX');
 assert.ok(report.rows.every((r,i)=>i===0||r.averageDailyMove<=report.rows[i-1].averageDailyMove));
 assert.ok(report.rows.every(r=>r.marketCap>=20e9&&r.marketCap<=200e9&&r.averageDailyMove<=5));
 assert.equal(report.rows.find(r=>r.symbol==='T33').predictionPercent,null);assert.equal(report.rows[0].predictionPercent,0.3);
 assert.match(dailyReportMarkdown(report),/2026-10-19/);assert.match(dailyReportMarkdown(report),/\+0.30%/);assert.match(dailyReportCSV(report),/Predicted_open_to_close_percent/);
});
test('closing report rejects mismatched models and excludes stale or incomplete histories',()=>{
 const {data,forecasts}=fixture();assert.throws(()=>buildDailyReport(data,{...forecasts,lookback:30},new Date('2026-10-17T19:00:00Z')),/one-year/);
 data.stocks[0].history.pop();data.stocks[1].history=data.stocks[1].history.slice(-10);
 assert.equal(buildDailyReport(data,forecasts,new Date('2026-10-17T19:00:00Z')).matchingStocks,35);
 assert.equal(buildDailyReport(data,forecasts,new Date('2026-10-16T18:00:00Z')),null);
 data.report.filters.lookbackDays=30;assert.equal(buildDailyReport(data,forecasts,new Date('2026-10-17T19:00:00Z')),null);
});
test('completed-session selection handles weekends, holidays, early closes and winter time',()=>{
 assert.equal(completedSession(new Date('2026-07-03T22:00:00Z')),'2026-07-02');
 assert.equal(completedSession(new Date('2026-11-27T18:30:00Z')),'2026-11-27');
 assert.equal(completedSession(new Date('2026-12-01T20:30:00Z')),'2026-11-30');
 assert.equal(completedSession(new Date('2026-12-01T21:35:00Z')),'2026-12-01');
});
