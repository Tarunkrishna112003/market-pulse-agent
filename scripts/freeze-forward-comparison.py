"""Freeze a prospective local candidate/reference comparison without publishing."""
import hashlib
import importlib.util
import json
import os
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import joblib
import numpy as np
from sklearn.base import clone
from forecast_benchmark import arrays,before,candidates,fit_model
from forecast_models import WeightedForecast
from forecast_features import PastFeatureBuilder
from forecast_research import ForecastExperiment


def run():
    repo=Path(__file__).resolve().parent.parent;raw=repo/'work/backtest-2026-08-19_2026-10-19'
    research=repo/'work/forecast-research-2026-08-19_2026-10-19';paired=repo/'work/model-comparison-2026-08-19_2026-10-19'
    output=research/'forward';output.mkdir(exist_ok=True)
    source=json.loads((raw/'historical-data.json').read_text());market=json.loads((raw/'market.json').read_text())['daily'];last=market[-1]['date']
    target=subprocess.check_output(['node','--input-type=module','-e',"import {nextTradingDay} from './lib/trading-calendar.mjs'; console.log(nextTradingDay(process.argv[1]));",last],cwd=repo,text=True).strip()
    cutoff=datetime.fromisoformat(target).replace(hour=6,tzinfo=ZoneInfo('America/Los_Angeles')).astimezone(timezone.utc)
    now=datetime.now(timezone.utc)
    if now>=cutoff:raise ValueError('Refuse to create or backfill a forward forecast after its morning cutoff')
    path=output/f'{target}.json'
    if path.exists():print(f'Existing frozen forward forecasts preserved: {path}',flush=True);return
    spec=importlib.util.spec_from_file_location('historical_replay',repo/'scripts/historical-backtest.py');replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    symbols=[c['symbol'] for c in source['companies']];builder=PastFeatureBuilder(source['companies'],market,symbols)
    rows=joblib.load(research/'converged/enriched-rows.joblib');eligible=replay.training_rows(rows,target,365)
    assert max(r['targetDate'] for r in eligible)<target
    block='2026-10-15';prior=replay.training_rows(rows,block,365);dates=sorted({r['targetDate'] for r in prior});start=dates[-30];split=dates[-15]
    calibration=[r for r in prior if r['date']==r['targetDate'] and start<=r['targetDate']<split]
    train=before(prior,min(r['date'] for r in calibration))
    prototype=ForecastExperiment('direction_boosted').fit(train,block).calibrate_probability(calibration)
    candidate=ForecastExperiment('direction_boosted').fit(eligible,target);candidate.probability_calibrator=prototype.probability_calibrator
    ready=[]
    for symbol in symbols:
        context=replay.prediction_context(builder.companies[symbol],market,target)
        if context is None or context['lastInputDate']!=last:raise ValueError('Missing most recent complete input session')
        ready.append(builder.enrich({'symbol':symbol,'date':target,'targetDate':target,'x':context['x'],'y':0,'lastInputDate':context['lastInputDate']}))
    p=candidate.predict(ready);probability=candidate.probability(ready);lower=candidate.predict_quantile(ready,.1);upper=candidate.predict_quantile(ready,.9)
    legacy=joblib.load(paired/'legacy'/block/'prediction-models/365-day-model.joblib');variant=legacy['metrics']['features'];x,y=arrays(eligible,variant);px,_=arrays(ready,variant)
    legacy_model=clone(legacy['model']).fit(x,y);old=legacy_model.predict(px)
    selection=json.loads((raw/f'results/selection-{block}.json').read_text());registry=candidates();variant=selection['features'];weights=selection['ensembleWeights']
    local=WeightedForecast([fit_model(registry[name],eligible,variant) for name in weights],list(weights.values()));px,_=arrays(ready,variant);v8=local.predict(px)
    generated=datetime.now(timezone.utc)
    if generated>=cutoff:raise ValueError('Training missed the cutoff; no forward forecasts will be saved')
    entries=[]
    for i,symbol in enumerate(symbols):
        values=[p[i],old[i],v8[i],lower[i],upper[i]]
        if not np.isfinite(values).all() or max(abs(v) for v in values)>1:raise ValueError('Unsupported prediction')
        entries.append({'symbol':symbol,'candidatePercent':float(np.expm1(p[i])*100),'candidateUpProbability':float(probability[i]),
                        'candidate80Range':{'lowerPercent':float(np.expm1(lower[i])*100),'upperPercent':float(np.expm1(upper[i])*100)},
                        'v7Percent':float(np.expm1(old[i])*100),'v8Percent':float(np.expm1(v8[i])*100),'lastInputDate':last})
    inputs=[raw/'historical-data.json',raw/'market.json',research/'converged/plan.json',repo/'scripts/forecast_features.py',repo/'scripts/forecast_research.py',Path(__file__)]
    hashes={str(v.relative_to(repo)):hashlib.sha256(v.read_bytes()).hexdigest() for v in inputs}
    result={'targetDate':target,'generatedAt':generated.isoformat(),'morningCutoff':cutoff.isoformat(),'priceHistoryDownloadedAt':source['downloadedAt'],
            'lastTrainingTargetDate':max(r['targetDate'] for r in eligible),'candidate':'direction_boosted','status':'Experimental local forward comparison; no outcomes known or included.',
            'modelSettingsSelectedAsOf':block,'cohort':'Same fixed 25 stocks from the saved weekly test','dataScope':'Price-only; prior completed sessions',
            'inputSHA256':hashes,'entries':entries}
    # Exclusive creation: later runs cannot substitute new predictions after seeing outcomes.
    with path.open('x') as file:json.dump(result,file,indent=2,allow_nan=False)
    joblib.dump({'candidate':candidate,'v7':legacy_model,'v8':local,'symbols':symbols,'targetDate':target},output/f'{target}-models.joblib')
    print(json.dumps({'targetDate':target,'generatedAt':generated.isoformat(),'cutoff':cutoff.isoformat(),'stocks':len(entries),'saved':str(path)},indent=2),flush=True)


if __name__=='__main__':run()
