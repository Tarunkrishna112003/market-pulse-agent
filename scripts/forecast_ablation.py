"""Controlled feature/weighting ablations; fixed settings and unchanged raw rows."""
import csv
import importlib.util
import json
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import RobustScaler
from forecast_features import PastFeatureBuilder
from forecast_research import target_weights,evaluate


class AblationModel:
    def __init__(self,kind,features='recent',balanced=True):self.kind=kind;self.features=features;self.balanced=balanced
    def matrix(self,rows):return np.asarray([r['x'][:19] if self.features=='original' else r['z'] for r in rows])
    def fit(self,rows,cutoff):
        x=self.matrix(rows);y=np.array([r['y'] for r in rows]);low,high=np.quantile(y,[.005,.995]);y=np.clip(y,low,high)
        if max(r['targetDate'] for r in rows)>=cutoff:raise ValueError('Future training label')
        weights=target_weights(rows,cutoff) if self.balanced else np.ones(len(rows))
        self.scaler=RobustScaler().fit(x) if self.kind=='ridge' else None
        if self.scaler is not None:x=self.scaler.transform(x)
        if self.kind=='ridge':self.model=Ridge(alpha=100)
        else:self.model=HistGradientBoostingRegressor(loss='absolute_error',max_iter=100,max_leaf_nodes=7,min_samples_leaf=60,learning_rate=.04,l2_regularization=20,early_stopping=False,random_state=42)
        self.model.fit(x,y,sample_weight=weights);return self
    def predict(self,rows):
        x=self.matrix(rows);x=self.scaler.transform(x) if self.scaler is not None else x
        return self.model.predict(x)


def run():
    root=Path(__file__).resolve().parent.parent;original=root/'work/backtest-2026-08-19_2026-10-19'
    output=root/'work/forecast-research-2026-08-19_2026-10-19/ablations';output.mkdir(exist_ok=True)
    spec=importlib.util.spec_from_file_location('historical_replay',root/'scripts/historical-backtest.py');replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    rows=joblib.load(output.parent/'enriched-rows.joblib');source=json.loads((original/'historical-data.json').read_text());market=json.loads((original/'market.json').read_text())['daily']
    actual=json.loads((original/'results/results.json').read_text());actual_by_key={(r['date'],r['symbol']):r['actualPercent'] for r in actual['entries']}
    dates=sorted({r['date'] for r in actual['entries']});symbols=[c['symbol'] for c in source['companies']];builder=PastFeatureBuilder(source['companies'],market,symbols)
    settings={f'{kind}_{view}_{balance}':(kind,view,balance=='balanced') for kind in ('ridge','median') for view,balance in [('original','unweighted'),('original','balanced'),('recent','unweighted'),('recent','balanced')]}
    (output/'plan.json').write_text(json.dumps({'settings':settings,'status':'Exploratory controlled ablations; no recipe selection from these test outcomes.'},indent=2))
    frozen=[]
    for date in dates:
        path=output/f'frozen-{date}.json'
        if path.exists():frozen.extend(json.loads(path.read_text()));continue
        train=replay.training_rows(rows,date,365);ready=[]
        for symbol in symbols:
            context=replay.prediction_context(builder.companies[symbol],market,date)
            ready.append(builder.enrich({'symbol':symbol,'date':date,'targetDate':date,'x':context['x'],'y':0}))
        predictions={name:AblationModel(*params).fit(train,date).predict(ready) for name,params in settings.items()}
        daily=[{'date':date,'symbol':symbol,'trainingTargetEnd':max(r['targetDate'] for r in train),'predictions':{name:float(p[i]) for name,p in predictions.items()}} for i,symbol in enumerate(symbols)]
        path.write_text(json.dumps(daily,indent=2,allow_nan=False));frozen.extend(daily);print(f'{date}: ablations frozen',flush=True)
    joined=[{**r,'actualLogReturn':float(np.log1p(actual_by_key[(r['date'],r['symbol'])]/100))} for r in frozen]
    metrics={}
    for name in settings:
        metrics[name]={}
        for period,predicate in [('development',lambda r:r['date']<'2026-10-01'),('confirmation',lambda r:r['date']>='2026-10-01'),('wholePeriod',lambda r:True)]:
            subset=[r for r in joined if predicate(r)];metrics[name][period]=evaluate(np.array([r['actualLogReturn'] for r in subset]),np.array([r['predictions'][name] for r in subset]))
    (output/'results.json').write_text(json.dumps({'metrics':metrics,'entries':joined},indent=2,allow_nan=False))
    lines=['# Controlled feature and weighting ablations','','All rows, dates and model settings stay fixed. Each comparison changes feature view or sample weights. These results are exploratory.','',
           '| Configuration | Development direction | Development MAE | Confirmation direction | Confirmation MAE |','|---|---:|---:|---:|---:|']
    for name,metric in metrics.items():lines.append(f"| {name} | {metric['development']['direction']:.2%} | {metric['development']['mae']:.4f} | {metric['confirmation']['direction']:.2%} | {metric['confirmation']['mae']:.4f} |")
    (output/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps(metrics,indent=2),flush=True)


if __name__=='__main__':run()
