import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.DASHBOARD_PREVIEW_URL||'http://127.0.0.1:4173/';
const target=await (await fetch('http://127.0.0.1:9223/json/new?'+encodeURIComponent(base),{method:'PUT'})).json();
const socket=new WebSocket(target.webSocketDebuggerUrl),pending=new Map(),errors=[];let sequence=0;
await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true})});
socket.addEventListener('message',event=>{const message=JSON.parse(event.data);if(message.id){const task=pending.get(message.id);pending.delete(message.id);if(message.error)task.reject(Error(message.error.message));else task.resolve(message.result)}else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text+' '+(message.params.exceptionDetails.exception?.description||''))});
function command(method,params={}){return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))})}
async function evaluate(expression){const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value;}
async function wait(expression){for(let i=0;i<120;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,250))}throw Error('Timed out: '+expression)}
async function route(hash){await evaluate(`location.hash=${JSON.stringify(hash)}`);await wait(`document.body.dataset.section===${JSON.stringify(hash.split('/')[0])}`);await new Promise(r=>setTimeout(r,150))}
const root='work/dashboard-preview';await mkdir(root,{recursive:true});
async function screenshot(name){const result=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(root+'/'+name+'.png',Buffer.from(result.data,'base64'))}
try{
 await command('Page.enable');await command('Runtime.enable');await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await wait("document.body.dataset.ready==='true'||document.body.dataset.error==='true'");assert.equal(await evaluate("document.body.dataset.error||''"),'');
 assert.equal(await evaluate("document.querySelectorAll('.main-nav a').length"),4);
 assert.ok(await evaluate("document.querySelectorAll('#volatilityRows .company-link').length>0"));await screenshot('volatility-desktop');
 await evaluate("document.getElementById('volatilityFilters').elements.maxCap.value='50';document.getElementById('volatilityFilters').requestSubmit()");
 await route('predictions');assert.equal(await evaluate("document.getElementById('predictionFilters').elements.maxCap.value"),'200');await screenshot('predictions-desktop');
 await route('explore');assert.ok(await evaluate("document.querySelectorAll('#discoveryCards .stock-card').length>=3"));
 await evaluate("const q=document.getElementById('stockSearch');q.value='AppLovin';q.dispatchEvent(new Event('input',{bubbles:true}))");await wait("document.getElementById('exploreRows').textContent.includes('APP')");
 await evaluate("document.getElementById('stockSearch').value='CRDO';document.getElementById('stockSearch').dispatchEvent(new Event('input',{bubbles:true}))");await wait("document.querySelector('#exploreRows .company-link')?.textContent==='CRDO'");await screenshot('explore-search');
 await evaluate("document.querySelector('#exploreRows .company-link').click()");await wait("!document.getElementById('exploreDetail').hidden&&document.getElementById('exploreDetail').textContent.includes('CRDO')");
 assert.ok(await evaluate("document.querySelector('#exploreDetail .price-chart')!==null"));assert.ok(await evaluate("document.querySelectorAll('#exploreDetail tbody tr').length>=50"));
 await evaluate("document.querySelector('#exploreDetail .price-chart').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))");assert.equal(await evaluate("document.querySelector('#exploreDetail .chart-tooltip').hidden"),false);await screenshot('explore-detail-desktop');
 await evaluate("[...document.querySelectorAll('#exploreDetail button')].find(b=>b.textContent.includes('Show all sessions'))?.click()");assert.ok(await evaluate("document.querySelectorAll('#exploreDetail tbody tr').length>200"));
 await route('testing');assert.equal(await evaluate("document.querySelectorAll('#testRows tr').length"),25);await screenshot('testing-desktop');
 await evaluate("document.getElementById('testVariant').value='late';document.getElementById('testVariant').dispatchEvent(new Event('change'))");assert.equal(await evaluate("document.querySelectorAll('#testRows tr').length"),25);assert.ok(await evaluate("document.getElementById('testingExplanation').textContent.includes('full day')"));
 await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await route('volatility');await evaluate('window.scrollTo(0,0)');
 assert.ok(await evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'));await screenshot('volatility-mobile');
 await evaluate("document.getElementById('menuButton').click()");assert.equal(await evaluate("document.getElementById('menuButton').getAttribute('aria-expanded')"),'true');
 await evaluate("document.querySelector('[data-section=explore]').click()");await wait("document.body.dataset.section==='explore'");assert.equal(await evaluate("document.getElementById('menuButton').getAttribute('aria-expanded')"),'false');
 await evaluate("document.getElementById('stockSearch').value='';document.getElementById('stockSearch').dispatchEvent(new Event('input',{bubbles:true}))");await new Promise(r=>setTimeout(r,250));await screenshot('explore-mobile');
 await evaluate("document.querySelector('#exploreRows .watch-button').click()");assert.equal(await evaluate("document.querySelector('#exploreRows .watch-button').getAttribute('aria-pressed')"),'true');
 await evaluate("document.querySelector('[data-mode=watchlist]').click()");assert.ok(await evaluate("document.querySelectorAll('#exploreRows .company-link').length>=1"));
 await route('testing');assert.ok(await evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'));assert.equal(await evaluate("document.querySelectorAll('#testRows tr').length"),25);await screenshot('testing-mobile');
 await route('predictions');assert.ok(await evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'));await screenshot('predictions-mobile');
 await command('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:process.cwd()+'/'+root+'/downloads'});
 await route('testing');await evaluate("document.getElementById('testingCsv').click()");
 assert.deepEqual(errors,[]);console.log('Browser checks passed: navigation, independent filters, discovery, name/ticker search, yearly chart and history, 25-stock testing, after-open separation, responsive layout, mobile menu.');
 await writeFile(root+'/browser-checks.json',JSON.stringify({passed:true,errors,screenshots:['volatility-desktop','predictions-desktop','explore-search','explore-detail-desktop','testing-desktop','volatility-mobile','explore-mobile']},null,2));
}finally{socket.close();await fetch('http://127.0.0.1:9223/json/close/'+target.id)}
