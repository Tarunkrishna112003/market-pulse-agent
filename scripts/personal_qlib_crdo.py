"""CRDO-only Qlib experiment; real data stays on a GitHub-hosted runner."""
import json
import os
from datetime import datetime, timezone


def make_samples(bars):
    import numpy as np
    import pandas as pd
    close, opening = bars['Close'], bars['Open']
    ret = close.pct_change(fill_method=None)
    features = {}
    for lag in range(1, 11):
        features[f'return_lag_{lag}'] = ret.shift(lag)
    for window in (5, 10, 20, 60):
        features[f'momentum_{window}'] = close.pct_change(window, fill_method=None).shift(1)
        features[f'volatility_{window}'] = ret.rolling(window).std().shift(1)
        features[f'volume_ratio_{window}'] = (bars.Volume / bars.Volume.rolling(window).mean()).shift(1)
        features[f'ma_ratio_{window}'] = (close / close.rolling(window).mean() - 1).shift(1)
    features['intraday_previous'] = (close / opening - 1).shift(1)
    features['range_previous'] = ((bars.High - bars.Low) / opening).shift(1)
    x = pd.DataFrame(features)
    y = 100 * (close / opening - 1)
    frame = pd.concat({'feature': x, 'label': y.to_frame('return_points')}, axis=1)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    frame.index = pd.MultiIndex.from_arrays([frame.index, ['CRDO'] * len(frame)], names=['datetime', 'instrument'])
    return frame


def split_samples(frame):
    if len(frame) < 350:
        raise ValueError('Insufficient history for training, validation and 30-session holdout')
    return frame.iloc[:-90], frame.iloc[-90:-30], frame.iloc[-30:]


def metrics(actual, predicted):
    import numpy as np
    return dict(samples=len(actual), maePoints=float(np.mean(abs(actual-predicted))),
                msePointsSquared=float(np.mean((actual-predicted)**2)),
                directionAccuracy=float(np.mean(np.sign(actual)==np.sign(predicted))))


def main():
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or
        os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
        os.environ.get('GITHUB_REF_NAME') != 'personal-test'):
        raise RuntimeError('Run real CRDO data only on GitHub-hosted personal-test branch')
    import numpy as np
    import pandas as pd
    import yfinance as yf
    import qlib
    from qlib.data.dataset import Dataset
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.workflow import R

    # Exclude the current Eastern date, including partially completed sessions.
    today = pd.Timestamp.now(tz='America/New_York').date().isoformat()
    bars = yf.download('CRDO', start='1900-01-01', end=today, auto_adjust=True,
                       actions=True, progress=False, threads=False, multi_level_index=False)
    if bars.empty:
        raise RuntimeError('Provider returned no CRDO history')
    bars.index = pd.to_datetime(bars.index).tz_localize(None)
    if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError('Invalid trading date ordering')
    if ((bars.Open <= 0) | (bars.Close <= 0)).any():
        raise ValueError('Invalid source prices')
    frame = make_samples(bars)
    train, valid, test = split_samples(frame)

    class CRDODataset(Dataset):
        def __init__(self, parts):
            self.parts = parts
            self.segments = {key: (value.index[0][0], value.index[-1][0]) for key, value in parts.items()}
            super().__init__()
        def prepare(self, segment, col_set=None, **kwargs):
            data = self.parts[segment]
            return data if col_set is None else data[col_set]

    # Qlib workflow records remain temporary on the runner. No production assets are touched.
    qlib.init(provider_uri='/tmp/personal-qlib-provider', region='us',
              exp_manager={'class':'MLflowExpManager', 'module_path':'qlib.workflow.expm',
                           'kwargs':{'uri':'file:/tmp/personal-qlib-mlruns','default_exp_name':'CRDO'}})
    dataset = CRDODataset(dict(train=train, valid=valid, test=test))
    model = LGBModel(loss='mse', num_boost_round=500, early_stopping_rounds=40,
                     learning_rate=.025, num_leaves=7, max_depth=3, min_data_in_leaf=30,
                     lambda_l2=20, feature_fraction=.85, num_threads=2,
                     seed=42, deterministic=True, force_col_wise=True)
    with R.start(experiment_name='CRDO-only-heldout'):
        model.fit(dataset, verbose_eval=0)
        predicted = model.predict(dataset).to_numpy()
    actual = test['label']['return_points'].to_numpy()
    train_y = train['label']['return_points']
    majority_sign = 1 if (train_y > 0).mean() >= .5 else -1
    summary = dict(model='Qlib LGBModel / CRDO only', createdAt=datetime.now(timezone.utc).isoformat(),
                   qlibVersion=qlib.__version__, source='Yahoo Finance via yfinance; adjusted daily OHLCV',
                   firstAvailableDate=str(bars.index[0].date()), lastAvailableDate=str(bars.index[-1].date()),
                   rawRows=len(bars), trainRows=len(train), validationRows=len(valid),
                   trainEnd=str(train.index[-1][0].date()), validationEnd=str(valid.index[-1][0].date()),
                   testStart=str(test.index[0][0].date()), testEnd=str(test.index[-1][0].date()),
                   bestIteration=model.model.best_iteration, metrics=metrics(actual,predicted),
                   zeroReturnBaseline=metrics(actual,np.zeros(len(actual))),
                   trainMeanBaseline=metrics(actual,np.full(len(actual),train_y.mean())),
                   majorityDirectionBaselineAccuracy=float(np.mean(np.sign(actual)==majority_sign)),
                   note='Frozen 30-session holdout; no tuning on test outcomes. Not directly comparable to multi-stock metrics.')
    print('CRDO_QLIB_RESULT=' + json.dumps(summary), flush=True)
    print('date,predicted_open_to_close_percent,actual_open_to_close_percent,error_points,direction_correct')
    for index, pred, real in zip(test.index,predicted,actual):
        print(f'{index[0].date()},{pred:.4f},{real:.4f},{pred-real:.4f},{np.sign(pred)==np.sign(real)}')
    # User requested display only: no extra result report/model artifact is uploaded.


if __name__ == '__main__':
    main()
