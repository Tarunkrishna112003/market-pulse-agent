import {stockHistory} from './stock-history.mjs';
const $=id=>document.getElementById(id);
const params=new URLSearchParams(location.search),symbol=params.get('symbol');
const money=v=>Number.isFinite(v)?'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
const back=new URLSearchParams(params);for(const key of ['symbol','report'])back.delete(key);$('back').href='index.html?'+back;
try{
 if(!symbol)throw Error('Choose a stock from the screener.');
 const response=await fetch('data.json',{cache:'no-store'});if(!response.ok)throw Error('Stock history is temporarily unavailable.');
 const data=await response.json(),stock=data.stocks.find(s=>s.symbol===symbol);if(!stock)throw Error('This stock has no successful history in the latest scan.');
 const days=Number(params.get('days')||data.report.filters.lookbackDays),result=stockHistory(stock,data.report,days);
 document.title=stock.symbol+' · Daily price history';$('title').textContent=`${stock.name} (${stock.symbol})`;
 $('window').textContent=`${result.start} through ${result.end} · ${days} calendar days · ${result.days.length} trading sessions · USD`;
 for(const d of result.days){const row=document.createElement('tr');[d.date,money(d.low),money(d.high),money(d.close),Number.isFinite(d.change)?`${d.change>=0?'+':''}${d.change.toFixed(2)}%`:'—'].forEach((value,i)=>{const cell=document.createElement('td');if(i===1&&d.low===result.minLow||i===2&&d.high===result.maxHigh){const strong=document.createElement('strong');strong.textContent=value;cell.append(strong)}else cell.textContent=value;if(i===4)cell.className=d.change>=0?'positive':'negative';row.append(cell)});$('historyRows').append(row)}
 $('empty').textContent=result.days.length?'':'No trading sessions are available within the selected window.';
 $('status').textContent=`Scan completed ${new Date(data.report.createdAt).toLocaleString()}. ${params.get('report')&&params.get('report')!==data.report.id?'The snapshot has updated since you opened the screener; this page shows the latest scan. ':''}${result.missingRanges?'Daily lows and highs were not recorded for some sessions; those values show — until a new scan supplies them.':''}`;
}catch(e){$('status').textContent=e.message}
