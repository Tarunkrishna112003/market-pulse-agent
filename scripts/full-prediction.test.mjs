import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {MODEL_VERSION} from '../lib/prediction.mjs';
import {publishedForecastRows} from '../lib/published-forecasts.mjs';

test('finalize archives non-top-25 full-table forecasts and recovery keeps original values and timestamps',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'full-forecast-archive-'));
 try{
  const generatedAt='2026-11-03T17:00:00Z',reportId='all-stocks';
  const stocks=['TOP','SMALL','LARGE','MISSING'].map(symbol=>({symbol,name:symbol}));
  const forecasts=stocks.map((s,i)=>({symbol:s.symbol,state:'estimated',forecastModel:'supervised',returnBasis:'open-to-close',modelVersion:MODEL_VERSION,lookback:365,targetDate:'2026-11-03',generatedAt,estimatedPercent:i-1}));
  forecasts[3]={symbol:'MISSING',state:'no-signal',lookback:365,targetDate:'2026-11-03',reason:'Historical prices unavailable'};
  await mkdir(join(directory,'predictions'));
  const files={
   'data.json':{report:{id:reportId,top25:[stocks[0]],errors:[]},stocks},
   'prediction-news.json':{reportId,companies:[],errors:[]},
   'prediction-trained.json':{modelVersion:MODEL_VERSION,supportedLookbacks:[365],trainedModels:[{trainingRows:1}],rows:[{symbol:'TOP',forecasts:[forecasts[0]]}]},
   'prediction-training.json':{generatedAt,companies:[]},
   'predictions/365.json':{reportId,lookback:365,rows:forecasts},
   'mock.mjs':null};
  for(const [name,value] of Object.entries(files))if(value)await writeFile(join(directory,name),JSON.stringify(value));
  await writeFile(join(directory,'mock.mjs'),`globalThis.fetch=async()=>({ok:true,json:async()=>({records:[]})});`);
  const run=spawnSync(process.execPath,['--import',join(directory,'mock.mjs'),resolve('scripts/prediction-agent.mjs'),'--finalize',directory],{encoding:'utf8',timeout:10000});
  assert.equal(run.status,0,run.stderr);
  let history=JSON.parse(await readFile(join(directory,'prediction-history.json'),'utf8'));
  assert.deepEqual(history.records.map(r=>r.symbol).sort(),['LARGE','MISSING','SMALL','TOP']);
  await writeFile(join(directory,'prediction-history.json'),JSON.stringify({records:history.records.filter(r=>r.symbol==='TOP')}));
  const recover=()=>spawnSync(process.execPath,[resolve('scripts/archive-published-forecasts.mjs'),directory],{encoding:'utf8',timeout:10000});
  assert.equal(recover().status,0);assert.equal(recover().status,0);
  history=JSON.parse(await readFile(join(directory,'prediction-history.json'),'utf8'));
  assert.equal(history.records.length,4);
  const small=history.records.find(r=>r.symbol==='SMALL');assert.equal(small.generatedAt,generatedAt);assert.equal(small.estimatedPercent,0);assert.equal(small.actualPercent,undefined);
  const missing=history.records.find(r=>r.symbol==='MISSING');assert.equal(missing.estimatedPercent,null);assert.equal(missing.reason,'Historical prices unavailable');
  assert.throws(()=>publishedForecastRows({reportId},[{reportId:'wrong',rows:forecasts}]),/match/);
 }finally{await rm(directory,{recursive:true,force:true})}
});

test('prediction agent prepares every scanned stock and reuses archived OHLCV regardless of cap',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'full-prediction-'));
 try{
  const stocks=[{symbol:'TRAIN',name:'Training Company',marketCap:30e9},{symbol:'SMALL',name:'Small Company',marketCap:1e6},{symbol:'LARGE',name:'Large Company',marketCap:500e9}].map(s=>({...s,price:100,priceAsOf:new Date().toISOString()}));
  stocks[1].predictionBaseline=[[new Date(Date.now()-400*86400000).toISOString().slice(0,10),99,1,98,100,98,5555]];stocks[1].history=[['2026-01-02',100,1,99,101,99,7777]];
  await writeFile(join(directory,'data.json'),JSON.stringify({report:{id:'all-stocks',filters:{minMarketCap:20e9,maxMarketCap:100e9,lookbackDays:17},top25:[stocks[0]]},stocks}));
  await writeFile(join(directory,'mock.mjs'),`globalThis.fetch=async url=>({ok:true,json:async()=>String(url).includes('gdelt')?{timeline:[{series:'Average Tone',data:[]}]}:{chart:{result:[{timestamp:[Date.now()/1000-86400*3,Date.now()/1000-86400*2],indicators:{quote:[{close:[100,101],open:[99,100],low:[98,99],high:[102,103],volume:[1000,1000]}]}}]}}});`);
  const result=spawnSync(process.execPath,['--import',join(directory,'mock.mjs'),resolve('scripts/prediction-agent.mjs'),'--training-data',directory],{encoding:'utf8',timeout:15000});
  assert.equal(result.status,0,result.stderr);
  const dataset=JSON.parse(await readFile(join(directory,'prediction-training.json'),'utf8'));
  assert.deepEqual(dataset.companies.map(c=>c.symbol).sort(),['LARGE','SMALL','TRAIN']);
  assert.equal(dataset.companies.find(c=>c.symbol==='SMALL').inferenceOnly,true);
  assert.equal(dataset.companies.find(c=>c.symbol==='LARGE').inferenceOnly,true);
  assert.equal(dataset.availableLookback,17);assert.equal(dataset.companies.find(c=>c.symbol==='SMALL').daily[1].volume,7777);
 }finally{await rm(directory,{recursive:true,force:true})}
});
