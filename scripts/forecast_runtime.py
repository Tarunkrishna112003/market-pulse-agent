"""Runtime adapter for the direction-boosted candidate, using past-only OHLCV."""
from datetime import date, timedelta
import numpy as np
from forecast_research import ForecastExperiment
from forecast_features import PastFeatureBuilder, RECENT_NAMES

MODEL_VERSION = 'annual-open-to-close-v9-direction-boosted'


def window_rows(rows, cutoff):
    start = (date.fromisoformat(cutoff)-timedelta(days=365)).isoformat()
    hourly = (date.fromisoformat(cutoff)-timedelta(days=90)).isoformat()
    return [r for r in rows if start <= r['targetDate'] < cutoff and r['date'] < cutoff
            and (r['date'] == r['targetDate'] or r['date'] >= hourly)]


def calibrated_fit(rows, cutoff):
    rows = window_rows(rows, cutoff)
    dates = sorted({r['targetDate'] for r in rows if r['date'] == r['targetDate']})
    if len(dates) < 60 or len(rows) < 200:
        raise ValueError('Direction model requires 60 completed morning dates and 200 observations')
    # Same 15-date calibration segment used by the research recipe, followed by
    # a 15-date gap. Calibration predictions come from an earlier fitted model.
    calibration = [r for r in rows if r['date'] == r['targetDate'] and dates[-30] <= r['targetDate'] < dates[-15]]
    train = [r for r in rows if r['date'] < dates[-30] and r['targetDate'] < dates[-30]]
    prototype = ForecastExperiment('direction_boosted').fit(train, cutoff).calibrate_probability(calibration)
    model = ForecastExperiment('direction_boosted').fit(rows, cutoff)
    model.probability_calibrator = prototype.probability_calibrator
    return model, {'trainingTargetEnd': max(r['targetDate'] for r in rows),
                   'calibrationTrainingEnd': max(r['targetDate'] for r in train),
                   'calibrationStart': dates[-30], 'calibrationEnd': max(r['targetDate'] for r in calibration)}


def fit_runtime(rows, companies, market, cutoff):
    import joblib
    from pathlib import Path
    symbols = sorted({r['symbol'] for r in rows})
    builder = PastFeatureBuilder(companies, market, symbols)
    enriched = []
    skipped = 0
    for row in window_rows(rows, cutoff):
        try:
            enriched.append(builder.enrich(row))
        except (ValueError, TypeError, KeyError, IndexError):
            skipped += 1
    dates = sorted({r['targetDate'] for r in enriched if r['date'] == r['targetDate']})
    if len(dates) < 75:
        raise ValueError('Insufficient completed dates for chronological direction-model evaluation')
    test_start = dates[-10]
    evaluation_model, evaluation_bounds = calibrated_fit(enriched, test_start)
    test = [r for r in enriched if r['date'] == r['targetDate'] and r['targetDate'] >= test_start]
    actual = np.expm1([r['y'] for r in test])*100
    predicted = np.expm1(evaluation_model.predict(test))*100
    lower = np.expm1(evaluation_model.predict_quantile(test, .1))*100
    upper = np.expm1(evaluation_model.predict_quantile(test, .9))*100
    final, bounds = calibrated_fit(enriched, cutoff)
    metric = {'model': 'direction_boosted', 'features': 'past_only_ohlcv_recent_market_stock_identity',
              'trainingRows': len(enriched), 'skippedFeatureRows': skipped, 'testSamples': len(test),
              'testTradingDates': 10, 'testStart': test_start, 'testEnd': max(r['targetDate'] for r in test),
              'meanAbsoluteError': float(np.mean(abs(actual-predicted))),
              'naiveMeanAbsoluteError': float(np.mean(abs(actual))),
              'directionAccuracy': float(np.mean(np.sign(actual) == np.sign(predicted))),
              'intervalCoverage': float(np.mean((actual >= lower) & (actual <= upper))),
              'validationPassed': False, 'releaseStatus': 'Experimental; selected by user for forward evaluation',
              'algorithm': 'Boosted direction probabilities with earlier-fit probability calibration and volatility-scaled signed magnitude distributions',
              'evaluationBounds': evaluation_bounds, 'fitBounds': bounds,
              'intervalMethod': 'Nominal empirical quantiles; measured coverage is not a guarantee',
              'returnBasis': 'open-to-close'}
    bundle = {'model': final, 'metrics': metric, 'symbols': symbols, 'modelVersion': MODEL_VERSION,
              'featureNames': RECENT_NAMES, 'returnBasis': 'open-to-close'}
    directory = Path('prediction-models'); directory.mkdir(exist_ok=True)
    joblib.dump(bundle, directory/'adaptive-day-model.joblib')
    return bundle, builder


def predict_runtime(bundle, builder, current, lookback):
    model = bundle['model']; metric = bundle['metrics']; forecasts = {}; ready = []; keys = []
    for symbol, context in current.items():
        try:
            ready.append(builder.enrich({**context, 'symbol': symbol, 'date': context['inferenceDate'], 'y': 0.}))
            keys.append(symbol)
        except (ValueError, TypeError, KeyError, IndexError) as error:
            forecasts[symbol] = {'state': 'no-signal', 'lookback': lookback, 'reason': f'Incomplete direction-model features: {error}'}
    if not ready:
        return forecasts
    values = model.predict(ready); probabilities = model.probability(ready)
    lower = model.predict_quantile(ready, .1); upper = model.predict_quantile(ready, .9)
    for i, symbol in enumerate(keys):
        record = current[symbol]; value = values[i]; percent = float(np.expm1(value)*100)
        if not np.isfinite([value, percent, probabilities[i], lower[i], upper[i]]).all() or max(abs(value), abs(lower[i]), abs(upper[i])) > 1:
            forecasts[symbol] = {'state': 'no-signal', 'lookback': lookback, 'reason': 'Model output outside supported range'}
            continue
        forecasts[symbol] = {**{k: record[k] for k in ('baseDate', 'quoteAsOf', 'targetDate', 'generatedAt', 'sessions')},
            'state': 'estimated', 'forecastModel': 'supervised', 'modelVersion': MODEL_VERSION,
            'returnBasis': 'open-to-close', 'lookback': lookback, 'quotePrice': record['basePrice'],
            'estimatedPercent': percent, 'priceOnlyPercent': percent, 'newsContributionPoints': 0.,
            'newsLabel': 'context only; price model selected', 'upProbability': float(probabilities[i]),
            'direction': 'positive' if percent > .05 else 'negative' if percent < -.05 else 'neutral',
            'interval': {'level': .8, 'lowerPercent': float(np.expm1(lower[i])*100), 'upperPercent': float(np.expm1(upper[i])*100)},
            'validationPassed': False, 'experimental': True, 'confidenceStatus': 'low-confidence', 'modelQuality': metric}
    return forecasts
