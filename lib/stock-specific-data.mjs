import {trainingPrices} from './supervised-data.mjs';
import {easternSessionClock,currentOrNextForecastSession,scheduledCloseMinute,nextTradingDay,previousTradingDay} from './trading-calendar.mjs';

const sectorFunds={Technology:'XLK','Information Technology':'XLK',Healthcare:'XLV','Health Care':'XLV',Financials:'XLF','Financial Services':'XLF',Finance:'XLF','Consumer Cyclical':'XLY','Consumer Discretionary':'XLY','Consumer Defensive':'XLP','Consumer Staples':'XLP',Industrials:'XLI',Energy:'XLE','Basic Materials':'XLB',Materials:'XLB','Real Estate':'XLRE',Utilities:'XLU','Communication Services':'XLC',Telecommunications:'XLC'};
export function completedDaily(bars,now){
 return bars.filter(bar=>{
  const candidate=new Date(bar.date+'T20:00:00Z'),clock=easternSessionClock(candidate);
  const close=candidate.getTime()+(scheduledCloseMinute(bar.date)-clock.minute)*60000;
  return close+15*60000<=now.getTime();
 });
}

export async function collectStockSpecificData(data,{now=new Date(),fetchImpl=fetch,historyDays=2200}={}){
 const cohort=(data.report.top25||data.report.stocks||[]).slice(0,25).map(s=>s.symbol);
 const stocks=data.stocks,companies=[],errors=[],context={};let index=0;
 const pool=new Set(cohort),groups=new Map();
 for(const stock of [...stocks].sort((a,b)=>(b.marketCap||0)-(a.marketCap||0))){
  if(!(stock.marketCap>=20e9&&stock.marketCap<=200e9)||/\b(ETF|warrant|preferred|units?)\b/i.test(stock.name||''))continue;
  const sector=stock.sector||'Unknown';if(!groups.has(sector))groups.set(sector,[]);groups.get(sector).push(stock.symbol);
 }
 while(pool.size<100){let added=false;for(const group of groups.values()){while(group.length&&pool.has(group[0]))group.shift();if(group.length&&pool.size<100){pool.add(group.shift());added=true}}if(!added)break}
 if(pool.size<100)for(const stock of stocks){pool.add(stock.symbol);if(pool.size>=100)break}
 const targetDate=currentOrNextForecastSession(now),expectedLast=previousTradingDay(targetDate),clock=easternSessionClock(now);
 await Promise.all(Array.from({length:4},async()=>{while(index<stocks.length){const stock=stocks[index++];try{
  let prices;
  const cached=stock.predictionHistory||[...(stock.predictionBaseline||[]),...(stock.history||[])];
  const reusable=!pool.has(stock.symbol)&&cached.length>=100&&cached.every(b=>Array.isArray(b)&&b.length>=7&&[b[1],b[3],b[4],b[5],b[6]].every(Number.isFinite));
  if(reusable){
   const bars=new Map(cached.map(b=>[b[0],{date:b[0],close:b[1],low:b[3],high:b[4],open:b[5],volume:b[6],closeMinute:scheduledCloseMinute(b[0]),nextSession:nextTradingDay(b[0])}]));
   if(!bars.has(expectedLast)){
    const recent=await trainingPrices(stock.symbol,{now,fetchImpl,dailyOnly:true,historyDays:14,includeCorporateActions:true});
    for(const bar of recent.daily)bars.set(bar.date,bar);
   }
   prices={daily:[...bars.values()].sort((a,b)=>a.date.localeCompare(b.date)),hourly:[]};
  }else prices=await trainingPrices(stock.symbol,{now,fetchImpl,dailyOnly:true,historyDays:pool.has(stock.symbol)?historyDays:460,includeCorporateActions:true});
  let daily=completedDaily(prices.daily,now);
  if(!pool.has(stock.symbol)&&historyDays<=1000)daily=daily.slice(-100);
  const last=daily.at(-1);
  const ready=Boolean(last&&last.nextSession===targetDate);
  companies.push({symbol:stock.symbol,name:stock.name,sector:stock.sector||'Unknown',exchange:stock.exchange,daily,hourly:[],newsTimeline:[],sectorETF:stock.sectorETF||sectorFunds[stock.sector]||null,
   inferenceOnly:!cohort.includes(stock.symbol),sharedTraining:pool.has(stock.symbol),
   forecastContext:{state:ready?'ready':'stale',reason:'The model requires the complete session immediately before the forecast date',
    targetDate,inferenceDate:targetDate,inferenceMinute:540,baseDate:last?.date,basePrice:last?.close,
    quoteAsOf:last?.date,generatedAt:now.toISOString()}});
  if(index%250===0)console.log(`Prepared stock histories: ${index}/${stocks.length}`);
 }catch(error){errors.push({symbol:stock.symbol,source:'Stock-specific daily history',error:error.message})}}}));
 const symbols=['^GSPC','^VIX',...new Set(Object.values(sectorFunds))];index=0;
 await Promise.all(Array.from({length:4},async()=>{while(index<symbols.length){const symbol=symbols[index++];try{
  const prices=await trainingPrices(symbol,{now,fetchImpl,dailyOnly:true,historyDays,includeCorporateActions:true});
  context[symbol]={...prices,daily:completedDaily(prices.daily,now)};
 }catch(error){errors.push({symbol,source:'Stock-specific market context',error:error.message})}}}));
 if(!context['^GSPC']?.daily.length)throw Error('Complete market history is required');
 return {generatedAt:now.toISOString(),reportId:data.report.id,companies,context,market:context['^GSPC'].daily,
  availableLookback:data.report.filters.lookbackDays,universe:stocks.map(s=>({symbol:s.symbol,name:s.name})),errors,
  trainingHistoryDays:historyDays>1000?1825:365,generatedAfterOpen:clock.date===targetDate&&clock.minute>=570,
  newsMode:'Context only; model features are completed daily prices and volume'};
}
