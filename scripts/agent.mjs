import {attachMarketNews} from '../lib/stock-news.mjs';
import {universe,scanStock,dates,makeReport} from '../lib/screener.mjs';
import {writeFile} from 'node:fs/promises';
const key=process.env.FMP_API_KEY;
const w=dates(),stocks=await universe(key),results=[],errors=[];
for(const s of stocks){try{results.push(await scanStock(s,w,key));}catch(e){errors.push({symbol:s.symbol,error:e.message});}await new Promise(r=>setTimeout(r,300));}
const report=makeReport(results,errors,w,stocks.length);
await attachMarketNews(report);
console.table(report.stocks.map((s,i)=>({rank:i+1,ticker:s.symbol,name:s.name,marketCapUSD:s.marketCap,averageAbsoluteDailyPercent:s.average.toFixed(2),latestDailyPercent:s.change.toFixed(2)})));
await writeFile(process.env.REPORT_PATH||'outputs/report.json',JSON.stringify(report,null,2));
if(process.env.SITE_URL){const r=await fetch(new URL('/api/reports',process.env.SITE_URL),{method:'POST',headers:{'Content-Type':'application/json',...(process.env.AGENT_TOKEN?{Authorization:'Bearer '+process.env.AGENT_TOKEN}:{Origin:new URL(process.env.SITE_URL).origin})},body:JSON.stringify(report)});if(!r.ok)throw Error('Dashboard upload failed: '+r.status);}
console.log(`${results.length}/${stocks.length} screened; ${errors.length} errors.`);if(errors.length)process.exitCode=1;
