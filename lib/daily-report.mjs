import {easternSessionClock,tradingDay,sessionExpired,previousTradingDay,nextTradingDay} from './trading-calendar.mjs';

export function completedSession(now=new Date()){
 const clock=easternSessionClock(now);
 return tradingDay(clock.date)&&sessionExpired(clock.date,now)?clock.date:previousTradingDay(clock.date);
}

export function buildDailyReport(data,forecasts,now=new Date()){
 const date=completedSession(now),targetDate=nextTradingDay(date),report=data.report;
 if(report.filters.lookbackDays<365||report.end<date||!sessionExpired(date,new Date(report.createdAt)))return null;
 if(forecasts.reportId!==report.id||forecasts.lookback!==365)throw Error('Daily report requires matching one-year forecasts');
 if(!forecasts.rows.some(f=>f.targetDate===targetDate))return null;
 const start=new Date(date+'T00:00:00Z');start.setUTCDate(start.getUTCDate()-364);const startDate=start.toISOString().slice(0,10);
 const forecastMap=new Map(forecasts.rows.map(f=>[f.symbol,f]));const candidates=[];
 for(const stock of data.stocks){
  if(!(stock.marketCap>=20e9&&stock.marketCap<=200e9))continue;
  const archive=stock.predictionHistory||[...(stock.predictionBaseline||[]),...(stock.history||[])];
  if(!archive.some(d=>d[0]<startDate))continue;
  const days=archive.filter(d=>d[0]>=startDate&&d[0]<=date).sort((a,b)=>a[0].localeCompare(b[0]));
  if(!days.length||days.at(-1)[0]!==date||days.some(d=>!Number.isFinite(d[2])))continue;
  const average=days.reduce((sum,d)=>sum+Math.abs(d[2]),0)/days.length;
  if(average>5)continue;
  const forecast=forecastMap.get(stock.symbol);
  const usable=forecast?.state==='estimated'&&forecast.returnBasis==='open-to-close'&&forecast.targetDate===targetDate&&Number.isFinite(forecast.estimatedPercent);
  candidates.push({symbol:stock.symbol,name:stock.name,marketCap:stock.marketCap,close:days.at(-1)[1],averageDailyMove:average,latestChange:days.at(-1)[2],predictionPercent:usable?forecast.estimatedPercent:null,predictionState:usable?'estimated':forecast?.state||'unavailable',predictionReason:usable?null:forecast?.reason||'A forecast for the next session is unavailable',targetDate,sessions:days.length});
 }
 candidates.sort((a,b)=>b.averageDailyMove-a.averageDailyMove||a.symbol.localeCompare(b.symbol));
 return {sessionDate:date,targetDate,generatedAt:now.toISOString(),scanId:report.id,scanCreatedAt:report.createdAt,historyDays:365,returnBasis:'open-to-close',filters:{minMarketCap:20e9,maxMarketCap:200e9,minAverage:0,maxAverage:5},matchingStocks:candidates.length,scannedStocks:data.stocks.length,sourceFailures:report.errors?.length||0,rows:candidates.slice(0,25).map((s,i)=>({rank:i+1,...s}))};
}

const pct=n=>Number.isFinite(n)?`${n>=0?'+':''}${n.toFixed(2)}%`:'Unavailable';
const safe=s=>String(s).replaceAll('|','\\|').replaceAll('\n',' ');
export function dailyReportMarkdown(report){
 return [`# Market-close prediction report · ${report.sessionDate}`,'',`Next trading session: **${report.targetDate}**. All predictions use **365 calendar days** and measure that session’s **open-to-close change**.`,`Filters: **$20B–$200B market cap**, **0–5% average absolute daily movement**. Ranked by movement, highest first.`, '', '| Rank | Company / ticker | Market cap | Closing price | Avg. daily move | Predicted open → close |','|---:|---|---:|---:|---:|---:|',...report.rows.map(s=>`| ${s.rank} | ${safe(s.name)} (${safe(s.symbol)}) | $${(s.marketCap/1e9).toFixed(2)}B | $${s.close.toFixed(2)} | ${s.averageDailyMove.toFixed(2)}% | ${pct(s.predictionPercent)} |`),'',`${report.matchingStocks} matches; showing ${report.rows.length}. ${report.sourceFailures} scan-source failures. Generated ${report.generatedAt}.`,'','“Variance” here means average absolute daily close-to-close movement, not statistical variance. Predictions are model outputs. Unavailable forecasts are left blank in the CSV.','',...report.rows.filter(s=>s.predictionPercent===null).map(s=>`${safe(s.symbol)}: ${safe(s.predictionReason)}`),''].join('\n');
}
export function dailyReportCSV(report){
 const columns=['Rank','Ticker','Company','Market_cap_USD','Closing_price_USD','Average_daily_move_percent','Forecast_session','Predicted_open_to_close_percent','History_calendar_days','Prediction_status','Reason'];
 const cell=value=>{let s=value==null?'':String(value);if(/^[=+@\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"'};
 return '\uFEFF'+[columns,...report.rows.map(s=>[s.rank,s.symbol,s.name,s.marketCap,s.close,s.averageDailyMove,report.targetDate,s.predictionPercent,365,s.predictionState,s.predictionReason])].map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n';
}
