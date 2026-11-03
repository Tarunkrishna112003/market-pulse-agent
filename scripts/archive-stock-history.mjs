// Run on GitHub-hosted runners only. Raw history is stored as immutable release assets.
import {mkdir,readFile,writeFile,stat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {gzipSync,gunzipSync} from 'node:zlib';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {resolve} from 'node:path';
import {withArchiveRetry} from '../lib/archive-retry.mjs';
import {BASE_TAG,ARCHIVE_CONTEXT,ARCHIVE_SCHEMA,CSV_COLUMNS,csvLine,barCSV,shardFor,archiveURL,discoverArchiveUniverse,parseArchiveChart,updateWindow,mergedCheckpoint,shouldCollect,lastCompletedDailySession,changedArchiveBars} from '../lib/history-archive.mjs';
import {easternSessionClock,scheduledCloseMinute,previousTradingDay} from '../lib/trading-calendar.mjs';
const exec=promisify(execFile),args=new Map();for(let i=2;i<process.argv.length;i+=2)args.set(process.argv[i],process.argv[i+1]);
if(process.env.GITHUB_ACTIONS!=='true'||process.env.RUNNER_ENVIRONMENT!=='github-hosted')throw Error('Full-history collection is restricted to GitHub-hosted runners. No laptop download is supported.');
if(!/^[-\w]+\/[-.\w]+$/.test(process.env.GITHUB_REPOSITORY||''))throw Error('Missing repository');
if(process.env.GITHUB_REF_NAME!=='testing-server')throw Error('Archive jobs run only on testing-server');
let mode=args.get('--mode')||'backfill';const shard=Number(args.get('--shard')||0),shards=8;
if(!['prepare','backfill','update','summary','auto'].includes(mode)||!Number.isInteger(shard)||shard<0||shard>=shards)throw Error('Invalid archive mode/shard');
const now=new Date(),repo=process.env.GITHUB_REPOSITORY,run=process.env.GITHUB_RUN_ID+'-'+process.env.GITHUB_RUN_ATTEMPT,root=resolve('work/github-history');await mkdir(root,{recursive:true});
async function gh(...a){return withArchiveRetry(async()=>(await exec('gh',[...a,'--repo',repo],{maxBuffer:16*1024*1024})).stdout);}
async function releaseExists(tag){try{return JSON.parse(await gh('release','view',tag,'--json','tagName')).tagName===tag}catch(e){if(/release not found|404|Not Found/i.test(e.stderr||''))return false;throw e}}
async function ensureRelease(tag,notes){if(!await releaseExists(tag)){try{await gh('release','create',tag,'--target','testing-server','--prerelease','--title',tag,'--notes',notes)}catch(error){if(!await releaseExists(tag))throw error}}}
async function assetNames(tag){return new Set(JSON.parse(await gh('release','view',tag,'--json','assets')).assets.map(a=>a.name));}
async function download(tag,name){const folder=resolve(root,'downloads',tag);await mkdir(folder,{recursive:true});await gh('release','download',tag,'--pattern',name,'--dir',folder,'--clobber');return readFile(resolve(folder,name));}
async function upload(tag,name,bytes,{mutable=false}={}){
 if(bytes.length>=500*1024*1024)throw Error('Archive chunk exceeds 500 MiB safety limit');
 const path=resolve(root,name);await writeFile(path,bytes);
 if(!mutable&&(await assetNames(tag)).has(name)){const remote=await download(tag,name);if(!remote.equals(bytes))throw Error('Immutable asset conflict: '+name);return;}
 try{await gh('release','upload',tag,path,...(mutable?['--clobber']:[]))}catch(error){if(!mutable&&(await assetNames(tag)).has(name)&&(await download(tag,name)).equals(bytes))return;throw error}
}
const archiveNotes='Testing-server historical stock dataset, schema v1. Immutable gzip CSV history and manifests; checkpoint assets are rebuildable metadata. Current listings, provider-available daily history; not a survivorship-free database. No live-site deployment.';
if(mode==='prepare'){
 await ensureRelease(BASE_TAG,archiveNotes);
 if(!(await assetNames(BASE_TAG)).has('universe.json.gz')){
  const universe=await discoverArchiveUniverse();await upload(BASE_TAG,'universe.json.gz',gzipSync(Buffer.from(JSON.stringify(universe)),{mtime:0}));
 }
 let universe=JSON.parse(gunzipSync(await download(BASE_TAG,(await assetNames(BASE_TAG)).has('universe-current.json.gz')?'universe-current.json.gz':'universe.json.gz')));
 if(easternSessionClock(new Date(universe.createdAt)).date!==easternSessionClock(now).date){
  const fresh=await discoverArchiveUniverse(),active=new Set(fresh.stocks.map(s=>s.symbol)),combined=new Map(universe.stocks.map(s=>[s.symbol,{...s,active:active.has(s.symbol)}]));for(const stock of fresh.stocks)combined.set(stock.symbol,{...stock,active:true});
  universe={...fresh,stocks:[...combined.values()]};const bytes=gzipSync(Buffer.from(JSON.stringify(universe)),{mtime:0}),tag='testing-stock-updates-'+now.toISOString().slice(0,10);await ensureRelease(tag,archiveNotes);await upload(tag,'universe-'+run+'.json.gz',bytes);await upload(BASE_TAG,'universe-current.json.gz',bytes,{mutable:true});
 }
 if(!(await assetNames(BASE_TAG)).has('context-universe.json'))await upload(BASE_TAG,'context-universe.json',Buffer.from(JSON.stringify({stocks:ARCHIVE_CONTEXT.map(symbol=>({symbol,name:symbol,kind:'context',sector:'Context'}))})));
 console.log(`Archive universe: ${universe.stocks.length} listings across NASDAQ and NYSE. No cap/movement filter.`);process.exit(0);
}
const names=await assetNames(BASE_TAG),universe=JSON.parse(gunzipSync(await download(BASE_TAG,names.has('universe-current.json.gz')?'universe-current.json.gz':'universe.json.gz')));
const context=names.has('context-universe.json')?JSON.parse(await download(BASE_TAG,'context-universe.json')).stocks:[];
const all=[...universe.stocks,...context].filter(s=>shardFor(s.symbol,shards)===shard),checkpointName=`checkpoint-${shard}.json`;
let checkpoint={schemaVersion:ARCHIVE_SCHEMA,symbols:{}};if((await assetNames(BASE_TAG)).has(checkpointName))checkpoint=JSON.parse(await download(BASE_TAG,checkpointName));
if(mode==='auto')mode=Object.values(checkpoint.symbols).some(s=>s.status==='backfilled')?'update':'backfill';
if(mode==='summary'){
 let backfilled=0,unsupported=0,unavailable=0,failed=0,pending=0;for(const s of all){const c=checkpoint.symbols[s.symbol];if(c?.status==='backfilled')backfilled++;else if(c?.status==='unsupported')unsupported++;else if(c?.status==='unavailable')unavailable++;else if(c?.lastError)failed++;else pending++;}
 const report={shard,universe:all.length,backfilled,unsupported,unavailable,failed,pending,checkpointUpdatedAt:checkpoint.updatedAt||null};console.log(JSON.stringify(report));
 if(process.env.GITHUB_STEP_SUMMARY)await writeFile(process.env.GITHUB_STEP_SUMMARY,`### Stock history shard ${shard}\n\n${JSON.stringify(report,null,2)}\n`);process.exit(failed||pending?1:0);
}
const completedSession=lastCompletedDailySession(now),regularCollection=shouldCollect(now),needsCatchup=s=>s.active!==false&&checkpoint.symbols[s.symbol]?.status==='backfilled'&&(checkpoint.symbols[s.symbol]?.['1d']?.lastDate||'')<completedSession;
if(mode==='update'&&!regularCollection&&!all.some(needsCatchup)){console.log('Outside trading hours and completed daily history is current; no new bars needed.');process.exit(0);}
const selected=mode==='backfill'?all.filter(s=>!['backfilled','unsupported'].includes(checkpoint.symbols[s.symbol]?.status)):all.filter(s=>{const c=checkpoint.symbols[s.symbol];return (regularCollection||needsCatchup(s))&&s.active!==false&&c?.status!=='unsupported'&&(c?.status==='backfilled'||!c?.lastAttemptAt||easternSessionClock(new Date(c.lastAttemptAt)).date!==easternSessionClock(now).date)});
if(!selected.length){console.log(`Shard ${shard}: no ${mode} work.`);process.exit(0)}
const tag=mode==='backfill'?BASE_TAG:'testing-stock-updates-'+now.toISOString().slice(0,10);await ensureRelease(tag,archiveNotes);
// One update chunk per shard per run keeps a daily release below the 1000-asset limit.
const batchSize=mode==='backfill'?50:selected.length;let failures=0,unavailable=0,lastStart=0;
async function fetchChart(symbol,interval,since){
 const url=archiveURL(symbol,interval,{now,since});let last;
 for(let attempt=0;attempt<4;attempt++){
  const delay=Math.max(0,900-(Date.now()-lastStart));if(delay)await new Promise(r=>setTimeout(r,delay));lastStart=Date.now();
  try{const response=await fetch(url,{headers:{'User-Agent':'Mozilla/5.0'},signal:AbortSignal.timeout(30000)});
   if(!response.ok){const error=Error('Chart HTTP '+response.status);error.retryable=response.status===429||response.status>=500;const retry=Number(response.headers.get('retry-after'));error.wait=Number.isFinite(retry)?Math.min(180000,retry*1000):0;throw error}
   return parseArchiveChart(symbol,await response.json(),interval,now);
  }catch(error){last=error;if(error.retryable===false||attempt===3)break;await new Promise(r=>setTimeout(r,Math.max(error.wait||0,5000*2**attempt)));}
 }throw last;
}
for(let offset=0;offset<selected.length;offset+=batchSize){
 const stocks=selected.slice(offset,offset+batchSize),results=[],lines=[csvLine(CSV_COLUMNS)];let rows=0;
 for(const stock of stocks){
  const intervals=[],needsBackfill=mode==='backfill'||checkpoint.symbols[stock.symbol]?.status!=='backfilled',clock=easternSessionClock(now),daily=needsBackfill||clock.minute>=scheduledCloseMinute(clock.date)+15||(checkpoint.symbols[stock.symbol]?.['1d']?.lastDate||'')<previousTradingDay(clock.date);
  try{
   for(const interval of needsBackfill?['1d']:(daily?['1d','30m']:['30m'])){
    const window=needsBackfill?{since:null,gap:null}:updateWindow(checkpoint.symbols[stock.symbol],interval,now);
    let record=await fetchChart(stock.symbol,interval,window.since);
    if(mode==='update'&&interval==='1d'&&(record.lastSplitTimestamp||0)>(checkpoint.symbols[stock.symbol]?.['1d']?.lastSplitTimestamp||0)){record=await fetchChart(stock.symbol,'1d',null);record.warnings.push('Full-history revision appended following a newly reported stock split');}
    if(record.status==='unsupported'){results.push({symbol:stock.symbol,status:'unsupported',reason:record.reason});break;}
    if(needsBackfill&&record.status!=='saved')throw Error('No completed daily bars returned for full history request');
    record=changedArchiveBars(record,checkpoint.symbols[stock.symbol]?.[interval]);
    for(const bar of record.bars){lines.push(barCSV(bar));rows++;}
    const {bars,...coverage}=record;intervals.push({interval,...coverage,gap:window.gap});
   }
   if(intervals.length)results.push({symbol:stock.symbol,status:'saved',backfill:needsBackfill,intervals});
  }catch(error){if(intervals.length)results.push({symbol:stock.symbol,status:'saved',backfill:needsBackfill,intervals});const missing=/^Chart HTTP (404|422)$|^No completed daily bars/.test(error.message);if(missing)unavailable++;else failures++;results.push({symbol:stock.symbol,status:missing?'unavailable':'error',error:error.message});}
  if((offset+results.length)%25===0)console.log(`Shard ${shard}: ${offset+results.length}/${selected.length} tickers processed; ${failures} failures`);
 }
 const bytes=gzipSync(Buffer.from(lines.join('')),{level:6,mtime:0}),hash=createHash('sha256').update(bytes).digest('hex'),stem=`${mode}-p${shard}-${run}-b${offset/batchSize}-${hash.slice(0,12)}`;
 const manifest={schemaVersion:ARCHIVE_SCHEMA,mode,shard,shards,createdAt:now.toISOString(),source:'Yahoo Finance chart',sourceCommit:process.env.GITHUB_SHA,asset:stem+'.csv.gz',sha256:hash,rows,columns:CSV_COLUMNS,results};
 // Commit data first, then its immutable manifest, then advance the rebuildable cursor.
 await upload(tag,manifest.asset,bytes);await upload(tag,stem+'.manifest.json',Buffer.from(JSON.stringify(manifest)));
 checkpoint=mergedCheckpoint(checkpoint,results,now.toISOString());await upload(BASE_TAG,checkpointName,Buffer.from(JSON.stringify(checkpoint)),{mutable:true});
 console.log(`Saved ${manifest.asset}: ${rows} bars (${(bytes.length/1048576).toFixed(2)} MiB compressed).`);
}
console.log(`Shard ${shard} finished: ${selected.length} attempted, ${failures} request failures, ${unavailable} unavailable histories. Failed tickers are retained for retry.`);
if(unavailable)console.log(`::warning::${unavailable} listings have no available price history in this feed. Coverage gaps are recorded; no prices were fabricated.`);
if(failures)process.exitCode=1;
