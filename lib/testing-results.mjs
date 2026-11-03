import {tradingDay,sessionExpired} from './trading-calendar.mjs';
export function pacificClock(now=new Date()){
 const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now).map(x=>[x.type,x.value]));
 return {date:`${p.year}-${p.month}-${p.day}`,minute:Number(p.hour)*60+Number(p.minute)};
}
export function cutoffAt(date){
 const candidate=new Date(date+'T14:00:00Z'),clock=pacificClock(candidate);
 return new Date(candidate.getTime()-(clock.minute-360)*60000).toISOString();
}
export function extendTest(previous,now=new Date()){
 const result=structuredClone(previous);
 const dates=new Set(result.dates),keys=new Set(result.entries.map(e=>`${e.date}:${e.symbol}`));
 const through=['2026-10-30',pacificClock(now).date].sort().at(-1);
 for(let day=new Date('2026-10-26T00:00:00Z');day.toISOString().slice(0,10)<=through;day.setUTCDate(day.getUTCDate()+1)){
  const date=day.toISOString().slice(0,10);if(!tradingDay(date))continue;dates.add(date);
  for(const stock of result.stocks){const key=`${date}:${stock.symbol}`;if(keys.has(key))continue;
   result.entries.push({date,symbol:stock.symbol,cutoffAt:cutoffAt(date),prediction:null,actual:null,status:'pending'});keys.add(key);
  }
 }
 result.dates=[...dates].sort();return result;
}
export function restoreSavedPredictions(previous,history,now=new Date(),selection=null){
 const result=structuredClone(previous);
 for(const entry of result.entries){
  // Append later trading days; previously frozen forecasts remain unchanged.
  if(entry.date<'2026-10-26'||now.getTime()<Date.parse(entry.cutoffAt))continue;
  const candidates=(history.records||[]).filter(r=>(!selection||entry.date<selection.activationDate||r.modelVersion===selection.version)&&r.symbol===entry.symbol&&r.targetDate===entry.date&&r.lookback===365&&r.returnBasis==='open-to-close'&&Number.isFinite(r.estimatedPercent)&&Date.parse(r.generatedAt)<=now.getTime());
  candidates.sort((a,b)=>Date.parse(a.generatedAt)-Date.parse(b.generatedAt));
  const row=candidates.find(r=>Date.parse(r.generatedAt)<Date.parse(entry.cutoffAt));
  if(!entry.prediction&&row)entry.prediction={percent:row.estimatedPercent,generatedAt:row.generatedAt,observedAt:now.toISOString(),modelVersion:row.modelVersion,source:'Saved published prediction-history.json',historyId:row.id,recoveredFromHistory:true};
  for(const late of candidates.filter(r=>r.generatedAfterOpen&&Date.parse(r.generatedAt)>=Date.parse(entry.cutoffAt))){
   entry.lateForecasts??=[];
   if(!entry.lateForecasts.some(r=>r.modelVersion===late.modelVersion&&r.generatedAt===late.generatedAt))entry.lateForecasts.push({percent:late.estimatedPercent,generatedAt:late.generatedAt,observedAt:now.toISOString(),modelVersion:late.modelVersion,generatedAfterOpen:true,historyId:late.id,recoveredFromHistory:true,source:'Saved published after-open forecast; excluded from morning test'});
  }
 }
 return result;
}
export function createTest(report,now=new Date()){
 // Fixed requested test week: do not move it if the first deployment is late.
 const monday=new Date('2026-10-19T00:00:00Z');
 const dates=[];for(let i=0;i<5;i++){const d=new Date(monday);d.setUTCDate(d.getUTCDate()+i);const date=d.toISOString().slice(0,10);if(tradingDay(date))dates.push(date)}
 if(!Array.isArray(report.rows)||report.rows.length!==25||new Set(report.rows.map(s=>s.symbol)).size!==25)throw Error('Testing requires the published set of 25 stocks');
 const stocks=report.rows.map(s=>({symbol:s.symbol,name:s.name,exchange:s.exchange}));
 return {version:1,createdAt:now.toISOString(),cohortSession:report.sessionDate,historyDays:365,returnBasis:'open-to-close',dates,stocks,entries:dates.flatMap(date=>stocks.map(s=>({date,symbol:s.symbol,cutoffAt:cutoffAt(date),prediction:null,actual:null,status:'pending'})))};
}
export function updateTest(previous,snapshot,prices,now=new Date(),selection=null){
 const result=structuredClone(previous),clock=pacificClock(now);const observedAt=now.toISOString();
 const forecasts=new Map((snapshot.rows||[]).map(row=>[row.symbol,row]));const actuals=new Map(prices.map(stock=>[stock.symbol,stock.daily]));
 for(const entry of result.entries){
  const before=now.getTime()<Date.parse(entry.cutoffAt);
  const forecast=forecasts.get(entry.symbol);
  // Read only the already-public forecast feed. Keep the first eligible morning
  // prediction unchanged, even if later scans or models give a different number.
  if(!entry.prediction&&(!selection||entry.date<selection.activationDate||snapshot.modelVersion===selection.version)&&clock.date===entry.date&&before&&snapshot.lookback===365&&forecast?.state==='estimated'&&forecast.lookback===365&&forecast.returnBasis==='open-to-close'&&forecast.targetDate===entry.date&&Number.isFinite(forecast.estimatedPercent)&&Date.parse(snapshot.generatedAt)<=now.getTime()){
   entry.prediction={percent:forecast.estimatedPercent,generatedAt:snapshot.generatedAt,observedAt,reportId:snapshot.reportId,modelVersion:snapshot.modelVersion,source:'Published predictions/365.json'};
  }
  if(forecast?.generatedAfterOpen&&forecast.state==='estimated'&&forecast.targetDate===entry.date&&forecast.returnBasis==='open-to-close'&&Number.isFinite(forecast.estimatedPercent)&&Date.parse(snapshot.generatedAt)>=Date.parse(entry.cutoffAt)&&Date.parse(snapshot.generatedAt)<=now.getTime()){
   const version=forecast.modelVersion||snapshot.modelVersion;
   entry.lateForecasts??=[];
   const generatedAt=forecast.generatedAt||snapshot.generatedAt;
   if(!entry.lateForecasts.some(f=>f.modelVersion===version&&f.generatedAt===generatedAt))entry.lateForecasts.push({percent:forecast.estimatedPercent,generatedAt,observedAt,modelVersion:version,generatedAfterOpen:true,source:'New model forecast generated after open; excluded from morning test'});
  }
  if(!entry.actual&&sessionExpired(entry.date,now)){
   const day=actuals.get(entry.symbol)?.find(day=>day.date===entry.date);
   if(Number.isFinite(day?.open)&&Number.isFinite(day?.close)&&day.open>0&&day.close>0){entry.actual={open:day.open,close:day.close,percent:(day.close/day.open-1)*100,recordedAt:observedAt};}
  }
  entry.status=entry.prediction?(entry.actual?'compared':sessionExpired(entry.date,now)?'awaiting-price':'awaiting-close'):before?'pending':'missed-cutoff';
  if(entry.prediction&&entry.actual){entry.errorPoints=Math.abs(entry.prediction.percent-entry.actual.percent);entry.directionCorrect=Math.sign(entry.prediction.percent)===Math.sign(entry.actual.percent);}
  if(entry.actual)for(const late of entry.lateForecasts||[]){late.actualPercent=entry.actual.percent;late.errorPoints=Math.abs(late.percent-entry.actual.percent);late.directionCorrect=Math.sign(late.percent)===Math.sign(entry.actual.percent);}
 }
 result.updatedAt=observedAt;return result;
}
