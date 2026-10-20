// Explicit one-time model switch. Normal snapshots remain first-write immutable.
import {createHash} from 'node:crypto';
import {cutoffAt} from './testing-results.mjs';
export const FROZEN_SHA256='339a6f6a48eeb6b653cb96476d6b8f0a42b187e74fb88147f8eb0ae286e25de3';
export function useFrozenOctober20(previous,raw,now=new Date()){
 if(createHash('sha256').update(raw).digest('hex')!==FROZEN_SHA256)throw Error('Frozen October 20 forecast integrity check failed');
 const frozen=JSON.parse(raw),date='2026-10-20',version='annual-open-to-close-v9-direction-boosted';
 const generated=Date.parse(frozen.generatedAt);
 if(frozen.targetDate!==date||!Number.isFinite(generated)||generated>=Date.parse(cutoffAt(date))||generated>now.getTime()||frozen.lastTrainingTargetDate>=date)throw Error('Invalid frozen forecast provenance');
 const predictions=new Map(frozen.entries.map(r=>[r.symbol,r]));
 if(predictions.size!==25||frozen.entries.length!==25||previous.stocks.some(s=>!predictions.has(s.symbol)))throw Error('Frozen forecast cohort mismatch');
 const result=structuredClone(previous);
 for(const entry of result.entries){
  if(entry.date!==date)continue;
  const row=predictions.get(entry.symbol);
  if(!Number.isFinite(row.candidatePercent)||row.lastInputDate>=date)throw Error('Invalid frozen prediction');
  if(entry.prediction?.frozenSHA256===FROZEN_SHA256)continue;
  if(entry.prediction)(entry.previousPredictions??=[]).push(entry.prediction);
  entry.prediction={percent:row.candidatePercent,generatedAt:frozen.generatedAt,observedAt:now.toISOString(),
   modelVersion:version,source:'Locally frozen before market open; published during October 20 model switch',
   frozenSHA256:FROZEN_SHA256,originallyPublic:false,upProbability:row.candidateUpProbability};
  delete entry.errorPoints;delete entry.directionCorrect;
 }
 return result;
}
