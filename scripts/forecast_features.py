"""Past-only short-horizon OHLCV features derived from the existing dataset."""
from bisect import bisect_left
from datetime import date
import numpy as np

RECENT_NAMES=(['oc_lag_'+str(i) for i in range(1,6)]+
    [f'{name}_{window}' for window in (5,20,60) for name in ('oc_mean','oc_median','oc_vol','cc_momentum','cc_vol')]+
    ['gap_last','gap_mean_5','gap_mean_20','volume_ratio_5','volume_ratio_20','range_last','range_mean_20',
     'close_location','body_fraction','rsi_14','market_return','market_momentum_5','market_momentum_20','market_vol_20','beta_60'])


class PastFeatureBuilder:
    def __init__(self,companies,market,symbols):
        self.companies={c['symbol']:c for c in companies}
        self.dates={symbol:[d['date'] for d in c['daily']] for symbol,c in self.companies.items()}
        self.market=market;self.market_dates=[d['date'] for d in market]
        self.market_by_date={d['date']:d for d in market}
        self.symbols=list(symbols);self.cache={}

    def recent(self,symbol,anchor):
        key=(symbol,anchor)
        if key in self.cache:return self.cache[key]
        # Target/anchor-day bars are excluded, including their opening prices.
        past=self.companies[symbol]['daily'][:bisect_left(self.dates[symbol],anchor)][-81:]
        if len(past)<61:raise ValueError('At least 61 prior complete daily bars required')
        close=np.array([d['close'] for d in past]);opening=np.array([d['open'] for d in past])
        high=np.array([d['high'] for d in past]);low=np.array([d['low'] for d in past])
        volume=np.array([d.get('volume') or 0 for d in past],dtype=float)
        if not all(np.isfinite(x).all() for x in (close,opening,high,low,volume)) or np.any(opening<=0):raise ValueError('Incomplete historical OHLCV')
        oc=np.log(close/opening);cc=np.diff(np.log(close));gap=np.log(opening[1:]/close[:-1])
        values=list(oc[-5:][::-1])
        for window in (5,20,60):
            values.extend([np.mean(oc[-window:]),np.median(oc[-window:]),np.std(oc[-window:]),np.log(close[-1]/close[-window-1]),np.std(cc[-window:])])
        ranges=np.log(np.maximum(high,low)/np.maximum(low,1e-8));width=max(high[-1]-low[-1],1e-8)
        gain=np.maximum(cc[-14:],0).mean();loss=np.maximum(-cc[-14:],0).mean()
        rsi=(gain-loss)/max(gain+loss,1e-8)
        market=self.market[:bisect_left(self.market_dates,anchor)][-81:]
        mc=np.array([d['close'] for d in market]);mr=np.diff(np.log(mc))
        paired=[]
        for previous,current in zip(past[-61:],past[-60:]):
            a=self.market_by_date.get(previous['date']);b=self.market_by_date.get(current['date'])
            if a and b:paired.append((np.log(current['close']/previous['close']),np.log(b['close']/a['close'])))
        pair=np.asarray(paired);beta=float(np.cov(pair.T,ddof=0)[0,1]/max(np.var(pair[:,1]),1e-8)) if len(pair)>10 else 0.
        values.extend([gap[-1],np.mean(gap[-5:]),np.mean(gap[-20:]),
                       np.log(max(volume[-1],1)/max(np.mean(volume[-5:]),1)),
                       np.log(max(volume[-1],1)/max(np.mean(volume[-20:]),1)),
                       ranges[-1],np.mean(ranges[-20:]),(close[-1]-low[-1])/width,(close[-1]-opening[-1])/width,rsi,
                       mr[-1],np.log(mc[-1]/mc[-6]),np.log(mc[-1]/mc[-21]),np.std(mr[-20:]),beta])
        scale=float(max(np.std(oc[-20:]),.002))
        result=(list(map(float,values)),scale,float(np.median(oc[-20:])),float(np.mean(oc[-20:])))
        if len(values)!=len(RECENT_NAMES) or not np.isfinite(values).all():raise ValueError('Invalid derived features')
        self.cache[key]=result;return result

    def enrich(self,row):
        recent,scale,median,mean=self.recent(row['symbol'],row['date'])
        weekday=date.fromisoformat(row['targetDate']).weekday()
        x=list(row['x'][:19])+recent+[float(weekday==i) for i in range(5)]+[float(row['symbol']==symbol) for symbol in self.symbols]
        return {**row,'z':x,'scale':scale,'recentMedian':median,'recentMean':mean}
