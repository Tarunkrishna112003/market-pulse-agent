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
                   'calibrationStart': dates[-30], 'calibrationEnd': max(r['targetDate'] for r in calibration),
                   'calibrationSlope': float(prototype.probability_calibrator.coef_[0,0]) if prototype.probability_calibrator is not None else None,
                   'calibrationIntercept': float(prototype.probability_calibrator.intercept_[0]) if prototype.probability_calibrator is not None else None}



def evaluate_runtime(rows, cutoff):
    """Replay the actual daily fitting procedure on ten completed mornings."""
    completed = window_rows(rows, cutoff)
    dates = sorted({r['targetDate'] for r in completed if r['date'] == r['targetDate']})[-10:]
    records = []
    for day in dates:
        model, bounds = calibrated_fit(rows, day)
        test = [r for r in completed if r['date'] == r['targetDate'] == day]
        values = model.predict(test); probability = model.probability(test)
        lower = model.predict_quantile(test, .1); upper = model.predict_quantile(test, .9)
        prior = window_rows(rows, day)
        prior_morning = [r for r in prior if r['date'] == r['targetDate']]
        historical_direction = 1 if np.mean([r['y'] > 0 for r in prior_morning]) > .5 else -1
        for i, row in enumerate(test):
            records.append({'date': day, 'symbol': row['symbol'], 'actual': row['y'],
                            'prediction': float(values[i]), 'upProbability': float(probability[i]),
                            'lower': float(lower[i]), 'upper': float(upper[i]),
                            'historicalDirection': historical_direction, 'fitBounds': bounds})
    actual = np.expm1([r['actual'] for r in records])*100
    predicted = np.expm1([r['prediction'] for r in records])*100
    lower = np.expm1([r['lower'] for r in records])*100
    upper = np.expm1([r['upper'] for r in records])*100
    up = actual > 0; down = actual < 0
    return {'testSamples': len(records), 'testTradingDates': len(dates),
            'testStart': min(dates), 'testEnd': max(dates),
            'meanAbsoluteError': float(np.mean(abs(actual-predicted))),
            'naiveMeanAbsoluteError': float(np.mean(abs(actual))),
            'directionAccuracy': float(np.mean(np.sign(actual) == np.sign(predicted))),
            'balancedDirectionAccuracy': float(.5*(np.mean(predicted[up] > 0)+np.mean(predicted[down] < 0))) if up.any() and down.any() else None,
            'historicalMajorityDirectionAccuracy': float(np.mean(np.sign(actual) == [r['historicalDirection'] for r in records])),
            'alwaysUpDirectionAccuracy': float(np.mean(up)),
            'alwaysDownDirectionAccuracy': float(np.mean(down)),
            'predictedUpFraction': float(np.mean(predicted > 0)),
            'intervalCoverage': float(np.mean((actual >= lower) & (actual <= upper))),
            'evaluationMethod': 'Daily refits with the same procedure used by current inference'}, records


def fit_runtime(rows, companies, market, cutoff, return_basis="open-to-close"):
    if return_basis not in ("open-to-close", "close-to-close"):
        raise ValueError("Unsupported return basis")
    import joblib
    from pathlib import Path
    symbols = sorted({r['symbol'] for r in rows})
    builder = PastFeatureBuilder(companies, market, symbols)
    enriched = []
    skipped = 0
    # Include enough preceding labels for every evaluation day's own 365-day fit.
    available_dates = sorted({r['targetDate'] for r in window_rows(rows, cutoff) if r['date'] == r['targetDate']})
    if len(available_dates) < 75:
        raise ValueError('Insufficient completed dates for chronological direction-model evaluation')
    earliest_test = available_dates[-10]
    history_start = (date.fromisoformat(earliest_test)-timedelta(days=365)).isoformat()
    for row in [r for r in rows if history_start <= r['targetDate'] < cutoff]:
        try:
            enriched.append(builder.enrich(row))
        except (ValueError, TypeError, KeyError, IndexError):
            skipped += 1
    dates = sorted({r['targetDate'] for r in window_rows(enriched, cutoff) if r['date'] == r['targetDate']})
    if len(dates) < 75:
        raise ValueError('Insufficient completed dates for chronological direction-model evaluation')
    evaluation, evaluation_records = evaluate_runtime(enriched, cutoff)
    final, bounds = calibrated_fit(enriched, cutoff)
    benchmark_passed = (evaluation['meanAbsoluteError'] < evaluation['naiveMeanAbsoluteError']*.995
                        and evaluation['directionAccuracy'] > max(.52,evaluation['historicalMajorityDirectionAccuracy'])
                        and (evaluation['balancedDirectionAccuracy'] or 0) > .52)
    metric = {'model': 'direction_boosted', 'features': 'past_only_ohlcv_recent_market_stock_identity',
              'trainingRows': len(window_rows(enriched, cutoff)), 'skippedFeatureRows': skipped,
              **evaluation,
              'validationPassed': False, 'validationStatus': 'not-certified', 'benchmarkPassed': bool(benchmark_passed), 'releaseStatus': 'Experimental; selected by user for forward evaluation',
              'algorithm': 'Boosted direction probabilities with earlier-fit probability calibration and volatility-scaled signed magnitude distributions',
              'evaluationBounds': {day: next(r['fitBounds'] for r in evaluation_records if r['date'] == day) for day in sorted({r['date'] for r in evaluation_records})}, 'fitBounds': bounds,
              'intervalMethod': 'Nominal empirical quantiles; measured coverage is not a guarantee',
              'returnBasis': return_basis}
    bundle = {'model': final, 'metrics': metric, 'symbols': symbols, 'modelVersion': MODEL_VERSION,
              'featureNames': RECENT_NAMES, 'returnBasis': return_basis}
    directory = Path('prediction-models'); directory.mkdir(exist_ok=True)
    artifact='adaptive-day-model' if return_basis=='open-to-close' else 'close-to-close-day-model'
    joblib.dump(bundle, directory/f'{artifact}.joblib')
    import json
    (directory/('runtime-chronological-evaluation.json' if return_basis=='open-to-close' else 'close-to-close-chronological-evaluation.json')).write_text(json.dumps(evaluation_records,allow_nan=False))
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
    raw_probabilities = model.raw_probability(ready)
    lower = model.predict_quantile(ready, .1); upper = model.predict_quantile(ready, .9)
    for i, symbol in enumerate(keys):
        record = current[symbol]; value = values[i]; percent = float(np.expm1(value)*100)
        if not np.isfinite([value, percent, probabilities[i], lower[i], upper[i]]).all() or max(abs(value), abs(lower[i]), abs(upper[i])) > 1:
            forecasts[symbol] = {'state': 'no-signal', 'lookback': lookback, 'reason': 'Model output outside supported range'}
            continue
        forecasts[symbol] = {**{k: record[k] for k in ('baseDate', 'quoteAsOf', 'targetDate', 'generatedAt', 'sessions')},
            'state': 'estimated', 'forecastModel': 'supervised', 'modelVersion': MODEL_VERSION,
            'returnBasis': bundle.get('returnBasis','open-to-close'), 'lookback': lookback, 'quotePrice': record['basePrice'],
            'estimatedPercent': percent, 'priceOnlyPercent': percent, 'newsContributionPoints': 0.,
            'newsLabel': 'context only; price model selected', 'upProbability': float(probabilities[i]), 'rawUpProbability': float(raw_probabilities[i]),
            'direction': 'positive' if percent > .05 else 'negative' if percent < -.05 else 'neutral',
            'interval': {'level': .8, 'lowerPercent': float(np.expm1(lower[i])*100), 'upperPercent': float(np.expm1(upper[i])*100)},
            'validationPassed': False, 'experimental': True, 'confidenceStatus': 'experimental', 'modelQuality': metric}
    return forecasts


def return_estimates(open_forecast, close_forecast, close_error=None):
    """Keep both signed return forecasts in detailed and compact published rows."""
    result={}
    for key,basis,forecast in [('openToClose','open-to-close',open_forecast),
                                ('closeToClose','close-to-close',close_forecast)]:
        result[key]={'returnBasis':basis,'state':forecast.get('state','no-signal'),
                     'targetDate':forecast.get('targetDate',open_forecast.get('targetDate')),
                     'estimatedPercent':forecast.get('estimatedPercent'),
                     'interval':forecast.get('interval'),
                     'confidenceStatus':forecast.get('confidenceStatus'),
                     'validationPassed':forecast.get('validationPassed',False)}
        if result[key]['state']!='estimated':
            result[key]['reason']=forecast.get('reason',close_error if key=='closeToClose' else None)
    return result
