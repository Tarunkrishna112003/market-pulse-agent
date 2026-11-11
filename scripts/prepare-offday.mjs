import {mkdir,writeFile} from 'node:fs/promises';
import {collectStockSpecificData,completedDaily} from '../lib/stock-specific-data.mjs';
import {trainingPrices} from '../lib/supervised-data.mjs';
import {easternSessionClock,tradingDay,scheduledCloseMinute,previousTradingDay,nextTradingDay} from '../lib/trading-calendar.mjs';

const now=new Date();
const pacific=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now).map(p=>[p.type,p.value]));
const today=`${pacific.year}-${pacific.month}-${pacific.day}`;
const minutes=Number(pacific.hour)*60+Number(pacific.minute);
const calendar={};
for(let d=new Date(now.getTime()-370*86400000);d<=new Date(now.getTime()+14*86400000);d.setUTCDate(d.getUTCDate()+1)){
 const date=d.toISOString().slice(0,10);
 if(tradingDay(date))calendar[date]={previous:previousTradingDay(date),closeMinute:scheduledCloseMinute(date)};
}
const eastern=easternSessionClock(now);
const morning=tradingDay(today)&&minutes>=300&&minutes<375;
const closing=tradingDay(today)&&eastern.minute>=scheduledCloseMinute(today)+15&&eastern.minute<scheduledCloseMinute(today)+150;
const initialize=process.argv.includes('--initialize');
const phase=initialize?'initialize':morning?'morning':closing?'closing':'skip';
await mkdir('work/offday',{recursive:true});
if(phase==='skip'){
 await writeFile('work/offday/control.json',JSON.stringify({phase}));
 console.log('Outside the morning and closing windows.');
 process.exit(0);
}
if(morning&&!initialize){
 const previous=await fetch('https://raw.githubusercontent.com/Tarunkrishna112003/market-pulse-agent/offday-predictions-data/index.json?check='+Date.now(),{signal:AbortSignal.timeout(20000)});
 if(previous.ok){
  const index=await previous.json();
  if(index.lastRun?.date===today&&index.lastRun?.estimated===index.stocks.length){
   await writeFile('work/offday/control.json',JSON.stringify({phase:'skip'}));
   console.log('Every stock already has its saved forecast for this trading day.');process.exit(0);
  }
 }
 if(!previous.ok&&previous.status!==404)throw Error('Cannot verify existing off-day archive: '+previous.status);
}
const source=await fetch('https://tarunkrishna112003.github.io/market-pulse-agent/data.json',{signal:AbortSignal.timeout(180000)});
if(!source.ok)throw Error('Cannot load the scanned stock universe: '+source.status);
const data=await source.json();
if(!data.report?.id||!Array.isArray(data.stocks)||!data.stocks.length)throw Error('Invalid stock universe');
const universe=data.stocks.map(s=>({symbol:s.symbol,name:s.name||s.symbol,exchange:s.exchange||null}));
const control={phase,today,generatedAt:now.toISOString(),sourceReportId:data.report.id,universe,calendar,
 activationDate:initialize?nextTradingDay(today):today};
await writeFile('work/offday/control.json',JSON.stringify(control));
if(initialize)process.exit(0);

let dataset;
if(morning){
 dataset=await collectStockSpecificData(data,{now,historyDays:2200});
 // Both US zones change DST together. 05:00 Pacific is 08:00 Eastern.
 const cutoffClock=new Date(now);cutoffClock.setUTCSeconds(0,0);
 const cutoffSeconds=Math.floor((cutoffClock.getTime()+(480-eastern.minute)*60000)/1000);
 let cursor=0;
 await Promise.all(Array.from({length:6},async()=>{
  while(cursor<dataset.companies.length){
   const company=dataset.companies[cursor++];
   const url=new URL('https://query1.finance.yahoo.com/v8/finance/chart/'+encodeURIComponent(company.symbol.replaceAll('.','-')));
   url.searchParams.set('interval','1h');url.searchParams.set('includePrePost','true');
   url.searchParams.set('period1',String(cutoffSeconds-(company.sharedTraining?729:7)*86400));
   url.searchParams.set('period2',String(cutoffSeconds));
   try{
    let response;
    for(let attempt=0;attempt<3;attempt++){
     response=await fetch(url,{headers:{'User-Agent':'Mozilla/5.0'},signal:AbortSignal.timeout(25000)});
     if(response.ok||![429,500,502,503,504].includes(response.status))break;
     await new Promise(resolve=>setTimeout(resolve,1500*(attempt+1)));
    }
    if(!response.ok)throw Error('HTTP '+response.status);
    const result=(await response.json()).chart?.result?.[0],quote=result?.indicators?.quote?.[0];
    if(!result?.timestamp||!quote)throw Error('No hourly history');
    company.hourly=result.timestamp.map((timestamp,i)=>({timestamp,durationSeconds:3600,open:quote.open?.[i],high:quote.high?.[i],low:quote.low?.[i],close:quote.close?.[i],volume:quote.volume?.[i]}));
   }catch(error){company.hourly=[];dataset.errors.push({symbol:company.symbol,source:'Off-day extended hours',error:error.message});}
   if(cursor%250===0)console.log(`Extended-hours histories ${cursor}/${dataset.companies.length}`);
  }
 }));
}else{
 dataset={companies:[],errors:[]};
 let cursor=0;
 await Promise.all(Array.from({length:6},async()=>{
  while(cursor<data.stocks.length){
   const stock=data.stocks[cursor++];
   const daily=[...(stock.predictionBaseline||[]),...(stock.history||[])].map(b=>({date:b[0],close:b[1],open:b[5],high:b[4],low:b[3],volume:b[6]}));
   if(!daily.some(b=>b.date===today)){
    try{
     const recent=await trainingPrices(stock.symbol,{now,dailyOnly:true,historyDays:7});
     const merged=new Map(daily.map(b=>[b.date,b]));
     for(const bar of completedDaily(recent.daily,now))merged.set(bar.date,bar);
     dataset.companies.push({symbol:stock.symbol,daily:[...merged.values()]});
    }catch(error){dataset.companies.push({symbol:stock.symbol,daily});dataset.errors.push({symbol:stock.symbol,error:error.message});}
   }else dataset.companies.push({symbol:stock.symbol,daily});
  }
 }));
}
await writeFile('work/offday/dataset.json',JSON.stringify(dataset));
console.log(JSON.stringify({phase,stocks:universe.length,companies:dataset.companies.length,sourceFailures:dataset.errors.length}));
