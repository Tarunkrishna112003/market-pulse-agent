import {SCAN_INTERVAL_MS} from './scan-status.mjs';
const ACTIVE=new Set(['queued','in_progress','pending','waiting','requested']);
const RETRY_INTERVAL_MS=30*60*1000;
export function scanTriggerDecision(runs,now=Date.now()){
 if(!Array.isArray(runs))throw Error('Invalid GitHub scan history');
 if(runs.some(run=>ACTIVE.has(run.status)))return {due:false,reason:'A scan is already running or queued'};
 const completed=runs.filter(run=>run.status==='completed');
 const latestSuccess=completed.filter(run=>run.conclusion==='success').sort((a,b)=>Date.parse(b.updated_at)-Date.parse(a.updated_at))[0];
 if(latestSuccess){const finished=Date.parse(latestSuccess.updated_at);if(!Number.isFinite(finished)||finished>now)throw Error('Invalid scan completion timestamp');const nextScanAt=new Date(finished+SCAN_INTERVAL_MS).toISOString();if(now<finished+SCAN_INTERVAL_MS)return {due:false,reason:'Three-hour interval has not elapsed',nextScanAt};}
 const latestAttempt=[...runs].sort((a,b)=>Date.parse(b.updated_at||b.created_at)-Date.parse(a.updated_at||a.created_at))[0];
 if(latestAttempt){const attempted=Date.parse(latestAttempt.updated_at||latestAttempt.created_at);if(!Number.isFinite(attempted)||attempted>now)throw Error('Invalid scan attempt timestamp');if(latestAttempt.conclusion!=='success'&&now<attempted+RETRY_INTERVAL_MS)return {due:false,reason:'Waiting before retrying an unsuccessful scan',nextScanAt:new Date(attempted+RETRY_INTERVAL_MS).toISOString()};}
 return {due:true,reason:latestSuccess?'Three hours have elapsed since the last successful scan':'No successful scan yet'};
}
export async function triggerDueScan({repository,token,now=Date.now(),fetchImpl=fetch}={}){
 if(!/^[\w.-]+\/[\w.-]+$/.test(repository||''))throw Error('A valid GitHub repository is required');
 if(!token)throw Error('GitHub Actions token is required');
 const base=`https://api.github.com/repos/${repository}/actions/workflows/scan-and-publish.yml`;
 const headers={Authorization:`Bearer ${token}`,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'market-pulse-scan-trigger'};
 const response=await fetchImpl(base+'/runs?per_page=100',{headers,signal:AbortSignal.timeout(20000)});
 if(!response.ok)throw Error('Cannot read GitHub scan history (HTTP '+response.status+')');
 const history=await response.json();const decision=scanTriggerDecision(history.workflow_runs,now);
 if(!decision.due)return decision;
 const dispatched=await fetchImpl(base+'/dispatches',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({ref:'main',inputs:{lookback_days:'30',min_cap_b:'20',max_cap_b:'100',min_move:'0',max_move:'5'}}),signal:AbortSignal.timeout(20000)});
 if(!dispatched.ok)throw Error('Cannot trigger GitHub scan (HTTP '+dispatched.status+')');
 return {...decision,triggered:true};
}
