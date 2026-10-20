"""Bounded forecast experiments: unchanged raw data, past-only features and weighting."""
import numpy as np
import warnings
from sklearn.exceptions import ConvergenceWarning
from datetime import date
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.preprocessing import RobustScaler

RECIPES={
 'recent_oc_median':('recent',False),
 'recent_oc_mean_shrunk':('recent_mean',False),
 'ridge_recent':('ridge',False),
 'ridge_volatility_scaled':('ridge',True),
 'boosted_median_recent':('median',False),
 'boosted_median_volatility_scaled':('median',True),
 'boosted_mean_volatility_scaled':('mean',True),
 'direction_logistic':('logistic',True),
 'direction_boosted':('classifier',True),
}


def target_weights(rows,cutoff):
    groups={}
    for row in rows:
        key=(row['symbol'],row['targetDate']);groups[key]=groups.get(key,0)+(2 if row['date']==row['targetDate'] else 1)
    weights=[]
    for row in rows:
        age=(date.fromisoformat(cutoff)-date.fromisoformat(row['targetDate'])).days
        if age<=0:raise ValueError('Training labels must precede cutoff')
        priority=2 if row['date']==row['targetDate'] else 1
        weights.append(priority/groups[(row['symbol'],row['targetDate'])]*2**(-age/60))
    weights=np.array(weights);return weights/weights.mean()


def weighted_quantile(values,weights,quantiles):
    order=np.argsort(values);v=np.asarray(values)[order];w=np.asarray(weights)[order]
    cdf=(np.cumsum(w)-.5*w)/w.sum()
    return np.interp(quantiles,cdf,v,left=v[0],right=v[-1])


class ForecastExperiment:
    def __init__(self,recipe):self.recipe=recipe;self.kind,self.normalized=RECIPES[recipe]

    def fit(self,rows,cutoff):
        self.cutoff=cutoff;self.training_end=max(r['targetDate'] for r in rows)
        weights=target_weights(rows,cutoff)
        x=np.asarray([r['z'] for r in rows]);y=np.asarray([r['y'] for r in rows]);scale=np.asarray([r['scale'] for r in rows])
        self.probability_calibrator=None
        if self.kind in ('recent','recent_mean'):return self
        if self.kind in ('ridge','logistic'):
            self.scaler=RobustScaler().fit(x);x=self.scaler.transform(x)
        else:self.scaler=None
        if self.kind in ('logistic','classifier'):
            truth=(y>0).astype(int)
            if self.kind=='logistic':self.model=LogisticRegression(C=.1,max_iter=300,random_state=42)
            else:self.model=HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=60,learning_rate=.04,l2_regularization=20,early_stopping=False,random_state=42)
            with warnings.catch_warnings(record=True) as recorded:
                warnings.simplefilter('always',ConvergenceWarning)
                self.model.fit(x,truth,sample_weight=weights)
            if self.kind=='logistic' and any(issubclass(item.category,ConvergenceWarning) for item in recorded):
                self.model.set_params(max_iter=2000,warm_start=True)
                with warnings.catch_warnings():
                    warnings.simplefilter('error',ConvergenceWarning)
                    self.model.fit(x,truth,sample_weight=weights)
            self.fit_diagnostics={'iterations':int(np.max(self.model.n_iter_)) if hasattr(self.model,'n_iter_') else None,
                                  'solverRetried':self.kind=='logistic' and self.model.max_iter==2000}
            normalized=y/scale
            self.distributions={}
            for positive in (False,True):
                mask=(y>0)==positive
                self.distributions[positive]=(np.abs(normalized[mask]),weights[mask])
        else:
            target=y/scale if self.normalized else y
            # Robustness thresholds are learned only from this training subset.
            low,high=np.quantile(target,[.005,.995]);target=np.clip(target,low,high)
            if self.kind=='ridge':self.model=Ridge(alpha=100)
            else:self.model=HistGradientBoostingRegressor(loss='absolute_error' if self.kind=='median' else 'squared_error',max_iter=100,max_leaf_nodes=7,min_samples_leaf=60,learning_rate=.04,l2_regularization=20,early_stopping=False,random_state=42)
            self.model.fit(x,target,sample_weight=weights)
        return self

    def raw_probability(self,rows):
        x=np.asarray([r['z'] for r in rows]);x=self.scaler.transform(x) if self.scaler is not None else x
        return np.clip(self.model.predict_proba(x)[:,1],1e-5,1-1e-5)

    def calibrate_probability(self,rows):
        if self.kind not in ('logistic','classifier'):return self
        if max(r['targetDate'] for r in rows)>=self.cutoff:raise ValueError('Calibration must precede forecast cutoff')
        p=self.raw_probability(rows);truth=np.array([r['y']>0 for r in rows],dtype=int)
        if len(set(truth))>1:
            self.probability_calibrator=LogisticRegression(C=.1,max_iter=200,random_state=42).fit(np.log(p/(1-p))[:,None],truth)
        return self

    def probability(self,rows):
        p=self.raw_probability(rows)
        return self.probability_calibrator.predict_proba(np.log(p/(1-p))[:,None])[:,1] if self.probability_calibrator is not None else p

    def predict_quantile(self,rows,level=.5):
        p=self.probability(rows)
        scale=np.array([r['scale'] for r in rows]);result=np.zeros(len(rows))
        for i,probability in enumerate(p):
            if level==.5 and probability==.5:continue
            if level>1-probability:
                q=(level-(1-probability))/probability
                values,weights=self.distributions[True];result[i]=weighted_quantile(values,weights,q)*scale[i]
            else:
                q=1-level/(1-probability)
                values,weights=self.distributions[False];result[i]=-weighted_quantile(values,weights,q)*scale[i]
        return result

    def predict(self,rows):
        if self.kind=='recent':return np.array([r['recentMedian'] for r in rows])
        if self.kind=='recent_mean':return np.array([r['recentMean']*.5 for r in rows])
        if self.kind in ('logistic','classifier'):return self.predict_quantile(rows)
        x=np.asarray([r['z'] for r in rows]);x=self.scaler.transform(x) if self.scaler is not None else x
        value=self.model.predict(x)
        return value*np.array([r['scale'] for r in rows]) if self.normalized else value


def evaluate(truth,prediction):
    actual=np.expm1(truth)*100;pred=np.expm1(prediction)*100
    return {'mae':float(np.mean(np.abs(actual-pred))),'direction':float(np.mean(np.sign(actual)==np.sign(pred)))}


def select_joint(truth,predictions,reference):
    baseline=evaluate(truth,reference)
    eligible=[]
    for name,prediction in predictions.items():
        metric=evaluate(truth,prediction)
        if metric['mae']<=baseline['mae']*.995 and metric['direction']>=baseline['direction']+.02:eligible.append((metric['mae'],name))
    return min(eligible)[1] if eligible else 'v7_reference'
