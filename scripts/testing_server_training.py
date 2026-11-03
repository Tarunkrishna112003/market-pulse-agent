"""GitHub-hosted continual experiment. Permanent bars and models are append-only assets.

SQLite below is a disposable runner-side index; it is never created on the user's
laptop by the CLI. The live-site model and its artifacts are not modified.
"""
import csv
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from collections import Counter

BASE_TAG = 'testing-stock-history-v1'
INDEX_TAG = 'testing-stock-model-index-v1'
VERSION = 'testing-server-continual-v1'
CONTEXT = ['^GSPC', '^VIX', 'XLK', 'XLV', 'XLF', 'XLY', 'XLP', 'XLI', 'XLE', 'XLB', 'XLRE', 'XLU', 'XLC']
SECTORS = {'Technology':'XLK','Information Technology':'XLK','Healthcare':'XLV','Health Care':'XLV',
 'Financials':'XLF','Financial Services':'XLF','Finance':'XLF','Consumer Cyclical':'XLY','Consumer Discretionary':'XLY',
 'Consumer Defensive':'XLP','Consumer Staples':'XLP','Industrials':'XLI','Energy':'XLE','Basic Materials':'XLB',
 'Materials':'XLB','Real Estate':'XLRE','Utilities':'XLU','Communication Services':'XLC','Telecommunications':'XLC'}


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def require_runner():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Real archive/model operations run only on GitHub-hosted runners; no laptop history download')
    if os.environ.get('GITHUB_REF_NAME') != 'testing-server':
        raise RuntimeError('Continual training is restricted to testing-server')


def merge_registry(previous, values):
    result = dict(previous or {})
    for value in sorted(set(values)):
        if value not in result:
            result[value] = max(result.values(), default=-1) + 1
    return result


def feature_code_hash():
    return hashlib.sha256(Path(__file__).with_name('stock_specific.py').read_bytes()).hexdigest()


def init_stage(connection):
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('''CREATE TABLE IF NOT EXISTS bars (
      symbol TEXT NOT NULL, day TEXT NOT NULL, opening REAL NOT NULL, high REAL NOT NULL,
      low REAL NOT NULL, close REAL NOT NULL, volume REAL, split INTEGER NOT NULL,
      observed_at TEXT NOT NULL, PRIMARY KEY(symbol,day)) WITHOUT ROWID''')


def ingest_csv(connection, stream):
    """Build a latest-revision training view while retaining all originals on GitHub."""
    rows = []
    for row in csv.DictReader(stream):
        if row['interval'] != '1d':
            continue
        prices = [float(row[k]) for k in ('open', 'high', 'low', 'close')]
        if not all(math.isfinite(p) and p > 0 for p in prices):
            raise ValueError('Nonfinite archived prices')
        opening, high, low, close = prices
        if low > min(opening, close) + 1e-5 or high < max(opening, close) - 1e-5:
            raise ValueError('Invalid archived OHLC ordering')
        actions = json.loads(row.get('corporate_actions') or '[]')
        rows.append((row['symbol'], row['session_date'], opening, high, low, close,
                     float(row['volume']) if row.get('volume') else None,
                     int(any(a.get('kind') == 'splits' for a in actions)), row['observed_at']))
        if len(rows) >= 10000:
            _write_rows(connection, rows)
            rows = []
    _write_rows(connection, rows)


def _write_rows(connection, rows):
    connection.executemany('''INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(symbol,day) DO UPDATE SET opening=excluded.opening,high=excluded.high,
      low=excluded.low,close=excluded.close,volume=excluded.volume,split=excluded.split,
      observed_at=excluded.observed_at WHERE excluded.observed_at >= bars.observed_at''', rows)
    connection.commit()


def read_bars(connection, symbol, calendar):
    rows = connection.execute('SELECT day,opening,high,low,close,volume,split FROM bars WHERE symbol=? ORDER BY day', (symbol,))
    return [dict(date=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5],
                 nextSession=calendar.get(r[0]), **({'corporateAction':'provider-reported-split', 'labelEligible':False} if r[6] else {})) for r in rows]


def choose_training_indices(indices, budget=128):
    """Bounded replay spans all available years and includes the latest observations."""
    if len(indices) <= budget:
        return list(indices)
    recent = min(32, budget // 2)
    count = budget - recent
    old = indices[:-recent]
    chosen = [old[round(i * (len(old)-1) / max(1, count-1))] for i in range(count)]
    return sorted(set(chosen + indices[-recent:]))


def validation_dates(market_dates, last_evaluated=None):
    dates = sorted(set(market_dates))
    return [d for d in dates if d > last_evaluated][-120:] if last_evaluated else dates[-20:]


def score(actual, predicted):
    import numpy as np
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    if not len(actual) or not np.isfinite(predicted).all():
        raise ValueError('No finite validation predictions')
    return {'samples':len(actual), 'maePoints':float(np.mean(abs(actual-predicted))),
            'msePointsSquared':float(np.mean((actual-predicted)**2)),
            'directionAccuracy':float(np.mean(np.sign(actual) == np.sign(predicted)))}


def promotion_allowed(candidate, parent):
    return parent is None or (candidate['maePoints'] < parent['maePoints'] and
                              candidate['directionAccuracy'] >= parent['directionAccuracy'])


def train_candidate(train, validation, names, parent_path=None, rounds=None):
    import numpy as np
    import lightgbm as lgb
    from stock_specific import JointReturnObjective
    if not train or not validation:
        raise ValueError('Training and temporal validation samples are required')
    start = min(r['targetDate'] for r in validation)
    if any(r['targetDate'] >= start or r['lastInputDate'] >= r['targetDate'] for r in train):
        raise ValueError('Training/validation overlap or future inputs')
    if any(r['lastInputDate'] >= r['targetDate'] for r in validation):
        raise ValueError('Validation includes future inputs')
    counts = Counter(r['targetDate'] for r in train)
    today = datetime.fromisoformat(start)
    weights = np.array([2**(-min(3650, (today-datetime.fromisoformat(r['targetDate'])).days)/180)/counts[r['targetDate']] for r in train])
    weights /= weights.mean()
    x = np.asarray([r['x'] for r in train], dtype=np.float32)
    y = np.asarray([r['actualPercent']/r['scale'] for r in train], dtype=np.float32)
    objective = JointReturnObjective(.1)
    def loss(predicted, dataset):
        return objective(dataset.get_label(), predicted, dataset.get_weight())
    params = dict(objective=loss, metric='None', learning_rate=.035, num_leaves=15,
                  max_depth=5, min_data_in_leaf=100, lambda_l2=20., max_bin=63,
                  num_threads=2, seed=42, deterministic=True, force_col_wise=True, verbosity=-1)
    categorical = [n for n in ('symbol_id','sector_id') if n in names]
    dataset = lgb.Dataset(x, label=y, weight=weights, feature_name=names, categorical_feature=categorical)
    parent = lgb.Booster(model_file=str(parent_path)) if parent_path else None
    if parent and parent.feature_name() != names:
        raise ValueError('Checkpoint feature schema changed; refusing to reset or reorder weights')
    model = lgb.train(params, dataset, num_boost_round=rounds or (10 if parent else 150), init_model=parent)
    vx = np.asarray([r['x'] for r in validation], dtype=np.float32)
    scales = np.asarray([r['scale'] for r in validation])
    actual = [r['actualPercent'] for r in validation]
    metrics = score(actual, model.predict(vx)*scales)
    parent_metrics = score(actual, parent.predict(vx)*scales) if parent else None
    return model, {'candidate':metrics, 'parent':parent_metrics,
                   'accept':promotion_allowed(metrics, parent_metrics),
                   'trainRows':len(train), 'validationStart':start,
                   'validationEnd':max(r['targetDate'] for r in validation),
                   'trainingTargetEnd':max(r['targetDate'] for r in train),
                   'continuedFromCheckpoint':parent is not None,
                   'parentTrees':parent.num_trees() if parent else 0,'candidateTrees':model.num_trees()}


def github_command(args, attempts=4):
    for attempt in range(attempts):
        result = subprocess.run(['gh', *args],capture_output=True,text=True)
        if result.returncode == 0:
            return result.stdout
        error = subprocess.CalledProcessError(result.returncode,['gh', *args],result.stdout,result.stderr)
        transient = re.search(r'HTTP 5\d\d|HTTP 429|timed? ?out|connection reset|unexpected EOF|TLS handshake',result.stderr,re.I)
        if not transient or attempt == attempts-1:
            raise error
        time.sleep(2*2**attempt)


def recover_model_pointer(archive):
    """Recover a lost mutable pointer from immutable accepted evaluation manifests."""
    for tag in sorted((t for t in archive.release_tags() if re.fullmatch(r'testing-stock-models-\d{6}',t)),reverse=True):
        evaluations=sorted((a['name'] for a in archive.assets(tag) if a['name'].startswith('evaluation-') and a['name'].endswith('.json')),reverse=True)
        for name in evaluations:
            metadata=archive.json(tag,name)
            if metadata.get('metrics',{}).get('accept'):
                path=archive.download(metadata['release'],metadata['modelAsset'])
                if hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['modelSha256']:
                    raise RuntimeError('Recovery model checksum mismatch; refusing a reset')
                archive.upload(INDEX_TAG,'checkpoint.json',json.dumps(metadata).encode(),mutable=True)
                print('Recovered the existing model pointer from its immutable accepted version.',flush=True)
                return metadata
    return {}


class GitHubArchive:
    def __init__(self, root):
        require_runner()
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = os.environ['GITHUB_REPOSITORY']
        self.cached_assets = {}

    def gh(self, *args):
        return github_command([*args,'--repo',self.repo])

    def assets(self, tag, refresh=False):
        if tag not in self.cached_assets or refresh:
            self.cached_assets[tag] = json.loads(self.gh('release','view',tag,'--json','assets'))['assets']
        return self.cached_assets[tag]

    def has_release(self, tag):
        try:
            self.gh('release','view',tag)
            return True
        except subprocess.CalledProcessError as error:
            if re.search(r'not found|404',error.stderr,re.I):return False
            raise

    def ensure_release(self, tag):
        if not self.has_release(tag):
            self.gh('release','create',tag,'--target','testing-server','--prerelease','--title',tag,'--notes',
                    'Testing-server continual-learning experiment. Versioned model weights/forecasts; no production deployment. Only pointer metadata is mutable.')

    def download(self, tag, name):
        if not re.fullmatch(r'[\w.\-]+', name):
            raise ValueError('Unsafe archive filename')
        folder = self.root / tag
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        self.gh('release','download',tag,'--pattern',name,'--dir',str(folder),'--clobber')
        return path

    def json(self, tag, name):
        path = self.download(tag,name)
        return json.loads(gzip.decompress(path.read_bytes()) if name.endswith('.gz') else path.read_text())

    def upload(self, tag, name, content, mutable=False):
        if not mutable and any(a['name'] == name for a in self.assets(tag, refresh=True)):
            if self.download(tag,name).read_bytes()==content:return
            raise RuntimeError('Refusing to overwrite an immutable archive/model asset')
        path = self.root / name
        path.write_bytes(content)
        try:
            self.gh('release','upload',tag,str(path),*(['--clobber'] if mutable else []))
        except subprocess.CalledProcessError:
            if not mutable and any(a['name']==name for a in self.assets(tag,refresh=True)) and self.download(tag,name).read_bytes()==content:return
            raise
        self.cached_assets.pop(tag, None)

    def release_tags(self):
        return github_command(['api','--paginate',f'repos/{self.repo}/releases','--jq','.[].tag_name']).splitlines()

    def update_tags(self):
        return sorted(t for t in self.release_tags() if re.fullmatch(r'testing-stock-updates-\d{4}-\d{2}-\d{2}', t))

    def stage(self, connection):
        manifests = 0
        for tag in [BASE_TAG] + self.update_tags():
            assets = self.assets(tag)
            by_name = {a['name']:a for a in assets}
            for name in sorted(n for n in by_name if n.endswith('.manifest.json')):
                manifest = self.json(tag,name)
                if manifest.get('schemaVersion') != 1:
                    raise ValueError('Unsupported archive schema')
                if not any(any(i['interval'] == '1d' for i in r.get('intervals', [])) for r in manifest['results']):
                    continue
                if manifest['asset'] not in by_name:
                    raise ValueError('Manifest has no committed data asset')
                path = self.download(tag,manifest['asset'])
                digest = hashlib.sha256()
                with path.open('rb') as source:
                    for block in iter(lambda:source.read(1024*1024), b''):
                        digest.update(block)
                if digest.hexdigest() != manifest['sha256']:
                    raise ValueError('Archive checksum mismatch')
                with gzip.open(path,'rt',newline='') as source:
                    ingest_csv(connection,source)
                path.unlink()  # Only the runner's disposable staging copy is removed.
                manifests += 1
                if manifests % 10 == 0:
                    print(f'Indexed {manifests} daily archive chunks', flush=True)
        return manifests


def _attach_company(builder, company, bars):
    import numpy as np
    from stock_specific import good_bar
    symbol = company['symbol']
    builder.companies[symbol] = company
    builder.series[symbol] = company
    builder.bars[symbol] = bars
    builder.dates[symbol] = [b['date'] for b in bars]
    builder.invalid_prefix[symbol] = np.r_[0,np.cumsum([not good_bar(b) or bool(b.get('corporateAction')) for b in bars])]
    builder.values[symbol] = [np.array([b.get(k, np.nan) for b in bars], dtype=float) for k in ('open','close','high','low','volume')]


def build_examples(connection, universe, metadata, last_evaluated=None, per_stock=128):
    from stock_specific import DailyStockFeatures, good_bar
    market_dates = [r[0] for r in connection.execute("SELECT day FROM bars WHERE symbol='^GSPC' ORDER BY day")]
    if len(market_dates) < 90:
        raise ValueError('Complete market context has not been archived yet')
    future = subprocess.check_output(['node','--input-type=module','-e',
        "import {nextTradingDay} from './lib/trading-calendar.mjs';console.log(nextTradingDay(process.argv[1]))", market_dates[-1]], text=True).strip()
    calendar = dict(zip(market_dates, market_dates[1:] + [future]))
    valid_dates = validation_dates(market_dates,last_evaluated)
    if not valid_dates:
        raise ValueError('No new validation dates')
    before = valid_dates[0]
    context = {symbol:{'daily':read_bars(connection,symbol,calendar)} for symbol in CONTEXT}
    if not context['^VIX']['daily']:
        raise ValueError('VIX context has not been archived')
    builder = DailyStockFeatures({'companies':[], 'context':context})
    symbols = merge_registry(metadata.get('symbolIds'),[s['symbol'] for s in universe['stocks']])
    sectors = merge_registry(metadata.get('sectorIds'),[s.get('sector') or 'Unknown' for s in universe['stocks']])
    builder.symbol_ids, builder.sector_ids = symbols, sectors
    train, validation, inference, errors, coverage = [], [], [], [], {}
    for i, company in enumerate(universe['stocks']):
        symbol = company['symbol']
        bars = read_bars(connection,symbol,calendar)
        if len(bars) < 62:
            errors.append({'symbol':symbol,'reason':'Fewer than 62 completed sessions'})
            continue
        company = {**company,'sector':company.get('sector') or 'Unknown', 'sectorETF':SECTORS.get(company.get('sector'))}
        _attach_company(builder,company,bars)
        training_indices = [j for j in range(61,len(bars)) if bars[j]['date'] < before]
        indices = choose_training_indices(training_indices,per_stock)
        indices += [j for j in range(61,len(bars)) if bars[j]['date'] in valid_dates]
        made = 0
        for j in indices:
            bar = bars[j]
            if not good_bar(bar) or bar.get('corporateAction'):
                continue
            try:
                row = builder.features(symbol,bar['date'])
                row['actualPercent'] = (bar['close']/bar['open']-1)*100
                (train if bar['date'] < before else validation).append(row)
                made += 1
            except (ValueError,KeyError,TypeError):
                pass
        coverage[symbol] = made
        try:
            if company.get('active') is not False:
                inference.append(builder.features(symbol,future))
        except (ValueError,KeyError,TypeError) as error:
            errors.append({'symbol':symbol,'reason':str(error)})
        for dictionary in (builder.companies,builder.series,builder.bars,builder.dates,builder.invalid_prefix,builder.values):
            dictionary.pop(symbol,None)
        if i % 100 == 0:
            print(f'Built historical examples for {i+1}/{len(universe["stocks"])} listings', flush=True)
    return train,validation,inference,{'featureNames':builder.names,'symbolIds':symbols,'sectorIds':sectors,
        'forecastTarget':future,'rowsBySymbol':coverage,'unavailable':errors,'replayRowsPerStock':per_stock}


def main():
    require_runner()
    import numpy as np
    archive = GitHubArchive('work/testing-training')
    names = {a['name'] for a in archive.assets(BASE_TAG)}
    universe = archive.json(BASE_TAG,'universe-current.json.gz' if 'universe-current.json.gz' in names else 'universe.json.gz')
    checkpoints = [archive.json(BASE_TAG,f'checkpoint-{i}.json') for i in range(8)]
    eligible = [s for c in checkpoints for s in c['symbols'].values() if s.get('status') == 'backfilled' and s['symbol'] not in CONTEXT]
    latest = max(s['1d']['lastDate'] for s in eligible)
    current = sum(s['1d']['lastDate'] == latest for s in eligible)
    if len(eligible) < len(universe['stocks'])*.9 or current < len(eligible)*.9:
        raise RuntimeError('Less than 90% of archived equities have the latest completed daily label; waiting for data')
    archive.ensure_release(INDEX_TAG)
    index_names = {a['name'] for a in archive.assets(INDEX_TAG)}
    parent_meta = archive.json(INDEX_TAG,'checkpoint.json') if 'checkpoint.json' in index_names else recover_model_pointer(archive)
    last_attempt = archive.json(INDEX_TAG,'last-evaluation.json') if 'last-evaluation.json' in index_names else {}
    last = max(parent_meta.get('lastEvaluatedDate',''),last_attempt.get('lastEvaluatedDate','')) or None
    if last and latest <= last:
        print('No new completed daily labels. Saved model is unchanged; no history download or fitting.', flush=True)
        return
    if parent_meta and (parent_meta.get('modelVersion') != VERSION or parent_meta.get('featureCodeSha256') != feature_code_hash()):
        raise RuntimeError('Model/feature version changed; refusing an implicit reset of the checkpoint')
    parent_path = None
    if parent_meta:
        parent_path = archive.download(parent_meta['release'],parent_meta['modelAsset'])
        if hashlib.sha256(parent_path.read_bytes()).hexdigest() != parent_meta['modelSha256']:
            raise RuntimeError('Persisted model checksum mismatch')
    connection = sqlite3.connect(archive.root/'training-view.sqlite')
    init_stage(connection)
    count = archive.stage(connection)
    train, validation, inference, metadata = build_examples(connection,universe,parent_meta,last)
    if len(train) < 10000 or len(validation) < 1000:
        raise RuntimeError('Too few clean examples for full-universe continual training; keeping the saved checkpoint')
    print(f'Training from {len(train)} replay examples across archived years; validating {len(validation)} fresh outcomes.', flush=True)
    model, metrics = train_candidate(train,validation,metadata['featureNames'],parent_path)
    run = os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    tag = 'testing-stock-models-'+stamp[:6]
    archive.ensure_release(tag)
    stem = stamp+'-'+run
    model_name = 'model-'+stem+'.txt'
    model_path = archive.root/model_name
    model.save_model(str(model_path))
    artifact = model_path.read_bytes()
    metadata.update(modelVersion=VERSION,featureCodeSha256=feature_code_hash(),release=tag,modelAsset=model_name,
        modelSha256=hashlib.sha256(artifact).hexdigest(),createdAt=utcnow(),lastEvaluatedDate=latest,
        metrics=metrics,archivedDailyChunks=count,sourceCommit=os.environ['GITHUB_SHA'],experimental=True,
        parentModel=parent_meta.get('modelAsset'),stockCoverage=len(eligible),universeListings=len(universe['stocks']))
    await_bytes = json.dumps(metadata,allow_nan=False,indent=2).encode()
    archive.upload(tag,model_name,artifact)
    archive.upload(tag,'evaluation-'+stem+'.json',await_bytes)
    # Forecasts remain in the testing archive; they are not published to production.
    import lightgbm as lgb
    active = model if metrics['accept'] else lgb.Booster(model_file=str(parent_path))
    forecasts = []
    values = active.predict(np.asarray([r['x'] for r in inference],dtype=np.float32),num_threads=2) if inference else []
    for row, normalized in zip(inference,values):
        value = float(normalized*row['scale'])
        if math.isfinite(value) and value > -100:
            forecasts.append({'symbol':row['symbol'],'targetDate':metadata['forecastTarget'],'estimatedPercent':value,
                'returnBasis':'open-to-close','lastInputDate':row['lastInputDate'],'generatedAt':metadata['createdAt'],
                'modelVersion':VERSION,'modelAsset':model_name if metrics['accept'] else parent_meta['modelAsset'],'experimental':True})
    archive.upload(tag,'forecasts-'+stem+'.json.gz',gzip.compress(json.dumps({'records':forecasts}).encode(),mtime=0))
    if metrics['accept']:
        archive.upload(INDEX_TAG,'checkpoint.json',await_bytes,mutable=True)
    archive.upload(INDEX_TAG,'last-evaluation.json',json.dumps({'lastEvaluatedDate':latest,'release':tag,
        'evaluationAsset':'evaluation-'+stem+'.json','accepted':metrics['accept'],'createdAt':utcnow()}).encode(),mutable=True)
    print(json.dumps({'metrics':metrics,'accepted':metrics['accept'],'forecasts':len(forecasts),'modelRelease':tag}), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('## Testing-server continual model\n\n'+json.dumps(metrics,indent=2)+'\n\nNo production deployment.\n')


if __name__ == '__main__':
    main()
