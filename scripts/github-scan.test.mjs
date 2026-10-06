import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,cp,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
test('GitHub scanner attempts the whole universe and publishes filtered report and browser modules',async()=>{
 const temp=await mkdtemp(join(tmpdir(),'github-scan-'));
 try{
 await cp('github-pages',join(temp,'github-pages'),{recursive:true});await cp('lib',join(temp,'lib'),{recursive:true});
 await writeFile(join(temp,'mock.mjs'),`globalThis.fetch=async url=>{if(String(url).includes('screener/stocks'))return {ok:true,json:async()=>({data:{totalrecords:2,asof:'fixture',table:{rows:[{symbol:'MATCH',name:'Matching Company',marketCap:'30000000000'},{symbol:'OUTSIDE',name:'Outside Company',marketCap:'1000000000'}]}}})};const end=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());const base=Date.parse(end+'T17:00:00Z')/1000;return {ok:true,json:async()=>({chart:{result:[{meta:{instrumentType:'EQUITY',exchangeName:'NMS'},timestamp:[base-31*86400,base-3*86400,base-2*86400],indicators:{quote:[{close:[100,110,121]}]}}]}})}};`);
 const result=spawnSync(process.execPath,['--import',join(temp,'mock.mjs'),resolve('scripts/github-scan.mjs')],{cwd:temp,env:{...process.env,FMP_API_KEY:'',LOOKBACK_DAYS:'30',MIN_MOVE:'5',MIN_CAP_B:'20',MAX_CAP_B:'100'},encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);
 const data=JSON.parse(await readFile(join(temp,'public-site/data.json'),'utf8'));assert.equal(data.report.total,2);assert.equal(data.stocks.length,2);assert.deepEqual(data.report.top25.map(s=>s.symbol),['MATCH']);assert.equal(data.stocks[0].history.length,2);
 assert.match(await readFile(join(temp,'public-site/all-matching-stocks.csv'),'utf8'),/MATCH/);assert.doesNotMatch(await readFile(join(temp,'public-site/all-matching-stocks.csv'),'utf8'),/OUTSIDE/);
 assert.match(await readFile(join(temp,'public-site/filters.mjs'),'utf8'),/normalizeFilters/);assert.match(await readFile(join(temp,'public-site/index.html'),'utf8'),/Apply filters/);
 }finally{await rm(temp,{recursive:true,force:true})}
});
