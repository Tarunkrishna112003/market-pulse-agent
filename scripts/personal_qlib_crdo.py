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


def train_neural_blocks(network, optimizer, train_x, train_y, valid_x, valid_y,
                        runs=10, epochs_per_run=5, start_epoch=0, previous_best=None):
    """Keep network AND Adam state across blocks; each epoch visits every train row."""
    import copy
    import torch
    if len(train_x) < 2:
        raise ValueError('At least two training rows are required for batch normalization')
    records, best_state, best_epoch = [], None, None
    best_loss = float('inf')
    if previous_best is not None:
        best_state = copy.deepcopy(previous_best[0].state_dict())
        best_epoch = previous_best[1]['bestEpoch']
        best_loss = previous_best[1]['bestValidationMSE']
    with torch.no_grad():
        network.eval()
        initial_loss = float(torch.mean((network(train_x).reshape(-1)-train_y)**2))
    for run in range(1, runs+1):
        for inner_epoch in range(1, epochs_per_run+1):
            network.train()
            order = torch.randperm(len(train_x))
            # Balanced batches prevent BatchNorm's single-row final batch error.
            for indices in torch.tensor_split(order, max(1, len(order)//64)):
                optimizer.zero_grad(set_to_none=True)
                predicted = network(train_x[indices]).reshape(-1)
                loss = torch.mean((predicted-train_y[indices])**2)
                if not torch.isfinite(loss):
                    raise ValueError('Nonfinite neural training loss')
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(), 5.)
                optimizer.step()
            network.eval()
            with torch.no_grad():
                train_loss = float(torch.mean((network(train_x).reshape(-1)-train_y)**2))
                valid_loss = float(torch.mean((network(valid_x).reshape(-1)-valid_y)**2))
            epoch = start_epoch+(run-1)*epochs_per_run+inner_epoch
            if valid_loss < best_loss:
                best_loss, best_epoch = valid_loss, epoch
                best_state = copy.deepcopy(network.state_dict())
        record = dict(run=start_epoch//epochs_per_run+run, cumulativeEpochs=epoch, trainMSE=train_loss,
                      validationMSE=valid_loss)
        records.append(record)
        print('CRDO_BACKPROP_RUN=' + json.dumps(record), flush=True)
    # Final weights remain intact; select a separate validation-best copy for inference.
    selected = copy.deepcopy(network)
    selected.load_state_dict(best_state)
    selected.eval()
    return selected, dict(initialTrainMSE=initial_loss, runs=records,
                         bestEpoch=best_epoch, bestValidationMSE=best_loss)


def neural_experiment(train, valid, test):
    import numpy as np
    import torch
    from qlib.contrib.model.pytorch_nn import Net
    torch.set_num_threads(2)
    torch.manual_seed(42)
    np.random.seed(42)
    torch.use_deterministic_algorithms(True)
    # Fit scaling on train only, never on validation or test prices.
    mean = train['feature'].mean()
    std = train['feature'].std().clip(lower=1e-8)
    def tensor(part):
        return torch.tensor(((part['feature']-mean)/std).to_numpy(), dtype=torch.float32)
    tx, vx = tensor(train), tensor(valid)
    ty = torch.tensor(train['label']['return_points'].to_numpy(), dtype=torch.float32)
    vy = torch.tensor(valid['label']['return_points'].to_numpy(), dtype=torch.float32)
    network = Net(input_dim=tx.shape[1], layers=(32,16))
    optimizer = torch.optim.Adam(network.parameters(), lr=.001, weight_decay=.01)
    selected, history = train_neural_blocks(network, optimizer, tx, ty, vx, vy)
    print('CRDO_REPRODUCED_FIRST_50=' + json.dumps(history), flush=True)
    selected, continued_history = train_neural_blocks(
        network, optimizer, tx, ty, vx, vy, start_epoch=50, previous_best=(selected,history))
    # Test outcomes enter only reporting, after all 100 epochs and checkpoint selection.
    with torch.no_grad():
        selected_pred = selected(tensor(test)).reshape(-1).numpy()
        final_pred = network(tensor(test)).reshape(-1).numpy()
    actual = test['label']['return_points'].to_numpy()
    print('CRDO_BACKPROP_RESULT=' + json.dumps(dict(
        model='Qlib Net MLP (32,16), Adam backpropagation', totalEpochs=100,
        reproducedFirst50=history, trainingHistory=continued_history,
        selectedMetrics=metrics(actual,selected_pred),
        epoch100Metrics=metrics(actual,final_pred),
        testStart=str(test.index[0][0].date()), testEnd=str(test.index[-1][0].date()),
        note='Previously examined historical holdout; validation-only checkpoint selection, not a new prospective test.'
    )), flush=True)
    return selected_pred


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
    # Fixed cutoff keeps the repeat on precisely the original train/valid/test dates.
    today = '2026-11-03'
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
    neural_predictions = neural_experiment(train, valid, test)
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
    print('NEURAL_date,predicted_open_to_close_percent,actual_open_to_close_percent,error_points,direction_correct')
    for index, pred, real in zip(test.index,neural_predictions,actual):
        print(f'NEURAL_{index[0].date()},{pred:.4f},{real:.4f},{pred-real:.4f},{np.sign(pred)==np.sign(real)}')
    # User requested display only: no extra result report/model artifact is uploaded.


if __name__ == '__main__':
    main()
