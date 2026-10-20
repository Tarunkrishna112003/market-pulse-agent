"""Supervised next-session forecasting with chronological selection, calibration and holdout.
Historical news uses only completed UTC-day GDELT aggregates. Latest classifier
headlines are evidence/context; their scores are not interchangeable with GDELT tone.
"""
import json
import math
import statistics
import sys
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
NY = ZoneInfo('America/New_York')
MODEL_VERSION = 'annual-open-to-close-v9-direction-boosted'
FEATURES = ['last_return','mean_return','volatility','momentum','downside_volatility','range','position','volume_ratio','quote_vs_previous','minutes_to_close','market_return','market_momentum','is_preopen','calendar_days',*[f'return_lag_{i}' for i in range(5,0,-1)],'news_tone','news_tone_7d','news_present']

def feature_vector(company, anchor_date, anchor_price, minute, lookback, market):
    start = (datetime.fromisoformat(anchor_date)-timedelta(days=lookback)).date().isoformat()
    observable = [d for d in company['daily'] if d['date'] < anchor_date]
    if not observable or observable[0]['date'] > start:
        return None
    prior = [d for d in observable if d['date'] >= start]
    if len(prior) < 5:
        return None
    # Compute returns only from consecutive observable prices; never from future bars.
    returns = [math.log(b['close']/a['close']) for a,b in zip(observable,observable[1:]) if b['date'] >= start]
    if len(returns)<5:return None
    vol = statistics.stdev(returns) if len(returns)>1 else 0
    lows = [d.get('low') for d in prior if d.get('low') is not None]
    highs = [d.get('high') for d in prior if d.get('high') is not None]
    low,high = min(lows or [prior[-1]['close']]),max(highs or [prior[-1]['close']])
    volumes = [d.get('volume',0) or 0 for d in prior]
    market_prior = [d for d in market if start <= d['date'] < anchor_date]
    market_return = math.log(market_prior[-1]['close']/market_prior[-2]['close']) if len(market_prior)>1 else 0
    market_momentum = math.log(market_prior[-1]['close']/market_prior[0]['close']) if len(market_prior)>1 else 0
    # Prior complete UTC dates only, avoiding same-day headline look-ahead.
    news = [d for d in company.get('newsTimeline',[]) if start <= d['date'] < anchor_date]
    week = [d for d in news if d['date'] >= (datetime.fromisoformat(anchor_date)-timedelta(days=7)).date().isoformat()]
    return [returns[-1],statistics.mean(returns),vol,math.log(prior[-1]['close']/prior[0]['close']),math.sqrt(sum(min(r,0)**2 for r in returns)/len(returns)),math.log(high/low) if low>0 else 0,(anchor_price-low)/max(high-low,1e-8),(volumes[-1]/max(statistics.mean(volumes),1)) if volumes else 0,math.log(anchor_price/prior[-1]['close']),min(1,max(0,960-minute)/390),market_return,market_momentum,int(minute<570),lookback,*returns[-5:],news[-1]['tone'] if news else 0,statistics.mean([d['tone'] for d in week]) if week else 0,int(bool(news))]

def build_rows(company,lookback,market,now):
    daily = {d['date']:d for d in company['daily']}
    dates = sorted(daily)
    next_date = {a:b for a,b in zip(dates,dates[1:])}
    rows=[]
    # Same-session open-to-close target; future opening prices are labels, never inputs.
    def session_return(day):
        opening=day.get('open')
        return math.log(day['close']/opening) if isinstance(opening,(int,float)) and math.isfinite(opening) and opening>0 else None
    # Pre-open examples use the prior close, with only information available at 9am.
    for previous,date in zip(dates,dates[1:]):
        if daily[previous].get('nextSession',date)!=date:continue
        target_close=datetime.fromisoformat(date).replace(tzinfo=NY,hour=daily[date].get('closeMinute',960)//60,minute=daily[date].get('closeMinute',960)%60)
        if target_close.astimezone(timezone.utc)>now or session_return(daily[date]) is None:continue
        features=feature_vector(company,date,daily[previous]['close'],540,lookback,market)
        if features is not None:rows.append({'symbol':company['symbol'],'date':date,'targetDate':date,'x':features,'y':session_return(daily[date])})
    for bar in company['hourly']:
        begin=datetime.fromtimestamp(bar['timestamp'],timezone.utc).astimezone(NY)
        # Yahoo regular-session 60m bars: the final bar can be shorter than 60m.
        date=begin.date().isoformat()
        close_minute=daily.get(date,{}).get('closeMinute',960)
        cutoff=datetime.combine(begin.date(),datetime.min.time(),NY).replace(hour=close_minute//60,minute=close_minute%60)
        end=min(begin+timedelta(hours=1),cutoff)
        if begin.hour<9 or begin.hour==9 and begin.minute<30 or begin>=cutoff or end.astimezone(timezone.utc)>now:
            continue
        target=next_date.get(date)
        if not target or target not in daily or daily.get(date,{}).get('nextSession',target)!=target:
            continue
        # Next close must already be known at data collection time.
        target_minute=daily[target].get('closeMinute',960)
        target_close=datetime.fromisoformat(target).replace(tzinfo=NY,hour=target_minute//60,minute=target_minute%60)
        if target_close.astimezone(timezone.utc)>now or session_return(daily[target]) is None:
            continue
        features=feature_vector(company,date,bar['close'],end.hour*60+end.minute,lookback,market)
        if features is None:
            continue
        rows.append({'symbol':company['symbol'],'date':date,'targetDate':target,'x':features,'y':session_return(daily[target])})
    return rows

def time_partitions(rows):
    dates=sorted({r['date'] for r in rows})
    if len(dates)<40 or len(rows)<500:
        raise ValueError('At least 40 trading dates and 500 training observations are required')
    test_start=dates[-10];cal_start=dates[-20]
    test=[r for r in rows if r['date']>=test_start]
    calibration=[r for r in rows if cal_start<=r['date']<test_start and r['targetDate']<test_start]
    selection=[r for r in rows if r['date']<cal_start and r['targetDate']<cal_start]
    if len(selection)<200 or len(calibration)<50 or len(test)<50:
        raise ValueError('Insufficient separated training/calibration/test data')
    return selection,calibration,test,dates

def fit_window(rows,current,lookback):
    import numpy as np
    import joblib
    from forecast_benchmark import evaluate, summary, choose, before, arrays, candidates, fit_model
    from forecast_models import WeightedForecast, GatedAttentionRegressor
    from pathlib import Path
    folds,records=evaluate(rows)
    result=summary(records)
    # Freeze the release decision using outer results; final fitting uses available history.
    passed=(result['meanAbsoluteError']<min(result['naiveMeanAbsoluteError'],result['medianMeanAbsoluteError'])*.98
            and result['directionAccuracy']>.52 and result['intervalCoverage']>=.65)
    final,selection=choose(rows)
    dates=sorted({r['targetDate'] for r in rows});cal_start=dates[-10]
    calibration=[r for r in rows if r['targetDate']>=cal_start];train=before(rows,min(r['date'] for r in calibration))
    weights=selection['ensembleWeights'];registry=candidates();variant=selection['features']
    calibration_model=WeightedForecast([fit_model(registry[name],train,variant) for name in weights],list(weights.values()))
    cx,cy=arrays(calibration,variant);residual=cy-calibration_model.predict(cx)
    low,high=[float(v) for v in np.quantile(residual,[.1,.9])]
    # Repeat selected neural components with independent seeds; retain seed diagnostics.
    seed_checks=[]
    for name in weights:
        if isinstance(registry[name],GatedAttentionRegressor):
            predictions=[]
            for seed in (42,43,44):
                fitted=fit_model(registry[name].set_params(random_state=seed),train,variant)
                predictions.append(fitted.predict(cx))
            seed_checks.append({'model':name,'seeds':[42,43,44],
                'calibrationMAEBySeed':[float(np.mean(np.abs(np.expm1(p)*100-np.expm1(cy)*100))) for p in predictions],
                'meanPredictionStdPoints':float(np.mean(np.std(np.expm1(predictions)*100,axis=0)))})
    metric={'returnBasis':'open-to-close',**selection,**result,'trainingRows':len(rows),
            'testSamples':len(records),'testStart':min(r['date'] for r in records),
            'testEnd':max(r['targetDate'] for r in records),'validationPassed':passed,
            'calibrationSamples':len(calibration),'seedStability':seed_checks,
            'benchmarkFolds':folds,'algorithm':'Nested purged target-date walk-forward benchmark; inner candidate tuning and nonnegative ensemble selection.',
            'benchmarkScope':'Current training cohort; mixed existing morning/intraday observations; not point-in-time universe validation.',
            'intervalMethod':'Earlier-fit residual quantiles, evaluated after refitting; empirical coverage reported, no coverage guarantee.'}
    directory=Path('prediction-models');directory.mkdir(exist_ok=True)
    bundle={'model':final,'features':FEATURES if variant=='prices_and_news' else FEATURES[:-3],
            'metrics':metric,'calibrationResidualQuantiles':[low,high],'calibrationResiduals':residual.tolist(),
            'modelVersion':MODEL_VERSION,'returnBasis':'open-to-close'}
    joblib.dump(bundle,directory/f'{lookback}-day-model.joblib')
    (directory/'chronological-benchmark.json').write_text(json.dumps({'modelVersion':MODEL_VERSION,'metrics':metric,'predictions':records},allow_nan=False))
    return predict_records(bundle,current,lookback),metric


def predict_records(bundle,current,lookback):
    import numpy as np
    final=bundle['model'];metric=bundle['metrics'];variant=metric['features']
    low,high=bundle['calibrationResidualQuantiles'];passed=metric['validationPassed'];forecasts={}
    keys=list(current)
    from forecast_benchmark import feature_array
    vectors=feature_array([current[key]['x'] for key in keys],variant) if keys else np.empty((0,0))
    if keys:
        # Batch inference runs every tree on every stock/window without per-row thread overhead.
        values=final.predict(vectors)
        if variant=='prices_and_news':
            neutral=vectors.copy();neutral[:,-3:-1]=0
            neutral_values=final.predict(neutral)
        else:neutral_values=values
    for index,symbol in enumerate(keys):
        record=current[symbol];value=float(values[index]);no_news=float(neutral_values[index]);base=record['basePrice'];percent=float(np.expm1(value)*100)
        if not all(math.isfinite(v) for v in [value,percent]) or abs(value)>1:
            forecasts[symbol]={'state':'no-signal','lookback':record.get('lookback',lookback),'reason':'Model output outside supported range'};continue
        forecasts[symbol]={'state':'estimated','forecastModel':'supervised','returnBasis':'open-to-close','lookback':record.get('lookback',lookback),'sessions':record['sessions'],'baseDate':record['baseDate'],'quotePrice':base,'quoteAsOf':record['quoteAsOf'],'targetDate':record['targetDate'],'generatedAt':record['generatedAt'],'estimatedPercent':percent,'direction':'positive' if percent>0.05 else 'negative' if percent< -0.05 else 'neutral','priceOnlyPercent':float(np.expm1(no_news)*100),'newsContributionPoints':percent-float(np.expm1(no_news)*100),'newsLabel':'learned news features' if variant=='prices_and_news' else 'context only; price model selected','interval':{'level':0.8,'lowerPercent':float(np.expm1(value+low)*100),'upperPercent':float(np.expm1(value+high)*100)},'validationPassed':passed,'modelQuality':metric,'newsCount':record.get('newsCount',0),'newsFeatureCutoff':record.get('newsFeatureCutoff'),'experimental':not passed,'confidenceStatus':'validated' if passed else 'low-confidence','upProbability':float(np.mean(np.asarray(bundle['calibrationResiduals'])> -value)) if bundle.get('calibrationResiduals') else None}
    return forecasts

def main():
    with open(sys.argv[1],encoding='utf-8') as source:dataset=json.load(source)
    with open(sys.argv[2],encoding='utf-8') as source:news=json.load(source)
    now=datetime.fromisoformat(dataset['generatedAt'].replace('Z','+00:00'))
    import joblib
    from pathlib import Path
    # Detailed rows are retained only for the training cohort; full-universe table
    # results are written one period at a time rather than accumulated in memory.
    training_companies=[c for c in dataset['companies'] if not c.get('inferenceOnly')]
    news_by_symbol={n['symbol']:n for n in news['companies']}
    rows_out=[{'symbol':c['symbol'],'name':c['name'],'headlines':news_by_symbol.get(c['symbol'],{}).get('headlines',[]),'forecasts':[],'newsState':news_by_symbol.get(c['symbol'],{}).get('state','unavailable')} for c in training_companies]
    lookup={r['symbol']:r for r in rows_out};metrics=[]
    maximum=365
    windows=[365]
    training_windows=[365]
    records=[]
    for company in training_companies:
        for index,window in enumerate(training_windows):
            candidates=build_rows(company,window,dataset['market'],now)
            records.extend(r for r in candidates if datetime.fromisoformat(r['date']).toordinal()%len(training_windows)==index)
    bundle=None;training_error=None
    try:
        from forecast_runtime import fit_runtime
        cutoff=(now.astimezone(NY).date()+timedelta(days=1)).isoformat()
        bundle,builder=fit_runtime(records,dataset['companies'],dataset['market'],cutoff)
        metrics.append({'lookback':0,'adaptive':True,**bundle['metrics']})
    except Exception as error:
        training_error=str(error)[:300]
        metrics.append({'lookback':0,'adaptive':True,'state':'unavailable','error':training_error})
    universe=dataset.get('universe') or [{'symbol':c['symbol'],'name':c['name']} for c in dataset['companies']]
    directory=Path(sys.argv[3]).parent/'predictions';directory.mkdir(parents=True,exist_ok=True)
    compact_keys=['confidenceStatus','validationPassed','upProbability','interval','state','forecastModel','returnBasis','lookback','targetDate','estimatedPercent','reason']
    for window in windows:
        current={};forecasts={}
        for company in dataset['companies']:
            symbol=company['symbol'];context=company['forecastContext']
            if context['state']!='ready':
                forecasts[symbol]={'state':'stale','lookback':window,'reason':context['reason'],'targetDate':context['targetDate']};continue
            inference_date=context['inferenceDate'];inference_minute=context['inferenceMinute']
            vector=feature_vector(company,inference_date,context['basePrice'],inference_minute,window,dataset['market'])
            if vector is None:
                forecasts[symbol]={'state':'insufficient-history','lookback':window,'reason':'Insufficient complete history for the selected calendar-day period'};continue
            current[symbol]={**context,'symbol':symbol,'lookback':window,'x':vector,'generatedAt':dataset['generatedAt'],'sessions':len([d for d in company['daily'] if d['date']<inference_date and d['date']>=(datetime.fromisoformat(inference_date)-timedelta(days=window)).date().isoformat()]),'newsCount':len(news_by_symbol.get(symbol,{}).get('headlines',[])),'newsFeatureCutoff':'prior completed UTC day'}
        if bundle is not None:
            from forecast_runtime import predict_runtime
            forecasts.update(predict_runtime(bundle,builder,current,window))
        else:
            forecasts.update({symbol:{'state':'no-signal','lookback':window,'reason':training_error} for symbol in current})
        table_rows=[]
        for stock in universe:
            symbol=stock['symbol']
            forecast=forecasts.get(symbol,{'state':'no-signal','lookback':window,'reason':'Historical prices could not be retrieved'})
            if symbol in lookup:
                detail={k:v for k,v in forecast.items() if k!='modelQuality'}
                if detail.get('state')=='estimated':detail['modelKey']='adaptive'
                lookup[symbol]['forecasts'].append(detail)
            table_rows.append({'symbol':symbol,**{k:forecast[k] for k in compact_keys if k in forecast}})
        with (directory/f'{window}.json').open('w',encoding='utf-8') as output:
            json.dump({'reportId':dataset['reportId'],'lookback':window,'rows':table_rows},output,allow_nan=False)
        if window==maximum or window%30==0:print(f'Wrote {window}/{maximum} history periods for {len(universe)} stocks',flush=True)
    result={'returnBasis':'open-to-close','modelVersion':MODEL_VERSION,'supportedLookbacks':windows,'rows':rows_out,'trainedModels':metrics,'trainingErrors':dataset['errors'],'dataCaveats':['All prediction features use the past 365 calendar days, independent of screener display filters.','Historical tests use the current top-25 cohort, not point-in-time screener membership. All additional tickers in the full scan use the pooled model; their individual performance is not separately validated and company news may be missing.','The direction-boosted model is experimental; forward validation remains necessary.','News is context only; the direction-boosted prediction model uses price features.']}
    with open(sys.argv[3],'w',encoding='utf-8') as output:json.dump(result,output,allow_nan=False)
    print(json.dumps({'trainedModels':metrics,'rows':len(rows_out)}))

if __name__=='__main__':main()
