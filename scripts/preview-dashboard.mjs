import http from 'node:http';
import {createReadStream,createWriteStream} from 'node:fs';
import {mkdir,access,rename,stat} from 'node:fs/promises';
import {resolve,extname,dirname,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {Readable} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {createGzip} from 'node:zlib';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..'),snapshots=resolve(root,'work/dashboard-preview/site');
const base='https://tarunkrishna112003.github.io/market-pulse-agent/';
const files=['data.json','predictions.json','predictions/365.json','testing-results.json'];
const downloads=await Promise.allSettled(files.map(async file=>{
 const target=resolve(snapshots,file);await mkdir(dirname(target),{recursive:true});
 if(!process.argv.includes('--refresh')){try{await access(target);return}catch{}}
 console.log('Downloading published snapshot: '+file);
 const response=await fetch(base+file+'?preview='+Date.now(),{signal:AbortSignal.timeout(180000)});
 if(!response.ok)throw Error(file+': HTTP '+response.status);
 await pipeline(Readable.fromWeb(response.body),createWriteStream(target+'.tmp'));await rename(target+'.tmp',target);
}));
for(const result of downloads)if(result.status==='rejected')throw result.reason;
const libFiles=new Set(['filters.mjs','csv-report.mjs','stock-history.mjs','trading-calendar.mjs']);
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.svg':'image/svg+xml','.png':'image/png'};
const server=http.createServer(async(req,res)=>{
 try{
  const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\//,'')||'index.html';
  if(name.split('/').some(p=>p==='..'||p.startsWith('.'))){res.writeHead(403);res.end();return}
  const folder=files.includes(name)?snapshots:libFiles.has(name)?resolve(root,'lib'):resolve(root,'github-pages');
  const path=resolve(folder,name);if(!path.startsWith(folder+sep)){res.writeHead(403);res.end();return}
  const info=await stat(path);if(!info.isFile())throw Error('Not a file');
  const headers={'Content-Type':types[extname(path)]||'application/octet-stream','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
  const compress=info.size>2048&&/gzip/.test(req.headers['accept-encoding']||'')&&/\.(json|js|mjs|css|html)$/.test(name);
  if(compress)headers['Content-Encoding']='gzip';else headers['Content-Length']=info.size;
  res.writeHead(200,headers);if(req.method==='HEAD'){res.end();return}
  const source=createReadStream(path);if(compress)await pipeline(source,createGzip({level:1}),res);else await pipeline(source,res);
 }catch(error){if(!res.headersSent)res.writeHead(404,{'Content-Type':'text/plain'});if(!res.writableEnded)res.end('File unavailable');}
});
const port=Number(process.env.DASHBOARD_PREVIEW_PORT||4173);
server.listen(port,'127.0.0.1',()=>console.log(`Local dashboard: http://127.0.0.1:${port}/ — snapshots in ${snapshots}`));
