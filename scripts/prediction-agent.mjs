import {readFile,writeFile} from 'node:fs/promises';
import {gatherPredictionNews} from '../lib/prediction-news.mjs';
import {updateLedger,validationSummary,MODEL_VERSION} from '../lib/prediction.mjs';
import {trainingPrices,gatherTrainingData} from '../lib/supervised-data.mjs';
import {easternSessionClock,nextForecastSession,tradingDay,previousTradingDay} from '../lib/trading-calendar.mjs';
const site=process.argv[3]||'public-site',mode=process.argv[2],now=new Date();
const data=JSON.parse(await readFile(site+'/data.json','utf8'));
const bySymbol=new Map(data.stocks.map(s=>[s.symbol,s]));
const stocks=(data.report.top25||data.report.stocks||[]).slice(0,25).map(s=>bySymbol.get(s.symbol)).filter(Boolean);
if(mode==='--prepare'){
 const news=await gatherPredictionNews(stocks,{now});news.reportId=data.report.id;await writeFile(site+'/prediction-news.json',JSON.stringify(news));console.log(`Fetched company news for ${stocks.length} stocks; ${news.errors.length} source failures.`);
}else if(mode==='--training-data'){
 const dataset=await gatherTrainingData(stocks,{now});dataset.reportId=data.report.id;dataset.availableLookback=data.report.filters.lookbackDays;dataset.universe=data.stocks.map(s=>({symbol:s.symbol,name:s.name}));
 const covered=new Set(dataset.companies.map(c=>c.symbol));const eligible=data.stocks.filter(s=>!covered.has(s.symbol));let inferenceIndex=0;
 await Promise.all(Array.from({length:4},async()=>{while(inferenceIndex<eligible.length){const stock=eligible[inferenceIndex++];try{const cached=(stock.predictionHistory||[...(stock.predictionBaseline||[]),...(stock.history||[])]);const reusable=cached.length>0&&cached[0][0]<=new Date(now.getTime()-365*86400000).toISOString().slice(0,10)&&cached.every(d=>Array.isArray(d)&&d.length>=7&&Number.isFinite(d[6]));const prices=reusable?{daily:cached.map(d=>({date:d[0],close:d[1],low:d[3],high:d[4],open:d[5],volume:d[6]})),hourly:[]}:await trainingPrices(stock.symbol,{now,dailyOnly:true,historyDays:380});dataset.companies.push({...stock,...prices,newsTimeline:[],inferenceOnly:true})}catch(e){dataset.errors.push({symbol:stock.symbol,source:'Yahoo inference prices',error:e.message})}await new Promise(r=>setTimeout(r,250))}}));
 const clock=easternSessionClock(now),targetDate=nextForecastSession(now);
 for(const company of dataset.companies){const original=bySymbol.get(company.symbol);const quoteAsOf=original.priceAsOf||original.priceDate;const quoteClock=quoteAsOf?.length>10?easternSessionClock(new Date(quoteAsOf)):null;
 const preopen=targetDate===clock.date||!tradingDay(clock.date);const inferenceDate=preopen?targetDate:quoteClock?.date;const expectedLast=inferenceDate?previousTradingDay(inferenceDate):null;const last=company.daily.filter(d=>expectedLast&&d.date<=expectedLast).at(-1);
 const ready=Boolean(quoteClock&&Date.parse(quoteAsOf)<=now.getTime()&&original.price>0&&last?.date===expectedLast&&quoteClock.date===(preopen?expectedLast:clock.date));
 company.forecastContext={state:ready?'ready':'stale',reason:'A current quote and complete recent training prices are required',targetDate,baseDate:last?.date,basePrice:original.price,quoteAsOf:quoteAsOf?.length>10?quoteAsOf:last?.date+'T20:00:00Z',inferenceDate,inferenceMinute:preopen?540:quoteClock?.minute};
 }
 await writeFile(site+'/prediction-training.json',JSON.stringify(dataset));console.log(`Training dataset: ${dataset.companies.length} companies; ${dataset.errors.length} source failures.`);
}else if(mode==='--finalize'){
 try{
 let news;try{news=JSON.parse(await readFile(site+'/prediction-sentiment.json','utf8'))}catch{news=JSON.parse(await readFile(site+'/prediction-news.json','utf8'));news.modelState='unavailable'}
 if(news.reportId!==data.report.id)throw Error('Prediction news belongs to a different report');
 let previous=[];const r=await fetch('https://tarunkrishna112003.github.io/market-pulse-agent/prediction-history.json',{signal:AbortSignal.timeout(20000),cache:'no-store'});
 if(r.ok){const saved=await r.json();if(!Array.isArray(saved.records))throw Error('Invalid saved prediction history');previous=saved.records}else if(r.status!==404)throw Error('Cannot restore prediction history (HTTP '+r.status+')');
 const trained=JSON.parse(await readFile(site+'/prediction-trained.json','utf8'));const trainedRows=new Map(trained.rows.map(r=>[r.symbol,r]));const rows=[...trained.rows,...stocks.filter(s=>!trainedRows.has(s.symbol)).map(s=>trainedRows.get(s.symbol)||{symbol:s.symbol,name:s.name,headlines:news.companies.find(c=>c.symbol===s.symbol)?.headlines||[],newsState:'unavailable',forecasts:[365].map(lookback=>({state:'no-signal',lookback,reason:'Historical training prices could not be retrieved'}))})];
 for(const row of rows)for(const f of row.forecasts||[])if(f.modelKey)f.modelQuality=trained.trainedModels.find(m=>m.adaptive);
 const training=JSON.parse(await readFile(site+'/prediction-training.json','utf8'));const evaluated=new Map(training.companies.map(c=>[c.symbol,{symbol:c.symbol,days:c.daily}]));
 const ledger=updateLedger(previous,data.stocks.map(s=>evaluated.get(s.symbol)||s),rows.filter(r=>stocks.some(s=>s.symbol===r.symbol)),new Date(training.generatedAt));
 for(const row of rows)for(const f of row.forecasts||[])if(f.modelKey)delete f.modelQuality;
 const result={returnBasis:'open-to-close',supportedLookbacks:trained.supportedLookbacks,state:trained.trainedModels.some(m=>m.trainingRows)?'trained':'unavailable',error:trained.trainedModels.filter(m=>m.error).map(m=>m.error).join('; '),reportId:data.report.id,scanCreatedAt:data.report.createdAt,generatedAt:now.toISOString(),availableLookback:365,modelVersion:MODEL_VERSION,trainedModels:trained.trainedModels,trainingErrors:trained.trainingErrors,dataCaveats:trained.dataCaveats,newsModel:news.model||null,newsModelState:news.modelState||'unavailable',newsErrors:news.errors||[],topSymbols:stocks.map(s=>s.symbol),coverage:{scope:'full-scan',stocks:data.stocks.length,total:data.report.total,sourceFailures:data.report.errors.length},rows,validation:[365].map(lookback=>({lookback,...validationSummary(ledger,lookback)}))};
 const tableWindows=trained.supportedLookbacks||[];
 for(const window of tableWindows){const saved=JSON.parse(await readFile(site+'/predictions/'+window+'.json','utf8'));if(saved.reportId!==data.report.id||saved.lookback!==window||saved.rows.length!==data.stocks.length)throw Error('Incomplete or mismatched '+window+'-day forecasts');}
 result.tableFiles=tableWindows;
 await writeFile(site+'/predictions.json',JSON.stringify(result));await writeFile(site+'/prediction-history.json',JSON.stringify({updatedAt:now.toISOString(),records:ledger}));console.log(`Published forecasts for ${data.stocks.length} scanned stocks; ${ledger.filter(r=>r.actualPercent!=null).length} saved forecasts evaluated.`);
 }catch(e){await writeFile(site+'/predictions.json',JSON.stringify({state:'unavailable',generatedAt:now.toISOString(),error:e.message,rows:[]}));console.error(e.message);process.exitCode=1}
}else throw Error('Use --prepare or --finalize');
