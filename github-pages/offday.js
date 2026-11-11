import {exchangeLabel} from './exchange.mjs';

const $=id=>document.getElementById(id);
const repository='Tarunkrishna112003/market-pulse-agent';
const base=`https://raw.githubusercontent.com/${repository}/offday-predictions-data/`;
const state={index:null,rows:[],shown:100,request:0,historyRequest:0};
const percent=n=>Number.isFinite(n)?`${n>=0?'+':''}${n.toFixed(2)}%`:'—';
const timestamp=value=>new Date(value).toLocaleString('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' Pacific';
function node(tag,text,className){const element=document.createElement(tag);if(text!=null)element.textContent=text;if(className)element.className=className;return element;}
function cell(text,value){return node('td',text,Number.isFinite(value)?value>=0?'positive':'negative':'');}
function empty(target,columns,message){const tr=node('tr',null,'table-empty');const td=node('td',message);td.colSpan=columns;tr.append(td);target.append(tr);}
async function fetchJSON(path){const response=await fetch(base+path+'?refresh='+Date.now(),{cache:'no-store'});if(!response.ok){const error=Error(`Archive request failed (${response.status})`);error.status=response.status;throw error;}return response.json();}
function outcome(row){
 if(row.state!=='estimated')return row.reason||'Awaiting the first daily forecast';
 if(!Number.isFinite(row.actualPercent))return 'Awaiting closing data';
 return row.directionCorrect?'Correct direction':'Wrong direction';
}
function predictionCell(row){
 const td=cell(percent(row.estimatedPercent),row.estimatedPercent);
 if(row.generatedAt)td.append(node('small',timestamp(row.generatedAt)));
 if(row.publishedAfterOpen)td.append(node('small','Published after open'));
 return td;
}
function render(){
 const normalize=value=>String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9]+/g,' ').trim();
 const words=normalize($('offdaySearch').value).split(/\s+/).filter(Boolean);
 const filtered=state.rows.filter(row=>words.every(word=>normalize(row.symbol+' '+row.name).includes(word)));
 const target=$('offdayRows');target.replaceChildren();
 for(const row of filtered.slice(0,state.shown)){
  const tr=node('tr');const company=node('td');const ticker=node('button',row.symbol,'text-button');ticker.addEventListener('click',()=>showHistory(row.symbol));
  const line=node('div',null,'ticker-line');line.append(ticker,node('span',exchangeLabel(row),'exchange-badge'));
  company.append(line,node('div',row.name||row.symbol,'company-name'));
  tr.append(company,predictionCell(row),cell(percent(row.actualPercent),row.actualPercent),cell(Number.isFinite(row.errorPoints)?row.errorPoints.toFixed(2):'—'),cell(outcome(row)));target.append(tr);
 }
 if(!filtered.length)empty(target,5,'No stocks match this search.');
 $('offdayCount').textContent=`Showing ${Math.min(state.shown,filtered.length)} of ${filtered.length.toLocaleString()} stocks`;
 $('offdayMore').hidden=state.shown>=filtered.length;
 const estimated=state.rows.filter(row=>row.state==='estimated').length;
 $('offdaySummary').textContent=`${estimated.toLocaleString()} saved forecasts · ${state.rows.length.toLocaleString()} stocks · select a ticker for its history`;
}
async function loadDay(){
 const request=++state.request;state.shown=100;
 const date=$('offdayDate').value;
 $('offdayStatus').textContent=date?'Loading '+date+'…':'The first daily forecasts will appear from '+state.index.activationDate+'.';
 try{
  const session=date?await fetchJSON('sessions/'+date+'.json'):null;
  if(request!==state.request)return;
  const rows=new Map((session?.rows||[]).map(row=>[row.symbol,row]));
  state.rows=(state.index.stocks||[]).map(stock=>({...stock,...rows.get(stock.symbol)}));
  // Preserve stocks with saved forecasts even if the current listing has changed.
  for(const row of session?.rows||[])if(!state.rows.some(stock=>stock.symbol===row.symbol))state.rows.push(row);
  $('offdayStatus').textContent=date?`${date} · inputs through 5 AM Pacific · ${state.index.modelVersion}`:'The first daily forecasts will appear from '+state.index.activationDate+'.';
  render();
 }catch(error){
  if(request!==state.request)return;
  state.rows=[];render();$('offdayStatus').textContent='Could not load this day’s saved forecasts. '+error.message;
 }
}
async function showHistory(symbol){
 const request=++state.historyRequest;$('offdayHistory').hidden=false;
 $('historyTitle').textContent='Prediction history · '+symbol;$('historyStatus').textContent='Loading saved history…';$('offdayHistoryRows').replaceChildren();
 try{
  const history=await fetchJSON('stocks/'+encodeURIComponent(symbol)+'.json');
  if(request!==state.historyRequest)return;
  for(const row of history.records){const tr=node('tr');tr.append(cell(row.targetDate),cell(percent(row.estimatedPercent),row.estimatedPercent),cell(percent(row.actualPercent),row.actualPercent),cell(Number.isFinite(row.errorPoints)?row.errorPoints.toFixed(2):'—'),cell(outcome(row)),cell(row.generatedAt?timestamp(row.generatedAt):'—'));$('offdayHistoryRows').append(tr);}
  $('historyStatus').textContent=`${history.records.length} saved trading days · ${exchangeLabel(history)}`;
 }catch(error){
  if(request!==state.historyRequest)return;
  $('historyStatus').textContent=error.status===404?'No saved forecasts are available for this stock yet.':'Saved history could not be loaded. Please try again.';
 }
 $('offdayHistory').scrollIntoView({behavior:'smooth',block:'start'});
}
$('offdaySearch').addEventListener('input',()=>{state.shown=100;render();});
$('offdayDate').addEventListener('change',loadDay);
$('offdayMore').addEventListener('click',()=>{state.shown+=100;render();});
$('historyClose').addEventListener('click',()=>{state.historyRequest++;$('offdayHistory').hidden=true;});
function closeMenu(){document.body.classList.remove('menu-open');$('navBackdrop').hidden=true;$('menuButton').setAttribute('aria-expanded','false');}
$('menuButton').addEventListener('click',()=>{const open=!document.body.classList.contains('menu-open');document.body.classList.toggle('menu-open',open);$('navBackdrop').hidden=!open;$('menuButton').setAttribute('aria-expanded',String(open));});
$('navBackdrop').addEventListener('click',closeMenu);
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeMenu();});
try{
 state.index=await fetchJSON('index.json');
 $('updatedAt').textContent='Updated '+timestamp(state.index.updatedAt);
 const dates=[...state.index.sessions].sort().reverse();
 if(!dates.length)$('offdayDate').append(new Option('Awaiting first session',''));
 for(const date of dates)$('offdayDate').append(new Option(date,date));
 await loadDay();
}catch(error){$('offdayStatus').textContent='The prediction archive could not be loaded. '+error.message;$('updatedAt').textContent='Archive unavailable';}
