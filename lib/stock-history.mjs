export function stockHistory(stock,report,lookbackDays){
 if(!Number.isInteger(lookbackDays)||lookbackDays<1||lookbackDays>365)throw Error('Choose between 1 and 365 calendar days.');
 if(!/^\d{4}-\d{2}-\d{2}$/.test(report?.end||''))throw Error('The report has no valid history end date.');
 if(lookbackDays>(report.filters?.lookbackDays||30))throw Error(`This scan contains ${report.filters?.lookbackDays||30} calendar days. Run a scan with a longer lookback to see more history.`);
 const start=new Date(report.end+'T00:00:00Z');start.setUTCDate(start.getUTCDate()-(lookbackDays-1));const startDate=start.toISOString().slice(0,10);
 const history=(stock.history||stock.days||[]).map(d=>Array.isArray(d)?{date:d[0],close:d[1],change:d[2],low:d[3],high:d[4]}:d).filter(d=>d.date>=startDate&&d.date<=report.end).sort((a,b)=>a.date.localeCompare(b.date));
 const lows=history.map(d=>d.low).filter(v=>Number.isFinite(v)&&v>0),highs=history.map(d=>d.high).filter(v=>Number.isFinite(v)&&v>0);
 return {start:startDate,end:report.end,days:history,minLow:lows.length?Math.min(...lows):null,maxHigh:highs.length?Math.max(...highs):null,missingRanges:history.some(d=>!(Number.isFinite(d.low)&&d.low>0&&Number.isFinite(d.high)&&d.high>0))};
}
