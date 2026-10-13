import {readFile,writeFile} from 'node:fs/promises';
import {gatherPredictionNews} from '../lib/prediction-news.mjs';
import {updateLedger,validationSummary,MODEL_VERSION} from '../lib/prediction.mjs';
import {trainingPrices,gatherTrainingData} from '../lib/supervised-data.mjs';
import {easternSessionClock,nextForecastSession,tradingDay,previousTradingDay,sessionExpired} from '../lib/trading-calendar.mjs';
const site=process.argv[3]||'public-site',mode=process.argv[2],now=new Date();
const data=JSON.parse(await readFile(site+'/data.json','utf8'));
const bySymbol=new Map(data.stocks.map(s=>[s.symbol,s]));
const stocks=(data.report.top25||data.report.stocks||[]).slice(0,25).map(s=>bySymbol.get(s.symbol)).filter(Boolean);
if(mode==='--prepare'){
 const news=await gatherPredictionNews(stocks,{now});news.reportId=data.report.id;await writeFile(site+'/prediction-news.json',JSON.stringify(news));console.log(`Fetched company news for ${stocks.length} stocks; ${news.errors.length} source failures.`);
}else if(mode==='--training-data'){
 const dataset=await gatherTrainingData(stocks,{now});dataset.reportId=data.report.id;
 const covered=new Set(dataset.companies.map(c=>c.symbol));const eligible=data.stocks.filter(s=>!covered.has(s.symbol)&&s.marketCap>=data.report.filters.minMarketCap&&s.marketCap<=data.report.filters.maxMarketCap);let inferenceIndex=0;
 await Promise.all(Array.from({length:2},async()=>{while(inferenceIndex<eligible.length){const stock=eligible[inferenceIndex++];try{const prices=await trainingPrices(stock.symbol,{now,dailyOnly:true});dataset.companies.push({...stock,...prices,newsTimeline:[],inferenceOnly:true})}catch(e){dataset.errors.push({symbol:stock.symbol,source:'Yahoo inference prices',error:e.message})}await new Promise(r=>setTimeout(r,500))}}));
 const clock=easternSessionClock(now),targetDate=nextForecastSession(now);
 for(const company of dataset.companies){const original=bySymbol.get(company.symbol);const quoteAsOf=original.priceAsOf||original.priceDate;const quoteClock=quoteAsOf?.length>10?easternSessionClock(new Date(quoteAsOf)):null;const expectedLast=tradingDay(clock.date)&&sessionExpired(clock.date,now)?clock.date:previousTradingDay(clock.date);const last=company.daily.filter(d=>d.date<=expectedLast).at(-1);
 const ready=Boolean(quoteClock&&Date.parse(quoteAsOf)<=now.getTime()&&original.price>0&&last?.date===expectedLast&&(!(tradingDay(clock.date)&&clock.minute>=570&&!sessionExpired(clock.date,now))||quoteClock.date===clock.date));
 const preopen=targetDate===clock.date||!tradingDay(clock.date);
 company.forecastContext={state:ready?'ready':'stale',reason:'A current quote and complete recent training prices are required',targetDate,baseDate:last?.date,basePrice:original.price,quoteAsOf:quoteAsOf?.length>10?quoteAsOf:last?.date+'T20:00:00Z',inferenceDate:preopen?targetDate:quoteClock?.date,inferenceMinute:preopen?540:quoteClock?.minute};
 }
 await writeFile(site+'/prediction-training.json',JSON.stringify(dataset));console.log(`Training dataset: ${dataset.companies.length} companies; ${dataset.errors.length} source failures.`);
}else if(mode==='--finalize'){
 try{
 let news;try{news=JSON.parse(await readFile(site+'/prediction-sentiment.json','utf8'))}catch{news=JSON.parse(await readFile(site+'/prediction-news.json','utf8'));news.modelState='unavailable'}
 if(news.reportId!==data.report.id)throw Error('Prediction news belongs to a different report');
 let previous=[];const r=await fetch('https://tarunkrishna112003.github.io/market-pulse-agent/prediction-history.json',{signal:AbortSignal.timeout(20000),cache:'no-store'});
 if(r.ok){const saved=await r.json();if(!Array.isArray(saved.records))throw Error('Invalid saved prediction history');previous=saved.records}else if(r.status!==404)throw Error('Cannot restore prediction history (HTTP '+r.status+')');
 const trained=JSON.parse(await readFile(site+'/prediction-trained.json','utf8'));const trainedRows=new Map(trained.rows.map(r=>[r.symbol,r]));const rows=[...trained.rows,...stocks.filter(s=>!trainedRows.has(s.symbol)).map(s=>trainedRows.get(s.symbol)||{symbol:s.symbol,name:s.name,headlines:news.companies.find(c=>c.symbol===s.symbol)?.headlines||[],newsState:'unavailable',forecasts:[10,20,30].map(lookback=>({state:'no-signal',lookback,reason:'Historical training prices could not be retrieved'}))})];
 const ledger=updateLedger(previous,data.stocks,rows.filter(r=>stocks.some(s=>s.symbol===r.symbol)),now);
 const result={state:trained.trainedModels.some(m=>m.trainingRows)?'trained':'unavailable',error:trained.trainedModels.filter(m=>m.error).map(m=>m.error).join('; '),reportId:data.report.id,scanCreatedAt:data.report.createdAt,generatedAt:now.toISOString(),availableLookback:data.report.filters.lookbackDays,modelVersion:MODEL_VERSION,trainedModels:trained.trainedModels,trainingErrors:trained.trainingErrors,dataCaveats:trained.dataCaveats,newsModel:news.model||null,newsModelState:news.modelState||'unavailable',newsErrors:news.errors||[],topSymbols:stocks.map(s=>s.symbol),coverage:{minMarketCap:data.report.filters.minMarketCap,maxMarketCap:data.report.filters.maxMarketCap,stocks:rows.length},rows,validation:[10,20,30].map(lookback=>({lookback,...validationSummary(ledger,lookback)}))};
 await writeFile(site+'/predictions.json',JSON.stringify(result));await writeFile(site+'/prediction-history.json',JSON.stringify({updatedAt:now.toISOString(),records:ledger}));console.log(`Published ${rows.length} trained prediction rows; ${ledger.filter(r=>r.actualPercent!=null).length} saved forecasts evaluated.`);
 }catch(e){await writeFile(site+'/predictions.json',JSON.stringify({state:'unavailable',generatedAt:now.toISOString(),error:e.message,rows:[]}));console.error(e.message);process.exitCode=1}
}else throw Error('Use --prepare or --finalize');
