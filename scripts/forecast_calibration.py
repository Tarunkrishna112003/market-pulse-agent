"""Magnitude adjustments fitted on earlier, out-of-sample morning predictions."""
import numpy as np

SCALES=(.25,.5,1.,1.5,2.,3.,5.)
BLENDS=(0.,.25,.5,.75,1.)


def percent_mae(truth,prediction):
    return float(np.mean(np.abs(np.expm1(truth)*100-np.expm1(prediction)*100)))


def choose_scale(predicted,truth):
    # Prefer the unadjusted forecast when losses tie.
    return min(SCALES,key=lambda factor:(percent_mae(truth,predicted*factor),abs(np.log(factor))))


def magnitude_blend(predicted,magnitude,weight):
    magnitude=np.maximum(np.asarray(magnitude),1e-8)
    return (1-weight)*predicted+weight*np.sign(predicted)*magnitude


def fit_calibration(predicted,truth,symbols,target_dates,magnitude,cutoff):
    predicted=np.asarray(predicted,dtype=float);truth=np.asarray(truth,dtype=float)
    magnitude=np.asarray(magnitude,dtype=float);symbols=np.asarray(symbols)
    if not len(predicted) or not(len(predicted)==len(truth)==len(symbols)==len(target_dates)==len(magnitude)):
        raise ValueError('Aligned nonempty calibration observations required')
    if any(date>=cutoff for date in target_dates):raise ValueError('Calibration labels must precede the forecast cutoff')
    if not all(np.isfinite(values).all() for values in (predicted,truth,magnitude)):raise ValueError('Nonfinite calibration values')
    # One morning observation per symbol and target session avoids counting repeated intraday labels as independent.
    if len(set(zip(symbols.tolist(),target_dates)))!=len(predicted):raise ValueError('Repeated stock/target calibration labels')
    scale=float(choose_scale(predicted,truth));stock_scales={}
    for symbol in sorted(set(symbols)):
        mask=symbols==symbol;n=int(mask.sum())
        raw=choose_scale(predicted[mask],truth[mask]) if n>=20 else scale
        strength=n/(n+60)
        stock_scales[str(symbol)]=float(np.exp((1-strength)*np.log(scale)+strength*np.log(raw)))
    blend=float(min(BLENDS,key=lambda weight:(percent_mae(truth,magnitude_blend(predicted,magnitude,weight)),weight)))
    return {'scale':scale,'stockScales':stock_scales,'magnitudeBlend':blend,'samples':len(predicted),
            'targetStart':min(target_dates),'targetEnd':max(target_dates),'cutoff':cutoff,
            'calibrationMAE':{'unadjusted':percent_mae(truth,predicted),'globalScale':percent_mae(truth,predicted*scale),
                              'magnitudeBlend':percent_mae(truth,magnitude_blend(predicted,magnitude,blend))}}


def apply_calibration(predicted,symbols,magnitude,configuration):
    predicted=np.asarray(predicted,dtype=float)
    return {'unadjusted':predicted.copy(),'global_scale':predicted*configuration['scale'],
            'stock_scale':predicted*np.array([configuration['stockScales'].get(symbol,configuration['scale']) for symbol in symbols]),
            'magnitude_blend':magnitude_blend(predicted,magnitude,configuration['magnitudeBlend'])}
