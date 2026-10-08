'use client';
import {useEffect,useState} from 'react';
import {useParams,useSearchParams} from 'next/navigation';
import {Table,TableHeader,TableBody,TableRow,TableHead,TableCell} from '@/components/ui/table';
import {stockHistory} from '@/lib/stock-history.mjs';
const money=(value:number)=>Number.isFinite(value)?'$'+value.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
export default function StockPage(){
 const params=useParams(),search=useSearchParams(),symbol=String(params.symbol||''),reportId=search.get('report'),daysParam=search.get('days');
 const [view,setView]=useState<any>(null),[message,setMessage]=useState('Loading stock history…');
 useEffect(()=>{let cancelled=false;setView(null);setMessage('Loading stock history…');
 async function load(){try{
  const response=await fetch('/api/reports',{cache:'no-store'});if(!response.ok)throw Error('Stock history is temporarily unavailable.');const reports=await response.json();
  const report=reportId?reports.find((r:any)=>r.id===reportId):reports[0];if(!report)throw Error('This saved report is no longer available. Return to the screener to open the latest report.');
  const stock=(report.top25||report.stocks||[]).find((s:any)=>s.symbol===symbol);if(!stock)throw Error('This stock has no history in the selected report.');
  const days=Number(daysParam||report.filters.lookbackDays),result=stockHistory(stock,report,days);if(cancelled)return;
  setView({stock,report,days,result});setMessage(`Scan completed ${new Date(report.createdAt).toLocaleString()}.${result.missingRanges?' Daily lows and highs are missing for some sessions; those values show — until a new scan supplies them.':''}`);
 }catch(e:any){if(!cancelled)setMessage(e.message)}}void load();return()=>{cancelled=true};
 },[symbol,reportId,daysParam]);
 return <main className="stock-history-page"><a className="quiet" href="/">← Back to stock screener</a><div className="heading"><div><div className="eyebrow">DAILY PRICE HISTORY · USD</div><h1>{view?`${view.stock.name} (${view.stock.symbol})`:symbol}</h1>{view&&<p>{view.result.start} through {view.result.end} · {view.days} calendar days · {view.result.days.length} trading sessions</p>}</div></div><p className="status" role="status">{message}</p>{view&&<section className="results"><div className="table-wrap"><Table><TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Low</TableHead><TableHead>High</TableHead><TableHead>Close</TableHead><TableHead>Daily change</TableHead></TableRow></TableHeader><TableBody>{view.result.days.map((d:any)=><TableRow key={d.date}><TableCell>{d.date}</TableCell><TableCell>{d.low===view.result.minLow?<b>{money(d.low)}</b>:money(d.low)}</TableCell><TableCell>{d.high===view.result.maxHigh?<b>{money(d.high)}</b>:money(d.high)}</TableCell><TableCell>{money(d.close)}</TableCell><TableCell className={d.change>=0?'up':'down'}>{Number.isFinite(d.change)?`${d.change>=0?'+':''}${d.change.toFixed(2)}%`:'—'}</TableCell></TableRow>)}</TableBody></Table>{!view.result.days.length&&<p className="empty">No trading sessions are available within the selected window.</p>}</div><p className="coverage-disclaimer">Daily change is the close-to-close return from the previous trading session. Weekends and market holidays have no rows. Bold prices mark the lowest daily low and highest daily high among displayed sessions.</p></section>}</main>;
}
