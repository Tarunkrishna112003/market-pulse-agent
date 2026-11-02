import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {archiveProviderSymbol,shardFor,csvLine,archiveURL,discoverArchiveUniverse,parseArchiveChart,mergedCheckpoint,updateWindow,shouldCollect} from '../lib/history-archive.mjs';
const now=new Date('2026-11-02T22:00:00Z');
const epoch=s=>Date.parse(s)/1000;
function chart({timestamps=[epoch('2026-10-30T13:30:00Z')],meta={},quote={}}={}){return {chart:{result:[{meta:{instrumentType:'EQUITY',exchangeName:'NMS',currency:'USD',...meta},timestamp:timestamps,indicators:{quote:[{open:[100],high:[105],low:[98],close:[103],volume:[1000],...quote}],adjclose:[{adjclose:[102]}]},events:{splits:{a:{date:timestamps[0],numerator:2,denominator:1}}}}]}}}
test('all caps and both full exchange lists enter the archive universe',async()=>{
 const found=await discoverArchiveUniverse(async url=>({ok:true,json:async()=>({data:{totalrecords:2,table:{rows:[{symbol:url.endsWith('nasdaq')?'SMALL':'BIG',name:'Company',marketCap:1},{symbol:url.endsWith('nasdaq')?'NEW':'LOW',name:'Other company',marketCap:1}]}}})}));
 assert.equal(found.stocks.length,4);assert.ok(found.stocks.some(s=>s.symbol==='SMALL'));assert.deepEqual(new Set(found.stocks.map(s=>s.exchange)),new Set(['NASDAQ','NYSE']));
 await assert.rejects(()=>discoverArchiveUniverse(async()=>({ok:true,json:async()=>({data:{totalrecords:3,table:{rows:[{symbol:'ONE'}]}}})})),/truncated/);
});
test('stable shards cover every listing once and CSV quotes corporate actions',()=>{
 for(const symbol of ['AAPL','CRDO','BRK.B','A,Company','TINY'])assert.equal(Array.from({length:8},(_,i)=>i).filter(i=>shardFor(symbol)===i).length,1);
 assert.equal(csvLine(['A,B','say "hi"',null,0]),'"A,B","say ""hi""",,0\n');
});
test('daily backfill begins before 1970 and intraday requests respect retention',()=>{
 assert.equal(archiveURL('BRK.B','1d',{now}).searchParams.get('period1'),'-2208988800');assert.ok(archiveURL('BRK.B','1d',{now}).pathname.endsWith('BRK-B'));
 assert.equal(Number(archiveURL('AAPL','5m',{now,since:0}).searchParams.get('period1')),now.getTime()/1000-58*86400);
 assert.throws(()=>archiveURL('AAPL','1m',{now}),/Unsupported/);
 assert.equal(archiveProviderSymbol('AKO/A'),'AKO-A');assert.equal(archiveProviderSymbol('ACP^A'),'ACP-PA');assert.equal(archiveProviderSymbol('^GSPC'),'^GSPC');
});
test('archive preserves price, adjustment and action fields, and rejects malformed bars',()=>{
 const data=parseArchiveChart('CRDO',chart(), '1d',now);assert.equal(data.status,'saved');assert.equal(data.bars[0].close,103);assert.equal(data.bars[0].adjusted_close,102);assert.ok(data.bars[0].corporate_actions.includes('splits'));assert.equal(data.bars[0].session_date,'2026-10-30');
 assert.equal(parseArchiveChart('FUND',chart({meta:{instrumentType:'ETF'}}),'1d',now).status,'unsupported');
 assert.equal(parseArchiveChart('CRDO',chart({quote:{high:[99]}}),'1d',now).invalidRows,1);
 assert.throws(()=>parseArchiveChart('CRDO',{chart:{error:{description:'No data'}}},'1d',now),/No data/);
});
test('partial daily and 5-minute bars never become completed training labels',()=>{
 const daily=chart({timestamps:[epoch('2026-11-02T14:30:00Z')]});
 assert.equal(parseArchiveChart('CRDO',daily,'1d',new Date('2026-11-02T21:10:00Z')).bars.length,0);
 assert.equal(parseArchiveChart('CRDO',daily,'1d',new Date('2026-11-02T21:15:00Z')).bars.length,1);
 const intra=chart({timestamps:[epoch('2026-11-02T15:00:00Z')]});
 assert.equal(parseArchiveChart('CRDO',intra,'5m',new Date('2026-11-02T15:05:00Z')).bars.length,0);
 assert.equal(parseArchiveChart('CRDO',intra,'5m',new Date('2026-11-02T15:06:30Z')).bars.length,1);
});
test('overlap and checkpoints preserve old history, never advance on failed collection',()=>{
 const original={schemaVersion:1,symbols:{CRDO:{status:'backfilled','1d':{lastTimestamp:100,firstDate:'2020-01-01',lastDate:'2026-10-30'}}}};
 const failed=mergedCheckpoint(original,[{symbol:'CRDO',status:'error',error:'HTTP 429'}],now.toISOString());assert.equal(failed.symbols.CRDO['1d'].lastTimestamp,100);assert.equal(original.symbols.CRDO.lastError,undefined);
 const success=mergedCheckpoint(failed,[{symbol:'CRDO',status:'saved',intervals:[{interval:'1d',status:'saved',firstDate:'2026-10-20',lastDate:'2026-11-02',lastTimestamp:200}]}],now.toISOString());
 assert.equal(success.symbols.CRDO['1d'].firstDate,'2020-01-01');assert.equal(success.symbols.CRDO['1d'].lastTimestamp,200);assert.equal(success.symbols.CRDO.lastError,null);
 const window=updateWindow({ '5m':{lastTimestamp:now.getTime()/1000-1000}},'5m',now);assert.equal(window.since,now.getTime()/1000-2800);
 assert.ok(updateWindow({'5m':{lastTimestamp:0}},'5m',now).gap);
});
test('regular-session collector handles weekends and DST using Eastern time',()=>{
 assert.equal(shouldCollect(new Date('2026-11-01T17:00:00Z')),false);assert.equal(shouldCollect(new Date('2026-11-02T14:30:00Z')),true);assert.equal(shouldCollect(new Date('2026-11-02T14:00:00Z')),false);assert.equal(shouldCollect(new Date('2026-11-02T22:00:00Z')),false);
});
test('large data collection is runner-only and immutable uploads never clobber raw files',async()=>{
 const code=await readFile('scripts/archive-stock-history.mjs','utf8'),workflow=await readFile('.github/workflows/testing-stock-history.yml','utf8');
 assert.match(code,/RUNNER_ENVIRONMENT!=='github-hosted'/);assert.match(code,/GITHUB_REF_NAME!=='testing-server'/);assert.match(code,/mutable:true/);assert.match(code,/upload\(tag,manifest.asset,bytes\)/);assert.match(workflow,/branches: \[testing-server\]/);assert.doesNotMatch(workflow,/deploy-pages|upload-pages/);
});

test('market context is archived explicitly without admitting unrelated funds as stocks',()=>{
 assert.equal(parseArchiveChart('^GSPC',chart({meta:{instrumentType:'INDEX',exchangeName:'SNP'}}),'1d',now).status,'saved');
 assert.equal(parseArchiveChart('XLK',chart({meta:{instrumentType:'ETF',exchangeName:'PCX'}}),'1d',now).status,'saved');
 assert.equal(parseArchiveChart('UNRELATED_ETF',chart({meta:{instrumentType:'ETF',exchangeName:'PCX'}}),'1d',now).status,'unsupported');
});

test('unavailable histories are explicit and never erase a prior successful cursor',()=>{
 const old={schemaVersion:1,symbols:{A:{status:'backfilled','1d':{lastTimestamp:10,lastDate:'2026-10-30'}}}};
 const next=mergedCheckpoint(old,[{symbol:'A',status:'unavailable',error:'Chart HTTP 404'},{symbol:'NEW',status:'unavailable',error:'No history'}],now.toISOString());
 assert.equal(next.symbols.A.status,'backfilled');assert.equal(next.symbols.A['1d'].lastTimestamp,10);assert.equal(next.symbols.NEW.status,'unavailable');assert.equal(next.symbols.NEW.lastError,'No history');
});
