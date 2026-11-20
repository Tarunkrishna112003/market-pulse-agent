import {latestScanTime,nextScanTime} from './scan-status.mjs';
import {PREOPEN_FORECAST_START,preopenTradingDate,easternSessionClock,scheduledCloseMinute,tradingDay,nextTradingDay} from './trading-calendar.mjs';
export function morningForecastDate(scheduledAt,now=Date.now()){
 if(scheduledAt!==latestScanTime(now))return '';
 const slot=easternSessionClock(new Date(scheduledAt));
 return slot.date>=PREOPEN_FORECAST_START&&slot.minute===480&&preopenTradingDate(new Date(now))===slot.date?slot.date:'';
}
const ACTIVE=new Set(['queued','in_progress','pending','waiting','requested']);
const RETRY_INTERVAL_MS=30*60*1000;
export function scanTriggerDecision(runs,now=Date.now()){
 if(!Array.isArray(runs))throw Error('Invalid GitHub scan history');
 if(runs.some(run=>ACTIVE.has(run.status)))return {due:false,reason:'A scan is already running or queued'};
 const clock=easternSessionClock(new Date(now));
 const morningSlot=clock.date>=PREOPEN_FORECAST_START&&clock.minute>=480&&tradingDay(clock.date)
  ?new Date(Math.floor(now/60000)*60000-(clock.minute-480)*60000).toISOString():null;
 const successful=runs.filter(run=>run.status==='completed'&&run.conclusion==='success');
 const morningComplete=morningSlot&&successful.some(run=>run.display_title==='Scan '+morningSlot);
 const scheduledAt=morningSlot&&!morningComplete?morningSlot:latestScanTime(now);
 const slot=Date.parse(scheduledAt);
 const morning=scheduledAt===morningSlot;
 for(const run of successful){
  const finished=Date.parse(run.updated_at),started=Date.parse(run.created_at||run.run_started_at||run.updated_at);
  if(!Number.isFinite(finished)||!Number.isFinite(started)||finished>now||started>now)throw Error('Invalid scan completion timestamp');
  const namedSlot=run.display_title?.match(/^Scan (\d{4}-\d{2}-\d{2}T.*Z)$/)?.[1];
  const satisfied=morning?namedSlot===scheduledAt:namedSlot?namedSlot===scheduledAt:started>=slot;
  if(satisfied&&started>=slot)return {due:false,reason:'This scheduled scan has already run',nextScanAt:nextScanTime(now)};
 }
 const retryInterval=morning&&morningForecastDate(scheduledAt,now)?5*60000:RETRY_INTERVAL_MS;
 const latestAttempt=[...runs].sort((a,b)=>Date.parse(b.updated_at||b.created_at)-Date.parse(a.updated_at||a.created_at))[0];
 if(latestAttempt){const attempted=Date.parse(latestAttempt.updated_at||latestAttempt.created_at);if(!Number.isFinite(attempted)||attempted>now)throw Error('Invalid scan attempt timestamp');if(latestAttempt.conclusion!=='success'&&now<attempted+retryInterval)return {due:false,reason:'Waiting before retrying an unsuccessful scan',nextScanAt:new Date(attempted+retryInterval).toISOString()};}
 return {due:true,reason:'Scheduled Pacific scan is due',scheduledAt};
}
export function afterCloseWindow(now=Date.now()){
 const clock=easternSessionClock(new Date(now)),close=scheduledCloseMinute(clock.date);
 return tradingDay(clock.date)&&clock.minute>=close+15&&clock.minute<=close+240;
}
export function needsClosingRefresh(snapshot,now=Date.now()){
 if(!afterCloseWindow(now))return false;
 const clock=easternSessionClock(new Date(now)),target=nextTradingDay(clock.date);
 const trainedThrough=(snapshot.trainedModels||[]).some(model=>model.trainingTargetEnd>=clock.date);
 const nextSession=(snapshot.rows||[]).some(row=>(row.forecasts||[]).some(f=>f.state==='estimated'&&f.targetDate===target&&Number.isFinite(f.estimatedPercent)));
 return !trainedThrough||!nextSession;
}
export async function triggerDueScan({repository,token,now=Date.now(),fetchImpl=fetch,checkAfterClose=false}={}){
 if(!/^[\w.-]+\/[\w.-]+$/.test(repository||''))throw Error('A valid GitHub repository is required');
 if(!token)throw Error('GitHub Actions token is required');
 const base=`https://api.github.com/repos/${repository}/actions/workflows/scan-and-publish.yml`;
 const headers={Authorization:`Bearer ${token}`,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'market-pulse-scan-trigger'};
 const response=await fetchImpl(base+'/runs?per_page=100',{headers,signal:AbortSignal.timeout(20000)});
 if(!response.ok)throw Error('Cannot read GitHub scan history (HTTP '+response.status+')');
 const history=await response.json();let decision=scanTriggerDecision(history.workflow_runs,now);
 // A scan begun at the 1 PM Pacific slot can finish before the provider's
 // closing-data buffer. Retry stale forecasts without overlapping active scans.
 if(checkAfterClose&&!decision.due&&decision.reason==='This scheduled scan has already run'&&afterCloseWindow(now)){
  const lastFinished=Math.max(0,...history.workflow_runs.map(run=>Date.parse(run.updated_at)||0));
  if(now>=lastFinished+RETRY_INTERVAL_MS){
   const [owner,name]=repository.split('/');
   // Never send the GitHub authorization header to the public Pages host.
   const published=await fetchImpl(`https://${owner}.github.io/${name}/predictions.json?freshness=${now}`,{cache:'no-store',signal:AbortSignal.timeout(20000)});
   if(!published.ok)throw Error('Cannot verify published closing forecasts (HTTP '+published.status+')');
   if(needsClosingRefresh(await published.json(),now))decision={due:true,reason:'After-close forecasts have not advanced to the next session'};
  }
 }
 if(!decision.due)return decision;
 const dispatched=await fetchImpl(base+'/dispatches',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({ref:'main',inputs:{lookback_days:'365',min_cap_b:'20',max_cap_b:'200',min_move:'0',max_move:'5',scheduled_at:decision.scheduledAt||latestScanTime(now)}}),signal:AbortSignal.timeout(20000)});
 if(!dispatched.ok)throw Error('Cannot trigger GitHub scan (HTTP '+dispatched.status+')');
 return {...decision,triggered:true};
}
