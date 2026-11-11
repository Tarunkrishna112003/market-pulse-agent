"""Prospective 5 AM extended-hours forecasts, stored on their own Git branch."""
import json
import math
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from extended_hours import ExtendedStockFeatures, cutoff_at
from stock_specific import StockSpecificReturnModel, good_bar
from stock_specific_runtime import build_stock_rows

MODEL_VERSION = 'offday-extended-hours-v1'
DATA_BRANCH = 'offday-predictions-data'


def read_json(path, fallback=None):
    return json.loads(path.read_text()) if path.exists() else fallback


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False, separators=(',', ':'))+'\n')


def merge_forecast(previous, candidate):
    """The first published estimate is frozen, while unavailable attempts can retry."""
    if previous and previous.get('state')=='estimated':
        return previous
    return candidate


def score_record(record, bar, calendar, now):
    if record.get('actualPercent') is not None or not bar or not good_bar(bar):
        return record
    day=record['targetDate']
    if day not in calendar:
        return record
    closing=datetime.combine(datetime.fromisoformat(day).date(),time(),ZoneInfo('America/New_York'))+timedelta(minutes=calendar[day]['closeMinute']+15)
    if now<closing:
        return record
    actual=100*(bar['close']/bar['open']-1)
    result={**record,'actualPercent':actual,'evaluatedAt':now.isoformat()}
    predicted=record.get('estimatedPercent')
    if isinstance(predicted,(int,float)) and math.isfinite(predicted):
        result.update(errorPoints=abs(predicted-actual),directionCorrect=(predicted>0)-(predicted<0)==(actual>0)-(actual<0))
    return result


def generate(data, control):
    target=control['today']
    if datetime.fromisoformat(control['generatedAt'].replace('Z','+00:00'))<cutoff_at(target):
        raise ValueError('The 5 AM Pacific input window is still open')
    builder=ExtendedStockFeatures(data)
    training=[]
    for company in data['companies']:
        if company.get('sharedTraining'):
            rows,_=build_stock_rows(builder,company['symbol'],target,years=5)
            training.extend(rows)
    if len(training)<200:
        raise ValueError('Insufficient completed historical training examples')
    model=StockSpecificReturnModel(years=5).fit(training,target,builder.market_columns)
    metadata={'trainingRows':len(training),'trainingTargetEnd':model.training_end,
              'trainingHistoryDays':1825,'trainingStocks':len({row['symbol'] for row in training}),
              'inputCutoffAt':cutoff_at(target).isoformat()}
    generated=datetime.now(timezone.utc)
    regular_open=datetime.combine(datetime.fromisoformat(target).date(),time(9,30),ZoneInfo('America/New_York'))
    companies={company['symbol']:company for company in data['companies']}
    records=[]
    for stock in control['universe']:
        symbol=stock['symbol']
        record={**stock,'targetDate':target,'modelVersion':MODEL_VERSION,'returnBasis':'open-to-close',
                'state':'unavailable','estimatedPercent':None,'actualPercent':None,
                'inputCutoffAt':cutoff_at(target).isoformat(),'generatedAt':generated.isoformat(),
                'publishedAfterOpen':generated>=regular_open}
        try:
            company=companies.get(symbol)
            if company is None:
                raise ValueError('Daily history unavailable')
            if company['forecastContext']['state']!='ready':
                raise ValueError('The previous completed trading session is unavailable')
            row=builder.features(symbol,target)
            coverage=row['extendedCoverage']
            record['coverage']=coverage
            if coverage['pre_missing'] or coverage['post_missing']:
                raise ValueError('Premarket or previous postmarket prices unavailable by 5 AM Pacific')
            predicted=float(model.predict([row])[0])
            record.update(state='estimated',estimatedPercent=predicted)
        except (ValueError,KeyError,TypeError) as error:
            record['reason']=str(error)
        records.append(record)
    published=datetime.now(timezone.utc)
    for record in records:
        record.update(generatedAt=published.isoformat(),publishedAfterOpen=published>=regular_open)
    return records,metadata


def git_store(repository, token, folder):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+',repository):
        raise ValueError('Invalid repository')
    import base64
    env={**os.environ,'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'http.https://github.com/.extraheader',
         'GIT_CONFIG_VALUE_0':'AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode()}
    def git(*args):
        return subprocess.run(['git',*args],cwd=folder,env=env,check=True,capture_output=True,text=True).stdout
    folder.mkdir(parents=True,exist_ok=True)
    git('init','-q')
    git('remote','add','origin','https://github.com/'+repository+'.git')
    request=urllib.request.Request(f'https://api.github.com/repos/{repository}/git/ref/heads/{DATA_BRANCH}',
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(request,timeout=30):pass
        git('fetch','--depth=1','origin',DATA_BRANCH)
        git('checkout','-B',DATA_BRANCH,'FETCH_HEAD')
    except urllib.error.HTTPError as error:
        if error.code!=404:raise
        git('checkout','--orphan',DATA_BRANCH)
    git('config','user.name','github-actions[bot]')
    git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    return git


def update_store(folder, control, data, candidates, model_metadata, now):
    prior=read_json(folder/'index.json',{})
    activation=prior.get('activationDate',control['activationDate'])
    universe={s['symbol']:s for s in prior.get('stocks',[])}
    universe.update({s['symbol']:s for s in control['universe']})
    by_symbol={c['symbol']:{b['date']:b for b in c['daily']} for c in data.get('companies',[])}
    candidate_map={r['symbol']:r for r in candidates if r['targetDate']>=activation}
    changed_dates=set()
    for symbol,stock in universe.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.^-]{0,25}',symbol):
            continue
        path=folder/'stocks'/(symbol+'.json')
        saved=read_json(path,{'symbol':symbol,'records':[]})
        history={r['targetDate']:r for r in saved['records']}
        candidate=candidate_map.get(symbol)
        if candidate:
            day=candidate['targetDate']
            merged=merge_forecast(history.get(day),candidate)
            if merged!=history.get(day):changed_dates.add(day)
            history[day]=merged
        for day,record in list(history.items()):
            evaluated=score_record(record,by_symbol.get(symbol,{}).get(day),control['calendar'],now)
            if evaluated!=record:changed_dates.add(day)
            history[day]=evaluated
        if history:
            write_json(path,{**stock,'records':sorted(history.values(),key=lambda r:r['targetDate'],reverse=True)})
    sessions=set(prior.get('sessions',[]))|changed_dates
    latest_estimated=prior.get('lastRun',{}).get('estimated',0) if prior.get('lastRun',{}).get('date')==control['today'] else 0
    for day in changed_dates:
        rows=[]
        for symbol in universe:
            saved=read_json(folder/'stocks'/(symbol+'.json'),{'records':[]})
            row=next((r for r in saved['records'] if r['targetDate']==day),None)
            if row:rows.append(row)
        write_json(folder/'sessions'/(day+'.json'),{'date':day,'modelVersion':MODEL_VERSION,'rows':rows})
        if day==control['today']:
            latest_estimated=sum(row['state']=='estimated' for row in rows)
    index={'version':1,'modelVersion':MODEL_VERSION,'activationDate':activation,
           'updatedAt':now.isoformat(),'sessions':sorted(sessions),'stocks':list(universe.values()),
           'training':model_metadata or prior.get('training'),
           'lastRun':{'phase':control['phase'],'date':control['today'],'sourceReportId':control['sourceReportId'],
                      'sourceErrors':len(data.get('errors',[])),'estimated':latest_estimated}}
    write_json(folder/'index.json',index)
    return index


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('Collection and model training run on GitHub-hosted runners')
    control=read_json(Path('work/offday/control.json'))
    if control['phase']=='skip':return
    folder=Path('work/offday/store')
    git=git_store(os.environ['GITHUB_REPOSITORY'],os.environ['GH_TOKEN'],folder)
    prior=read_json(folder/'index.json',{})
    data=read_json(Path('work/offday/dataset.json'),{'companies':[],'errors':[]})
    candidates,metadata=[],None
    activation=prior.get('activationDate',control['activationDate'])
    if control['phase']=='morning' and control['today']>=activation:
        candidates,metadata=generate(data,control)
    index=update_store(folder,control,data,candidates,metadata,datetime.now(timezone.utc))
    git('add','index.json','stocks','sessions') if (folder/'stocks').exists() else git('add','index.json')
    git('commit','-m','Save off-day forecasts and completed actuals for '+control['today'])
    git('push','origin','HEAD:refs/heads/'+DATA_BRANCH)
    print(json.dumps({'sessions':len(index['sessions']),'stocks':len(index['stocks']),'phase':control['phase'],
                      'activationDate':index['activationDate'],'estimates':sum(r['state']=='estimated' for r in candidates)}))


if __name__=='__main__':main()
