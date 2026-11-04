"""CRDO-only indicator ablation; all features precede the forecast session."""
import json
import os
import numpy as np
import pandas as pd
from personal_qlib_crdo import metrics
from personal_qlib_crdo_rolling import context_samples
from personal_crdo_sec_lightgbm import fit_predict
from personal_crdo_sources import public_fetch, sec_records, sec_features, SEC_URL


def wilder(series, window=14):
    # Seed Wilder smoothing with the first window's arithmetic mean.
    result = pd.Series(np.nan, index=series.index)
    start = series.first_valid_index()
    if start is None:
        return result
    position = series.index.get_loc(start) + window - 1
    if position >= len(series):
        return result
    result.iloc[position] = series.iloc[position-window+1:position+1].mean()
    for i in range(position+1, len(series)):
        result.iloc[i] = (result.iloc[i-1]*(window-1)+series.iloc[i])/window
    return result


def indicators(bars):
    c, h, l = bars.Close, bars.High, bars.Low
    ema9, ema20 = c.ewm(span=9, adjust=False).mean(), c.ewm(span=20, adjust=False).mean()
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    change = c.diff()
    gain, loss = wilder(change.clip(lower=0)), wilder(-change.clip(upper=0))
    rsi = 100*gain/(gain+loss)
    rsi = rsi.mask((gain+loss)==0, 50)
    macd = c.ewm(span=12, adjust=False).mean()-c.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    middle, std = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr = wilder(tr)
    up, down = h.diff(), -l.diff()
    plus = wilder(up.where((up>down)&(up>0), 0))/atr*100
    minus = wilder(down.where((down>up)&(down>0), 0))/atr*100
    dx = (100*(plus-minus).abs()/(plus+minus)).mask((plus+minus)==0, 0)
    features = pd.DataFrame({
        'ema9_distance': c/ema9-1, 'ema20_distance': c/ema20-1,
        'ema9_20_spread': ema9/ema20-1,
        'sma50_distance': c/sma50-1, 'sma200_distance': c/sma200-1,
        'sma50_200_spread': sma50/sma200-1, 'rsi14': rsi,
        'macd_relative': macd/c, 'macd_signal_relative': signal/c,
        'macd_histogram_relative': (macd-signal)/c,
        'bollinger_position': (c-middle)/(2*std), 'bollinger_width': 4*std/middle,
        'adx14': wilder(dx), 'plus_di14': plus, 'minus_di14': minus,
        'atr14_relative': atr/c,
    })
    return features.shift(1).replace([np.inf, -np.inf], np.nan)


def session_vwap_features(daily, intraday):
    # Regular session only. This is a 5-minute typical-price VWAP approximation,
    # not exchange trade-by-trade VWAP; never use the target session's bars.
    intraday = intraday.tz_convert('America/New_York')
    regular = intraday.between_time('09:30', '15:59').copy()
    regular['day'] = regular.index.tz_localize(None).normalize()
    regular['pv'] = (regular.High+regular.Low+regular.Close)/3*regular.Volume
    grouped = regular.groupby('day')
    totals = grouped.Volume.sum()
    vwap = grouped.pv.sum()/totals.where(totals>0)
    values = (daily.Close/vwap.reindex(daily.index)-1).shift(1)
    return pd.DataFrame({'previous_session_vwap_distance': values,
                         'previous_session_vwap_missing': values.isna().astype(int)}, index=daily.index)


def main():
    if (os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted'
            or os.environ.get('GITHUB_REF_NAME')!='personal-test'):
        raise RuntimeError('Real data and training only on GitHub-hosted personal-test')
    import yfinance as yf
    today = pd.Timestamp.now(tz='America/New_York').date()
    def download(symbol):
        bars = yf.download(symbol, start='1900-01-01', end=str(today), auto_adjust=True,
                           progress=False, threads=False, multi_level_index=False)
        bars.index = pd.to_datetime(bars.index).tz_localize(None)
        if bars.empty or bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
            raise ValueError('Invalid history '+symbol)
        if not np.isfinite(bars.Close).all() or (bars.Close<=0).any():
            raise ValueError('Invalid prices '+symbol)
        return bars
    bars = download('CRDO')
    if (bars[['Open','High','Low','Close']]<=0).any().any():
        raise ValueError('Invalid CRDO OHLC')
    base = context_samples(bars, {s:download(t) for s,t in [('QQQ','QQQ'),('SOXX','SOXX'),('VIX','^VIX')]})
    raw, audit = public_fetch(SEC_URL, os.environ['SEC_USER_AGENT'])
    facts = sec_records(json.loads(raw))
    if not facts:
        raise ValueError('Missing SEC facts')
    financial, _ = sec_features(base, bars, facts)
    for name in financial:
        base[('feature',name)] = financial[name]
    technical = indicators(bars)
    dates = base.index.get_level_values('datetime')
    enriched = base.copy()
    for name in technical:
        enriched[('feature',name)] = technical[name].reindex(dates).to_numpy()
    enriched = enriched.dropna()
    base = base.loc[enriched.index]  # Identical training and test dates in the comparison.
    datasets = {'existing_prices_context_sec':base, 'plus_daily_indicators':enriched}
    vwap_audit = {}
    try:
        intraday = yf.download('CRDO', period='60d', interval='5m', auto_adjust=True,
                               progress=False, threads=False, multi_level_index=False)
        if intraday.empty:
            raise ValueError('No intraday history returned')
        vw = session_vwap_features(bars, intraday)
        full = enriched.copy()
        for name in vw:
            full[('feature',name)] = vw[name].reindex(full.index.get_level_values('datetime')).to_numpy()
        datasets['plus_daily_indicators_and_vwap'] = full
        vwap_audit = dict(sourceBars=len(intraday),
            preTestRowsWithVWAP=int(full.iloc[:-20]['feature']['previous_session_vwap_distance'].notna().sum()),
            testRowsWithVWAP=int(full.iloc[-20:]['feature']['previous_session_vwap_distance'].notna().sum()))
    except Exception as error:
        vwap_audit = {'unavailable':str(error)}
    actual = base.iloc[-20:]['label']['return_points'].to_numpy()
    results, details, predictions = {}, {}, {}
    for name, frame in datasets.items():
        pred, detail = fit_predict(frame, test_size=20)
        results[name], details[name], predictions[name] = metrics(actual, pred), detail, pred
    results['zero_return_baseline'] = metrics(actual, np.zeros(20))
    majority = 1 if (base.iloc[:-20]['label']['return_points']>0).mean()>=.5 else -1
    results['training_majority_direction_baseline'] = metrics(actual, np.full(20, majority))
    dates = base.iloc[-20:].index.get_level_values('datetime')
    result = dict(symbol='CRDO', sessions=20, testStart=str(dates[0].date()), testEnd=str(dates[-1].date()),
        priceStart=str(bars.index[0].date()), metrics=results, models=details, vwap=vwap_audit,
        secFacts=len(facts), productionModified=False,
        limitations=['Retrospective dates overlap earlier experiments; not a fresh independent holdout.',
            '200-session warmup omitted equally for every candidate.',
            'VWAP uses limited recent 5-minute history; earlier rows remain missing, never fabricated.',
            'All indicators use previous completed sessions; no test labels used for fitting or tree-count selection.'])
    print('CRDO_INDICATOR_RESULT='+json.dumps(result), flush=True)
    print('date,model,predicted_percent,actual_percent,absolute_error_points,direction_correct')
    for name, pred in predictions.items():
        for day, p, y in zip(dates, pred, actual):
            print(f'{day.date()},{name},{p:.4f},{y:.4f},{abs(p-y):.4f},{np.sign(p)==np.sign(y)}', flush=True)
    summary = ['### CRDO: last 20 completed sessions', f'{dates[0].date()} to {dates[-1].date()}',
        '| Model | Direction | MAE (points) | MSE (points²) |', '|---|---:|---:|---:|']
    for name, score in results.items():
        summary.append(f"| {name} | {score['directionAccuracy']:.1%} | {score['maePoints']:.4f} | {score['msePointsSquared']:.4f} |")
    summary.append('\nRetrospective comparison. VWAP is a recent 5-minute-bar approximation; see coverage in logs.')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out:
        out.write('\n'.join(summary)+'\n')


if __name__=='__main__':
    main()
