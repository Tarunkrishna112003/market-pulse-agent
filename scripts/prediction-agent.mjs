import {readFile,writeFile} from 'node:fs/promises';
import {gatherPredictionNews} from '../lib/prediction-news.mjs';
import {predictStock,priceBacktest,updateLedger,validationSummary,MODEL_VERSION} from '../lib/prediction.mjs';
const site=process.argv[3]||'public-site',mode=process.argv[2],now=new Date();
const data=JSON.parse(await readFile(site+'/data.json','utf8'));
const bySymbol=new Map(data.stocks.map(s=>[s.symbol,s]));
const stocks=(data.report.top25||data.report.stocks||[]).slice(0,25).map(s=>bySymbol.get(s.symbol)).filter(Boolean);
if(mode==='--prepare'){
 const news=await gatherPredictionNews(stocks,{now});news.reportId=data.report.id;await writeFile(site+'/prediction-news.json',JSON.stringify(news));console.log(`Fetched company news for ${stocks.length} stocks; ${news.errors.length} source failures.`);
}else if(mode==='--finalize'){
 try{
 let news;try{news=JSON.parse(await readFile(site+'/prediction-sentiment.json','utf8'))}catch{news=JSON.parse(await readFile(site+'/prediction-news.json','utf8'));news.modelState='unavailable'}
 if(news.reportId!==data.report.id)throw Error('Prediction news belongs to a different report');
 let previous=[];const r=await fetch('https://tarunkrishna112003.github.io/market-pulse-agent/prediction-history.json',{signal:AbortSignal.timeout(20000),cache:'no-store'});
 if(r.ok){const saved=await r.json();if(!Array.isArray(saved.records))throw Error('Invalid saved prediction history');previous=saved.records}else if(r.status!==404)throw Error('Cannot restore prediction history (HTTP '+r.status+')');
 const rows=stocks.map(stock=>{const company=news.companies.find(c=>c.symbol===stock.symbol);return {symbol:stock.symbol,name:stock.name,headlines:company?.headlines||[],newsState:company?.state||'unavailable',forecasts:[10,20,30].map(lookback=>{try{return {...predictStock(stock,lookback,company,now),backtest:priceBacktest(stock,lookback)}}catch(e){return {state:'error',lookback,reason:e.message}}})}});
 const ledger=updateLedger(previous,data.stocks,rows,now);
 const result={state:'experimental',reportId:data.report.id,scanCreatedAt:data.report.createdAt,generatedAt:now.toISOString(),availableLookback:data.report.filters.lookbackDays,modelVersion:MODEL_VERSION,newsModel:news.model||null,newsModelState:news.modelState||'unavailable',newsErrors:news.errors||[],rows,validation:[10,20,30].map(lookback=>({lookback,...validationSummary(ledger,lookback)}))};
 await writeFile(site+'/predictions.json',JSON.stringify(result));await writeFile(site+'/prediction-history.json',JSON.stringify({updatedAt:now.toISOString(),records:ledger}));console.log(`Published ${rows.length} experimental prediction rows; ${ledger.filter(r=>r.actualPercent!=null).length} saved forecasts evaluated.`);
 }catch(e){await writeFile(site+'/predictions.json',JSON.stringify({state:'unavailable',generatedAt:now.toISOString(),error:e.message,rows:[]}));console.error(e.message);process.exitCode=1}
}else throw Error('Use --prepare or --finalize');
