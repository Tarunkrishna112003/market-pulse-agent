import {normalizeFilters} from './filters.mjs';
import {stockHistory} from './stock-history.mjs';
import {forecastSessionForModel,sessionExpired} from './trading-calendar.mjs';

export function parseRanges(values){
 const number=(key,fallback)=>values[key]==null||values[key]===''?fallback:Number(values[key]);
 return normalizeFilters({minMarketCap:number('minCap',20)*1e9,maxMarketCap:number('maxCap',200)*1e9,
  minAverage:number('minMove',0),maxAverage:number('maxMove',null),lookbackDays:number('days',30)});
}

export function movementRows(data,filters){
 if(filters.lookbackDays>data.report.filters.lookbackDays)throw Error(`This snapshot contains ${data.report.filters.lookbackDays} days. Choose a shorter lookback.`);
 const start=new Date(data.report.end+'T00:00:00Z');start.setUTCDate(start.getUTCDate()-filters.lookbackDays+1);const from=start.toISOString().slice(0,10);
 return data.stocks.flatMap(stock=>{
  if(!Number.isFinite(stock.marketCap)||stock.marketCap<filters.minMarketCap||stock.marketCap>filters.maxMarketCap)return [];
  const days=(stock.history||[]).filter(d=>d[0]>=from&&d[0]<=data.report.end&&Number.isFinite(d[2]));if(!days.length)return [];
  const average=days.reduce((sum,d)=>sum+Math.abs(d[2]),0)/days.length;
  if(average<filters.minAverage||filters.maxAverage!==null&&average>filters.maxAverage)return [];
  return [{...stock,average,sessions:days.length,change:days.at(-1)[2]}];
 }).sort((a,b)=>b.average-a.average||a.symbol.localeCompare(b.symbol));
}

export function usableForecast(forecast,now=new Date()){
 return Boolean(forecast?.state==='estimated'&&forecast.returnBasis==='open-to-close'&&forecast.forecastModel==='supervised'&&Number.isFinite(forecast.estimatedPercent)&&forecast.targetDate===forecastSessionForModel(forecast,now)&&!sessionExpired(forecast.targetDate,now));
}

export function predictionRows(data,forecasts,options,now=new Date()){
 const filters=parseRanges(options),min=options.minPrediction===''||options.minPrediction==null?null:Number(options.minPrediction),max=options.maxPrediction===''||options.maxPrediction==null?null:Number(options.maxPrediction);
 if(min!==null&&!Number.isFinite(min)||max!==null&&!Number.isFinite(max)||min!==null&&max!==null&&min>max)throw Error('Enter a valid minimum and maximum predicted change.');
 return movementRows(data,filters).flatMap(stock=>{
  const forecast=forecasts.get(stock.symbol),available=usableForecast(forecast,now),p=available?forecast.estimatedPercent:null;
  if(options.availableOnly&&!available)return [];
  if((min!==null||max!==null||options.direction&&options.direction!=='all')&&!available)return [];
  if(min!==null&&p<min||max!==null&&p>max||options.direction==='positive'&&p<=0||options.direction==='negative'&&p>=0)return [];
  return [{...stock,forecast,available}];
 }).sort((a,b)=>Number(b.available)-Number(a.available)||(Math.abs(b.forecast?.estimatedPercent||0)-Math.abs(a.forecast?.estimatedPercent||0))||a.symbol.localeCompare(b.symbol));
}

export function searchStocks(stocks,query='',mode='all',watchlist=new Set()){
 const q=query.trim().toLowerCase(),words=q.split(/\s+/).filter(Boolean);
 const result=stocks.filter(s=>words.every(w=>(s.symbol+' '+s.name).toLowerCase().includes(w))&&(mode!=='gainers'||s.change>0)&&(mode!=='decliners'||s.change<0)&&(mode!=='watchlist'||watchlist.has(s.symbol)));
 return result.sort((a,b)=>{
  if(q){const rank=s=>s.symbol.toLowerCase()===q?0:s.symbol.toLowerCase().startsWith(q)?1:2;const delta=rank(a)-rank(b);if(delta)return delta;}
  if(mode==='gainers')return (b.change||0)-(a.change||0)||a.symbol.localeCompare(b.symbol);
  if(mode==='decliners')return (a.change||0)-(b.change||0)||a.symbol.localeCompare(b.symbol);
  return (b.marketCap||0)-(a.marketCap||0)||a.symbol.localeCompare(b.symbol);
 });
}

export function historyView(stock,report,days){
 const result=stockHistory(stock,report,days),raw=stock.predictionHistory||[...(stock.predictionBaseline||[]),...(stock.history||[])];
 const prices=raw.map(d=>Array.isArray(d)?{date:d[0],close:d[1],volume:d[6]}:d).sort((a,b)=>a.date.localeCompare(b.date));
 const first=result.days[0],last=result.days.at(-1);const baseline=first?prices.filter(d=>d.date<first.date&&Number.isFinite(d.close)&&d.close>0).at(-1)||first:null;
 const volume=new Map(prices.map(d=>[d.date,d.volume]));
 return {...result,days:result.days.map(d=>({...d,volume:volume.get(d.date)})),
  returnPercent:baseline&&last&&baseline.close>0?(last.close/baseline.close-1)*100:null,
  baselineDate:baseline?.date,firstDate:first?.date,lastDate:last?.date};
}

export function testDayView(data,date,variant='morning'){
 const entries=new Map(data.entries.filter(e=>e.date===date).map(e=>[e.symbol,e]));
 const rows=data.stocks.map(stock=>{
  const entry=entries.get(stock.symbol);const late=[...(entry?.lateForecasts||[])].sort((a,b)=>String(a.generatedAt).localeCompare(String(b.generatedAt))).at(-1);
  const prediction=variant==='late'?late:entry?.prediction,actual=entry?.actual;
  const compared=Number.isFinite(prediction?.percent)&&Number.isFinite(actual?.percent);
  return {stock,entry,prediction,actual,compared,error:compared?Math.abs(prediction.percent-actual.percent):null,
   directionCorrect:compared?Math.sign(prediction.percent)===Math.sign(actual.percent):null};
 });
 const scored=rows.filter(r=>r.compared);
 return {rows,total:rows.length,predicted:rows.filter(r=>Number.isFinite(r.prediction?.percent)).length,
  compared:scored.length,correct:scored.filter(r=>r.directionCorrect).length,
  mae:scored.length?scored.reduce((sum,r)=>sum+r.error,0)/scored.length:null};
}

export function csvText(headers,rows){
 const escape=value=>{let text=value==null?'':String(value);if(typeof value==='string'&&/^[=+@\-\t\r]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"'};
 return '\uFEFF'+[headers,...rows].map(row=>row.map(escape).join(',')).join('\r\n')+'\r\n';
}
