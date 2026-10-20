"""Local retrospective walk-forward replay; never writes to public-site or weekly records."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import joblib
import numpy as np
from forecast_benchmark import choose,arrays,before,candidates,fit_model
from forecast_models import WeightedForecast

spec=importlib.util.spec_from_file_location('prediction_ml',Path(__file__).with_name('ml-prediction.py'))
ml=importlib.util.module_from_spec(spec);spec.loader.exec_module(ml)


def training_rows(rows,target_date,training_days=365):
    start=(datetime.fromisoformat(target_date)-timedelta(days=training_days)).date().isoformat()
    hourly_start=(datetime.fromisoformat(target_date)-timedelta(days=90)).date().isoformat()
    return [r for r in rows if start<=r['targetDate']<target_date and r['date']<target_date
            and (r['date']==r['targetDate'] or r['date']>=hourly_start)]


def prediction_context(company,market,target_date):
    # Physically remove the held-out day and all later bars before constructing inputs.
    past={**company,'daily':[d for d in company['daily'] if d['date']<target_date],
          'hourly':[],'newsTimeline':[]}
    market_past=[d for d in market if d['date']<target_date]
    if not past['daily'] or not market_past:return None
    previous=market_past[-1]['date'];last=past['daily'][-1]
    if last['date']!=previous:return None
    x=ml.feature_vector(past,target_date,last['close'],540,365,market_past)
    if x is None:return None
    cutoff=datetime.fromisoformat(target_date).replace(hour=6,tzinfo=ZoneInfo('America/Los_Angeles'))
    return {'x':x,'baseDate':last['date'],'basePrice':last['close'],
            'informationCutoff':cutoff.astimezone(timezone.utc).isoformat(),
            'lastInputDate':last['date']}


def summarize(entries):
    resolved=[e for e in entries if e.get('actualPercent') is not None and e.get('predictedPercent') is not None]
    if not resolved:return {'comparisons':0}
    return {'comparisons':len(resolved),'correctDirections':sum(e['directionCorrect'] for e in resolved),
            'directionAccuracy':sum(e['directionCorrect'] for e in resolved)/len(resolved),
            'meanAbsoluteError':sum(e['errorPoints'] for e in resolved)/len(resolved),
            'zeroBaselineMAE':sum(abs(e['actualPercent']) for e in resolved)/len(resolved),
            'medianBaselineMAE':sum(abs(e['actualPercent']-e['medianBaselinePercent']) for e in resolved)/len(resolved),
            'intervalCoverage':sum(e['lowerPercent']<=e['actualPercent']<=e['upperPercent'] for e in resolved)/len(resolved)}


def finalize(frozen,companies):
    # This step is deliberately separate: target opens/closes cannot choose predictions.
    actuals={c['symbol']:{d['date']:d for d in c['daily']} for c in companies}
    result=[]
    for prediction in frozen:
        entry=dict(prediction);day=actuals.get(entry['symbol'],{}).get(entry['date'])
        if entry.get('predictedPercent') is None:entry['status']='prediction-unavailable'
        elif day and all(isinstance(day.get(k),(int,float)) and math.isfinite(day[k]) and day[k]>0 for k in ('open','close')):
            actual=(day['close']/day['open']-1)*100
            entry.update(actualOpen=day['open'],actualClose=day['close'],actualPercent=actual,
                         errorPoints=abs(entry['predictedPercent']-actual),
                         directionCorrect=bool(np.sign(entry['predictedPercent'])==np.sign(actual)),status='compared')
        else:entry['status']='actual-unavailable'
        result.append(entry)
    return result


def write_reports(output,frozen,companies,metadata):
    entries=finalize(frozen,companies);dates=sorted({e['date'] for e in entries})
    result={**metadata,'summary':summarize(entries),'daily':[{'date':date,**summarize([e for e in entries if e['date']==date])} for date in dates],'entries':entries}
    (output/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    fields=['date','symbol','name','predictedPercent','actualPercent','errorPoints','directionCorrect','actualOpen','actualClose','lowerPercent','upperPercent','upProbability','medianBaselinePercent','model','featureVariant','trainingRows','trainingTargetStart','trainingTargetEnd','lastInputDate','informationCutoff','status']
    with (output/'results.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(entries)
    summary=result['summary'];lines=['# Historical backtest — saved 25-stock cohort','',f"Period: {dates[0]} through {dates[-1]} · {len(dates)} trading days.",'',
        'Reconstructed historical predictions, not forecasts saved at the time. Model settings and ensemble weights are selected before each 10-session block; selected models are refitted daily on prior outcomes.','',
        f"Comparisons: {summary.get('comparisons',0)} · Direction accuracy: {summary.get('directionAccuracy',0):.1%} · MAE: {summary.get('meanAbsoluteError',0):.3f} percentage points · Zero baseline MAE: {summary.get('zeroBaselineMAE',0):.3f}.",'',
        '## Daily results','','| Date | Comparisons | Correct direction | MAE (pp) | Zero baseline MAE (pp) |','|---|---:|---:|---:|---:|']
    for day in result['daily']:
        lines.append(f"| {day['date']} | {day['comparisons']} | {day.get('directionAccuracy',0):.1%} | {day.get('meanAbsoluteError',0):.3f} | {day.get('zeroBaselineMAE',0):.3f} |")
    for date in ['2026-10-13']:
        sample=[e for e in entries if e['date']==date]
        if sample:
            lines.extend(['',f'## {date} — all 25 stocks','','| Ticker | Prediction | Actual | Error (pp) | Direction |','|---|---:|---:|---:|---|'])
            for e in sample:
                if e.get('actualPercent') is not None and e.get('predictedPercent') is not None:
                    lines.append(f"| {e['symbol']} | {e['predictedPercent']:+.3f}% | {e['actualPercent']:+.3f}% | {e['errorPoints']:.3f} | {'Correct' if e['directionCorrect'] else 'Wrong'} |")
                else:lines.append(f"| {e['symbol']} | — | — | — | {e['status']} |")
    lines.extend(['','## Method and limits','',*['- '+c for c in metadata['caveats']]])
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return result


def run(args):
    root=Path(args.input);output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    source=json.loads((root/'historical-data.json').read_text());cohort=json.loads((root/'cohort.json').read_text())
    market=json.loads((root/'market.json').read_text())['daily']
    expected=[s['symbol'] for s in cohort['stocks']]
    if len(expected)!=25 or len(set(expected))!=25:raise ValueError('Expected the saved fixed 25-stock cohort')
    by_symbol={c['symbol']:c for c in source['companies']}
    companies=[by_symbol[s] for s in expected]
    dates=[d['date'] for d in market if args.start<=d['date']<=args.end]
    if not dates:raise ValueError('No market sessions in requested period')
    # Cache key covers data, model implementation, and replay parameters.
    digest=hashlib.sha256()
    for path in [root/'historical-data.json',root/'market.json',Path(__file__),Path(__file__).with_name('forecast_benchmark.py'),Path(__file__).with_name('forecast_models.py'),Path(__file__).with_name('ml-prediction.py')]:digest.update(path.read_bytes())
    digest.update(json.dumps(vars(args),sort_keys=True).encode());fingerprint=digest.hexdigest()
    manifest=output/'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text())['fingerprint']!=fingerprint:raise ValueError('Backtest inputs changed; use a fresh output directory')
    manifest.write_text(json.dumps({'fingerprint':fingerprint,'parameters':vars(args),'createdAt':datetime.now(timezone.utc).isoformat()},indent=2))
    rows_path=output/'training-rows.json'
    if rows_path.exists():all_rows=json.loads(rows_path.read_text())
    else:
        all_rows=[];end=datetime.fromisoformat(args.end).replace(hour=23,tzinfo=timezone.utc)
        earliest=(datetime.fromisoformat(args.start)-timedelta(days=365+370)).date().isoformat()
        for company in companies:
            prepared={**company,'daily':[d for d in company['daily'] if earliest<=d['date']<=args.end],
                      'hourly':[d for d in company['hourly'] if d['date']<=args.end],'newsTimeline':[]}
            built=ml.build_rows(prepared,365,market,end);all_rows.extend(built)
            print(f"Prepared {company['symbol']}: {len(built)} historical training observations",flush=True)
        rows_path.write_text(json.dumps(all_rows,allow_nan=False))
    metadata={'modelVersion':ml.MODEL_VERSION,'start':args.start,'end':args.end,'retuneEveryTradingDays':args.retune_every,
              'trainingDays':args.training_days,'featureLookbackDays':365,'cohortSource':'Published testing-results.json',
              'downloadedAt':source['downloadedAt'],'caveats':source['caveats']+[
                  'Current algorithms were designed after this period; this is retrospective research, not a live forward test.',
                  'No archived point-in-time news snapshots are available. This replay uses the supported price-only feature variants.',
                  'Model settings and weights are selected before each block and then held fixed within that block; model parameters are refitted daily.',
                  'Training outcomes use the preceding 365 calendar days. Each training observation also needs 365 days of earlier price history for its inputs.',
                  'Intraday training observations retain the existing preceding-90-day collection window. Daily feature inputs use only prior completed sessions.']}
    frozen=[];selection=None;block=None
    for index,date in enumerate(dates):
        started=time.monotonic();eligible=training_rows(all_rows,date,args.training_days)
        if not eligible:raise ValueError('No historical training rows for '+date)
        assert max(r['targetDate'] for r in eligible)<date
        if index%args.retune_every==0:
            block=date;path=output/f'selection-{block}.joblib'
            if path.exists():selection=joblib.load(path)
            else:
                print(f'Selecting models before {date}: {len(eligible)} rows, {len({r["targetDate"] for r in eligible})} prior target dates',flush=True)
                _,selection=choose(eligible);joblib.dump(selection,path)
                (output/f'selection-{block}.json').write_text(json.dumps(selection,indent=2,allow_nan=False))
            print(f"Block {block}: {selection['model']}, {selection['features']}, weights={selection['ensembleWeights']}",flush=True)
        saved=output/f'predictions-{date}.json'
        if saved.exists():daily=json.loads(saved.read_text());frozen.extend(daily);print(f'{date}: restored frozen predictions',flush=True);continue
        registry=candidates();variant=selection['features'];weights=selection['ensembleWeights']
        model=WeightedForecast([fit_model(registry[name],eligible,variant) for name in weights],list(weights.values()))
        # Historical-only calibration, using models fitted strictly before its tail.
        training_dates=sorted({r['targetDate'] for r in eligible});cal_start=training_dates[-10]
        cal=[r for r in eligible if r['targetDate']>=cal_start];fit_rows=before(eligible,min(r['date'] for r in cal))
        calibration_model=WeightedForecast([fit_model(registry[name],fit_rows,variant) for name in weights],list(weights.values()))
        cx,cy=arrays(cal,variant);residual=cy-calibration_model.predict(cx);low,high=np.quantile(residual,[.1,.9])
        contexts={c['symbol']:prediction_context(c,market,date) for c in companies}
        ready=[{'symbol':symbol,'x':context['x'],'y':0} for symbol,context in contexts.items() if context]
        px,_=arrays(ready,variant);values=dict(zip([r['symbol'] for r in ready],model.predict(px))) if ready else {}
        median=float(np.expm1(np.median([r['y'] for r in eligible]))*100)
        daily=[]
        for stock in cohort['stocks']:
            symbol=stock['symbol'];context=contexts[symbol]
            entry={'date':date,**stock,'model':selection['model'],'featureVariant':variant,'selectionBlock':block,
                   'trainingRows':len(eligible),'trainingTargetStart':min(r['targetDate'] for r in eligible),
                   'trainingTargetEnd':max(r['targetDate'] for r in eligible),'medianBaselinePercent':median,
                   'retrospective':True,'predictedPercent':None}
            if context:
                value=float(values[symbol]);entry.update({k:v for k,v in context.items() if k!='x'})
                entry.update(predictedPercent=float(np.expm1(value)*100),lowerPercent=float(np.expm1(value+low)*100),upperPercent=float(np.expm1(value+high)*100),upProbability=float(np.mean(residual> -value)))
            daily.append(entry)
        # Save predictions before the independent actual-price comparison step.
        saved.write_text(json.dumps(daily,indent=2,allow_nan=False));frozen.extend(daily)
        print(f'{date}: froze {len(values)}/25 predictions, {time.monotonic()-started:.1f}s',flush=True)
        # Only already-frozen predictions enter the intermediate result report.
        write_reports(output,frozen,companies,metadata)
    result=write_reports(output,frozen,companies,metadata)
    print(json.dumps({'tradingDays':len(dates),'stocks':25,**result['summary'],'output':str(output)},indent=2),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',default='work/backtest-2026-08-19_2026-10-19')
    parser.add_argument('--output',default='work/backtest-2026-08-19_2026-10-19/results')
    parser.add_argument('--start',default='2026-08-19');parser.add_argument('--end',default='2026-10-19')
    parser.add_argument('--training-days',type=int,default=365);parser.add_argument('--retune-every',type=int,default=10)
    args=parser.parse_args()
    if args.retune_every<1 or args.training_days<60:parser.error('Positive retuning interval and at least 60 training days required')
    run(args)
