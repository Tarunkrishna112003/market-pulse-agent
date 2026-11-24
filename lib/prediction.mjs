import {sessionExpired} from './trading-calendar.mjs';
import {readFileSync} from 'node:fs';
export const MODEL_SELECTION=JSON.parse(readFileSync(new URL('../data/prediction-model.json',import.meta.url),'utf8'));
export const MODEL_VERSION=MODEL_SELECTION.version;
export const EXTENDED_MODEL_VERSION=MODEL_VERSION+'-extended-5am-v1';
export function historyDays(stock){
 const bars=stock.predictionHistory||(stock.history?[...(stock.predictionBaseline||[]),...stock.history]:stock.days||[]);
 return bars.map(d=>Array.isArray(d)?{date:d[0],close:d[1],change:d[2],low:d[3],high:d[4],open:d[5]}:d).sort((a,b)=>a.date.localeCompare(b.date));
}
export function updateLedger(previous,stocks,forecasts,now=new Date()){
 if(!Array.isArray(previous))throw Error('Invalid prediction ledger');
 const bySymbol=new Map(stocks.map(stock=>[stock.symbol,stock]));
 const closeStatus=new Map(),historyBySymbol=new Map(),targetDates=new Set();
 for(const row of previous)if(Number.isFinite(row.estimatedPercent)&&row.targetDate)targetDates.add(row.targetDate);
 const ledger=previous.map(row=>{
  if(!Number.isFinite(row.estimatedPercent)||row.actualPercent!=null&&(row.sessionPrices||row.returnBasis!=='open-to-close'))return row;
  const stock=bySymbol.get(row.symbol);
  if(!stock||!row.targetDate)return row;
  if(!closeStatus.has(row.targetDate))closeStatus.set(row.targetDate,sessionExpired(row.targetDate,now));
  if(!closeStatus.get(row.targetDate))return row;
  if(!historyBySymbol.has(row.symbol))historyBySymbol.set(row.symbol,new Map(historyDays(stock).filter(d=>targetDates.has(d.date)).map(d=>[d.date,d])));
  const day=historyBySymbol.get(row.symbol).get(row.targetDate);
  if(!day)return row;
  const close=day.close,base=row.returnBasis==='open-to-close'?day?.open:row.baseClose;
  if(!(close>0&&base>0))return row;
  const {open,high,low}=day;
  const validRange=row.returnBasis==='open-to-close'&&[open,high,low,close].every(price=>Number.isFinite(price)&&price>0)
   &&low<=Math.min(open,close)&&high>=Math.max(open,close);
  const withPrices=validRange?{...row,sessionPrices:{open,high,low,close}}:row;
  if(row.actualPercent!=null)return withPrices;
  if(sessionExpired(row.targetDate,new Date(row.generatedAt)))return row;
  const actual=(close/base-1)*100;
  return {...withPrices,actualPercent:actual,errorPoints:Math.abs(actual-row.estimatedPercent),baselineErrorPoints:Math.abs(actual),directionCorrect:Math.sign(actual)===Math.sign(row.estimatedPercent),evaluatedAt:now.toISOString()};
 });
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
