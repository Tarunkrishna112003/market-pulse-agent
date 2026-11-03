import {currentOrNextForecastSession} from './trading-calendar.mjs';
// The full table, rather than the detailed top-25 list, is the forecast archive source.
export function publishedForecastRows(metadata,tables){
 const rows=new Map();
 const normalize=f=>({...f,generatedAt:f.generatedAt||metadata.generatedAt,modelVersion:f.modelVersion||metadata.modelVersion,
  returnBasis:f.returnBasis||'open-to-close',targetDate:f.targetDate||(metadata.generatedAt?currentOrNextForecastSession(new Date(metadata.generatedAt)):undefined)});
 for(const table of tables){
  if(table.reportId!==metadata.reportId||!Array.isArray(table.rows))throw Error('Forecast table does not match its published scan');
  for(const forecast of table.rows){
   if(!forecast.symbol)throw Error('Forecast table row is missing its ticker');
   if(!rows.has(forecast.symbol))rows.set(forecast.symbol,{symbol:forecast.symbol,forecasts:[]});
   rows.get(forecast.symbol).forecasts.push(normalize({...forecast,lookback:forecast.lookback??table.lookback}));
  }
 }
 // Preserve detailed records with their own publication timestamps as well.
 for(const row of metadata.rows||[]){
  if(!rows.has(row.symbol))rows.set(row.symbol,{symbol:row.symbol,forecasts:[]});
  rows.get(row.symbol).forecasts.push(...(row.forecasts||[]).map(normalize));
 }
 return [...rows.values()];
}
