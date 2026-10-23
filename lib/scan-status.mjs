export const SCAN_TIMEZONE='America/Los_Angeles';
export const SCAN_HOURS=[5,13,17,21];
export const SCAN_SCHEDULE='Daily at 5 AM, 1 PM, 5 PM and 9 PM Pacific';
const pacificHour=new Intl.DateTimeFormat('en-US',{timeZone:SCAN_TIMEZONE,hour:'numeric',hourCycle:'h23'});
function scheduledTime(now,direction){
 if(!Number.isFinite(now))throw Error('Invalid schedule timestamp');
 const hour=60*60*1000;
 let candidate=Math.floor(now/hour)*hour;
 if(direction>0)candidate+=hour;
 for(let i=0;i<48;i++,candidate+=direction*hour){
  if(SCAN_HOURS.includes(Number(pacificHour.format(new Date(candidate)))))return new Date(candidate).toISOString();
 }
 throw Error('No scheduled scan found');
}
export function nextScanTime(now=Date.now()){return scheduledTime(now,1)}
export function latestScanTime(now=Date.now()){return scheduledTime(now,-1)}
export function scanDue(next,now=Date.now()){return Boolean(next)&&Number.isFinite(Date.parse(next))&&now>=Date.parse(next)}
export function scanPresentation(agent,hasReport){const scanFinished=Boolean(agent?.scanCompletedAt)||(agent?.phase==='LLM reviewing every company'&&agent?.pricesScanned>=agent?.discovered&&agent?.discovered>0);if(scanFinished||hasReport&&['complete','partial'].includes(agent?.state))return {title:'Scan complete — results below',badge:'Scan complete',priceRunning:false};if(agent?.state==='running')return {title:hasReport?'Scanning — previous results shown below':'Scanning NASDAQ stocks…',badge:'Scanning',priceRunning:true};if(agent?.state==='error')return {title:hasReport?'Scan interrupted — saved results below':'Scan interrupted',badge:'Interrupted',priceRunning:false};return {title:hasReport?'Scan complete — results below':'Preparing your live report',badge:hasReport?'Scan complete':'Connecting',priceRunning:false};}
