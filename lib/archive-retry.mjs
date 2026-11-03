// Retry only transient transport/service failures; callers preserve immutable writes.
export function transientArchiveError(error){return /HTTP 5\d\d|HTTP 429|timed? ?out|ECONNRESET|EAI_AGAIN|TLS handshake|connection reset|unexpected EOF/i.test(String(error?.stderr||error?.message||error));}
export async function withArchiveRetry(operation,{attempts=4,sleep=ms=>new Promise(r=>setTimeout(r,ms))}={}){
 for(let attempt=0;attempt<attempts;attempt++){
  try{return await operation()}catch(error){if(attempt===attempts-1||!transientArchiveError(error))throw error;await sleep(2000*2**attempt)}
 }
}
