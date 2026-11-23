import {readFile,writeFile} from 'node:fs/promises';
import {useFrozenOctober20} from '../lib/frozen-forecast-migration.mjs';
import {createTest,extendTest,restoreSavedPredictions,updateTest} from '../lib/testing-results.mjs';
import {PREOPEN_FORECAST_START,sessionExpired} from '../lib/trading-calendar.mjs';
import {trainingPrices} from '../lib/supervised-data.mjs';
import {EXTENDED_MODEL_VERSION,MODEL_SELECTION} from '../lib/prediction.mjs';
const site=process.argv[2]||'public-site',base='https://tarunkrishna112003.github.io/market-pulse-agent/';
async function published(file,optional=false){const r=await fetch(base+file+'?testing='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(30000)});if(optional&&r.status===404)return null;if(!r.ok)throw Error('Cannot read published '+file+': HTTP '+r.status);return r.json()}
async function current(file){try{return JSON.parse(await readFile(site+'/'+file,'utf8'))}catch(error){if(error.code!=='ENOENT')throw error;return published(file)}}
const now=new Date(),previous=await published('testing-results.json',true);
const state=extendTest(previous||createTest(await published('daily-report.json')),now);
const scan=await current('data.json'),exchanges=new Map(scan.stocks.map(stock=>[stock.symbol,stock.exchange]));
state.stocks=state.stocks.map(stock=>({...stock,exchange:exchanges.get(stock.symbol)||stock.exchange}));
const [metadata,forecasts]=await Promise.all([current('predictions.json'),current('predictions/365.json')]);
if(metadata.reportId!==forecasts.reportId)throw Error('Published forecast changed during download; preserving previous test');
const prices=[],errors=[];let index=0;
const rangeStart=new Date(now.getTime()-13*86400000).toISOString().slice(0,10);
if(state.entries.some(entry=>sessionExpired(entry.date,now)&&(!entry.actual||entry.date>=rangeStart&&entry.prediction?.percent&&!entry.actual.range)))await Promise.all(Array.from({length:3},async()=>{while(index<state.stocks.length){const stock=state.stocks[index++];try{prices.push(await trainingPrices(stock.symbol,{now,dailyOnly:true,historyDays:14}))}catch(error){errors.push({symbol:stock.symbol,error:error.message})}}}));
const history=await current('prediction-history.json');
const recovered=restoreSavedPredictions(state,history,now,MODEL_SELECTION);
const migrated=useFrozenOctober20(recovered,await readFile(new URL('../data/frozen-forecasts/2026-10-20.json',import.meta.url),'utf8'),now);
const selection=metadata.modelVersion===EXTENDED_MODEL_VERSION?{...MODEL_SELECTION,version:EXTENDED_MODEL_VERSION}:MODEL_SELECTION;
const result=updateTest(migrated,{...forecasts,generatedAt:metadata.generatedAt,modelVersion:metadata.modelVersion},prices,now,selection);result.priceErrors=errors;
for(const entry of result.entries)if(entry.date>=PREOPEN_FORECAST_START)delete entry.lateForecasts;
await writeFile(site+'/testing-results.json',JSON.stringify(result));
console.log(`Testing ${state.dates.join(', ')}: ${result.entries.filter(e=>e.prediction).length} frozen forecasts; ${result.entries.filter(e=>e.status==='compared').length} comparisons.`);
