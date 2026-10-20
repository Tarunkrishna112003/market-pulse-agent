// Download historical bars separately from training. The Python runner applies each
// historical cutoff and opens target-day labels only after producing predictions.
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {scheduledCloseMinute,nextTradingDay} from '../lib/trading-calendar.mjs';
const directory=process.argv[2]||'work/backtest-2026-08-19_2026-10-19';
await mkdir(directory,{recursive:true});
async function json(url){const r=await fetch(url,{headers:{'User-Agent':'Mozilla/5.0'},signal:AbortSignal.timeout(35000)});if(!r.ok)throw Error(`${r.status} ${url}`);return r.json()}
const cohort=await json('https://tarunkrishna112003.github.io/market-pulse-agent/testing-results.json');
if(cohort.stocks?.length!==25||new Set(cohort.stocks.map(s=>s.symbol)).size!==25)throw Error('Expected the saved 25-stock testing cohort');
await writeFile(directory+'/cohort.json',JSON.stringify(cohort,null,2));
const dateNY=t=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(t*1000));
const errors=[];
async function download(symbol,interval,range){
 const path=directory+'/'+symbol.replaceAll('^','INDEX-')+'-'+interval+'.json';
 try{const saved=JSON.parse(await readFile(path,'utf8'));if(saved.symbol===symbol&&saved.interval===interval&&saved.bars?.length)return saved}catch{}
 let last;
 for(const host of ['query2.finance.yahoo.com','query1.finance.yahoo.com']){
  for(let attempt=0;attempt<2;attempt++){
   try{
    const url=`https://${host}/v8/finance/chart/${encodeURIComponent(symbol)}?range=${range}&interval=${interval}&includePrePost=false`;
    const data=await json(url),result=data.chart?.result?.[0],quote=result?.indicators?.quote?.[0];
    if(!result?.timestamp?.length||!quote?.close)throw Error('No historical bars');
    const bars=result.timestamp.map((timestamp,i)=>({timestamp,date:dateNY(timestamp),closeMinute:scheduledCloseMinute(dateNY(timestamp)),nextSession:nextTradingDay(dateNY(timestamp)),open:quote.open?.[i],close:quote.close[i],low:quote.low?.[i],high:quote.high?.[i],volume:quote.volume?.[i]})).filter(b=>Number.isFinite(b.close)&&b.close>0).sort((a,b)=>a.timestamp-b.timestamp);
    const saved={symbol,interval,range,downloadedAt:new Date().toISOString(),source:url,bars};
    await writeFile(path,JSON.stringify(saved));return saved;
   }catch(error){last=error;await new Promise(resolve=>setTimeout(resolve,1000*(attempt+1)))}
  }
 }
 throw last;
}
const companies=[];
for(const stock of [...cohort.stocks,{symbol:'^GSPC',name:'S&P 500'}]){
 const item={...stock,daily:[],hourly:[],newsTimeline:[]};
 for(const [interval,range] of [['1d','5y'],['1h','6mo']]){
  try{const saved=await download(stock.symbol,interval,range);item[interval==='1d'?'daily':'hourly']=saved.bars;console.log(`${stock.symbol}: ${saved.bars.length} ${interval} bars`)}catch(error){errors.push({symbol:stock.symbol,interval,error:error.message});console.error(`${stock.symbol} ${interval}: ${error.message}`)}
 }
 if(stock.symbol==='^GSPC')await writeFile(directory+'/market.json',JSON.stringify(item));else companies.push(item);
}
await writeFile(directory+'/historical-data.json',JSON.stringify({downloadedAt:new Date().toISOString(),cohort:cohort.stocks,companies,errors,newsMode:'price-only; archived point-in-time news snapshots unavailable',caveats:['Historical bars are downloaded today and may reflect later corrections or split adjustments.','The fixed cohort was selected this week, after the historical test period began. This is a retrospective test of that cohort, not point-in-time stock selection.']}));
console.log(`Saved ${companies.length} companies; ${errors.length} download errors`);
