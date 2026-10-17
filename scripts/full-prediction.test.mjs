import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';

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
