"""Local end-to-end experiments, with a frozen development choice before confirmation."""
import csv
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
import joblib
import numpy as np
from sklearn.base import clone
from forecast_benchmark import arrays,before
from forecast_features import PastFeatureBuilder,RECENT_NAMES
from forecast_research import ForecastExperiment,RECIPES,evaluate,select_joint

REPO=Path(__file__).resolve().parent.parent
INPUT=REPO/'work/backtest-2026-08-19_2026-10-19'
PAIRED=REPO/'work/model-comparison-2026-08-19_2026-10-19'
OUTPUT=Path(os.environ.get('MARKET_PULSE_RESEARCH_OUTPUT',str(REPO/'work/forecast-research-2026-08-19_2026-10-19')))
spec=importlib.util.spec_from_file_location('historical_replay',REPO/'scripts/historical-backtest.py')
replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)


def base_predict(template,rows,current):
    variant=template['metrics']['features'];x,y=arrays(rows,variant);px,_=arrays(current,variant)
    return clone(template['model']).fit(x,y).predict(px)


def get_predictions(models,rows):
    result={name:model.predict(rows) for name,model in models.items()}
    result['blend_direction_regression']=.5*result['direction_boosted']+.5*result['boosted_median_volatility_scaled']
    return result


def select_development(rows):
    truth=np.array([r['actualLogReturn'] for r in rows])
    predictions={name:np.array([r['predictions'][name] for r in rows]) for name in rows[0]['predictions'] if name!='v7_reference'}
    reference=np.array([r['predictions']['v7_reference'] for r in rows])
    return select_joint(truth,predictions,reference)


def summarize(rows,name):
    y=np.array([r['actualLogReturn'] for r in rows]);p=np.array([r['predictions'][name] for r in rows])
    result=evaluate(y,p);result['samples']=len(rows);result['zeroMAE']=float(np.mean(np.abs(np.expm1(y)*100)))
    result['largeErrorsOver2pp']=float(np.mean(np.abs(np.expm1(y)*100-np.expm1(p)*100)>2))
    result['largeErrorsOver5pp']=float(np.mean(np.abs(np.expm1(y)*100-np.expm1(p)*100)>5))
    probabilities=[r.get('probabilities',{}).get(name) for r in rows]
    intervals=[r.get('intervals',{}).get(name) for r in rows]
    if all(value is not None for value in probabilities):
        probability=np.clip(np.array(probabilities),1e-8,1-1e-8);up=y>0
        result['brierScore']=float(np.mean((probability-up)**2))
        result['logLoss']=float(-np.mean(up*np.log(probability)+(1-up)*np.log(1-probability)))
    if all(value is not None for value in intervals):
        bounds=np.array(intervals);result['intervalCoverage']=float(np.mean((y>=bounds[:,0])&(y<=bounds[:,1])))
        result['meanIntervalWidthPoints']=float(np.mean(np.expm1(bounds[:,1])*100-np.expm1(bounds[:,0])*100))
    return result


def report(frozen,actual,choice):
    joined=[{**row,'actualLogReturn':np.log1p(actual[(row['date'],row['symbol'])]['actualPercent']/100)} for row in frozen]
    names=list(joined[0]['predictions']);dev=[r for r in joined if r['date']<'2026-10-01'];confirm=[r for r in joined if r['date']>='2026-10-01']
    metrics={name:{'development':summarize(dev,name),'confirmation':summarize(confirm,name),'wholePeriod':summarize(joined,name)} for name in names}
    result={'developmentChoice':choice,'metrics':metrics,'entries':joined,'caveats':[
        'Exploratory research: the original baseline results for this period were inspected before designing these experiments.',
        'The development choice is frozen from Aug 19–Sep 30 before computing new Oct 1–19 predictions. This is a chronological confirmation segment, not a genuinely new untouched market period.',
        'Same existing raw OHLCV data, fixed 25-stock cohort, 365-day label/feature history, 90-day intraday window and 6 AM Pacific cutoff. No archived news is substituted.',
        'New features use only prior completed bars. Stock/target groups are balanced, morning samples prioritized, and recency weights use a fixed 60-calendar-day half-life.',
        'Classification recipes estimate up/down probability directly, calibrate it on earlier dates, and convert conditional signed-magnitude distributions into a median return.',
        'Recipes and hyperparameters were fixed before this run. Model parameters are refitted daily; calibration and joint selection use only earlier dates.',
        'Promotion gate requires at least 0.5% lower MAE and 2 percentage points higher direction accuracy than v7 on the earlier selection segment; otherwise it falls back to v7.',
        'Confirmation results cannot establish future accuracy. No production changes are applied by this research script.']}
    (OUTPUT/'research-results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    with (OUTPUT/'research-results.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=['date','symbol','actualPercent',*names]);writer.writeheader()
        for row in joined:writer.writerow({'date':row['date'],'symbol':row['symbol'],'actualPercent':float(np.expm1(row['actualLogReturn'])*100),**{name:float(np.expm1(value)*100) for name,value in row['predictions'].items()}})
    lines=['# End-to-end forecast experiments','',f"Development choice frozen before confirmation: **{choice}**.",'',
        '| Recipe | Development direction | Development MAE (pp) | Confirmation direction | Confirmation MAE (pp) |','|---|---:|---:|---:|---:|']
    for name,metric in metrics.items():lines.append(f"| {name} | {metric['development']['direction']:.2%} | {metric['development']['mae']:.4f} | {metric['confirmation']['direction']:.2%} | {metric['confirmation']['mae']:.4f} |")
    lines.extend(['','## Method and limits','',*['- '+c for c in result['caveats']]])
    (OUTPUT/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'developmentChoice':choice,'metrics':metrics},indent=2),flush=True)
    return result


def run():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    source=json.loads((INPUT/'historical-data.json').read_text());market=json.loads((INPUT/'market.json').read_text())['daily']
    paired=json.loads((PAIRED/'comparison.json').read_text());actual={(r['date'],r['symbol']):r for r in paired['entries']}
    dates=sorted({key[0] for key in actual});symbols=[c['symbol'] for c in source['companies']]
    builder=PastFeatureBuilder(source['companies'],market,symbols)
    plan={'recipes':RECIPES,'recentFeatureNames':RECENT_NAMES,'stockIdentityFeatures':symbols,
          'developmentEnd':'2026-09-30','confirmationStart':'2026-10-01','confirmationEnd':'2026-10-19',
          'sampleWeights':'one total weight per stock/target; morning priority 2; 60-calendar-day recency half-life',
          'promotionGate':{'relativeMAEImprovement':.005,'directionImprovement':.02},'evaluationStatus':'Exploratory; original period already inspected.'}
    digest=hashlib.sha256()
    paths=[Path(__file__),REPO/'scripts/forecast_features.py',REPO/'scripts/forecast_research.py',INPUT/'historical-data.json',INPUT/'market.json',INPUT/'results/training-rows.json',PAIRED/'comparison.json']
    paths+=sorted((PAIRED/'legacy').glob('*/prediction-models/365-day-model.joblib'))
    for path in paths:digest.update(path.read_bytes())
    plan['fingerprint']=digest.hexdigest();plan_path=OUTPUT/'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text())['fingerprint']!=plan['fingerprint']:raise ValueError('Research inputs changed; use fresh output directory')
    plan_path.write_text(json.dumps(plan,indent=2))
    enriched_path=OUTPUT/'enriched-rows.joblib'
    if enriched_path.exists():rows=joblib.load(enriched_path)
    else:
        rows=[]
        for row in json.loads((INPUT/'results/training-rows.json').read_text()):rows.append(builder.enrich(row))
        joblib.dump(rows,enriched_path);print(f'Built {len(rows)} rows with {len(rows[0]["z"])} past-only features',flush=True)
    frozen=[];choice=None;configurations={};selected=None
    for index,date in enumerate(dates):
        if date=='2026-10-01':
            # Only development labels are opened for the global procedure choice.
            dev=[{**r,'actualLogReturn':np.log1p(actual[(r['date'],r['symbol'])]['actualPercent']/100)} for r in frozen if r['date']<'2026-10-01']
            choice=select_development(dev)
            (OUTPUT/'development-choice.json').write_text(json.dumps({'recipe':choice,'selectedBeforeConfirmation':True,'lastOutcomeUsed':'2026-09-30'},indent=2))
            print(f'Frozen development choice before October confirmation: {choice}',flush=True)
        eligible=replay.training_rows(rows,date,365)
        if index%10==0:
            block=date;started=time.monotonic();template=joblib.load(PAIRED/'legacy'/block/'prediction-models/365-day-model.joblib')
            prior_dates=sorted({r['targetDate'] for r in eligible});cal_start=prior_dates[-30];score_start=prior_dates[-15]
            calibration=[r for r in eligible if r['date']==r['targetDate'] and cal_start<=r['targetDate']<score_start]
            validation=[r for r in eligible if r['date']==r['targetDate'] and r['targetDate']>=score_start]
            train=before(eligible,min(r['date'] for r in calibration))
            assert max(r['targetDate'] for r in train)<min(r['date'] for r in calibration)
            assert max(r['targetDate'] for r in calibration)<min(r['date'] for r in validation)
            prototypes={name:ForecastExperiment(name).fit(train,date).calibrate_probability(calibration) for name in RECIPES}
            configurations={name:model.probability_calibrator for name,model in prototypes.items() if model.kind in ('logistic','classifier')}
            predictions=get_predictions(prototypes,validation)
            reference=base_predict(template,train,validation);truth=np.array([r['y'] for r in validation])
            selected=select_joint(truth,predictions,reference)
            ranking=sorted(predictions,key=lambda name:evaluate(truth,predictions[name])['mae'])[:3]
            mixture=np.mean([predictions[name] for name in ranking],axis=0)
            ensemble_ok=select_joint(truth,{'mixture':mixture},reference)=='mixture'
            selection={'block':block,'selected':selected,'ensembleRecipes':ranking,'useEnsemble':ensemble_ok,
                       'baseTrainingTargetEnd':max(r['targetDate'] for r in train),'probabilityCalibrationStart':min(r['targetDate'] for r in calibration),
                       'probabilityCalibrationEnd':max(r['targetDate'] for r in calibration),'selectionStart':min(r['targetDate'] for r in validation),
                       'selectionEnd':max(r['targetDate'] for r in validation),'metrics':{name:evaluate(truth,p) for name,p in predictions.items()},'reference':evaluate(truth,reference)}
            (OUTPUT/f'selection-{block}.json').write_text(json.dumps(selection,indent=2,allow_nan=False))
            print(f'{block}: prior-only joint choice {selected}; ensemble={ensemble_ok}; {time.monotonic()-started:.1f}s',flush=True)
        saved=OUTPUT/f'frozen-{date}.json'
        if saved.exists():frozen.extend(json.loads(saved.read_text()));continue
        ready=[]
        for symbol in symbols:
            context=replay.prediction_context(builder.companies[symbol],market,date)
            if context is None:raise ValueError('Missing context')
            ready.append(builder.enrich({'symbol':symbol,'date':date,'targetDate':date,'x':context['x'],'y':0,'lastInputDate':context['lastInputDate']}))
        models={name:ForecastExperiment(name).fit(eligible,date) for name in RECIPES}
        for name,calibrator in configurations.items():models[name].probability_calibrator=calibrator
        predictions=get_predictions(models,ready)
        probability_values={name:model.probability(ready) for name,model in models.items() if model.kind in ('logistic','classifier')}
        interval_values={name:np.stack([model.predict_quantile(ready,.1),model.predict_quantile(ready,.9)],axis=1) for name,model in models.items() if model.kind in ('logistic','classifier')}
        reference=np.log1p([actual[(date,symbol)]['methods']['v7_unadjusted']/100 for symbol in symbols])
        predictions['joint_selected']=reference.copy() if selected=='v7_reference' else predictions[selected]
        predictions['joint_ensemble']=np.mean([predictions[name] for name in ranking],axis=0) if ensemble_ok else reference.copy()
        predictions['v7_reference']=reference
        predictions['v8_reference']=np.log1p([actual[(date,symbol)]['methods']['v8_unadjusted']/100 for symbol in symbols])
        daily=[]
        for i,symbol in enumerate(symbols):
            values={name:float(p[i]) for name,p in predictions.items()}
            if not np.isfinite(list(values.values())).all() or max(abs(v) for v in values.values())>1:raise ValueError('Unsupported forecast')
            daily.append({'date':date,'symbol':symbol,'lastInputDate':ready[i]['lastInputDate'],
                          'trainingTargetEnd':max(r['targetDate'] for r in eligible),'selectionBlock':block,'predictions':values,'probabilities':{name:float(p[i]) for name,p in probability_values.items()},'intervals':{name:bounds[i].tolist() for name,bounds in interval_values.items()}})
        saved.write_text(json.dumps(daily,indent=2,allow_nan=False));frozen.extend(daily)
        print(f'{date}: froze {len(daily)} forecasts across {len(predictions)} fixed recipes',flush=True)
    return report(frozen,actual,choice)


if __name__=='__main__':run()
