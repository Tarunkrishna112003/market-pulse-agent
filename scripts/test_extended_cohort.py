"""Original saved testing cohort, fixed 30-session holdout, GitHub runner only."""
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from extended_hours import ExtendedStockFeatures
from stock_specific import DailyStockFeatures, StockSpecificReturnModel
from stock_specific_runtime import build_stock_rows
from personal_qlib_crdo import metrics


def calendar(start, end):
    code = """import {tradingDay,nextTradingDay,scheduledCloseMinute} from './lib/trading-calendar.mjs';
    const rows={};for(let d=new Date(process.argv[1]+'T00:00:00Z');d.toISOString().slice(0,10)<=process.argv[2];d.setUTCDate(d.getUTCDate()+1)){
    const day=d.toISOString().slice(0,10);if(tradingDay(day))rows[day]={nextSession:nextTradingDay(day),closeMinute:scheduledCloseMinute(day)};}console.log(JSON.stringify(rows));"""
    return json.loads(subprocess.check_output(['node','--input-type=module','-e',code,start,end], text=True))


def main():
    if (os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted'
            or os.environ.get('GITHUB_REF_NAME')!='personal-test'):
        raise RuntimeError('Real histories and training only on GitHub-hosted personal-test')
    import yfinance as yf
    now = datetime.now(ZoneInfo('America/New_York'))
    schedule = calendar((now-timedelta(days=2300)).date().isoformat(), (now+timedelta(days=10)).date().isoformat())
    today = now.date().isoformat()
    completed = [d for d, s in schedule.items() if d<today or d==today and now.hour*60+now.minute>=s['closeMinute']+15]
    test_dates = completed[-30:]
    cutoff, end = test_dates[0], (datetime.fromisoformat(test_dates[-1])+timedelta(days=1)).date().isoformat()
    url = 'https://tarunkrishna112003.github.io/market-pulse-agent/testing-results.json'
    with urllib.request.urlopen(url, timeout=60) as response:
        saved = json.load(response)
    cohort = saved['stocks']
    if len(cohort)!=25 or len({s['symbol'] for s in cohort})!=25:
        raise ValueError('Expected the original fixed 25-stock testing cohort')
    print('COHORT='+json.dumps({'source':url,'cohortSession':saved.get('cohortSession'),'stocks':cohort,'testDates':test_dates}), flush=True)
    errors = []
    def download(symbol, hourly=False):
        for attempt in range(3):
            frame = yf.download(symbol.replace('.','-'), start=str((now-timedelta(days=729 if hourly else 2200)).date()),
                end=None if hourly else end, interval='1h' if hourly else '1d', prepost=hourly,
                auto_adjust=False, actions=True, progress=False, threads=False, multi_level_index=False)
            if not frame.empty:
                break
            time.sleep(2*(attempt+1))
        if frame.empty:
            raise ValueError('No '+('extended hours' if hourly else 'daily')+' data returned')
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError('Invalid source timestamps')
        rows = []
        for timestamp, row in frame.iterrows():
            stamp = pd.Timestamp(timestamp)
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize('America/New_York')
            day = stamp.tz_convert('America/New_York').date().isoformat()
            bar = dict(timestamp=int(stamp.timestamp()),date=day,open=float(row.Open),close=float(row.Close),
                high=float(row.High),low=float(row.Low),volume=float(row.Volume),**schedule.get(day,{}))
            if hourly:
                bar['durationSeconds'] = 3600
            if row.get('Stock Splits',0):
                bar['corporateAction'] = 'provider-reported-split'
            if day in schedule and (hourly or day in completed):
                rows.append(bar)
        return rows
    companies = []
    for stock in cohort:
        symbol = stock['symbol']
        try:
            daily = download(symbol)
            try:
                hourly = download(symbol, True)
            except Exception as error:
                hourly = []
                errors.append(dict(symbol=symbol,source='extended hours',error=str(error)))
            companies.append(dict(**stock,daily=daily,hourly=hourly,sector=stock.get('sector','Unknown'),sectorETF=None))
            hours = {}
            for bar in hourly:
                hour = datetime.fromtimestamp(bar['timestamp'],ZoneInfo('America/New_York')).hour
                hours[str(hour)] = hours.get(str(hour),0)+1
            print('COLLECTED='+json.dumps(dict(symbol=symbol,daily=len(daily),hourly=len(hourly),easternHourCounts=hours)), flush=True)
        except Exception as error:
            errors.append(dict(symbol=symbol,source='daily',error=str(error)))
        time.sleep(.3)
    context = {}
    for symbol in ('^GSPC','^VIX'):
        try:
            context[symbol] = {'daily':download(symbol)}
        except Exception as error:
            errors.append(dict(symbol=symbol,source='market context',error=str(error)))
    if '^GSPC' not in context:
        raise ValueError('Missing market history')
    data = dict(companies=companies,context=context)
    builders = {'daily_only':DailyStockFeatures(data),'daily_plus_extended':ExtendedStockFeatures(data)}
    by_symbol = {c['symbol']:c for c in companies}
    training, models = {}, {}
    for name, builder in builders.items():
        rows = []
        for company in companies:
            samples, _ = build_stock_rows(builder,company['symbol'],cutoff,years=5)
            rows.extend(samples)
        if len(rows)<200:
            raise ValueError('Insufficient chronological training examples')
        training[name] = dict(rows=len(rows),lastLabel=max(r['targetDate'] for r in rows))
        models[name] = StockSpecificReturnModel(years=5).fit(rows,cutoff,builder.market_columns)
    records = []
    for stock in cohort:
        symbol = stock['symbol']
        for day in test_dates:
            record = dict(symbol=symbol,date=day,actual=None,predictions={},coverage=None)
            company = by_symbol.get(symbol)
            try:
                if company is None:
                    raise ValueError('Stock source unavailable')
                target = next(b for b in company['daily'] if b['date']==day)
                from stock_specific import good_bar
                if not good_bar(target) or target.get('corporateAction'):
                    raise ValueError('Invalid actual session prices')
                record['actual'] = 100*(target['close']/target['open']-1)
                for name,builder in builders.items():
                    row = builder.features(symbol,day)
                    record['predictions'][name] = float(models[name].predict([row])[0])
                    if name=='daily_plus_extended':
                        record['coverage'] = row['extendedCoverage']
                        record['inputCutoffAt'] = row['inputCutoffAt']
            except (ValueError,KeyError,TypeError,StopIteration) as error:
                record['unavailableReason'] = str(error) or type(error).__name__
            records.append(record)
    paired = [r for r in records if r['actual'] is not None and len(r['predictions'])==2]
    covered = [r for r in paired if r['coverage']['pre_missing']==0 and r['coverage']['post_missing']==0]
    def score(rows):
        if not rows:
            return None
        actual = np.array([r['actual'] for r in rows])
        return {name:metrics(actual,np.array([r['predictions'][name] for r in rows])) for name in models}
    result = dict(testStart=test_dates[0],testEnd=test_dates[-1],sessions=30,stocks=len(cohort),
        expectedComparisons=750,pairedComparisons=len(paired),bothExtendedSessionsAvailable=len(covered),
        training=training,allPaired=score(paired),extendedCoverageOnly=score(covered),
        perStock={s['symbol']:score([r for r in paired if r['symbol']==s['symbol']]) for s in cohort},
        errors=errors,productionModified=False,
        limitations=['Last 30 completed exchange sessions, not calendar days.',
            'Shared fixed 150-tree model trained on up to five years ending before the entire holdout; no test-label fitting.',
            'Retrospective cohort and dates have been examined previously; not prospective validation.',
            'Hourly OHLCV: only fully completed buckets before 05:00 Pacific. Not tick-level or full 5-minute premarket.',
            'Raw price basis matches live collector; unresolved splits/discontinuities are rejected.',
            'Absent extended bars are marked missing; coverage does not establish provider feed completeness.',
            'News is not included in this price/volume ablation.'])
    print('EXTENDED_COHORT_RESULT='+json.dumps(result), flush=True)
    for row in records:
        print('SESSION_COMPARISON='+json.dumps(row), flush=True)
    summary = ['### Extended-hours test: original 25-stock cohort',f'{test_dates[0]} through {test_dates[-1]} · 05:00 Pacific cutoff',
        f'{len(paired)}/750 paired comparisons; {len(covered)} with both extended sessions observed.',
        '| Model | Direction accuracy | MAE (points) | MSE (points²) |','|---|---:|---:|---:|']
    for name, metric in (result['allPaired'] or {}).items():
        summary.append(f"| {name} | {metric['directionAccuracy']:.1%} | {metric['maePoints']:.4f} | {metric['msePointsSquared']:.4f} |")
    summary.extend(['','Missing data never becomes fabricated extended-hours activity. See per-stock scores, coverage, and all 750 comparisons in logs.'])
    Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('\n'.join(summary)+'\n')


if __name__=='__main__':
    main()
