"""Live adapter for explicitly selected direct-return models.

Training uses completed prior sessions. The table remains compatible with the
annual forecast endpoint; trainingHistoryDays records the actual five-year cap.
The old classifier, calibration, and empirical median are never fallback paths.
"""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import joblib
import numpy as np
from stock_specific import DailyStockFeatures,StockSpecificReturnModel,PerStockReturnModel,good_bar


def build_stock_rows(builder,symbol,cutoff,years=5):
    start=(datetime.fromisoformat(cutoff)-timedelta(days=365*years)).date().isoformat();rows=[];skipped=0
    company=builder.companies[symbol];warnings={w['date'] for w in company.get('warnings',[])}
    for previous,target in zip(builder.bars[symbol],builder.bars[symbol][1:]):
        day=target['date']
        if not start<=day<cutoff:continue
        try:
            if not good_bar(target) or target.get('corporateAction') or target.get('labelEligible') is False or day in warnings:
                raise ValueError('Invalid target label')
            row=builder.features(symbol,day)
            row['actualPercent']=(target['close']/target['open']-1)*100
            rows.append(row)
        except (ValueError,KeyError,TypeError):skipped+=1
    return rows,skipped


def train_and_predict(data,config,artifact_directory):
    builder=DailyStockFeatures(data);directory=Path(artifact_directory);directory.mkdir(parents=True,exist_ok=True)
    target_dates={c['forecastContext']['targetDate'] for c in data['companies']}
    if len(target_dates)!=1:raise ValueError('Mixed prediction target sessions')
    target=next(iter(target_dates));years=5 if config['family']=='per-stock' else 1
    selected={c['symbol'] for c in data['companies'] if config['family']=='per-stock' or c.get('sharedTraining',not c.get('inferenceOnly'))}
    models={};training_counts={};skip_count=0;all_rows=[];training_end=[]
    if config['family']=='direction-aware':
        for symbol in sorted(selected):
            rows,skipped=build_stock_rows(builder,symbol,target,years);skip_count+=skipped;all_rows.extend(rows);training_counts[symbol]=len(rows)
        if len(all_rows)<200:raise ValueError('Insufficient completed training examples')
        model=StockSpecificReturnModel(direction_weight=.1,years=1,market=True).fit(all_rows,target,builder.market_columns)
        models['shared']=model;training_end.append(model.training_end)
        del all_rows
    elif config['family']=='per-stock':
        for i,symbol in enumerate(sorted(selected)):
            rows,skipped=build_stock_rows(builder,symbol,target,years);skip_count+=skipped;training_counts[symbol]=len(rows)
            if len(rows)<40:continue
            model=PerStockReturnModel(years=5).fit(rows,target,builder.market_columns)
            models[symbol]=model;training_end.append(model.training_end)
            if i%50==0:print(f'Fitted individual stock models: {i+1}/{len(selected)}',flush=True)
    else:raise ValueError('Unsupported explicitly selected model family')
    if not models:raise ValueError('No stock model could be fitted')
    metrics={'model':config['family'],'features':'stock-specific completed OHLCV patterns and market/sector context',
        'modelVersion':config['version'],'trainingRows':sum(training_counts.values()),'trainingRowsBySymbol':training_counts,
        'skippedFeatureRows':skip_count,'trainingTargetEnd':max(training_end),'trainingHistoryDays':years*365,
        'probabilityCalibration':'none','validationPassed':False,'validationStatus':'experimental-user-selected',
        'algorithm':'Separate per-stock Ridge equations' if config['family']=='per-stock' else 'Direct pseudo-Huber return regression with directional logistic penalty',
        'releaseStatus':'User selected for forward evaluation; historical joint improvement gate not passed',
        'returnBasis':'open-to-close'}
    joblib.dump({'models':models,'features':builder.names,'symbolIds':builder.symbol_ids,'sectorIds':builder.sector_ids,'modelVersion':config['version'],'metrics':metrics},directory/'stock-specific-live.joblib')
    (directory/'stock-specific-training.json').write_text(json.dumps(metrics,indent=2))
    forecasts={}
    for company in data['companies']:
        symbol=company['symbol'];context=company['forecastContext']
        base={'state':'no-signal','lookback':365,'modelVersion':config['version'],'targetDate':target,'returnBasis':'open-to-close','trainingHistoryDays':years*365}
        base.update(sessionMode='current-or-next',generatedAfterOpen=bool(data.get('generatedAfterOpen')))
        try:
            if context['state']!='ready':raise ValueError(context.get('reason','Incomplete prior session'))
            row=builder.features(symbol,target)
            model=models.get('shared') if config['family']=='direction-aware' else models.get(symbol)
            if model is None:raise ValueError('Insufficient clean history to train this stock; no legacy fallback')
            percent=float(model.predict([row])[0])
            forecast={**base,'state':'estimated','forecastModel':'supervised','estimatedPercent':percent,
                'priceOnlyPercent':percent,'newsContributionPoints':0.,'newsLabel':'Price/volume model; news shown as context',
                'baseDate':row['lastInputDate'],'quoteAsOf':context.get('quoteAsOf'),'quotePrice':context.get('basePrice'),
                'generatedAt':data['generatedAt'],'sessions':training_counts.get(symbol,0),
                'direction':'positive' if percent>0 else 'negative' if percent<0 else 'neutral',
                'validationPassed':False,'experimental':True,'confidenceStatus':'experimental','modelQuality':metrics}
            forecast['estimates']={'openToClose':{'state':'estimated','targetDate':target,'returnBasis':'open-to-close','estimatedPercent':percent,'validationPassed':False,'confidenceStatus':'experimental'},
                'closeToClose':{'state':'no-signal','targetDate':target,'returnBasis':'close-to-close','estimatedPercent':None,'validationPassed':False,'reason':'This selected model was trained for open-to-close returns only'}}
            forecasts[symbol]=forecast
        except (ValueError,KeyError,TypeError) as error:forecasts[symbol]={**base,'reason':str(error)}
    return forecasts,metrics


def run(dataset_path,sentiment_path,output_path,config):
    data=json.loads(Path(dataset_path).read_text());news=json.loads(Path(sentiment_path).read_text())
    if news.get('reportId')!=data['reportId']:raise ValueError('Sentiment and training report differ')
    forecasts,metrics=train_and_predict(data,config,Path('prediction-models'))
    output=Path(output_path);tables=output.parent/'predictions';tables.mkdir(parents=True,exist_ok=True)
    by_symbol={c['symbol']:c for c in data['companies']};news_by_symbol={n['symbol']:n for n in news.get('companies',[])}
    rows=[]
    for company in data['companies']:
        if company.get('inferenceOnly'):continue
        symbol=company['symbol'];forecast={k:v for k,v in forecasts[symbol].items() if k!='modelQuality'}
        if forecast['state']=='estimated':forecast['modelKey']='adaptive'
        rows.append({'symbol':symbol,'name':company.get('name',symbol),'headlines':news_by_symbol.get(symbol,{}).get('headlines',[]),'newsState':news_by_symbol.get(symbol,{}).get('state','unavailable'),'forecasts':[forecast]})
    compact=[]
    for stock in data['universe']:
        forecast=forecasts.get(stock['symbol'],{'state':'no-signal','lookback':365,'targetDate':next(iter(forecasts.values()))['targetDate'],'reason':'Historical prices unavailable'})
        compact.append({'symbol':stock['symbol'],**{k:v for k,v in forecast.items() if k not in ('modelQuality','modelKey')}})
    (tables/'365.json').write_text(json.dumps({'reportId':data['reportId'],'lookback':365,'modelVersion':config['version'],'trainingHistoryDays':metrics['trainingHistoryDays'],'rows':compact},allow_nan=False))
    result={'modelVersion':config['version'],'returnBasis':'open-to-close','supportedLookbacks':[365],'rows':rows,'trainedModels':[{'lookback':0,'adaptive':True,**metrics}],
            'trainingErrors':data.get('errors',[]),'dataCaveats':['Experimental model selected by user despite failing the historical joint improvement gate.',
            'Only complete prior sessions are inputs; current-session quotes and target opens are not features.',
            'Individual training history varies by ticker and IPO date. Invalid or insufficient history produces no signal.',
            'The 365 endpoint is retained for dashboard compatibility; trainingHistoryDays records the actual training cap.']}
    output.write_text(json.dumps(result,allow_nan=False));print(f"Wrote {len(compact)} forecasts using {config['version']}",flush=True)


if __name__=='__main__':
    config=json.loads((Path(__file__).resolve().parent.parent/'data/prediction-model.json').read_text())
    run(*sys.argv[1:4],config)
