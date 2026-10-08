import {readFile,writeFile} from 'node:fs/promises';
import {attachMarketNews} from '../lib/stock-news.mjs';
const path=process.argv[2];if(!path)throw Error('Pass the published report JSON path');
const data=JSON.parse(await readFile(path,'utf8'));if(!data.report||!Array.isArray(data.stocks))throw Error('Invalid published stock report');
await attachMarketNews(data.report);
await writeFile(path,JSON.stringify(data));
console.log(JSON.stringify(data.report.marketNews));
