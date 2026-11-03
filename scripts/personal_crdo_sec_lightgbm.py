"""CRDO-only LightGBM source comparison, latest 30 sessions excluded from fit."""
import hashlib
import io
import json
import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from personal_qlib_crdo import metrics
from personal_qlib_crdo_rolling import context_samples, CUTOFF
from personal_crdo_sources import (public_fetch,sec_records,sec_features,parse_tipranks_events,
                                  tipranks_features,public_tables,SEC_URL,TIP_FORECAST,TIP_PRICES)


def fit_predict(frame):
    import lightgbm as lgb
    if len(frame)<440:raise ValueError('Insufficient CRDO training history')
    train,valid,test=frame.iloc[:-90],frame.iloc[-90:-30],frame.iloc[-30:]
    if train.index[-1][0]>=valid.index[0][0] or valid.index[-1][0]>=test.index[0][0]:
        raise ValueError('Overlapping chronological segments')
    params=dict(objective='regression',n_estimators=500,learning_rate=.025,
                num_leaves=7,max_depth=3,min_child_samples=30,reg_lambda=20,
                colsample_bytree=.85,n_jobs=2,random_state=42,deterministic=True,
                force_col_wise=True,verbosity=-1)
    tuned=lgb.LGBMRegressor(**params)
    tuned.fit(train['feature'],train['label']['return_points'],
              eval_set=[(valid['feature'],valid['label']['return_points'])],
              callbacks=[lgb.early_stopping(40,verbose=False)])
    # Tree count fixed by earlier validation. Final fit includes every pre-test label.
    earlier=frame.iloc[:-30]
    params['n_estimators']=tuned.best_iteration_
    model=lgb.LGBMRegressor(**params)
    model.fit(earlier['feature'],earlier['label']['return_points'])
    prediction=model.predict(test['feature'])
    return prediction,dict(bestIteration=tuned.best_iteration_,trainRows=len(earlier),
                           trainStart=str(earlier.index[0][0].date()),trainEnd=str(earlier.index[-1][0].date()),
                           validationStart=str(valid.index[0][0].date()),validationEnd=str(valid.index[-1][0].date()),
                           finalFitIncludesValidationAfterTreeCountFrozen=True,
                           featureImportance=dict(zip(model.feature_name_,model.feature_importances_.tolist())))


def main():
    if (os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted'
        or os.environ.get('GITHUB_REF_NAME')!='personal-test'):
        raise RuntimeError('Real stock data and training run only on GitHub-hosted personal-test')
    import yfinance as yf
    agent=os.environ['SEC_USER_AGENT']
    def download(symbol):
        data=yf.download(symbol,start='1900-01-01',end=CUTOFF,auto_adjust=True,
                         progress=False,threads=False,multi_level_index=False)
        if data.empty:raise ValueError('Missing source '+symbol)
        data.index=pd.to_datetime(data.index).tz_localize(None)
        if data.index.has_duplicates or not data.index.is_monotonic_increasing:raise ValueError('Invalid timestamps')
        if ((data.Open<=0)|(data.Close<=0)|(data.High<data.Close)|(data.Low>data.Close)).any():
            raise ValueError('Malformed OHLC')
        return data
    bars=download('CRDO')
    frame=context_samples(bars,{key:download(symbol) for key,symbol in
                              [('QQQ','QQQ'),('SOXX','SOXX'),('VIX','^VIX')]})
    raw,sec_audit=public_fetch(SEC_URL,agent)
    facts=sec_records(json.loads(raw))
    if not facts:raise ValueError('No SEC facts: refusing to claim a financial-data experiment')
    financial,financial_audit=sec_features(frame,bars,facts)
    frame_sec=frame.copy()
    for name in financial:frame_sec[('feature',name)]=financial[name]
    sources={'sec':dict(**sec_audit,facts=len(facts),accessions=len({r['accession'] for r in facts}),
                        earliestAvailableAt=min(r['available'] for r in facts).isoformat(),
                        latestAvailableAt=max(r['available'] for r in facts).isoformat(),
                        availabilityPolicy='Each fact version joined by its filing date; withheld until next Eastern day. Later restatements never copied backward.')}
    events=[]
    try:
        body,audit=public_fetch(TIP_FORECAST,'MarketPulsePersonalResearch/1.0')
        events=parse_tipranks_events(body.decode())
        sources['tipranksAnalystHistory']=dict(**audit,events=len(events),
             earliestAction=min((e['day'] for e in events),default=None),
             latestAction=max((e['day'] for e in events),default=None),
             completeHistory=False,pointInTimeSnapshotArchive=False,
             note='Only publicly visible dated actions, retrieved retrospectively; current analyst ranks, current upside, consensus and Smart Score excluded. Recent-list selection may be biased.')
        if not events:sources['tipranksAnalystHistory']['error']='No dated actions available in returned public HTML'
    except Exception as error:
        sources['tipranksAnalystHistory']=dict(events=0,error=type(error).__name__+': '+str(error),completeHistory=False)
    # Public dated prices are a source-quality cross-check, never extra independent samples.
    try:
        body,audit=public_fetch(TIP_PRICES,'MarketPulsePersonalResearch/1.0')
        tables=public_tables(body.decode())
        table=next(t for t in tables if 'Open' in t.columns and 'Close' in t.columns)
        checked=[]
        for _,row in table.iterrows():
            day=pd.to_datetime(str(row.iloc[0]),errors='coerce')
            if pd.isna(day) or day not in bars.index:continue
            opening=float(str(row.Open).replace(',','').replace('$',''))
            close=float(str(row.Close).replace(',','').replace('$',''))
            source_return=100*(close/opening-1)
            reference=100*(bars.loc[day,'Close']/bars.loc[day,'Open']-1)
            checked.append(abs(source_return-reference))
        sources['tipranksPriceHistory']=dict(**audit,checkedSessions=len(checked),
            maxOpenCloseReturnDifferencePoints=max(checked) if checked else None,
            use='Cross-check only: same stock prices are not independent additional training examples')
    except Exception as error:
        sources['tipranksPriceHistory']=dict(error=type(error).__name__+': '+str(error))
    datasets={'prices_market_context':frame,'prices_context_sec':frame_sec}
    if events:
        tip=tipranks_features(frame,bars,events)
        combined=frame_sec.copy()
        for name in tip:combined[('feature',name)]=tip[name]
        sources['tipranksAnalystHistory']['preTestRowsWithKnownActions']=int((tip.iloc[:-30]['tipranks_missing']==0).sum())
        sources['tipranksAnalystHistory']['testRowsWithKnownActions']=int((tip.iloc[-30:]['tipranks_missing']==0).sum())
        datasets['prices_context_sec_public_tipranks_actions']=combined
    print('CRDO_SOURCE_AUDIT='+json.dumps(sources),flush=True)
    results={};predictions={};details={}
    actual=frame.iloc[-30:]['label']['return_points'].to_numpy()
    for name,data in datasets.items():
        pred,detail=fit_predict(data)
        predictions[name]=pred;details[name]=detail;results[name]=metrics(actual,pred)
    previous_mean=float(frame.iloc[:-30]['label']['return_points'].mean())
    results['zero_return']=metrics(actual,np.zeros(len(actual)))
    results['train_mean']=metrics(actual,np.full(len(actual),previous_mean))
    direction=1 if (frame.iloc[:-30]['label']['return_points']>0).mean()>=.5 else -1
    results['majority_direction']=metrics(actual,np.full(len(actual),direction))
    dates=frame.iloc[-30:].index.get_level_values('datetime')
    result=dict(symbol='CRDO',testStart=str(dates[0].date()),testEnd=str(dates[-1].date()),
                sessions=30,firstSourcePrice=str(bars.index[0].date()),sourcePriceRows=len(bars),
                metrics=results,models=details,sources=sources,
                secTestCoverage=financial_audit[-30:],
                limitations=['Previously examined retrospective test dates; no prospective accuracy claim.',
                             'SEC companyfacts preserves filed versions of standard financial concepts; does not include all report narrative, original earnings-release guidance, or analyst surprise estimates.',
                             'Public TipRanks events, when available, are an incomplete retrospective list, not a full as-of snapshot archive.'],
                productionModified=False)
    print('CRDO_SEC_LIGHTGBM_RESULT='+json.dumps(result),flush=True)
    print('date,model,predicted_open_to_close_percent,actual_open_to_close_percent,direction_correct')
    for name,pred in predictions.items():
        for day,p,y in zip(dates,pred,actual):print(f'{day.date()},{name},{p:.4f},{y:.4f},{np.sign(p)==np.sign(y)}',flush=True)
    # No raw datasets, reports, or model artifacts uploaded; results displayed in logs only.


if __name__=='__main__':main()
