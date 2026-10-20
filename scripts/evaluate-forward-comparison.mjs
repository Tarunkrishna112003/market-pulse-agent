// Evaluate the already-frozen local comparison after the target session closes.
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {sessionExpired} from '../lib/trading-calendar.mjs';
import {trainingPrices} from '../lib/supervised-data.mjs';
const path=process.argv[2]||'work/forecast-research-2026-08-19_2026-10-19/forward/2026-10-20.json';
const bytes=await readFile(path),saved=JSON.parse(bytes),now=new Date();
if(!(Date.parse(saved.generatedAt)<Date.parse(saved.morningCutoff)))throw Error('Forecast was not frozen before its morning cutoff');
if(!sessionExpired(saved.targetDate,now)){console.log(`Awaiting market close for ${saved.targetDate}; frozen forecasts remain unchanged.`);process.exit(0)}
const entries=[];let index=0;
await Promise.all(Array.from({length:2},async()=>{while(index<saved.entries.length){const prediction=saved.entries[index++];try{
 const prices=await trainingPrices(prediction.symbol,{now,dailyOnly:true,historyDays:14,fetchImpl:(url,options)=>{const target=new URL(url);target.hostname='query2.finance.yahoo.com';return fetch(target,options)}});
 const day=prices.daily.find(day=>day.date===saved.targetDate);if(!(day?.open>0&&day?.close>0))throw Error('Target opening or closing price unavailable');
 const actual=(day.close/day.open-1)*100;
 entries.push({symbol:prediction.symbol,actualPercent:actual,actualOpen:day.open,actualClose:day.close,
  comparisons:Object.fromEntries([['candidate',prediction.candidatePercent],['v7',prediction.v7Percent],['v8',prediction.v8Percent]].map(([method,percent])=>[method,{predictedPercent:percent,errorPoints:Math.abs(percent-actual),directionCorrect:Math.sign(percent)===Math.sign(actual)}]))});
 }catch(error){entries.push({symbol:prediction.symbol,error:error.message})}}}));
const complete=entries.filter(e=>e.comparisons),summary=Object.fromEntries(['candidate','v7','v8'].map(method=>[method,{comparisons:complete.length,directionAccuracy:complete.length?complete.filter(e=>e.comparisons[method].directionCorrect).length/complete.length:null,meanAbsoluteError:complete.length?complete.reduce((n,e)=>n+e.comparisons[method].errorPoints,0)/complete.length:null}]));
const result={targetDate:saved.targetDate,evaluatedAt:now.toISOString(),frozenForecastSHA256:createHash('sha256').update(bytes).digest('hex'),summary,entries};
const output=path.replace(/\.json$/,'-actual-comparison.json');if(output===path)throw Error('Expected .json forecast file');
await writeFile(output,JSON.stringify(result,null,2));console.log(JSON.stringify({targetDate:saved.targetDate,summary,output},null,2));
