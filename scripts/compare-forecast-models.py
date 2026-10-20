"""Compare committed v7, frozen local v8, and prior-only magnitude calibration locally."""
import argparse
import contextlib
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import joblib
import numpy as np
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from forecast_benchmark import arrays,before,candidates,fit_model
from forecast_models import WeightedForecast
from forecast_calibration import fit_calibration,apply_calibration,SCALES,BLENDS

REPO=Path(__file__).resolve().parent.parent
INPUT=REPO/'work/backtest-2026-08-19_2026-10-19'
ORIGINAL=INPUT/'results'
OUTPUT=REPO/'work/model-comparison-2026-08-19_2026-10-19'
spec=importlib.util.spec_from_file_location('historical_replay',REPO/'scripts/historical-backtest.py')
replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)


@contextlib.contextmanager
def in_directory(path):
    previous=Path.cwd();path.mkdir(parents=True,exist_ok=True)
    try:os.chdir(path);yield
    finally:os.chdir(previous)


def load_rows():return json.loads((ORIGINAL/'training-rows.json').read_text())


def prepare_legacy(date):
    path=OUTPUT/'legacy'/date
    if (path/'selection.json').exists():print(f'v7 selection {date}: restored',flush=True);return
    warnings.filterwarnings('ignore',category=ConvergenceWarning)
    spec=importlib.util.spec_from_file_location('legacy_forecaster',OUTPUT/'legacy/ml-prediction.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    if legacy.FEATURES!=replay.ml.FEATURES:raise ValueError('Feature schemas differ')
    eligible=replay.training_rows(load_rows(),date,365)
    assert max(r['targetDate'] for r in eligible)<date
    started=time.monotonic();print(f'v7 selection {date}: {len(eligible)} strictly earlier rows',flush=True)
    with in_directory(path):
        _,metric=legacy.fit_window(eligible,{},365)
        # Save only the real selected estimator; the old metadata always reports equal ensemble weights even when an individual wins.
        (Path('selection.json')).write_text(json.dumps(metric,indent=2,allow_nan=False))
    print(f"v7 selection {date}: {metric['model']}, {time.monotonic()-started:.1f}s",flush=True)


def magnitude_model():
    return HistGradientBoostingRegressor(loss='absolute_error',max_iter=80,max_leaf_nodes=7,min_samples_leaf=50,
                                        learning_rate=.05,l2_regularization=20,early_stopping=False,random_state=42)


def fit_base(template,eligible,variant,kind):
    if kind=='v7':
        x,y=arrays(eligible,variant);return clone(template).fit(x,y)
    registry=candidates()
    return WeightedForecast([fit_model(registry[name],eligible,variant) for name in template],list(template.values()))


def prepare_calibration(date,eligible,kind,template,variant):
    dates=sorted({r['targetDate'] for r in eligible});start=dates[-30]
    valid=[r for r in eligible if r['date']==r['targetDate'] and r['targetDate']>=start]
    train=before(eligible,min(r['date'] for r in valid))
    assert max(r['targetDate'] for r in train)<min(r['date'] for r in valid)
    base=fit_base(template,train,variant,kind)
    tx,ty=arrays(train,variant);vx,vy=arrays(valid,variant)
    absolute=magnitude_model().fit(tx,np.abs(ty))
    config=fit_calibration(base.predict(vx),vy,[r['symbol'] for r in valid],[r['targetDate'] for r in valid],absolute.predict(vx),date)
    config['baseFitTargetEnd']=max(r['targetDate'] for r in train)
    config['featureVariant']=variant
    return config


def score(rows,method):
    actual=np.array([r['actualPercent'] for r in rows]);p=np.array([r['methods'][method] for r in rows]);correct=np.sign(p)==np.sign(actual)
    zero=np.abs(actual);error=np.abs(actual-p)
    return {'samples':len(rows),'directionAccuracy':float(correct.mean()),'meanAbsoluteError':float(error.mean()),
            'zeroBaselineMAE':float(zero.mean()),'meanAbsolutePrediction':float(np.abs(p).mean()),
            'correctDirectionMAE':float(error[correct].mean()) if correct.any() else None,
            'wrongDirectionMAE':float(error[~correct].mean()) if (~correct).any() else None}


def report(frozen,source):
    actual={(r['date'],r['symbol']):r for r in source['entries']}
    joined=[]
    for row in frozen:
        reference=actual[(row['date'],row['symbol'])]
        joined.append({**row,'actualPercent':reference['actualPercent']})
    names=list(joined[0]['methods']);summary={name:score(joined,name) for name in names}
    daily=[{'date':date,'methods':{name:score([r for r in joined if r['date']==date],name) for name in names}} for date in sorted({r['date'] for r in joined})]
    # Paired resampling keeps stocks sharing a day together and preserves short serial blocks.
    rng=np.random.default_rng(42);improvements={name:[] for name in names if name!='v7_unadjusted'}
    for _ in range(3000):
        starts=rng.integers(0,len(daily),size=(len(daily)+4)//5)
        indexes=np.concatenate([(start+np.arange(5))%len(daily) for start in starts])[:len(daily)]
        for name in improvements:
            improvements[name].append(float(np.mean([daily[i]['methods']['v7_unadjusted']['meanAbsoluteError']-daily[i]['methods'][name]['meanAbsoluteError'] for i in indexes])))
    intervals={name:np.quantile(values,[.025,.975]).tolist() for name,values in improvements.items()}
    result={'summary':summary,'MAEImprovementVsV7_95Intervals':intervals,'daily':daily,'entries':joined,
            'caveats':source['caveats']+['These dates and the original v8 results were already inspected. This comparison is exploratory research, not a fresh untouched holdout.',
            'Both versions share the same price-only data, 365-day training outcome window, 365-day feature lookback, 90-day intraday window, fixed cohort, ten-session selection schedule and daily refitting.',
            'v7 uses its original committed candidate selection and estimator fitting. v8 uses the previously frozen local predictions.',
            'Calibrators are fitted only to earlier morning predictions from an earlier-fit model. Positive scaling and magnitude blending preserve each base forecast direction.',
            'Daily refits can shift calibration quality relative to its earlier-fit estimation. No live improvement is established by this retrospective comparison.']}
    (OUTPUT/'comparison.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    with (OUTPUT/'comparison.csv').open('w',newline='') as file:
        fields=['date','symbol','actualPercent',*names];writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        writer.writerows({'date':r['date'],'symbol':r['symbol'],'actualPercent':r['actualPercent'],**r['methods']} for r in joined)
    lines=['# Same-period model and magnitude comparison','',f"{len(joined)} comparisons · {len(daily)} trading days · same 25-stock cohort.",'',
           '| Method | Direction accuracy | MAE (pp) | MAE when direction correct | MAE when direction wrong |','|---|---:|---:|---:|---:|']
    for name,metric in summary.items():lines.append(f"| {name} | {metric['directionAccuracy']:.2%} | {metric['meanAbsoluteError']:.4f} | {metric['correctDirectionMAE']:.4f} | {metric['wrongDirectionMAE']:.4f} |")
    lines.extend(['',f"Always-zero baseline MAE: {summary[names[0]]['zeroBaselineMAE']:.4f} percentage points.",'','## Limits','',*['- '+c for c in result['caveats']]])
    (OUTPUT/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    return result


def run():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    source=json.loads((ORIGINAL/'results.json').read_text());dates=sorted({r['date'] for r in source['entries']});blocks=dates[::10]
    plan={'start':dates[0],'end':dates[-1],'stocks':25,'sessions':len(dates),'legacyCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
          'calibrationSessions':30,'positiveScaleGrid':SCALES,'magnitudeBlendGrid':BLENDS,'stockScaleShrinkageDates':60,
          'selectionSchedule':'Before each ten-session block; estimators refitted daily.',
          'noProductionChanges':True,'evaluationStatus':'Exploratory: the original results for this period have already been inspected.'}
    digest=hashlib.sha256()
    for path in [Path(__file__),REPO/'scripts/forecast_calibration.py',REPO/'scripts/forecast_models.py',REPO/'scripts/forecast_benchmark.py',REPO/'scripts/historical-backtest.py',ORIGINAL/'training-rows.json',ORIGINAL/'results.json',OUTPUT/'legacy/ml-prediction.py',OUTPUT/'legacy/forecast_models.py']:digest.update(path.read_bytes())
    fingerprint=digest.hexdigest();manifest=OUTPUT/'plan.json'
    if manifest.exists() and json.loads(manifest.read_text())['fingerprint']!=fingerprint:raise ValueError('Comparison inputs changed; use a new output directory')
    manifest.write_text(json.dumps({**plan,'fingerprint':fingerprint},indent=2))
    # Separate processes keep torch RNG and estimator state isolated between independent blocks.
    def worker(date):
        return subprocess.run([sys.executable,str(Path(__file__).resolve()),'--prepare-date',date],cwd=REPO,check=True)
    with ThreadPoolExecutor(max_workers=3) as executor:list(executor.map(worker,blocks))
    warnings.filterwarnings('ignore',category=ConvergenceWarning)
    all_rows=load_rows();source_data=json.loads((INPUT/'historical-data.json').read_text());companies=source_data['companies'];market=json.loads((INPUT/'market.json').read_text())['daily']
    reference={(r['date'],r['symbol']):r for r in source['entries']};frozen=[];configurations={};templates={};variants={}
    for index,date in enumerate(dates):
        eligible=replay.training_rows(all_rows,date,365)
        if index%10==0:
            block=date
            legacy=joblib.load(OUTPUT/'legacy'/block/'prediction-models/365-day-model.joblib')
            local=json.loads((ORIGINAL/f'selection-{block}.json').read_text())
            templates={'v7':legacy['model'],'v8':local['ensembleWeights']};variants={'v7':legacy['metrics']['features'],'v8':local['features']}
            for kind in ('v7','v8'):
                config_path=OUTPUT/f'calibration-{kind}-{block}.json'
                if config_path.exists():configurations[kind]=json.loads(config_path.read_text())
                else:
                    configurations[kind]=prepare_calibration(date,eligible,kind,templates[kind],variants[kind])
                    config_path.write_text(json.dumps(configurations[kind],indent=2,allow_nan=False))
            print(f'Calibration {block}: v7 scale={configurations["v7"]["scale"]}, blend={configurations["v7"]["magnitudeBlend"]}; v8 scale={configurations["v8"]["scale"]}, blend={configurations["v8"]["magnitudeBlend"]}',flush=True)
        saved=OUTPUT/f'frozen-{date}.json'
        if saved.exists():frozen.extend(json.loads(saved.read_text()));continue
        contexts={c['symbol']:replay.prediction_context(c,market,date) for c in companies}
        if any(context is None for context in contexts.values()):raise ValueError('Missing historical context; refuse unmatched comparisons')
        symbols=list(contexts);ready=[{'symbol':symbol,'x':contexts[symbol]['x'],'y':0} for symbol in symbols]
        daily=[{'date':date,'symbol':symbol,'lastInputDate':contexts[symbol]['lastInputDate'],
                'trainingTargetEnd':max(r['targetDate'] for r in eligible),'selectionBlock':block,'methods':{}} for symbol in symbols]
        for kind in ('v7','v8'):
            variant=variants[kind];px,_=arrays(ready,variant)
            if kind=='v7':base=fit_base(templates[kind],eligible,variant,kind).predict(px)
            else:base=np.log1p([reference[(date,symbol)]['predictedPercent']/100 for symbol in symbols])
            if configurations[kind]['magnitudeBlend']:
                tx,ty=arrays(eligible,variant);absolute=magnitude_model().fit(tx,np.abs(ty)).predict(px)
            else:absolute=np.abs(base)
            methods=apply_calibration(base,symbols,absolute,configurations[kind])
            for method,values in methods.items():
                if not np.isfinite(values).all() or np.any(np.abs(values)>1):raise ValueError('Unsupported forecast output')
                if not np.array_equal(np.sign(values),np.sign(base)):raise AssertionError('Magnitude calibration changed direction')
                for row,value in zip(daily,values):row['methods'][kind+'_'+method]=float(np.expm1(value)*100)
        # No target-day prices are written to frozen prediction files.
        saved.write_text(json.dumps(daily,indent=2,allow_nan=False));frozen.extend(daily)
        print(f'{date}: froze {len(daily)} paired forecasts',flush=True)
    return report(frozen,source)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepare-date');args=parser.parse_args()
    if args.prepare_date:prepare_legacy(args.prepare_date)
    else:run()
