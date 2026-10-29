"""Direct signed-return learner. No pooled forecast, median, or sign-mix rule.

Every feature uses completed sessions strictly before the target date. The joint
objective learns a continuous return and penalizes incorrect direction using the
same output, avoiding a calibrator that reverses ranks or changes its sign.
"""
from bisect import bisect_left
from datetime import date, timedelta
import numpy as np
from scipy.special import expit


def good_bar(bar):
    values=[bar.get(k) for k in ('open','close','low','high')]
    return all(isinstance(v,(int,float)) and np.isfinite(v) and v>0 for v in values) and bar['low']<=min(bar['open'],bar['close'])<=max(bar['open'],bar['close'])<=bar['high']


class JointReturnObjective:
    def __init__(self, direction_weight=.1, delta=1.):
        self.direction_weight=direction_weight;self.delta=delta

    def __call__(self, actual, predicted, weight):
        error=predicted-actual
        curvature=1+(error/self.delta)**2
        gradient=error/np.sqrt(curvature)
        hessian=curvature**(-1.5)
        sign=np.sign(actual);probability=expit(-sign*predicted)
        gradient-=self.direction_weight*sign*probability
        hessian+=self.direction_weight*sign**2*probability*(1-probability)
        if weight is not None:gradient*=weight;hessian*=weight
        return gradient,np.maximum(hessian,1e-8)


class DailyStockFeatures:
    def __init__(self,dataset):
        self.companies={c['symbol']:c for c in dataset['companies']}
        self.series={**dataset['context'],**self.companies}
        self.bars={s:sorted(c['daily'],key=lambda b:b['date']) for s,c in self.series.items()}
        self.dates={s:[b['date'] for b in bars] for s,bars in self.bars.items()}
        self.symbols=sorted(self.companies)
        self.sectors=sorted({c.get('sector') or 'Unknown' for c in self.companies.values()})
        self.symbol_ids={s:i for i,s in enumerate(self.symbols)}
        self.sector_ids={s:i for i,s in enumerate(self.sectors)}
        self.invalid_prefix={};self.values={}
        for symbol,company in self.series.items():
            warned={w['date'] for w in company.get('warnings',[])}
            invalid=[not good_bar(b) or bool(b.get('corporateAction')) or b['date'] in warned for b in self.bars[symbol]]
            self.invalid_prefix[symbol]=np.r_[0,np.cumsum(invalid)]
            self.values[symbol]=[np.array([b.get(k,np.nan) for b in self.bars[symbol]],dtype=float) for k in ('open','close','high','low','volume')]
        self.names=None;self.market_columns=None
        self.context_flags={}
        for symbol,company in dataset['context'].items():
            warned={w['date'] for w in company.get('warnings',[])}
            self.context_flags[symbol]=np.r_[0,np.cumsum([int(bool(b.get('corporateAction')) or b['date'] in warned) for b in self.bars[symbol]])]

    def context_flagged(self,symbol,target):
        if symbol not in self.context_flags:return False
        end=bisect_left(self.dates[symbol],target);prefix=self.context_flags[symbol]
        return bool(prefix[end]!=prefix[max(0,end-61)])

    def features(self,symbol,target):
        company=self.companies[symbol];end=bisect_left(self.dates[symbol],target)
        bars=self.bars[symbol][max(0,end-81):end]
        if len(bars)<61 or bars[-1].get('nextSession',target)!=target:
            raise ValueError('Missing consecutive prior history')
        start=max(0,end-81);prefix=self.invalid_prefix[symbol]
        if prefix[end]!=prefix[start]:
            raise ValueError('Historical price quality flag')
        opening,close,high,low,volume=(v[start:end] for v in self.values[symbol])
        cc=np.diff(np.log(close));oc=np.log(close/opening);gap=np.log(opening[1:]/close[:-1]);ranges=np.log(high/low)
        if np.any(abs(cc)>np.log(2)):raise ValueError('Unresolved price discontinuity')
        scale=max(float(np.std(oc[-20:]))*100,.3)
        names=[];values=[];market_columns=[]
        def add(name,value,market=False):
            if market:market_columns.append(len(values))
            names.append(name);values.append(float(value))
        for lag in range(1,11):
            for name,series in [('oc',oc),('cc',cc),('gap',gap)]:add(f'{name}_lag_{lag}',series[-lag]*100/scale)
        for window in (5,20,60):
            for name,series in [('oc',oc),('cc',cc),('gap',gap)]:
                add(f'{name}_mean_{window}',np.mean(series[-window:])*100/scale)
                add(f'{name}_vol_{window}',np.std(series[-window:])*100/scale)
            add(f'momentum_{window}',np.log(close[-1]/close[-window-1])*100/scale)
            add(f'volume_ratio_{window}',np.log(max(volume[-1],1)/max(np.mean(volume[-window:]),1)))
            add(f'range_ratio_{window}',ranges[-1]/max(np.mean(ranges[-window:]),1e-6))
        width=max(high[-1]-low[-1],1e-8)
        add('close_location',(close[-1]-low[-1])/width)
        add('body_fraction',(close[-1]-opening[-1])/width)
        add('upper_wick',(high[-1]-max(close[-1],opening[-1]))/width)
        add('lower_wick',(min(close[-1],opening[-1])-low[-1])/width)
        for window in (5,20):
            add(f'position_{window}',(close[-1]-min(low[-window:]))/max(max(high[-window:])-min(low[-window:]),1e-8))
        gain=np.maximum(cc[-14:],0).mean();loss=np.maximum(-cc[-14:],0).mean()
        add('rsi_balance',(gain-loss)/max(gain+loss,1e-8))
        add('stock_volatility',scale)
        for label,context in [('market','^GSPC'),('sector',company.get('sectorETF')),('vix','^VIX')]:
            end=bisect_left(self.dates.get(context,[]),target)
            observed=self.bars.get(context,[])[max(0,end-61):end]
            prefix=self.invalid_prefix.get(context)
            valid=len(observed)>=21 and observed[-1]['date']==bars[-1]['date'] and not self.context_flagged(context,target) and prefix[end]==prefix[max(0,end-61)]
            add(label+'_missing',not valid,True)
            if valid:
                prices=np.array([b['close'] for b in observed]);returns=np.diff(np.log(prices))
                for window in (1,5,20):
                    value=np.log(prices[-1]/prices[-window-1])*100/scale
                    add(f'{label}_momentum_{window}',value,True)
                    if label!='vix':add(f'{label}_relative_{window}',np.log(close[-1]/close[-window-1])*100/scale-value,True)
                add(label+'_volatility',np.std(returns[-20:])*100,True)
                if label=='vix':add('vix_level',prices[-1],True)
            else:
                for window in (1,5,20):
                    add(f'{label}_momentum_{window}',0,True)
                    if label!='vix':add(f'{label}_relative_{window}',0,True)
                add(label+'_volatility',0,True)
                if label=='vix':add('vix_level',0,True)
        for weekday in range(5):add(f'weekday_{weekday}',date.fromisoformat(target).weekday()==weekday)
        add('symbol_id',self.symbol_ids[symbol]);add('sector_id',self.sector_ids[company.get('sector') or 'Unknown'])
        x=np.array(values,dtype=np.float32)
        if not np.isfinite(x).all():raise ValueError('Nonfinite historical features')
        if self.names is not None and self.names!=names:raise ValueError('Feature schema changed')
        self.names=names;self.market_columns=market_columns
        return {'symbol':symbol,'targetDate':target,'lastInputDate':bars[-1]['date'],'x':x,'scale':scale}


class StockSpecificReturnModel:
    def __init__(self,direction_weight=.1,years=1,market=True):
        self.direction_weight=direction_weight;self.years=years;self.market=market

    def fit(self,rows,cutoff,market_columns):
        import lightgbm as lgb
        if not rows or any(r['targetDate']>=cutoff or r['lastInputDate']>=r['targetDate'] for r in rows):
            raise ValueError('Training outcomes must precede forecast date')
        start=(date.fromisoformat(cutoff)-timedelta(days=365*self.years)).isoformat()
        rows=[r for r in rows if r['targetDate']>=start]
        self.training_end=max(r['targetDate'] for r in rows)
        self.columns=[i for i in range(len(rows[0]['x'])) if self.market or i not in market_columns]
        # All examples are one snapshot per stock/session. Each market date has
        # equal total weight before recency decay, despite changing IPO coverage.
        counts={}
        for row in rows:counts[row['targetDate']]=counts.get(row['targetDate'],0)+1
        weights=np.array([2**(-(date.fromisoformat(cutoff)-date.fromisoformat(r['targetDate'])).days/180)/counts[r['targetDate']] for r in rows])
        weights/=weights.mean()
        x=np.asarray([r['x'] for r in rows])[:,self.columns]
        y=np.array([r['actualPercent']/r['scale'] for r in rows])
        self.model=lgb.LGBMRegressor(objective=JointReturnObjective(self.direction_weight),
            n_estimators=150,learning_rate=.035,num_leaves=15,max_depth=5,
            min_child_samples=100,reg_lambda=20.,max_bin=63,
            n_jobs=2,random_state=42,deterministic=True,force_col_wise=True,verbosity=-1)
        self.model.fit(x,y,sample_weight=weights,categorical_feature=[len(self.columns)-2,len(self.columns)-1])
        return self

    def predict(self,rows):
        x=np.asarray([r['x'] for r in rows])[:,self.columns]
        values=self.model.predict(x)*np.array([r['scale'] for r in rows])
        if not np.isfinite(values).all() or np.any(values<=-100):raise ValueError('Invalid model prediction; no fallback')
        return values

    def feature_contributions(self,rows):
        return self.model.booster_.predict(np.asarray([r['x'] for r in rows])[:,self.columns],pred_contrib=True)


class PerStockReturnModel:
    """Separate learned equation and training scaler for every ticker.

    Regularized regression is a comparator to shared pattern learning, not a
    pooled or historical-median fallback. No untrained ticker receives a value.
    """
    def __init__(self,years=5):self.years=years

    def fit(self,rows,cutoff,market_columns):
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import RobustScaler
        if not rows or any(r['targetDate']>=cutoff or r['lastInputDate']>=r['targetDate'] for r in rows):
            raise ValueError('Training outcomes must precede forecast date')
        start=(date.fromisoformat(cutoff)-timedelta(days=365*self.years)).isoformat()
        rows=[r for r in rows if r['targetDate']>=start]
        self.training_end=max(r['targetDate'] for r in rows)
        self.columns=list(range(len(rows[0]['x'])-2));self.models={}
        groups={}
        for row in rows:groups.setdefault(row['symbol'],[]).append(row)
        for symbol,local in groups.items():
            if len(local)<40:continue
            x=np.asarray([r['x'] for r in local])[:,self.columns]
            scaler=RobustScaler().fit(x);x=np.clip(scaler.transform(x),-10,10)
            y=np.array([r['actualPercent']/r['scale'] for r in local])
            low,high=np.quantile(y,[.005,.995]);y=np.clip(y,low,high)
            weight=np.array([2**(-(date.fromisoformat(cutoff)-date.fromisoformat(r['targetDate'])).days/180) for r in local]);weight/=weight.mean()
            model=Ridge(alpha=1000.).fit(x,y,sample_weight=weight)
            self.models[symbol]=(scaler,model)
        return self

    def feature_contributions(self,rows):
        parts=[]
        for row in rows:
            if row['symbol'] not in self.models:raise ValueError('No trained individual stock model')
            scaler,model=self.models[row['symbol']]
            x=np.clip(scaler.transform(np.asarray(row['x'])[None,self.columns]),-10,10)[0]
            parts.append(np.r_[x*model.coef_,model.intercept_])
        return np.asarray(parts)

    def predict(self,rows):
        values=self.feature_contributions(rows).sum(axis=1)*[r['scale'] for r in rows]
        if not np.isfinite(values).all() or np.any(values<=-100):raise ValueError('Invalid individual stock prediction')
        return values
