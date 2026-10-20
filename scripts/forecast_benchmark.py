"""Target-date grouped, purged walk-forward selection and untouched outer evaluation."""
import math
import numpy as np
from sklearn.base import clone
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor, VotingRegressor
from sklearn.feature_selection import VarianceThreshold
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler
from forecast_models import GatedAttentionRegressor, ResidualMLPRegressor, LSTMRegressor, MathematicalForecast, WeightedForecast


def feature_array(values,variant):
    x=np.asarray([v if variant=='prices_and_news' else v[:-3] for v in values],dtype=float)
    if variant=='prices_without_market':x[:,10:12]=0
    return x


def arrays(rows,variant):
    return feature_array([r['x'] for r in rows],variant),np.asarray([r['y'] for r in rows],dtype=float)


def before(rows,date):
    return [r for r in rows if r['date']<date and r['targetDate']<date]


def target_blocks(rows,block_size=10,max_blocks=6,min_train_dates=30):
    dates=sorted({r['targetDate'] for r in rows})
    starts=list(range(min_train_dates,len(dates),block_size))[-max_blocks:]
    return [dates[start:start+block_size] for start in starts if len(dates[start:start+block_size])>=5]


def candidates():
    models={}
    # Feature selection/scaling fit separately within every training fold.
    for alpha in (1,100,1000):
        models[f'ridge_{alpha}']=make_pipeline(VarianceThreshold(),RobustScaler(),Ridge(alpha=alpha))
    for leaf,depth in ((10,6),(30,8)):
        models[f'random_forest_{leaf}']=RandomForestRegressor(n_estimators=100,max_depth=depth,min_samples_leaf=leaf,max_features=.8,n_jobs=2,random_state=42)
        models[f'extra_trees_{leaf}']=ExtraTreesRegressor(n_estimators=100,max_depth=depth,min_samples_leaf=leaf,max_features=.8,n_jobs=2,random_state=42)
    for loss in ('absolute_error','squared_error'):
        models[f'boosted_{loss}']=HistGradientBoostingRegressor(loss=loss,learning_rate=.05,max_iter=100,max_leaf_nodes=15,min_samples_leaf=20,l2_regularization=10,early_stopping=False,random_state=42)
    models['lstm']=LSTMRegressor()
    models['residual_mlp']=ResidualMLPRegressor()
    models['residual_mlp_return']=ResidualMLPRegressor(auxiliary_weight=0.)
    models['attention_regularized']=GatedAttentionRegressor(hidden_size=16,dropout=.25,weight_decay=.05,learning_rate=.0003)
    models['legacy_rf_lstm_math_ensemble']=VotingRegressor([
        ('random_forest',RandomForestRegressor(n_estimators=150,max_depth=8,min_samples_leaf=20,max_features=.8,n_jobs=2,random_state=42)),
        ('lstm',LSTMRegressor()),('mathematical_formula',MathematicalForecast(alpha=100))])
    models['attention_huber_03']=GatedAttentionRegressor(huber_delta=.3)
    models['attention_huber_2']=GatedAttentionRegressor(huber_delta=2.)
    # No second Ridge alias: MathematicalForecast is represented by ridge above.
    for attention in (False,True):
        for auxiliary in (0.,.1):
            name=('gated_attention' if attention else 'gated_lstm')+('_multitask' if auxiliary else '_return')
            models[name]=GatedAttentionRegressor(attention=attention,auxiliary_weight=auxiliary)
    return models


def fit_model(model,rows,variant):
    x,y=arrays(rows,variant)
    fitted=clone(model)
    if isinstance(fitted,GatedAttentionRegressor):
        dates=sorted({r['targetDate'] for r in rows})
        if len(dates)>=15:
            split=dates[-max(5,len(dates)//5)]
            valid=[r for r in rows if r['targetDate']>=split];train=before(rows,min(r['date'] for r in valid))
            if len(train)>=50 and len(valid)>=20:
                tx,ty=arrays(train,variant);vx,vy=arrays(valid,variant)
                fitted.fit(tx,ty,validation_data=(vx,vy))
                # Refit on all eligible history for the selected epoch count.
                fitted=clone(model).set_params(epochs=fitted.epochs_trained_)
    return fitted.fit(x,y)


def metrics(y,p,median=0.):
    actual=np.expm1(y)*100;pred=np.expm1(p)*100
    return {'samples':len(y),'meanAbsoluteError':float(np.mean(np.abs(actual-pred))),
            'naiveMeanAbsoluteError':float(np.mean(np.abs(actual))),
            'medianMeanAbsoluteError':float(np.mean(np.abs(actual-np.expm1(median)*100))),
            'directionAccuracy':float(np.mean(np.sign(y)==np.sign(p)))}


def choose(rows):
    """Inner selection only; no outer test labels enter candidate or weight selection."""
    blocks=target_blocks(rows,block_size=8,max_blocks=3,min_train_dates=20)
    news_eligible=sum(bool(r['x'][-1]) for r in rows)>=100 and len({r['targetDate'] for r in rows if r['x'][-1]})>=10
    variants=['prices','prices_without_market','prices_and_news'] if news_eligible else ['prices','prices_without_market']
    registry=candidates();scores=[];predictions={}
    for variant in variants:
        for name,model in registry.items():
            predicted=[];truth=[];ids=[]
            try:
                for block in blocks:
                    valid=[r for r in rows if r['targetDate'] in block];train=before(rows,min(r['date'] for r in valid))
                    if len(train)<100 or len(valid)<20:continue
                    fitted=fit_model(model,train,variant);vx,vy=arrays(valid,variant)
                    predicted.extend(fitted.predict(vx));truth.extend(vy)
                    ids.extend((r['symbol'],r['date'],r['targetDate'],i) for i,r in enumerate(valid))
                if predicted:
                    p=np.asarray(predicted);y=np.asarray(truth)
                    score={'model':name,'features':variant,'cvMAE':metrics(y,p)['meanAbsoluteError']}
                    scores.append(score);predictions[(variant,name)]=(p,y,ids)
            except Exception as error:
                scores.append({'model':name,'features':variant,'error':str(error)[:200]})
    valid=[s for s in scores if math.isfinite(s.get('cvMAE',float('inf')))]
    if not valid:raise ValueError('No candidate completed purged chronological validation')
    best=min(valid,key=lambda s:s['cvMAE']);variant=best['features']
    # Greedy convex blending: each new component has a nonnegative weight; weights sum to one.
    pool=[s for s in valid if s['features']==variant]
    pool=sorted(pool,key=lambda s:s['cvMAE'])[:4]
    first=best['model'];p,y,ids=predictions[(variant,first)];weights={first:1.};blended=p.copy()
    equal=np.mean([predictions[(variant,s['model'])][0] for s in pool],axis=0)
    equal_mae=metrics(y,equal)['meanAbsoluteError']
    for _ in range(3):
        winner=None;loss=metrics(y,blended)['meanAbsoluteError']
        for score in pool:
            candidate,cy,cids=predictions[(variant,score['model'])]
            if cids!=ids:continue
            for weight in (.1,.25,.5):
                mixed=(1-weight)*blended+weight*candidate
                value=metrics(y,mixed)['meanAbsoluteError']
                if value<loss-1e-6:loss=value;winner=(score['model'],weight,mixed)
        if winner is None:break
        name,weight,blended=winner
        weights={key:value*(1-weight) for key,value in weights.items()};weights[name]=weights.get(name,0)+weight
    # Equal weights remain a competing baseline and can win on inner validation.
    if equal_mae<metrics(y,blended)['meanAbsoluteError']:
        weights={s['model']:1/len(pool) for s in pool};blended=equal
    models=[fit_model(registry[name],rows,variant) for name in weights]
    fitted=WeightedForecast(models,list(weights.values()))
    return fitted,{'model':'validated_ensemble' if len(weights)>1 else next(iter(weights)),
                  'features':variant,'candidates':scores,'ensembleWeights':weights,
                  'equalWeightCvMAE':equal_mae,'cvMAE':metrics(y,blended)['meanAbsoluteError'],
                  'newsTrainingAvailable':news_eligible}


def evaluate(rows):
    dates=sorted({r['targetDate'] for r in rows})
    if len(dates)<60 or len(rows)<500:raise ValueError('At least 60 target trading dates and 500 observations are required')
    # Up to six non-overlapping 10-session outer folds. Short histories report fewer folds honestly.
    blocks=target_blocks(rows,block_size=10,max_blocks=6,min_train_dates=40)
    folds=[];records=[]
    for block in blocks:
        print(f'Chronological benchmark: {block[0]} through {block[-1]}',flush=True)
        test=[r for r in rows if r['targetDate'] in block];train=before(rows,min(r['date'] for r in test))
        if len(train)<200 or len(test)<20:continue
        model,selection=choose(train)
        tx,ty=arrays(test,selection['features']);pred=model.predict(tx)
        # A separately purged calibration tail; residuals are from an earlier fitted model.
        train_dates=sorted({r['targetDate'] for r in train});cal_start=train_dates[-10]
        calibration=[r for r in train if r['targetDate']>=cal_start]
        fit_rows=before(train,min(r['date'] for r in calibration))
        registry=candidates();weights=selection['ensembleWeights']
        calibrated=WeightedForecast([fit_model(registry[name],fit_rows,selection['features']) for name in weights],list(weights.values()))
        cx,cy=arrays(calibration,selection['features']);residual=cy-calibrated.predict(cx)
        low,high=np.quantile(residual,[.1,.9])
        fold={'testStart':block[0],'testEnd':block[-1],'trainingTargetEnd':max(r['targetDate'] for r in train),
              'firstTestObservation':min(r['date'] for r in test),'testTradingDates':len(block),**metrics(ty,pred,np.median([r['y'] for r in train])),
              'intervalCoverage':float(np.mean((ty>=pred+low)&(ty<=pred+high))),
              'selection':selection}
        # Compare each family on the same untouched outer block. Settings and feature
        # variants for that family are selected exclusively by its inner scores.
        def family(name):
            if name.startswith('ridge'):return 'ridge'
            if name.startswith('random_forest'):return 'random_forest'
            if name.startswith('extra_trees'):return 'extra_trees'
            if name.startswith('boosted'):return 'boosted_trees'
            if name.startswith('residual_mlp'):return 'residual_mlp'
            if name.startswith('attention') or name.startswith('gated_attention'):return 'attention_network'
            if name.startswith('gated_lstm'):return 'gated_lstm'
            return name
        family_best={}
        for score in selection['candidates']:
            if 'cvMAE' not in score:continue
            key=family(score['model'])
            if key not in family_best or score['cvMAE']<family_best[key]['cvMAE']:family_best[key]=score
        fold['modelComparisons']={}
        for key,score in family_best.items():
            fitted=fit_model(registry[score['model']],train,score['features'])
            fx,fy=arrays(test,score['features'])
            fold['modelComparisons'][key]={'configuration':score['model'],'features':score['features'],**metrics(fy,fitted.predict(fx))}
        folds.append(fold)
        for row,value in zip(test,pred):
            records.append({'symbol':row['symbol'],'date':row['date'],'targetDate':row['targetDate'],
                            'actualLogReturn':float(row['y']),'predictedLogReturn':float(value),
                            'medianLogReturn':float(np.median([r['y'] for r in train])),
                            'lowerLogReturn':float(value+low),'upperLogReturn':float(value+high),
                            'upProbability':float(np.mean(residual> -value))})
    if not folds:raise ValueError('Insufficient data for outer chronological benchmark')
    return folds,records


def summary(records):
    y=np.array([r['actualLogReturn'] for r in records]);p=np.array([r['predictedLogReturn'] for r in records])
    result=metrics(y,p)
    result['medianMeanAbsoluteError']=float(np.mean(np.abs(np.expm1(y)*100-np.expm1([r['medianLogReturn'] for r in records])*100)))
    result['intervalCoverage']=float(np.mean([r['lowerLogReturn']<=r['actualLogReturn']<=r['upperLogReturn'] for r in records]))
    probability=np.asarray([r['upProbability'] for r in records]);direction=y>0
    result['directionBrierScore']=float(np.mean((probability-direction)**2))
    result['probabilityCalibration']=[{'lower':float(lo),'upper':float(lo+.2),'samples':int(mask.sum()),'meanProbability':float(probability[mask].mean()) if mask.any() else None,'actualUpRate':float(direction[mask].mean()) if mask.any() else None} for lo in np.arange(0,1,.2) for mask in [(probability>=lo)&(probability<(lo+.2) if lo<.8 else probability<=1)]]
    result['confidenceFilters']=[]
    for threshold in (.5,.6,.7,.8):
        mask=np.maximum(probability,1-probability)>=threshold
        result['confidenceFilters'].append({'threshold':threshold,'retainedFraction':float(mask.mean()),'samples':int(mask.sum()),'directionAccuracy':float(np.mean((probability[mask]>=.5)==direction[mask])) if mask.any() else None})
    result['testTradingDates']=len({r['targetDate'] for r in records})
    # Date-block bootstrap: stocks sharing a market date do not count as independent days.
    daily=[]
    for date in sorted({r['targetDate'] for r in records}):
        sample=[r for r in records if r['targetDate']==date]
        improvement=np.mean([abs(np.expm1(r['actualLogReturn'])*100)-abs((np.expm1(r['actualLogReturn'])-np.expm1(r['predictedLogReturn']))*100) for r in sample])
        daily.append(improvement)
    rng=np.random.default_rng(42)
    means=np.mean(rng.choice(daily,size=(1000,len(daily)),replace=True),axis=1)
    result['dailyMAEImprovement95Interval']=np.quantile(means,[.025,.975]).tolist()
    result['monthly']={}
    for month in sorted({r['targetDate'][:7] for r in records}):
        sample=[r for r in records if r['targetDate'].startswith(month)]
        monthly=metrics(np.array([r['actualLogReturn'] for r in sample]),np.array([r['predictedLogReturn'] for r in sample]))
        monthly['medianMeanAbsoluteError']=float(np.mean([abs((np.expm1(r['actualLogReturn'])-np.expm1(r['medianLogReturn']))*100) for r in sample]))
        result['monthly'][month]=monthly
    return result
