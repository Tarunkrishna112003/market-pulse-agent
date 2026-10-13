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
MODEL_VERSION = 'rf-lstm-math-next-session-v4'
FEATURES = ['last_return','mean_return','volatility','momentum','downside_volatility','range','position','volume_ratio','quote_vs_previous','minutes_to_close','market_return','market_momentum','is_preopen',*[f'return_lag_{i}' for i in range(5,0,-1)],'news_tone','news_tone_7d','news_present']

def feature_vector(company, anchor_date, anchor_price, minute, lookback, market):
    start = (datetime.fromisoformat(anchor_date)-timedelta(days=lookback)).date().isoformat()
    observable = [d for d in company['daily'] if d['date'] < anchor_date]
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
    return [returns[-1],statistics.mean(returns),vol,math.log(prior[-1]['close']/prior[0]['close']),math.sqrt(sum(min(r,0)**2 for r in returns)/len(returns)),math.log(high/low) if low>0 else 0,(anchor_price-low)/max(high-low,1e-8),(volumes[-1]/max(statistics.mean(volumes),1)) if volumes else 0,math.log(anchor_price/prior[-1]['close']),min(1,max(0,960-minute)/390),market_return,market_momentum,int(minute<570),*returns[-5:],news[-1]['tone'] if news else 0,statistics.mean([d['tone'] for d in week]) if week else 0,int(bool(news))]

def build_rows(company,lookback,market,now):
    daily = {d['date']:d for d in company['daily']}
    dates = sorted(daily)
    next_date = {a:b for a,b in zip(dates,dates[1:])}
    rows=[]
    # Pre-open examples use the prior close, with only information available at 9am.
    for previous,date in zip(dates,dates[1:]):
        if daily[previous].get('nextSession',date)!=date:continue
        target_close=datetime.fromisoformat(date).replace(tzinfo=NY,hour=daily[date].get('closeMinute',960)//60,minute=daily[date].get('closeMinute',960)%60)
        if target_close.astimezone(timezone.utc)>now:continue
        features=feature_vector(company,date,daily[previous]['close'],540,lookback,market)
        if features is not None:rows.append({'symbol':company['symbol'],'date':date,'targetDate':date,'x':features,'y':math.log(daily[date]['close']/daily[previous]['close'])})
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
        if target_close.astimezone(timezone.utc)>now:
            continue
        features=feature_vector(company,date,bar['close'],end.hour*60+end.minute,lookback,market)
        if features is None:
            continue
        rows.append({'symbol':company['symbol'],'date':date,'targetDate':target,'x':features,'y':math.log(daily[target]['close']/bar['close'])})
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
    import os
    import joblib
    from sklearn.base import clone
    from sklearn.ensemble import ExtraTreesRegressor,HistGradientBoostingRegressor,RandomForestRegressor,VotingRegressor
    from forecast_models import LSTMRegressor,MathematicalForecast
    from sklearn.linear_model import Ridge
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import RobustScaler
    from sklearn.exceptions import ConvergenceWarning
    warnings.filterwarnings('ignore', category=ConvergenceWarning)
    selection,calibration,test,dates=time_partitions(rows)
    candidates={'ridge':make_pipeline(RobustScaler(),Ridge(alpha=100)), 'extra_trees':ExtraTreesRegressor(n_estimators=100,max_depth=7,min_samples_leaf=30,n_jobs=2,random_state=42), 'boosted_trees':HistGradientBoostingRegressor(loss='absolute_error',max_iter=100,max_leaf_nodes=15,min_samples_leaf=30,l2_regularization=10,early_stopping=False,random_state=42), 'neural_network':make_pipeline(RobustScaler(),MLPRegressor(hidden_layer_sizes=(32,16),alpha=10,max_iter=200,early_stopping=False,random_state=42))}
    candidates['random_forest']=RandomForestRegressor(n_estimators=150,max_depth=8,min_samples_leaf=20,max_features=0.8,n_jobs=2,random_state=42)
    candidates['lstm']=LSTMRegressor()
    candidates['mathematical_formula']=MathematicalForecast(alpha=100)
    # Equal weights are fixed before validation; compare the combination against each component.
    candidates['rf_lstm_math_ensemble']=VotingRegressor([(name,candidates[name]) for name in ['random_forest','lstm','mathematical_formula']],weights=[1,1,1])
    select_dates=sorted({r['date'] for r in selection})
    blocks=[select_dates[max(0,len(select_dates)-24+i*8):len(select_dates)-16+i*8] for i in range(3)]
    news_eligible=sum(r['x'][-1] for r in selection)>=100 and len({r['date'] for r in selection if r['x'][-1]})>=10
    variants=['prices','prices_and_news'] if news_eligible else ['prices']
    def arrays(records,variant):
        x=np.array([r['x'] if variant=='prices_and_news' else r['x'][:-3] for r in records],dtype=float);y=np.array([r['y'] for r in records],dtype=float);return x,y
    scores=[]
    for variant in variants:
        for name,model in candidates.items():
            errors=[]
            try:
                for block in blocks:
                    if not block:continue
                    train=[r for r in selection if r['date']<block[0] and r['targetDate']<block[0]]
                    valid=[r for r in selection if r['date'] in block]
                    if len(train)<100 or len(valid)<20:continue
                    x,y=arrays(train,variant);v,truth=arrays(valid,variant);fitted=clone(model).fit(x,y);pred=fitted.predict(v)
                    errors.extend(np.abs(np.expm1(pred)*100-np.expm1(truth)*100).tolist())
                if errors:scores.append({'model':name,'features':variant,'cvMAE':float(np.mean(errors))})
            except Exception as error:
                scores.append({'model':name,'features':variant,'error':str(error)[:200]})
    valid_scores=[s for s in scores if 'cvMAE' in s and math.isfinite(s['cvMAE'])]
    if not valid_scores:raise ValueError('No candidate completed chronological validation')
    best=min(valid_scores,key=lambda s:s['cvMAE']);variant=best['features'];model=candidates[best['model']]
    x,y=arrays(selection,variant);cal_model=clone(model).fit(x,y);cx,cy=arrays(calibration,variant);residual=cy-cal_model.predict(cx)
    low=float(np.quantile(residual,0.1));high=float(np.quantile(residual,0.9))
    test_start=min(r['date'] for r in test)
    train_before_test=[r for r in rows if r['date']<test_start and r['targetDate']<test_start]
    x,y=arrays(train_before_test,variant);frozen=clone(model).fit(x,y);tx,ty=arrays(test,variant);tp=frozen.predict(tx)
    actual=np.expm1(ty)*100;predicted=np.expm1(tp)*100
    mae=float(np.mean(np.abs(predicted-actual)));baseline=float(np.mean(np.abs(actual)));direction=float(np.mean(np.sign(tp)==np.sign(ty)));coverage=float(np.mean((ty>=tp+low)&(ty<=tp+high)))
    passed=mae<baseline*0.98 and direction>0.52 and coverage>=0.65
    metric={'model':best['model'],'features':variant,'trainingRows':len(rows),'testSamples':len(test),'testTradingDates':len({r['targetDate'] for r in test}),'testStart':min(r['date'] for r in test),'testEnd':max(r['targetDate'] for r in test),'meanAbsoluteError':mae,'naiveMeanAbsoluteError':baseline,'directionAccuracy':direction,'intervalCoverage':coverage,'validationPassed':passed,'newsTrainingAvailable':news_eligible,'candidates':scores,'calibrationSamples':len(calibration)}
    allx,ally=arrays(rows,variant);final=clone(model).fit(allx,ally);forecasts={}
    os.makedirs('prediction-models',exist_ok=True)
    metric['algorithm']='Choose the lowest chronological validation MAE among individual models and the RF/LSTM/math ensemble; evaluate once on untouched final sessions.'
    metric['ensembleWeights']={'random_forest':1/3,'lstm':1/3,'mathematical_formula':1/3}
    equation_model=final if best['model']=='mathematical_formula' else final.named_estimators_['mathematical_formula'] if best['model']=='rf_lstm_math_ensemble' else None
    if equation_model is not None:metric['mathematicalEquation']=equation_model.equation(FEATURES if variant=='prices_and_news' else FEATURES[:-3])
    joblib.dump({'model':final,'features':FEATURES if variant=='prices_and_news' else FEATURES[:-3],'calibrationResidualQuantiles':[low,high],'metrics':metric,'modelVersion':MODEL_VERSION},f'prediction-models/{lookback}-day-model.joblib')
    for symbol,record in current.items():
        vector=record['x'] if variant=='prices_and_news' else record['x'][:-3]
        value=float(final.predict(np.array([vector]))[0]);neutral=list(vector)
        if variant=='prices_and_news':neutral[-3]=0;neutral[-2]=0
        no_news=float(final.predict(np.array([neutral]))[0]);base=record['basePrice'];percent=float(np.expm1(value)*100);close=base*math.exp(value)
        if not all(math.isfinite(v) for v in [value,percent,close]) or abs(value)>1:
            forecasts[symbol]={'state':'no-signal','lookback':lookback,'reason':'Model output outside supported range'};continue
        forecasts[symbol]={'state':'estimated','forecastModel':'supervised','lookback':lookback,'sessions':record['sessions'],'baseDate':record['baseDate'],'baseClose':base,'quotePrice':base,'quoteAsOf':record['quoteAsOf'],'targetDate':record['targetDate'],'generatedAt':record['generatedAt'],'estimatedPercent':percent,'estimatedDollar':close-base,'projectedClose':close,'remainingPercent':percent,'direction':'positive' if percent>0.05 else 'negative' if percent< -0.05 else 'neutral','priceOnlyPercent':float(np.expm1(no_news)*100),'newsContributionPoints':percent-float(np.expm1(no_news)*100),'newsLabel':'learned news features' if variant=='prices_and_news' else 'context only; price model selected','interval':{'level':0.8,'lowerPercent':float(np.expm1(value+low)*100),'upperPercent':float(np.expm1(value+high)*100)},'validationPassed':passed,'modelQuality':metric,'newsCount':record.get('newsCount',0),'newsFeatureCutoff':record.get('newsFeatureCutoff'),'experimental':False}
    return forecasts,metric

def main():
    dataset=json.load(open(sys.argv[1],encoding='utf-8'));news=json.load(open(sys.argv[2],encoding='utf-8'))
    now=datetime.fromisoformat(dataset['generatedAt'].replace('Z','+00:00'))
    rows_out=[{'symbol':c['symbol'],'name':c['name'],'headlines':next((n['headlines'] for n in news['companies'] if n['symbol']==c['symbol']),[]),'forecasts':[],'newsState':next((n['state'] for n in news['companies'] if n['symbol']==c['symbol']),'unavailable')} for c in dataset['companies']]
    lookup={r['symbol']:r for r in rows_out};metrics=[]
    for window in [10,20,30]:
        records=[];current={}
        for company in dataset['companies']:
            if not company.get('inferenceOnly'):records.extend(build_rows(company,window,dataset['market'],now))
            context=company['forecastContext']
            if context['state']!='ready':lookup[company['symbol']]['forecasts'].append({'state':'stale','lookback':window,'reason':context['reason'],'targetDate':context['targetDate']});continue
            clock=datetime.fromisoformat(context['quoteAsOf'].replace('Z','+00:00')).astimezone(NY)
            inference_date=context['inferenceDate'];inference_minute=context['inferenceMinute']
            vector=feature_vector(company,inference_date,context['basePrice'],inference_minute,window,dataset['market'])
            if vector is None:lookup[company['symbol']]['forecasts'].append({'state':'insufficient-history','lookback':window,'reason':'Insufficient training/inference history'});continue
            current[company['symbol']]={**context,'x':vector,'generatedAt':dataset['generatedAt'],'sessions':len([d for d in company['daily'] if d['date']<inference_date and d['date']>=(datetime.fromisoformat(inference_date)-timedelta(days=window)).date().isoformat()]),'newsCount':len(lookup[company['symbol']]['headlines']),'newsFeatureCutoff':'prior completed UTC day'}
        try:
            forecasts,metric=fit_window(records,current,window);metrics.append({'lookback':window,**metric})
            for symbol,result in forecasts.items():lookup[symbol]['forecasts'].append(result)
        except Exception as error:
            metrics.append({'lookback':window,'state':'unavailable','error':str(error)[:300]})
            for symbol in current:lookup[symbol]['forecasts'].append({'state':'no-signal','lookback':window,'reason':str(error)[:300]})
    result={'modelVersion':MODEL_VERSION,'rows':rows_out,'trainedModels':metrics,'trainingErrors':dataset['errors'],'dataCaveats':['Historical tests use the current top-25 cohort, not point-in-time screener membership. Additional tickers in the scan market-cap band use the pooled model; their individual performance is not separately validated and company news may be missing.','GDELT archive data is reconstructed and may have revisions; forward validation remains necessary.','Current headline sentiment is context only; numerical news features use historical GDELT tone available before the feature cutoff.']}
    json.dump(result,open(sys.argv[3],'w',encoding='utf-8'),allow_nan=False)
    print(json.dumps({'trainedModels':metrics,'rows':len(rows_out)}))

if __name__=='__main__':main()
