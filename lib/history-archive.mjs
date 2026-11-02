// Persistent archive format. Prices are provider-reported, with adjustment metadata retained.
import {createHash} from 'node:crypto';
import {sessionExpired,easternSessionClock,tradingDay} from './trading-calendar.mjs';
const nyDate=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'});
export const ARCHIVE_SCHEMA=1;
export const CSV_COLUMNS=['symbol','interval','timestamp','session_date','open','high','low','close','volume','adjusted_close','corporate_actions','observed_at','source'];
export const BASE_TAG='testing-stock-history-v1';
export const shardFor=(symbol,count=8)=>createHash('sha256').update(symbol).digest().readUInt32BE(0)%count;
export const csvCell=value=>value==null?'':/[",\r\n]/.test(String(value))?'"'+String(value).replaceAll('"','""')+'"':String(value);
export const csvLine=values=>values.map(csvCell).join(',')+'\n';
export const barCSV=bar=>csvLine(CSV_COLUMNS.map(key=>bar[key]));
export function archiveURL(symbol,interval,{now=new Date(),since=null}={}){
 if(!['1d','5m'].includes(interval))throw Error('Unsupported archive interval');
 const u=new URL('https://query1.finance.yahoo.com/v8/finance/chart/'+encodeURIComponent(symbol.replaceAll('.','-')));
 const end=Math.floor(now.getTime()/1000);
 const start=interval==='1d'?(since==null?-2208988800:since):Math.max(end-58*86400,since==null?end-7*86400:since);
 u.search=new URLSearchParams({period1:String(Math.floor(start)),period2:String(end),interval,includePrePost:'false',events:'div,splits'}).toString();return u;
}
export async function discoverArchiveUniverse(fetchImpl=fetch){
 const lists=await Promise.all(['NASDAQ','NYSE'].map(async exchange=>{
  const response=await fetchImpl('https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&exchange='+exchange.toLowerCase(),{headers:{'User-Agent':'Mozilla/5.0',Accept:'application/json',Origin:'https://www.nasdaq.com'},signal:AbortSignal.timeout(30000)});
  if(!response.ok)throw Error('Universe HTTP '+response.status+' for '+exchange);
  const payload=await response.json(),rows=payload.data?.table?.rows,total=Number(payload.data?.totalrecords);
  if(!Array.isArray(rows)||!rows.length||!Number.isFinite(total)||rows.length<total||rows.length>=10000)throw Error(exchange+' listing response is empty or truncated');
  return rows.map(s=>({symbol:s.symbol,name:s.name,exchange,sector:s.sector||'Unknown',kind:'listing'}));
 }));
 const bySymbol=new Map();for(const listing of lists.flat()){
  if(typeof listing.symbol!=='string'||!listing.symbol.trim())throw Error('Invalid listing symbol');bySymbol.set(listing.symbol,listing);
 }
 const stocks=[...bySymbol.values()].sort((a,b)=>a.symbol.localeCompare(b.symbol));
 if(!stocks.some(s=>s.exchange==='NASDAQ')||!stocks.some(s=>s.exchange==='NYSE'))throw Error('Both exchanges are required');
 return {schemaVersion:ARCHIVE_SCHEMA,createdAt:new Date().toISOString(),scope:'All current NASDAQ and NYSE listings; chart metadata identifies supported equities. No market-cap or volatility filter.',stocks};
}
export function parseArchiveChart(symbol,payload,interval,now=new Date()){
 const result=payload.chart?.result?.[0];if(payload.chart?.error||!result)throw Error(payload.chart?.error?.description||'Missing chart result');
 const meta=result.meta||{};
 if(meta.instrumentType!=='EQUITY'||!['NMS','NGM','NCM','NAS','NYQ','NYSE'].includes(meta.exchangeName))return {status:'unsupported',bars:[],reason:'Provider does not identify this listing as a NASDAQ/NYSE equity',providerType:meta.instrumentType,providerExchange:meta.exchangeName};
 const timestamps=result.timestamp,quotes=result.indicators?.quote?.[0],adjusted=result.indicators?.adjclose?.[0]?.adjclose;
 if(!Array.isArray(timestamps)||!quotes)throw Error('Missing chart arrays');
 const actions=new Map();for(const [kind,events] of Object.entries(result.events||{}))for(const event of Object.values(events||{})){
  if(!Number.isFinite(event.date))continue;const date=nyDate.format(new Date(event.date*1000));if(!actions.has(date))actions.set(date,[]);actions.get(date).push({kind,...event});
 }
 const bars=[],seen=new Set(),today=easternSessionClock(now).date;const todayClosed=sessionExpired(today,new Date(now.getTime()-15*60000));let invalid=0,incomplete=0;
 for(let i=0;i<timestamps.length;i++){
  const ts=timestamps[i],date=Number.isFinite(ts)?nyDate.format(new Date(ts*1000)):null;
  const [open,high,low,close]=['open','high','low','close'].map(k=>quotes[k]?.[i]);
  if(!date||![open,high,low,close].every(v=>Number.isFinite(v)&&v>0)||low>Math.min(open,close)+1e-5||high<Math.max(open,close)-1e-5||low>high){invalid++;continue;}
  // A daily label becomes eligible 15 minutes after the scheduled market close.
  const complete=interval==='1d'?(date<today||date===today&&todayClosed):ts+300<=now.getTime()/1000-90;
  if(!complete){incomplete++;continue;}
  const key=interval==='1d'?date:ts;if(seen.has(key))throw Error('Duplicate bars in provider response');seen.add(key);
  bars.push({symbol,interval,timestamp:ts,session_date:date,open,high,low,close,volume:Number.isFinite(quotes.volume?.[i])&&quotes.volume[i]>=0?quotes.volume[i]:null,
   adjusted_close:Number.isFinite(adjusted?.[i])?adjusted[i]:null,corporate_actions:JSON.stringify(actions.get(date)||[]),observed_at:now.toISOString(),source:'Yahoo Finance chart'});
 }
 bars.sort((a,b)=>a.timestamp-b.timestamp);
 const first=bars[0],last=bars.at(-1),warnings=[];
 if(interval==='1d'&&first&&Number.isFinite(meta.firstTradeDate)&&first.timestamp-meta.firstTradeDate>14*86400)warnings.push('Provider history starts later than its reported first-trade date');
 if(invalid)warnings.push(invalid+' invalid/incomplete OHLC rows rejected');
 return {status:bars.length?'saved':'empty',bars,firstDate:first?.session_date,lastDate:last?.session_date,lastTimestamp:last?.timestamp,
  lastSplitTimestamp:Math.max(0,...Object.values(result.events?.splits||{}).map(e=>e.date).filter(Number.isFinite)),firstTradeTimestamp:meta.firstTradeDate??null,invalidRows:invalid,incompleteRows:incomplete,warnings,currency:meta.currency||null,exchangeTimezone:meta.exchangeTimezoneName||null};
}
export function updateWindow(checkpoint,interval,now=new Date()){
 const end=Math.floor(now.getTime()/1000),last=checkpoint?.[interval]?.lastTimestamp;
 if(interval==='1d')return {since:last==null?end-10*86400:last-10*86400,gap:null};
 return {since:last==null?end-7*86400:Math.max(end-58*86400,last-1800),gap:last!=null&&last<end-58*86400?'Intraday gap exceeds provider retention; older missing bars cannot be recovered from this feed':null};
}
export function shouldCollect(now=new Date()){
 const c=easternSessionClock(now);return tradingDay(c.date)&&c.minute>=570&&c.minute<=1005;
}
export function mergedCheckpoint(previous,results,observedAt){
 const next=structuredClone(previous||{schemaVersion:ARCHIVE_SCHEMA,symbols:{}});next.updatedAt=observedAt;
 for(const result of results){
  const current=next.symbols[result.symbol]||{symbol:result.symbol};const entry={...current,lastAttemptAt:observedAt};
  if(result.status==='error')entry.lastError=result.error;
  else if(result.status==='unsupported'){entry.status='unsupported';entry.reason=result.reason;}
  else{
   entry.lastError=null;
   for(const record of result.intervals||[]){const before=current[record.interval]||{};entry[record.interval]={...before,lastCheckedAt:observedAt};
    if(record.lastTimestamp!=null){entry[record.interval].lastTimestamp=Math.max(before.lastTimestamp??-Infinity,record.lastTimestamp);entry[record.interval].firstDate=[before.firstDate,record.firstDate].filter(Boolean).sort()[0];entry[record.interval].lastDate=[before.lastDate,record.lastDate].filter(Boolean).sort().at(-1);}
    entry[record.interval].lastSplitTimestamp=Math.max(before.lastSplitTimestamp||0,record.lastSplitTimestamp||0);entry[record.interval].warnings=record.warnings||[];if(record.gap)entry[record.interval].gap=record.gap;
   }
   // Only a full daily request can mark initial history as backfilled.
   if(result.backfill&&result.intervals?.some(r=>r.interval==='1d'&&r.status==='saved'))entry.status='backfilled';
  }
  next.symbols[result.symbol]=entry;
 }
 return next;
}
