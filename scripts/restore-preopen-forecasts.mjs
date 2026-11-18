import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {updateLedger,validationSummary} from '../lib/prediction.mjs';
import {afterOpenForecast} from '../lib/trading-calendar.mjs';

const site=process.argv[2]||'public-site';
const base='https://tarunkrishna112003.github.io/market-pulse-agent/';
async function published(file){
 const response=await fetch(base+file+'?restore='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(30000)});
 if(!response.ok)throw Error('Cannot restore '+file+' (HTTP '+response.status+')');
 return response.json();
}

const [metadata,history]=await Promise.all([published('predictions.json'),published('prediction-history.json')]);
const eligible=row=>!afterOpenForecast(row);
const tables=await Promise.all((metadata.tableFiles||[365]).map(async days=>{
 if(!Number.isInteger(days)||days<1||days>365)throw Error('Invalid forecast lookback');
 const table=await published('predictions/'+days+'.json');
 if(table.reportId!==metadata.reportId||table.lookback!==days)throw Error('Mismatched published forecasts');
 return [days,{...table,rows:table.rows.filter(eligible)}];
}));
const {stocks}=JSON.parse(await readFile(site+'/data.json','utf8'));
const now=new Date();
const records=updateLedger(history.records.filter(eligible),stocks,[],now);
metadata.rows=metadata.rows.map(row=>({...row,forecasts:(row.forecasts||[]).filter(eligible)}));
metadata.validation=(metadata.validation||[]).map(({lookback})=>({lookback,...validationSummary(records,lookback)}));

await mkdir(site+'/predictions',{recursive:true});
await Promise.all(tables.map(([days,table])=>writeFile(site+'/predictions/'+days+'.json',JSON.stringify(table))));
await writeFile(site+'/prediction-history.json',JSON.stringify({updatedAt:now.toISOString(),records}));
await writeFile(site+'/predictions.json',JSON.stringify(metadata));
