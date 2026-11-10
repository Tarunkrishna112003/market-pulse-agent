"""As-of 05:00 America/Los_Angeles price/volume features, never target OHLC."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import numpy as np
from stock_specific import DailyStockFeatures

PACIFIC = ZoneInfo('America/Los_Angeles')
EASTERN = ZoneInfo('America/New_York')


def cutoff_at(day):
    return datetime.combine(datetime.fromisoformat(day).date(), time(5), PACIFIC)


def extended_features(company, prior, target, scale):
    cutoff = cutoff_at(target)
    previous = prior['date']
    daily = [b for b in company['daily'] if b['date'] < target]
    normal_volume = max(float(np.mean([b.get('volume', 0) or 0 for b in daily[-20:]])), 1)
    base = prior['close']
    groups = {'post': [], 'pre': []}
    for bar in company.get('hourly', []):
        start = datetime.fromtimestamp(bar['timestamp'], EASTERN)
        end = start + timedelta(seconds=bar.get('durationSeconds', 3600))
        # Yahoo timestamps are bucket STARTS. Reject any bucket crossing cutoff.
        if end > cutoff or start >= cutoff:
            continue
        day = start.date().isoformat()
        minute = start.hour*60+start.minute
        close_minute = prior.get('closeMinute', 960)
        if day == previous and minute >= close_minute and end.hour*60+end.minute <= 1200 and end.date() == start.date():
            group = 'post'
        elif day == target and minute >= 240 and end <= cutoff:
            group = 'pre'
        else:
            continue
        if not all(isinstance(bar.get(k), (int, float)) and np.isfinite(bar[k]) and bar[k]>0 for k in ('open','high','low','close')):
            continue
        if bar['low']>min(bar['open'],bar['close']) or bar['high']<max(bar['open'],bar['close']):
            continue
        groups[group].append((start, end, bar))
    values = {}
    for label, raw in groups.items():
        selected = sorted(raw, key=lambda row: row[0])
        values[label+'_missing'] = float(not selected)
        values[label+'_bars'] = float(len(selected))
        values[label+'_volume_missing'] = 1.
        values[label+'_vwap_missing'] = 1.
        for name in ('gap','momentum','range','volume_ratio','vwap_distance','age_minutes'):
            values[label+'_'+name] = 0.
        if not selected:
            continue
        bars = [row[2] for row in selected]
        first, last = bars[0], bars[-1]
        observed_volume = [b for b in bars if isinstance(b.get('volume'),(int,float)) and np.isfinite(b['volume']) and b['volume']>0]
        volume = sum(b['volume'] for b in observed_volume)
        values[label+'_gap'] = 100*np.log(last['close']/base)/scale
        values[label+'_momentum'] = 100*np.log(last['close']/first['open'])/scale
        values[label+'_range'] = 100*np.log(max(b['high'] for b in bars)/min(b['low'] for b in bars))/scale
        if observed_volume:
            values[label+'_volume_missing'] = float(len(observed_volume)!=len(bars))
            values[label+'_volume_ratio'] = volume/normal_volume
            vwap = sum((b['high']+b['low']+b['close'])/3*b['volume'] for b in observed_volume)/volume
            values[label+'_vwap_distance'] = 100*np.log(last['close']/vwap)/scale
            values[label+'_vwap_missing'] = float(len(observed_volume)!=len(bars))
        endpoint = cutoff if label == 'pre' else datetime.combine(datetime.fromisoformat(previous).date(), time(20), EASTERN)
        values[label+'_age_minutes'] = (endpoint-selected[-1][1]).total_seconds()/60
    values['overnight_continuation'] = (values['pre_gap']-values['post_gap']) if groups['pre'] and groups['post'] else 0.
    return values


class ExtendedStockFeatures:
    def __init__(self, dataset):
        self.daily = DailyStockFeatures(dataset)
        self.names = None
        self.market_columns = None
        self.hourly_by_day = {}
        for company in dataset['companies']:
            days = {}
            for bar in company.get('hourly', []):
                day = datetime.fromtimestamp(bar['timestamp'], EASTERN).date().isoformat()
                days.setdefault(day, []).append(bar)
            self.hourly_by_day[company['symbol']] = days

    def __getattr__(self, name):
        return getattr(self.daily, name)

    def features(self, symbol, target):
        row = self.daily.features(symbol, target)
        prior = next(b for b in reversed(self.bars[symbol]) if b['date'] < target)
        days = self.hourly_by_day[symbol]
        company = {**self.companies[symbol], 'hourly':days.get(prior['date'], [])+days.get(target, [])}
        extra = extended_features(company, prior, target, row['scale'])
        row['x'] = np.r_[row['x'][:-2], list(extra.values()), row['x'][-2:]].astype(np.float32)
        self.names = self.daily.names[:-2]+list(extra)+self.daily.names[-2:]
        self.market_columns = self.daily.market_columns
        row['extendedCoverage'] = {key:extra[key] for key in ('post_missing','pre_missing','post_bars','pre_bars',
            'post_volume_missing','pre_volume_missing','post_vwap_missing','pre_vwap_missing')}
        row['inputCutoffAt'] = cutoff_at(target).isoformat()
        return row
