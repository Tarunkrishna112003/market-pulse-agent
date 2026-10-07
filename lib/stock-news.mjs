import {companyNews} from './research.mjs';
export async function attachStockNews(report,{signal}={}){
 const stocks=report.newsStocks||[];let next=0;
 async function worker(){while(next<stocks.length){const stock=stocks[next++];
  try{stock.headlines=await companyNews(stock.symbol,{signal});stock.newsStatus=stock.headlines.length?'available':'No recent headlines available';}
  catch(e){if(signal?.aborted)throw e;stock.headlines=[];stock.newsStatus='News feed temporarily unavailable';}
 }}
 await Promise.all(Array.from({length:3},worker));
 return report;
}
