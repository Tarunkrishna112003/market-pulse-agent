import {mkdir,writeFile,copyFile} from 'node:fs/promises';
import {attachStockNews} from '../lib/stock-news.mjs';
import {publicUniverse} from '../lib/public-market.mjs';
import {provider,scanStock,dates,makeReport} from '../lib/screener.mjs';
import {normalizeFilters} from '../lib/filters.mjs';
import {csv,summaryRows} from '../lib/csv-report.mjs';
const filters=normalizeFilters({lookbackDays:Number(process.env.LOOKBACK_DAYS||30),minMarketCap:Number(process.env.MIN_CAP_B||20)*1e9,maxMarketCap:Number(process.env.MAX_CAP_B||100)*1e9,minAverage:Number(process.env.MIN_MOVE||5),maxAverage:process.env.MAX_MOVE?Number(process.env.MAX_MOVE):null});
const window=dates(new Date(),filters.lookbackDays),key=process.env.FMP_API_KEY;
let listing;
try{listing=await publicUniverse({all:true})}catch{if(!key)throw Error('NASDAQ / NYSE discovery unavailable and FMP key not configured');listing=(await Promise.all(['NASDAQ','NYSE'].map(exchange=>provider('company-screener',{exchange,isEtf:false,isFund:false,isActivelyTrading:true,limit:10000},key).then(rows=>{if(!rows.length||rows.length>=10000)throw Error(exchange+' universe unavailable or truncated');return rows.map(s=>({...s,exchangeShortName:exchange}))})))).flat();if(!listing.length)throw Error('FMP universe unavailable or truncated');listing=listing.filter(s=>!s.isEtf&&!s.isFund).map(s=>({...s,_source:'fmp',marketCapAsOf:new Date().toISOString()}));}
const results=[],errors=[];let index=0;
async function worker(){while(index<listing.length){const s=listing[index++];try{results.push(await scanStock(s,window,key))}catch(e){errors.push({symbol:s.symbol,error:e.message})}if((results.length+errors.length)%100===0)console.log(`${results.length+errors.length}/${listing.length} attempted; ${errors.length} failed`);await new Promise(r=>setTimeout(r,500));}}
await Promise.all(Array.from({length:3},worker));
if(!results.length)throw Error('No valid stock histories returned; preserving previously published results');
const report=makeReport(results,errors,window,listing.length,filters);
await attachStockNews(report);
report.research={state:'disabled',reason:'Public GitHub scanner publishes calculated market data; local Ollama research remains available in the local app.'};
const stocks=results.map(({days,...s})=>({...s,history:days.map(d=>[d.date,d.close,d.change])}));
await mkdir('public-site',{recursive:true});
for(const file of ['index.html','app.js','style.css'])await copyFile('github-pages/'+file,'public-site/'+file);
await writeFile('public-site/.nojekyll','');
for(const file of ['filters.mjs','csv-report.mjs'])await copyFile('lib/'+file,'public-site/'+file);
await writeFile('public-site/data.json',JSON.stringify({report,stocks}));
for(const [name,items] of [['top-25',report.top25],['all-matching-stocks',report.allMatches],['all-screened-stocks',results]])await writeFile(`public-site/${name}.csv`,csv(summaryRows(items,report)));
console.log(`Scan complete: ${results.length}/${listing.length} valid histories; ${report.qualifying} matches. Published coverage includes ${errors.length} failures.`);
