const $=id=>document.getElementById(id),pct=n=>Number.isFinite(n)?`${n>=0?'+':''}${n.toFixed(2)}%`:'—';
const headings=['Company / ticker','Saved prediction · before 6 AM Pacific','Actual open → close','Error · percentage points','Status'];
function render(data){
 $('testDays').replaceChildren();
 for(const date of data.dates){
  const section=document.createElement('section'),heading=document.createElement('h2');
  heading.textContent=new Date(date+'T12:00:00Z').toLocaleDateString('en-US',{timeZone:'America/Los_Angeles',weekday:'long',month:'long',day:'numeric',year:'numeric'});
  section.append(heading);
  const summary=document.createElement('p'),wrapper=document.createElement('div'),table=document.createElement('table'),thead=document.createElement('thead'),header=document.createElement('tr'),body=document.createElement('tbody');
  wrapper.className='table';table.setAttribute('aria-label',heading.textContent+' testing results');
  for(const title of headings){const th=document.createElement('th');th.textContent=title;th.setAttribute('scope','col');header.append(th)}
  thead.append(header);table.append(thead,body);wrapper.append(table);
  const rows=data.entries.filter(e=>e.date===date);let compared=0,correct=0,error=0,saved=0;
  for(const entry of rows){
   const tr=document.createElement('tr'),stock=data.stocks.find(s=>s.symbol===entry.symbol);
   const cells=[`${stock?.name||entry.symbol} (${entry.symbol})`,pct(entry.prediction?.percent),pct(entry.actual?.percent),entry.errorPoints==null?'—':entry.errorPoints.toFixed(2),entry.status==='missed-cutoff'?'Missed 6 AM cutoff':entry.status==='pending'?'Waiting for morning prediction':entry.status==='awaiting-close'?'Saved; awaiting market close':entry.status==='awaiting-price'?'Waiting for closing data':entry.directionCorrect?'Correct direction':'Wrong direction'];
   cells.forEach((value,i)=>{const td=document.createElement('td');td.textContent=value;if(i===1&&entry.prediction){const time=document.createElement('small');time.textContent='Saved '+new Date(entry.prediction.observedAt).toLocaleString('en-US',{timeZone:'America/Los_Angeles'})+' Pacific';td.append(time)}tr.append(td)});body.append(tr);
   if(entry.prediction)saved++;
   if(entry.status==='compared'){compared++;if(entry.directionCorrect)correct++;error+=entry.errorPoints;}
  }
  summary.textContent=compared?`${compared}/${rows.length} comparisons · ${correct} correct directions (${(correct/compared*100).toFixed(0)}%) · average error ${(error/compared).toFixed(2)} percentage points`:`${saved}/${rows.length} predictions saved · Results will fill in as predictions are saved and this session closes.`;
  section.append(summary,wrapper);$('testDays').append(section);
 }
 $('testStatus').textContent='All trading days this week, in order. Each day keeps its own saved predictions and actual results.';
}
try{const response=await fetch('testing-results.json',{cache:'no-store'});if(!response.ok)throw Error('Testing results will appear after the next update.');const data=await response.json();$('week').textContent=`${data.dates[0]} to ${data.dates.at(-1)} · ${data.stocks.length} fixed stocks · cohort from ${data.cohortSession}`;render(data)}catch(error){$('testStatus').textContent=error.message}
