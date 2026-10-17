import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {buildDailyReport,dailyReportCSV,dailyReportMarkdown} from '../lib/daily-report.mjs';
const site=process.argv[2]||'public-site';
const data=JSON.parse(await readFile(site+'/data.json','utf8'));
let forecasts;try{forecasts=JSON.parse(await readFile(site+'/predictions/365.json','utf8'))}catch{forecasts={reportId:data.report.id,lookback:365,rows:[]}}
const report=buildDailyReport(data,forecasts);
const base='https://tarunkrishna112003.github.io/market-pulse-agent/';
const previousResponse=await fetch(base+'daily-report.json',{signal:AbortSignal.timeout(30000),cache:'no-store'});if(!previousResponse.ok&&previousResponse.status!==404)throw Error('Cannot restore daily report');const previous=previousResponse.ok?await previousResponse.json():null;
if(report&&(!previous||previous.sessionDate<report.sessionDate)){
 await writeFile(site+'/daily-report.json',JSON.stringify(report));
 await writeFile(site+'/daily-report.md',dailyReportMarkdown(report));
 await writeFile(site+'/daily-report.csv',dailyReportCSV(report));
 await mkdir('daily-reports',{recursive:true});
 for(const extension of ['json','md','csv'])await writeFile('daily-reports/'+report.sessionDate+'.'+extension,await readFile(site+'/daily-report.'+extension));
 console.log(`Prepared ${report.rows.length} stock predictions after ${report.sessionDate} close, targeting ${report.targetDate}.`);
}else{
 for(const extension of ['json','md','csv']){const r=await fetch(base+'daily-report.'+extension,{signal:AbortSignal.timeout(30000),cache:'no-store'});if(r.status===404)continue;if(!r.ok)throw Error('Cannot preserve daily report: HTTP '+r.status);await writeFile(site+'/daily-report.'+extension,await r.text());}
 console.log('No new completed-session report; preserved the latest published report if available.');
}
