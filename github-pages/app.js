import {parseRanges,movementRows,predictionRows,searchStocks,historyView,testDayView,usableForecast,csvText} from './dashboard-data.mjs';
import {sparkline,priceChart} from './dashboard-chart.mjs';

const $=id=>document.getElementById(id);
const state={data:null,metadata:null,forecasts:new Map(),testing:null,volatility:[],predictions:[],explore:[],volShown:25,predShown:25,exploreShown:25,mode:'all',historyShown:60,watchlist:new Set(),testView:null};
try{state.watchlist=new Set(JSON.parse(localStorage.getItem('market-pulse-watchlist')||'[]'))}catch{}
const labels={volatility:['Volatility report','Find the movement that fits your range.'],predictions:['Stock predictions','A separate view of the model’s forecasts, on your terms.'],explore:['Explore stocks','A familiar name. A new discovery. A year of perspective.'],testing:['Testing results','The predictions we saved, measured against what happened.']};
const fmt={money:n=>Number.isFinite(n)?n.toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}):'—',pct:n=>Number.isFinite(n)?`${n>=0?'+':''}${n.toFixed(2)}%`:'—',cap:n=>Number.isFinite(n)?n>=1e12?'$'+(n/1e12).toFixed(2)+'T':'$'+(n/1e9).toFixed(2)+'B':'—',number:n=>Number.isFinite(n)?n.toLocaleString('en-US'):'—'};
function time(value){const d=new Date(value);return Number.isFinite(d.getTime())?d.toLocaleString('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' Pacific':'Time unavailable'}
function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function append(parent,...children){parent.append(...children);return parent;}
function button(text,cls,action){const n=el('button',text,cls);n.type='button';if(action)n.addEventListener('click',action);return n;}
function notice(message,error=false){$('globalStatus').textContent=message;$('globalStatus').className='notice'+(error?' error':'');$('globalStatus').hidden=!message;}
function formValues(form){const values=Object.fromEntries(new FormData(form));if(form.elements.namedItem('availableOnly'))values.availableOnly=form.elements.namedItem('availableOnly').checked;return values;}
function companyCell(stock){const box=el('div',null,'company-cell'),mark=el('span',stock.symbol.slice(0,2),'stock-monogram'),text=el('div'),link=el('a',stock.symbol,'company-link');link.href='#explore/'+encodeURIComponent(stock.symbol);append(text,link,el('div',stock.name||stock.symbol,'company-name'));return append(box,mark,text);}
function cell(text,cls){return el('td',text,cls);}
function emptyRow(target,columns,message){const tr=el('tr',null,'table-empty'),td=cell(message);td.colSpan=columns;append(tr,td);target.append(tr);}
function download(headers,rows,name){const url=URL.createObjectURL(new Blob([csvText(headers,rows)],{type:'text/csv;charset=utf-8'})),a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function readRoute(){const raw=location.hash.slice(1);if(raw==='mainContent')return null;const [path,query='']=raw.split('?'),[part,symbol]=path.split('/');return {section:Object.hasOwn(labels,part)?part:'volatility',symbol:symbol?decodeURIComponent(symbol):null,days:Number(new URLSearchParams(query).get('days')||365)};}
function closeMenu(){document.body.classList.remove('menu-open');$('menuButton').setAttribute('aria-expanded','false');$('navBackdrop').hidden=true;}
function route(){
 const r=readRoute();if(!r)return;
 for(const key of Object.keys(labels))$('panel-'+key).hidden=key!==r.section;
 for(const link of document.querySelectorAll('[data-section]')){if(link.dataset.section===r.section)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
 $('breadcrumb').textContent=labels[r.section][0];$('pageTitle').textContent=labels[r.section][0];$('pageDescription').textContent=labels[r.section][1];document.title=labels[r.section][0]+' · Market Pulse';
 $('overviewStats').hidden=r.section==='testing'||r.section==='explore'&&Boolean(r.symbol);$('newsSection').hidden=r.section==='testing'||r.section==='explore'&&Boolean(r.symbol);closeMenu();
 if(!state.data)return;
 if(r.section==='volatility')renderVolatility();
 if(r.section==='predictions')renderPredictions();
 if(r.section==='explore'){if(r.symbol)renderDetail(r.symbol,r.days);else renderExplore();}
 if(r.section==='testing')renderTesting();
 document.body.dataset.section=r.section;
}
function summaryCard(label,value,foot,icon){const box=el('div',null,'summary-card');append(box,el('span',label,'summary-label'),el('div',value,'summary-value'),el('div',foot,'summary-foot'));if(icon)box.append(el('span',icon,'summary-icon'));return box;}
function renderStats(){
 const target=$('overviewStats');target.replaceChildren();const report=state.data.report,available=[...state.forecasts.values()].filter(f=>usableForecast(f)).length;
 append(target,summaryCard('Scanned universe',fmt.number(state.data.stocks.length),'Stocks with usable histories','▥'),summaryCard('Matching your range',fmt.number(state.volatility.length),'Current volatility filters','⌁'),summaryCard('Current model forecasts',fmt.number(available),'Available in this snapshot','↗'),summaryCard('History available',report.filters.lookbackDays+' days','Calendar-day scan coverage','◷'));
}
function renderVolatility(){
 try{const options=formValues($('volatilityFilters'));state.volFilters=parseRanges(options);state.volatility=movementRows(state.data,state.volFilters);$('volatilityFilterNote').textContent='The day filter changes historical movement statistics, not model training.';}
 catch(error){$('volatilityFilterNote').textContent=error.message;return;}
 const rows=state.volatility,target=$('volatilityRows');target.replaceChildren();
 for(const stock of rows.slice(0,state.volShown)){const tr=el('tr');append(tr,append(cell(),companyCell(stock)),cell(fmt.money(stock.price)),append(cell(),el('span',fmt.pct(stock.change),'move-pill'+(stock.change<0?' negative':''))),cell(stock.average.toFixed(2)+'%','volatility-value'),cell(fmt.cap(stock.marketCap)),cell(fmt.money(stock.low30)),cell(fmt.money(stock.high30)));target.append(tr);}
 if(!rows.length)emptyRow(target,7,'No stocks match these ranges. Try widening the market-cap or movement filters.');
 $('volatilityCount').textContent=fmt.number(rows.length);$('volatilitySummary').textContent=`Average absolute daily movement over ${state.volFilters.lookbackDays} calendar days · largest first`;
 $('volatilityPageInfo').textContent=`Showing ${Math.min(state.volShown,rows.length)} of ${fmt.number(rows.length)} matching stocks`;$('volatilityMore').hidden=state.volShown>=rows.length;
 $('volatilityTopCsv').disabled=!rows.length;$('volatilityAllCsv').disabled=!rows.length;renderStats();
}
function renderPredictions(){
 try{state.predictions=predictionRows(state.data,state.forecasts,formValues($('predictionFilters')));$('predictionFilterNote').textContent='The prediction covers the full session’s open-to-close return, including when generated after open. It does not predict the remaining intraday move.';}
 catch(error){$('predictionFilterNote').textContent=error.message;return;}
 const rows=state.predictions,target=$('predictionRows');target.replaceChildren();
 for(const stock of rows.slice(0,state.predShown)){
  const tr=el('tr'),f=stock.forecast,pred=cell();
  if(stock.available){append(pred,el('span',fmt.pct(f.estimatedPercent),'prediction-number '+(f.estimatedPercent>=0?'positive':'negative')));if(f.generatedAfterOpen)pred.append(el('span','Generated after open','after-open-badge'));pred.append(el('small',time(f.generatedAt||state.metadata?.generatedAt)));}
  else{pred.append(el('span',f?.state==='estimated'?'Forecast expired':'Unavailable','unavailable-label'));pred.title=f?.reason||'No usable forecast for the current or next session.';}
  append(tr,append(cell(),companyCell(stock)),cell(fmt.money(stock.price)),pred,cell(f?.targetDate||'—'),cell(stock.average.toFixed(2)+'%'),cell(fmt.cap(stock.marketCap)));target.append(tr);
 }
 if(!rows.length)emptyRow(target,6,'No available forecasts match these ranges. Widen the filters or turn off “Available forecasts only” to see missing and expired records.');
 $('predictionCount').textContent=fmt.number(rows.length);$('predictionSummary').textContent=`Sorted by absolute forecast move · ${state.metadata?.modelVersion||'Model information unavailable'}`;
 $('predictionPageInfo').textContent=`Showing ${Math.min(state.predShown,rows.length)} of ${fmt.number(rows.length)} matching stocks`;$('predictionMore').hidden=state.predShown>=rows.length;$('predictionCsv').disabled=!rows.length;
}
function toggleWatch(symbol){if(state.watchlist.has(symbol))state.watchlist.delete(symbol);else state.watchlist.add(symbol);try{localStorage.setItem('market-pulse-watchlist',JSON.stringify([...state.watchlist]))}catch{}route();}
function watchButton(symbol,full=false){const selected=state.watchlist.has(symbol);const n=button(full?(selected?'★ Watching':'☆ Add to watchlist'):(selected?'★':'☆'),full?'secondary-button':'watch-button',()=>toggleWatch(symbol));n.setAttribute('aria-pressed',String(selected));n.setAttribute('aria-label',(selected?'Remove ':'Add ')+symbol+(selected?' from watchlist':' to watchlist'));return n;}
function renderExplore(){
 $('exploreOverview').hidden=false;$('exploreDetail').hidden=true;const query=$('stockSearch').value;state.explore=searchStocks(state.data.stocks,query,state.mode,state.watchlist);
 $('discoverySection').hidden=Boolean(query.trim())||state.mode==='watchlist';const cards=$('discoveryCards');cards.replaceChildren();
 const popular=['AAPL','MSFT','NVDA','AMZN','CRDO','GOOGL','META','TSLA','APP','ALAB'];const map=state.stockMap;
 const featured=popular.map(s=>map.get(s)).filter(Boolean).slice(0,5);if(featured.length<5)for(const stock of searchStocks(state.data.stocks).slice(0,5))if(!featured.some(s=>s.symbol===stock.symbol)&&featured.length<5)featured.push(stock);
 for(const stock of featured){const card=el('a',null,'stock-card');card.href='#explore/'+encodeURIComponent(stock.symbol);append(card,append(el('div',null,'stock-card-heading'),el('span',stock.symbol),el('span','↗','muted')),el('div',stock.name,'stock-card-name'),el('div',fmt.money(stock.price),'stock-card-price'),el('div',fmt.pct(stock.change)+' last daily change','stock-card-change '+(stock.change>=0?'positive':'negative')),sparkline(stock.history||[],{filled:true}));cards.append(card);}
 for(const n of document.querySelectorAll('[data-mode]'))n.setAttribute('aria-pressed',String(n.dataset.mode===state.mode));
 const target=$('exploreRows');target.replaceChildren();
 for(const stock of state.explore.slice(0,state.exploreShown)){const tr=el('tr');append(tr,append(cell(),companyCell(stock)),cell(fmt.money(stock.price)),append(cell(),el('span',fmt.pct(stock.change),'move-pill'+(stock.change<0?' negative':''))),append(cell(),sparkline(stock.history||[])),cell(fmt.cap(stock.marketCap)),append(cell(),watchButton(stock.symbol)));target.append(tr);}
 if(!state.explore.length)emptyRow(target,6,state.mode==='watchlist'?'Your watchlist is empty or does not match this search. Use a star to save a stock.':'No match in the latest successful scan. Try a ticker or a shorter company name.');
 $('exploreResultTitle').textContent=query.trim()?'Search results':state.mode==='watchlist'?'Your watchlist':state.mode==='gainers'?'Daily gainers':state.mode==='decliners'?'Daily decliners':'Browse the market';
 $('exploreSummary').textContent=`${fmt.number(state.explore.length)} stocks · prices and changes from the latest scan`;
 $('explorePageInfo').textContent=`Showing ${Math.min(state.exploreShown,state.explore.length)} of ${fmt.number(state.explore.length)} stocks`;$('exploreMore').hidden=state.exploreShown>=state.explore.length;
}
function renderDetail(symbol,requestedDays){
 $('exploreOverview').hidden=true;const target=$('exploreDetail');target.hidden=false;target.replaceChildren();const back=el('a','← Back to explore','detail-back');back.href='#explore';target.append(back);
 const stock=state.stockMap.get(symbol.toUpperCase());if(!stock){const box=el('div',null,'surface surface-heading');append(box,el('p','This stock has no usable history in the latest scan. Its saved testing records remain available in Testing results.'));target.append(box);return;}
 const maximum=state.data.report.filters.lookbackDays;const days=Number.isInteger(requestedDays)&&requestedDays>=1?Math.min(requestedDays,maximum,365):Math.min(365,maximum);
 let view;try{view=historyView(stock,state.data.report,days)}catch(error){target.append(el('p',error.message));return;}
 document.title=stock.symbol+' · Explore · Market Pulse';$('breadcrumb').textContent='Explore / '+stock.symbol;$('pageTitle').textContent='A closer look.';$('pageDescription').textContent=stock.name;
 const box=el('div',null,'surface'),heading=el('div',null,'detail-heading'),company=el('div',null,'company-cell'),description=el('div');append(description,el('h2',stock.symbol),el('p',(stock.name||stock.symbol)+' · '+(stock.exchange||'US equity')));append(company,el('span',stock.symbol.slice(0,2),'stock-monogram'),description);append(heading,company,watchButton(stock.symbol,true));box.append(heading);
 append(box,append(el('div',null,'detail-price'),el('strong',fmt.money(stock.price)),el('span','Latest recorded price · '+(stock.priceAsOf?.length>10?time(stock.priceAsOf):stock.priceDate||stock.priceAsOf||state.data.report.end))));
 const toolbar=el('div',null,'chart-toolbar'),caption=el('div',fmt.pct(view.returnPercent)+' range return'+(view.baselineDate?' · since '+view.baselineDate:''),'chart-caption '+(view.returnPercent>=0?'positive':'negative')),controls=el('div',null,'segmented-control');
 for(const [label,length] of [['1W',7],['1M',30],['3M',90],['6M',180],['1Y',365]]){const n=button(label,'',()=>{state.historyShown=60;location.hash='explore/'+encodeURIComponent(stock.symbol)+'?days='+length});n.setAttribute('aria-pressed',String(length===days));n.disabled=length>maximum;n.title=n.disabled?'This snapshot contains only '+maximum+' calendar days':length+' calendar days';controls.append(n);}
 append(toolbar,caption,controls);box.append(toolbar,priceChart(view.days,`${stock.symbol} closing prices from ${view.firstDate||view.start} to ${view.lastDate||view.end}. Use arrow keys to inspect the chart.`));
 const stats=el('div',null,'detail-stats');for(const [label,value] of [['Range low',fmt.money(view.minLow)],['Range high',fmt.money(view.maxHigh)],['Market cap',fmt.cap(stock.marketCap)],['Trading sessions',fmt.number(view.days.length)]])append(stats,append(el('div'),el('span',label),el('strong',value)));box.append(stats);target.append(box);
 const tableBox=el('div',null,'surface');append(tableBox,append(el('div',null,'surface-heading'),append(el('div'),el('h2','Daily price history'),el('p',`${view.firstDate||view.start} to ${view.lastDate||view.end} · ${days} calendar-day window · USD`))));
 const wrap=el('div',null,'table-wrap'),table=el('table'),head=el('thead'),hrow=el('tr');for(const name of ['Date','Daily change','Low','High','Close','Volume'])hrow.append(el('th',name));head.append(hrow);table.append(head);const body=el('tbody');
 for(const day of [...view.days].reverse().slice(0,state.historyShown)){const tr=el('tr');append(tr,cell(day.date),cell(fmt.pct(day.change),day.change>=0?'positive':'negative'),cell(fmt.money(day.low)),cell(fmt.money(day.high)),cell(fmt.money(day.close)),cell(fmt.number(day.volume)));body.append(tr);}
 if(!view.days.length)emptyRow(body,6,'No recorded sessions are available in this range.');append(table,body);append(wrap,table);tableBox.append(wrap);
 const foot=el('div',null,'table-footer');foot.append(el('span',`Showing ${Math.min(state.historyShown,view.days.length)} of ${view.days.length} sessions`));if(state.historyShown<view.days.length)foot.append(button('Show all sessions ↓','text-button',()=>{state.historyShown=view.days.length;renderDetail(stock.symbol,days)}));tableBox.append(foot);target.append(tableBox);
 target.append(el('p',`Closing-price history is shown above. Daily change is close-to-close, not the model’s open-to-close target. ${view.missingRanges?'Some daily ranges were not supplied. ':''}${maximum<365?'A full year is unavailable in this snapshot. ':''}Young listings may have less than one year of history.`,'field-note'));
}
function renderTesting(){
 if(!state.testing){$('testingStatus').textContent='Saved testing data could not be loaded. Reload the preview after refreshing its published snapshots.';return;}
 const day=$('testDay').value,variant=$('testVariant').value,view=testDayView(state.testing,day,variant);state.testView=view;
 $('testingCohort').textContent=`All ${state.testing.stocks.length} original stocks · ${state.testing.dates[0]} to ${state.testing.dates.at(-1)} · cohort from ${state.testing.cohortSession}`;
 $('testingExplanation').textContent=variant==='late'?'After-open updates predict the full day’s open-to-close move, not the remaining intraday move. They are excluded from the morning-test results.':'Morning forecasts are frozen before 6:00 AM Pacific. Later updates cannot replace them. A missed cutoff means no eligible morning forecast was recorded.';
 const stats=$('testingStats');stats.replaceChildren();for(const [label,value] of [['Cohort stocks',String(view.total)],['Compared with actual',`${view.compared}/${view.total}`],['Correct direction',view.compared?`${view.correct}/${view.compared}`:'—'],['Average error',view.mae==null?'—':view.mae.toFixed(2)+' pts']])append(stats,append(el('div',null,'testing-stat'),el('span',label),el('strong',value)));
 const target=$('testRows');target.replaceChildren();
 for(const row of view.rows){const tr=el('tr'),pred=cell();pred.append(el('span',fmt.pct(row.prediction?.percent),row.prediction?.percent>=0?'positive':'negative'));if(row.prediction)pred.append(el('small',time(row.prediction.generatedAt||row.prediction.observedAt)),el('small',row.prediction.modelVersion||'Original model'));
  let status,cls='pending';if(row.compared){status=row.directionCorrect?'Correct direction':'Wrong direction';cls=row.directionCorrect?'':'wrong'}else if(variant==='late')status=row.prediction?'Awaiting actual move':'No after-open update';else if(row.entry?.status==='missed-cutoff')status='Missed 6 AM cutoff';else if(row.prediction)status=row.entry?.status==='awaiting-price'?'Awaiting closing data':'Awaiting market close';else status=row.entry?.status==='pending'?'Awaiting morning forecast':'No saved record';
  append(tr,append(cell(),companyCell(row.stock)),pred,cell(fmt.pct(row.actual?.percent),row.actual?.percent>=0?'positive':'negative'),cell(row.error==null?'—':row.error.toFixed(2)),append(cell(),el('span',status,'result-pill '+cls)));target.append(tr);
 }
 $('testingStatus').textContent=`${day} · ${variant==='late'?'Separate after-open comparison':'Frozen morning comparison'} · ${view.predicted} saved forecasts${state.testing.priceErrors?.length?' · Some closing-price downloads failed; missing results remain pending.':''}`;
 $('testingFooter').textContent=`All ${view.total} stocks are shown. Volatility and prediction filters do not affect this cohort.`;$('testingCsv').disabled=false;
}
function renderNews(){const target=$('newsCards');target.replaceChildren();const news=state.data.report.marketNews;const items=(news?.items||[]).filter(h=>{try{return new URL(h.url).protocol==='https:'}catch{return false}}).slice(0,3);
 for(const item of items){const box=el('article',null,'news-item'),link=el('a',item.title);link.href=item.url;link.target='_blank';link.rel='noreferrer';append(box,el('span',item.category||'Market news','news-topic'),link,el('small',(item.source||'Yahoo Finance')+' · '+time(item.publishedAt)));target.append(box);}
 if(!items.length)target.append(el('p',news?.state==='unavailable'?'Market headlines are temporarily unavailable.':'No headlines were included in this snapshot.','field-note'));
}

$('volatilityFilters').addEventListener('submit',event=>{event.preventDefault();state.volShown=25;if(state.data)renderVolatility()});
$('predictionFilters').addEventListener('submit',event=>{event.preventDefault();state.predShown=25;if(state.data)renderPredictions()});
$('volatilityMore').addEventListener('click',()=>{state.volShown+=25;renderVolatility()});$('predictionMore').addEventListener('click',()=>{state.predShown+=25;renderPredictions()});$('exploreMore').addEventListener('click',()=>{state.exploreShown+=25;renderExplore()});
let searchTimer;$('stockSearch').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.exploreShown=25;if(state.data)renderExplore()},120)});
for(const n of document.querySelectorAll('[data-mode]'))n.addEventListener('click',()=>{state.mode=n.dataset.mode;state.exploreShown=25;renderExplore()});
$('testDay').addEventListener('change',renderTesting);$('testVariant').addEventListener('change',renderTesting);
$('menuButton').addEventListener('click',()=>{const open=!document.body.classList.contains('menu-open');document.body.classList.toggle('menu-open',open);$('menuButton').setAttribute('aria-expanded',String(open));$('navBackdrop').hidden=!open});$('navBackdrop').addEventListener('click',closeMenu);
window.addEventListener('hashchange',()=>{try{route()}catch(error){notice(error.message,true)}});document.addEventListener('keydown',event=>{if(event.key==='Escape')closeMenu();if(event.key==='/'&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)){event.preventDefault();location.hash='explore';setTimeout(()=>$('stockSearch').focus(),0)}});
function volatilityExport(rows,name){download(['Ticker','Company','Latest_price_USD','Daily_change_percent','Average_daily_move_percent','Market_cap_USD','30_day_low','30_day_high','Movement_lookback_calendar_days'],rows.map(s=>[s.symbol,s.name,s.price,s.change,s.average,s.marketCap,s.low30,s.high30,state.volFilters.lookbackDays]),name)}
$('volatilityTopCsv').addEventListener('click',()=>volatilityExport(state.volatility.slice(0,25),'volatility-top-25.csv'));$('volatilityAllCsv').addEventListener('click',()=>volatilityExport(state.volatility,'volatility-all-matches.csv'));
$('predictionCsv').addEventListener('click',()=>download(['Ticker','Company','Predicted_open_to_close_percent','Target_session','Generated_at','After_open','Latest_price_USD','Market_cap_USD','Forecast_state'],state.predictions.map(s=>[s.symbol,s.name,s.available?s.forecast.estimatedPercent:null,s.forecast?.targetDate,s.forecast?.generatedAt||state.metadata?.generatedAt,s.forecast?.generatedAfterOpen||false,s.price,s.marketCap,s.available?'estimated':s.forecast?.state||'unavailable']),'stock-predictions.csv'));
$('testingCsv').addEventListener('click',()=>download(['Date','Ticker','Company','Record_type','Prediction_percent','Actual_percent','Absolute_error_points','Direction_correct','Generated_at','Model_version'],state.testView.rows.map(r=>[$('testDay').value,r.stock.symbol,r.stock.name,$('testVariant').value,r.prediction?.percent,r.actual?.percent,r.error,r.directionCorrect,r.prediction?.generatedAt,r.prediction?.modelVersion]),'testing-'+$('testDay').value+'-'+$('testVariant').value+'.csv'));
route();if(['127.0.0.1','localhost'].includes(location.hostname))$('localLabel').hidden=false;
async function fetchJSON(file){const response=await fetch(file,{cache:'no-store'});if(!response.ok)throw Error(file+' is unavailable (HTTP '+response.status+')');return response.json();}
try{
 const results=await Promise.allSettled(['data.json','predictions.json','predictions/365.json','testing-results.json'].map(fetchJSON));
 if(results[0].status!=='fulfilled')throw results[0].reason;state.data=results[0].value;
 if(!Array.isArray(state.data.stocks)||!state.data.report?.end)throw Error('The market snapshot is incomplete. Refresh the preview snapshots.');
 state.stockMap=new Map(state.data.stocks.map(s=>[s.symbol,s]));const warnings=[];
 if(results[1].status==='fulfilled')state.metadata=results[1].value;else warnings.push('Model metadata could not be loaded.');
 if(state.metadata?.reportId!==state.data.report.id){warnings.push('Forecasts belong to a different scan and are withheld.');}
 else if(results[2].status==='fulfilled'&&results[2].value.reportId===state.data.report.id){state.forecasts=new Map(results[2].value.rows.map(f=>[f.symbol,f]));}
 else{for(const row of state.metadata.rows||[]){const forecast=row.forecasts?.find(f=>f.lookback===365);if(forecast)state.forecasts.set(row.symbol,forecast)}warnings.push('The full-universe forecast table is unavailable; only saved detailed rows can be shown.');}
 if(results[3].status==='fulfilled'){state.testing=results[3].value;for(const date of state.testing.dates){const n=el('option',date);n.value=date;$('testDay').append(n)}const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());$('testDay').value=state.testing.dates.filter(d=>d<=today).at(-1)||state.testing.dates[0];}else warnings.push('Testing results could not be loaded.');
 const report=state.data.report;for(const id of ['volatilityFilters','predictionFilters']){$(id).elements.namedItem('days').max=report.filters.lookbackDays;$(id).elements.namedItem('days').value=Math.min(30,report.filters.lookbackDays);}
 const legacyFilters=new URLSearchParams(location.search);for(const key of ['minCap','maxCap','minMove','maxMove','days'])if(legacyFilters.has(key))$('volatilityFilters').elements.namedItem(key).value=legacyFilters.get(key);
 $('snapshotTime').textContent=time(report.createdAt);$('footerAsOf').textContent='Snapshot through '+report.end+' · Forecasts are model estimates.';
 $('reportDetails').textContent=`${fmt.number(report.scanned||state.data.stocks.length)} successful histories / ${fmt.number(report.total||state.data.stocks.length)} attempted. ${report.errors?.length||0} source failures. Scan completed ${time(report.createdAt)}. Sources: ${(report.sources||[]).join(', ')||'Published market report'}.`;
 notice(warnings.join(' '),Boolean(warnings.length));renderVolatility();renderNews();route();document.body.dataset.ready='true';
}catch(error){notice('Could not load the dashboard: '+error.message,true);document.body.dataset.error='true';}
