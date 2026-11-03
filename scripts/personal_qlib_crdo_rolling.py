"""CRDO-only rolling development experiment. Context symbols are never targets."""
import copy
import json
import os
import numpy as np
import pandas as pd
from personal_qlib_crdo import make_samples, metrics, train_neural_blocks

CUTOFF = '2026-11-03'


def context_samples(crdo, contexts):
    frame = make_samples(crdo)
    dates = frame.index.get_level_values('datetime')
    for symbol, bars in contexts.items():
        close = bars.Close
        returns = close.pct_change(fill_method=None)
        columns = {}
        for window in (1,5,20):
            columns[f'{symbol}_return_{window}'] = close.pct_change(window,fill_method=None).shift(1)
            if symbol != 'VIX':
                columns[f'CRDO_relative_{symbol}_{window}'] = (
                    crdo.Close.pct_change(window,fill_method=None).shift(1) - columns[f'{symbol}_return_{window}'])
        columns[f'{symbol}_volatility_20'] = returns.rolling(20).std().shift(1)
        if symbol == 'VIX':
            columns['VIX_level'] = close.shift(1)
        for name, values in columns.items():
            frame[('feature',name)] = values.reindex(dates).to_numpy()
    return frame.replace([np.inf,-np.inf],np.nan).dropna().sort_index()


def rolling_splits(frame, folds=1, test_size=30, valid_size=60, train_size=None):
    if len(frame) < folds*test_size+valid_size+350:
        raise ValueError('Too little CRDO history for the declared rolling experiment')
    for start in range(len(frame)-folds*test_size,len(frame),test_size):
        train = frame.iloc[0 if train_size is None else max(0,start-valid_size-train_size):start-valid_size]
        valid = frame.iloc[start-valid_size:start]
        test = frame.iloc[start:start+test_size]
        assert train.index[-1][0] < valid.index[0][0] < test.index[0][0]
        yield train,valid,test


def neural(train,valid,test, corrected):
    import torch
    from qlib.contrib.model.pytorch_nn import Net
    torch.manual_seed(42)
    torch.set_num_threads(2)
    mean,std = train['feature'].mean(),train['feature'].std().clip(lower=1e-8)
    def x(part):
        return torch.tensor(((part['feature']-mean)/std).to_numpy(),dtype=torch.float32)
    tx,vx = x(train),x(valid)
    ty = torch.tensor(train['label']['return_points'].to_numpy(),dtype=torch.float32)
    vy = torch.tensor(valid['label']['return_points'].to_numpy(),dtype=torch.float32)
    network = Net(input_dim=tx.shape[1],layers=(8,) if corrected else (32,16))
    if corrected:
        for module in network.modules():
            if isinstance(module,torch.nn.Dropout):module.p=.2
    optimizer = torch.optim.Adam(network.parameters(),lr=.001,weight_decay=.1 if corrected else .01)
    if not corrected:
        selected, history = train_neural_blocks(network,optimizer,tx,ty,vx,vy)
        epoch, trained = history['bestEpoch'],50
    else:
        best,epoch,stale,trained = float('inf'),0,0,0
        selected = None
        for current in range(1,101):
            network.train()
            for idx in torch.tensor_split(torch.randperm(len(tx)),max(1,len(tx)//64)):
                optimizer.zero_grad(set_to_none=True)
                loss = ((network(tx[idx]).reshape(-1)-ty[idx])**2).mean()
                if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(),1.)
                optimizer.step()
            network.eval()
            with torch.no_grad():value=float(((network(vx).reshape(-1)-vy)**2).mean())
            trained=current
            if value < best-1e-4:
                best,epoch,stale=value,current,0
                selected=copy.deepcopy(network)
            else:stale+=1
            if stale>=10:break
    selected.eval()
    with torch.no_grad():prediction=selected(x(test)).reshape(-1).numpy()
    return prediction,dict(selectedEpoch=epoch,trainedEpochs=trained)


def lgb_prediction(train,valid,test):
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.data.dataset import Dataset
    class Parts(Dataset):
        def __init__(self):
            self.parts=dict(train=train,valid=valid,test=test)
            self.segments={name:None for name in self.parts}
            super().__init__()
        def prepare(self,segment,col_set=None,**kwargs):
            return self.parts[segment] if col_set is None else self.parts[segment][col_set]
    model=LGBModel(loss='mse',num_boost_round=500,early_stopping_rounds=40,
                   learning_rate=.025,num_leaves=7,max_depth=3,min_data_in_leaf=30,
                   lambda_l2=20,feature_fraction=.85,num_threads=2,seed=42,
                   deterministic=True,force_col_wise=True)
    data=Parts()
    model.fit(data,verbose_eval=0)
    return model.predict(data).to_numpy(),dict(bestIteration=model.model.best_iteration)


def main():
    if (os.environ.get('GITHUB_ACTIONS')!='true' or
        os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted' or
        os.environ.get('GITHUB_REF_NAME')!='personal-test'):
        raise RuntimeError('Real data runs on GitHub-hosted personal-test only')
    import qlib
    import torch
    import yfinance as yf
    from qlib.workflow import R
    torch.use_deterministic_algorithms(True)
    def download(symbol):
        bars=yf.download(symbol,start='1900-01-01',end=CUTOFF,auto_adjust=True,
                         progress=False,threads=False,multi_level_index=False)
        if bars.empty:raise ValueError(f'Missing required source {symbol}')
        bars.index=pd.to_datetime(bars.index).tz_localize(None)
        if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
            raise ValueError('Invalid source timestamps')
        return bars
    crdo=download('CRDO')
    frame=context_samples(crdo,{name:download(symbol) for name,symbol in
                              [('QQQ','QQQ'),('SOXX','SOXX'),('VIX','^VIX')]})
    original_columns=make_samples(crdo).columns
    qlib.init(provider_uri='/tmp/personal-rolling-provider',region='us',
              exp_manager={'class':'MLflowExpManager','module_path':'qlib.workflow.expm',
                           'kwargs':{'uri':'file:/tmp/personal-rolling-mlruns','default_exp_name':'CRDO-rolling'}})
    names=['original_neural','corrected_neural_context','lightgbm_context','lightgbm_price_only',
           'zero_return','train_mean','majority_direction']
    totals={name:dict(actual=[],predicted=[]) for name in names}
    records=[]
    with R.start(experiment_name='CRDO-rolling-corrections'):
        for fold,(train,valid,test) in enumerate(rolling_splits(frame),1):
            actual=test['label']['return_points'].to_numpy()
            predictions={}
            details={}
            predictions['original_neural'],details['original_neural']=neural(
                train[original_columns],valid[original_columns],test[original_columns],False)
            predictions['corrected_neural_context'],details['corrected_neural_context']=neural(train,valid,test,True)
            predictions['lightgbm_context'],details['lightgbm_context']=lgb_prediction(train,valid,test)
            predictions['lightgbm_price_only'],details['lightgbm_price_only']=lgb_prediction(
                train[original_columns],valid[original_columns],test[original_columns])
            train_y=train['label']['return_points']
            predictions['zero_return']=np.zeros(len(test))
            predictions['train_mean']=np.full(len(test),train_y.mean())
            predictions['majority_direction']=np.full(len(test),1. if (train_y>0).mean()>=.5 else -1.)
            record=dict(fold=fold,trainRows=len(train),trainStart=str(train.index[0][0].date()),
                        trainEnd=str(train.index[-1][0].date()),validationEnd=str(valid.index[-1][0].date()),
                        testStart=str(test.index[0][0].date()),testEnd=str(test.index[-1][0].date()),
                        metrics={name:metrics(actual,pred) for name,pred in predictions.items()},details=details)
            records.append(record)
            for name,pred in predictions.items():
                totals[name]['actual'].extend(actual.tolist())
                totals[name]['predicted'].extend(pred.tolist())
            print('CRDO_ROLLING_FOLD='+json.dumps(record),flush=True)
            for day,real,pred in zip(test.index,actual,predictions['corrected_neural_context']):
                print(f'CRDO_ROLLING_DAY={day[0].date()},{pred:.4f},{real:.4f}',flush=True)
    result=dict(targets=['CRDO'],contextOnly=['QQQ','SOXX','^VIX'],folds=len(records),sessions=len(totals['zero_return']['actual']),
                firstAvailableDate=str(crdo.index[0].date()),rawRows=len(crdo),
                aggregate={name:metrics(np.array(value['actual']),np.array(value['predicted']))
                           for name,value in totals.items()},
                latestFold=records[-1],
                note='All available CRDO history before 60 validation and 30 test sessions; no training window cap. Historical development benchmark; test dates previously examined. No prospective claim or test-driven tuning.')
    print('CRDO_ROLLING_RESULT='+json.dumps(result),flush=True)


if __name__=='__main__':main()
