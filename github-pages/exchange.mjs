export function exchangeLabel(stock){
 const raw=String(stock?.exchangeShortName||stock?.exchange||'').toUpperCase().replace(/[^A-Z]/g,'');
 if(raw.startsWith('NASDAQ')||['NMS','NGM','NCM','NAS'].includes(raw))return 'NASDAQ';
 if(['NYSE','NYQ','NEWYORKSTOCKEXCHANGE'].includes(raw))return 'NYSE';
 return 'Exchange unavailable';
}
export function tickerLabel(stock){return `${stock.symbol} · ${exchangeLabel(stock)}`;}

