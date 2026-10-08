const NEWS_FEEDS=[{url:'https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US',source:'Yahoo Finance'},{url:'https://news.yahoo.com/rss/topstories',source:'Yahoo News'}];
const TOPICS=[
 ['Investment / funding',/\b(invest(?:s|ed|ing|ment|ments)?|funding|financing|raises?|raised|capital injection|backs?|backed)\b/i],
 ['Acquisition / merger',/\b(acqui(?:re[sd]?|ring|sition[s]?)|merger|merges?|buyout|takeover)\b/i],
 ['Deal / partnership',/\b(deals?|partnerships?|partners? with|contracts?|agreements?|joint venture|collaborat(?:ion|ions|es?))\b/i],
];
const decode=value=>value.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g,'$1').replace(/<[^>]*>/g,'').replace(/&(?:amp|quot|apos|lt|gt);/g,s=>({'&amp;':'&','&quot;':'"','&apos;':"'",'&lt;':'<','&gt;':'>'}[s])).replace(/&#(x[\da-f]+|\d+);/gi,(_,n)=>{const code=n[0].toLowerCase()==='x'?parseInt(n.slice(1),16):Number(n);return code>0&&code<=0x10ffff?String.fromCodePoint(code):''}).trim();
export function parseMarketNews(xml,now=new Date(),source='Yahoo Finance'){
 if(!/<(?:rss|feed)\b/i.test(xml))throw Error('Yahoo returned an invalid news feed');
 const seen=new Set(),items=[];
 for(const item of xml.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)){
  const tag=name=>decode(item[1].match(new RegExp('<'+name+'\\b[^>]*>([\\s\\S]*?)</'+name+'>','i'))?.[1]||'');
  const title=tag('title'),url=tag('link'),published=Date.parse(tag('pubDate'));
  const topic=TOPICS.find(([,pattern])=>pattern.test(title));
  if(!title||!/^https:\/\//i.test(url)||!topic||!Number.isFinite(published)||published<now.getTime()-7*86400000||published>now.getTime()+3600000)continue;
  if(/\b(should you|stocks? to buy|price target|stock picks?|buy or sell)\b/i.test(title))continue;
  const key=title.toLowerCase();if(seen.has(key))continue;seen.add(key);
  items.push({title:title.slice(0,500),url,publishedAt:new Date(published).toISOString(),source:tag('source')||source,category:topic[0]});
 }
 return items.sort((a,b)=>b.publishedAt.localeCompare(a.publishedAt)).slice(0,20);
}
export async function attachMarketNews(report,{signal,now=new Date()}={}){
 const news={source:'Yahoo Finance',feedUrl:NEWS_FEEDS[0].url,fetchedAt:now.toISOString(),items:[],state:'unavailable',errors:[]};
 for(const feed of NEWS_FEEDS){
  try{
   let xml;
   for(let attempt=0;attempt<2;attempt++){
    const response=await fetch(feed.url,{headers:{'User-Agent':'Mozilla/5.0','Accept':'application/rss+xml, application/xml, text/xml'},signal:signal?AbortSignal.any([signal,AbortSignal.timeout(15000)]):AbortSignal.timeout(15000)});
    if(response.ok){xml=await response.text();break;}
    if(attempt===0&&(response.status===429||response.status>=500)){await new Promise(resolve=>setTimeout(resolve,1000));if(signal?.aborted)throw signal.reason;continue;}
    throw Error('Yahoo news HTTP '+response.status);
   }
   const items=parseMarketNews(xml,now,feed.source);
   news.source=feed.source;news.feedUrl=feed.url;news.items=items;news.state=items.length?'available':'empty';if(items.length)break;
  }catch(e){if(signal?.aborted)throw e;news.errors.push({feedUrl:feed.url,error:e.message});}
 }
 if(news.state==='unavailable')news.error=news.errors.map(e=>e.error).join('; ');
 report.marketNews=news;return report;
}
