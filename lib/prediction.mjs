import {sessionExpired} from './trading-calendar.mjs';
import {readFileSync} from 'node:fs';
export const MODEL_SELECTION=JSON.parse(readFileSync(new URL('../data/prediction-model.json',import.meta.url),'utf8'));
export const MODEL_VERSION=MODEL_SELECTION.version;
export function historyDays(stock){return (stock.predictionHistory||stock.history||stock.days||[]).map(d=>Array.isArray(d)?{date:d[0],close:d[1],change:d[2],open:d[5]}:d).sort((a,b)=>a.date.localeCompare(b.date))}
export function updateLedger(previous,stocks,forecasts,now=new Date()){
 if(!Array.isArray(previous))throw Error('Invalid prediction ledger');const bySymbol=new Map(stocks.map(s=>[s.symbol,historyDays(s)]));const ledger=previous.map(row=>{if(row.actualPercent!=null||!Number.isFinite(row.estimatedPercent))return row;const day=bySymbol.get(row.symbol)?.find(d=>d.date===row.targetDate);const close=day?.close;const base=row.returnBasis==='open-to-close'?day?.open:row.baseClose;if(!(close>0&&base>0)||!sessionExpired(row.targetDate,now)||sessionExpired(row.targetDate,new Date(row.generatedAt)))return row;const actual=(close/base-1)*100;return {...row,actualPercent:actual,errorPoints:Math.abs(actual-row.estimatedPercent),baselineErrorPoints:Math.abs(actual),directionCorrect:Math.sign(actual)===Math.sign(row.estimatedPercent),evaluatedAt:now.toISOString()}});
 const signature=r=>[r.modelVersion||MODEL_VERSION,r.symbol,r.lookback,r.targetDate,r.generatedAt,r.estimatedPercent,r.state||'estimated',r.reason||''].join('|');
 const saved=new Set(ledger.map(signature)),keys=new Set(ledger.map(r=>r.id));
 for(const row of forecasts){for(const f of row.forecasts||[]){if(!['estimated','no-signal','unavailable'].includes(f.state)||f.state==='estimated'&&!Number.isFinite(f.estimatedPercent)||!f.targetDate||!Number.isFinite(Date.parse(f.generatedAt)))continue;const version=f.modelVersion||MODEL_VERSION;
 const record={symbol:row.symbol,state:f.state,reason:f.reason,modelVersion:version,returnBasis:f.returnBasis||'scan-to-close',lookback:f.lookback,targetDate:f.targetDate,baseClose:f.baseClose,estimatedPercent:f.state==='estimated'?f.estimatedPercent:null,priceOnlyPercent:f.priceOnlyPercent,generatedAt:f.generatedAt,newsCount:f.newsCount,modelFamily:f.modelQuality?.model||null,modelFeatures:f.modelQuality?.features||null,validationPassed:f.validationPassed===true,quoteAsOf:f.quoteAsOf,generatedAfterOpen:f.generatedAfterOpen===true,sessionMode:f.sessionMode,forecastModel:f.forecastModel||'supervised'};
 const key=signature(record);if(saved.has(key))continue;saved.add(key);
 const base=`${version}:${row.symbol}:${f.lookback}:${f.targetDate}`,id=keys.has(base)?`${base}:${f.generatedAt}:${f.estimatedPercent}`:base;
 if(keys.has(id))continue;keys.add(id);ledger.push({id,...record});
 }}
 return ledger.sort((a,b)=>b.generatedAt.localeCompare(a.generatedAt));
}
export function validationSummary(ledger,lookback){const resolved=ledger.filter(r=>r.modelVersion===MODEL_VERSION&&!r.generatedAfterOpen&&r.lookback===lookback&&Number.isFinite(r.actualPercent));return {samples:resolved.length,meanAbsoluteError:resolved.length?resolved.reduce((n,r)=>n+r.errorPoints,0)/resolved.length:null,naiveMeanAbsoluteError:resolved.length?resolved.reduce((n,r)=>n+r.baselineErrorPoints,0)/resolved.length:null,directionAccuracy:resolved.length?resolved.filter(r=>r.directionCorrect).length/resolved.length:null};}
