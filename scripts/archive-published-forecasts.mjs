import {readFile,writeFile} from 'node:fs/promises';
import {publishedForecastRows} from '../lib/published-forecasts.mjs';
import {updateLedger} from '../lib/prediction.mjs';
const site=process.argv[2]||'public-site';
const metadata=JSON.parse(await readFile(site+'/predictions.json','utf8'));
const history=JSON.parse(await readFile(site+'/prediction-history.json','utf8'));
if(!Array.isArray(history.records))throw Error('Invalid existing prediction archive');
const tables=await Promise.all((metadata.tableFiles||[365]).map(async days=>JSON.parse(await readFile(site+'/predictions/'+days+'.json','utf8'))));
// Preserve the original forecast timestamps and values. A display-only deployment
// has no fresh closing-price source, so recovered forecasts await normal scoring.
const records=updateLedger(history.records,[],publishedForecastRows(metadata,tables));
await writeFile(site+'/prediction-history.json',JSON.stringify({...history,updatedAt:new Date().toISOString(),records}));
console.log(`Preserved ${history.records.length} records; recovered ${records.length-history.records.length} forecasts from the full published table.`);
