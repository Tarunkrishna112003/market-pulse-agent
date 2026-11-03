"""Dated public CRDO financial and analyst features; no current-score backfill."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import io
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import numpy as np
import pandas as pd

NY=ZoneInfo('America/New_York')
SEC_URL='https://data.sec.gov/api/xbrl/companyfacts/CIK0001807794.json'
TIP_FORECAST='https://www.tipranks.com/stocks/crdo/forecast'
TIP_PRICES='https://www.tipranks.com/stocks/crdo/historical-prices'
TAGS={
 'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],
 'net_income':['NetIncomeLoss','ProfitLoss'], 'gross_profit':['GrossProfit'],
 'operating_income':['OperatingIncomeLoss'], 'eps':['EarningsPerShareDiluted'],
 'cash':['CashAndCashEquivalentsAtCarryingValue'], 'assets':['Assets'],
 'liabilities':['Liabilities'], 'shares':['EntityCommonStockSharesOutstanding'],
 'rd':['ResearchAndDevelopmentExpense'], 'stock_comp':['ShareBasedCompensation'],
 'operating_cashflow':['NetCashProvidedByUsedInOperatingActivities'],
 'capex':['PaymentsToAcquirePropertyPlantAndEquipment']}
FLOW={'revenue','net_income','gross_profit','operating_income','rd','stock_comp','operating_cashflow','capex'}


def public_fetch(url,agent):
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':agent,'Accept-Encoding':'identity'}),timeout=45) as response:
                body=response.read()
            return body,dict(url=url,sha256=hashlib.sha256(body).hexdigest(),bytes=len(body))
        except HTTPError as error:
            if error.code not in (429,500,502,503,504) or attempt==2:raise
            time.sleep(2**attempt)


def availability(filed):
    """No publication time supplied: withhold until the next Eastern calendar day."""
    return (datetime.fromisoformat(filed).replace(tzinfo=NY)+timedelta(days=1)).astimezone(timezone.utc)


def sec_records(payload):
    if str(payload.get('cik','')).lstrip('0')!='1807794':raise ValueError('Wrong SEC issuer')
    records=[]
    for metric,tags in TAGS.items():
        expected='shares' if metric=='shares' else 'USD/shares' if metric=='eps' else 'USD'
        for priority,tag in enumerate(tags):
            for namespace in ('us-gaap','dei'):
                concept=payload.get('facts',{}).get(namespace,{}).get(tag,{})
                for row in concept.get('units',{}).get(expected,[]):
                    if row.get('form') not in ('10-Q','10-Q/A','10-K','10-K/A','S-1','S-1/A'):continue
                    value=float(row['val'])
                    if not math.isfinite(value):continue
                    available=availability(row['filed'])
                    if row['end']>available.date().isoformat():raise ValueError('Future fiscal period')
                    records.append(dict(metric=metric,priority=priority,value=value,start=row.get('start'),
                                        end=row['end'],available=available,accession=row['accn']))
    return records


def latest_quarters(known,metric):
    periods={}
    for row in sorted((r for r in known if r['metric']==metric),key=lambda r:(r['available'],-r['priority'])):
        periods[row['start'],row['end']]=row
    result={}
    for row in periods.values():
        if not row['start']:continue
        duration=(pd.Timestamp(row['end'])-pd.Timestamp(row['start'])).days+1
        if 60<=duration<=115:result[row['end']]=row
    if metric in FLOW:
        for row in periods.values():
            if not row['start'] or row['end'] in result:continue
            prior=[r for r in periods.values() if r['start']==row['start'] and
                   60<=(pd.Timestamp(row['end'])-pd.Timestamp(r['end'])).days<=115]
            if prior:
                previous=max(prior,key=lambda r:r['end'])
                result[row['end']]={**row,'value':row['value']-previous['value'],
                                       'available':max(row['available'],previous['available'])}
    return sorted(result.values(),key=lambda r:r['end'])


def sec_features(frame,bars,records):
    rows=[];audit=[]
    for day,_ in frame.index:
        cutoff=day.to_pydatetime().replace(tzinfo=NY,hour=9).astimezone(timezone.utc)
        known=[r for r in records if r['available']<cutoff]
        quarterly={m:latest_quarters(known,m) for m in TAGS}
        revs=quarterly['revenue']; latest=revs[-1] if revs else None
        rev=latest['value'] if latest else None
        values={}
        def divide(a,b):return a/b if a is not None and b is not None and abs(b)>1e-9 else np.nan
        def balance(metric):
            items=[r for r in known if r['metric']==metric and not r['start']]
            return max(items,key=lambda r:(r['end'],r['available'],-r['priority']))['value'] if items else None
        values['log_quarter_revenue']=np.log1p(max(0,rev)) if rev is not None else np.nan
        prev=revs[-2] if len(revs)>1 else None
        valid_prev=prev and 60<=(pd.Timestamp(latest['end'])-pd.Timestamp(prev['end'])).days<=115
        values['revenue_qoq']=divide(rev,prev['value'])-1 if valid_prev else np.nan
        yoy=[r for r in revs[:-1] if 345<=(pd.Timestamp(latest['end'])-pd.Timestamp(r['end'])).days<=385] if latest else []
        values['revenue_yoy']=divide(rev,yoy[-1]['value'])-1 if yoy else np.nan
        for metric in ('gross_profit','operating_income','net_income','rd','stock_comp','operating_cashflow','capex'):
            value=next((r['value'] for r in reversed(quarterly[metric]) if latest and r['end']==latest['end']),None)
            values[metric+'_margin']=divide(value,rev)
        values['eps']=quarterly['eps'][-1]['value'] if quarterly['eps'] else np.nan
        assets,cash,liabilities,shares=(balance(m) for m in ('assets','cash','liabilities','shares'))
        values['cash_to_assets']=divide(cash,assets)
        values['liabilities_to_assets']=divide(liabilities,assets)
        trailing=revs[-4:]
        valid_ttm=len(trailing)==4 and all(60<=(pd.Timestamp(b['end'])-pd.Timestamp(a['end'])).days<=115 for a,b in zip(trailing,trailing[1:]))
        ttm=sum(r['value'] for r in trailing) if valid_ttm else None
        previous_price=float(bars.Close.loc[bars.index<day].iloc[-1])
        values['price_to_sales']=divide(previous_price*shares if shares else None,ttm)
        newest=max((r['available'] for r in known),default=None)
        values['days_since_filing']=(cutoff-newest).total_seconds()/86400 if newest else np.nan
        for name in list(values):values[name+'_missing']=float(not math.isfinite(values[name]))
        rows.append(values)
        audit.append(dict(day=str(day.date()),knownFacts=len(known),
                          latestAvailableAt=newest.isoformat() if newest else None))
    return pd.DataFrame(rows,index=frame.index).add_prefix('sec_'),audit


def public_tables(html):
    from bs4 import BeautifulSoup
    result=[]
    for table in BeautifulSoup(html,'html.parser').find_all('table'):
        rows=[[cell.get_text(' ',strip=True) for cell in row.find_all(['th','td'])]
              for row in table.find_all('tr')]
        rows=[row for row in rows if row]
        if len(rows)>1:
            result.append(pd.DataFrame([row for row in rows[1:] if len(row)==len(rows[0])],columns=rows[0]))
    return result


def parse_tipranks_events(html):
    tables=public_tables(html)
    events=[]
    for table in tables:
        columns={str(c).strip().lower():c for c in table.columns}
        datecol=next((c for label,c in columns.items() if label.startswith('date')),None)
        targetcol=next((c for label,c in columns.items() if label=='price target'),None)
        ratingcol=next((c for label,c in columns.items() if label=='position'),None)
        analystcol=next((c for label,c in columns.items() if label=='analyst profile'),None)
        if any(c is None for c in (datecol,targetcol,ratingcol,analystcol)):continue
        for _,row in table.iterrows():
            try:
                day=pd.to_datetime(str(row[datecol]),format='%m/%d/%y').date().isoformat()
            except ValueError:continue
            text=str(row[targetcol]);numbers=re.findall(r'\$\s*([\d,]+(?:\.\d+)?)',text)
            target=float(numbers[-1].replace(',','')) if numbers else None
            prior=float(numbers[0].replace(',','')) if len(numbers)>1 else None
            rating=str(row[ratingcol]).strip().lower()
            score=1 if 'buy' in rating else -1 if 'sell' in rating else 0 if 'hold' in rating else None
            if score is None:continue
            events.append(dict(day=day,available=availability(day),analyst=str(row[analystcol]),
                               target=target,previousTarget=prior,rating=score))
    unique={(e['day'],e['analyst'],e['target'],e['rating']):e for e in events}
    return sorted(unique.values(),key=lambda e:e['available'])


def tipranks_features(frame,bars,events):
    rows=[]
    for day,_ in frame.index:
        cutoff=day.to_pydatetime().replace(tzinfo=NY,hour=9).astimezone(timezone.utc)
        known=[e for e in events if e['available']<cutoff]
        recent=[e for e in known if (cutoff-e['available']).days<90]
        last={}
        for event in recent:last[event['analyst']]=event
        targets=[e['target'] for e in last.values() if e['target'] is not None]
        price=float(bars.Close.loc[bars.index<day].iloc[-1])
        new=[e for e in known if (cutoff-e['available']).total_seconds()<86400*7]
        revisions=[e['target']/e['previousTarget']-1 for e in new if e['target'] and e['previousTarget']]
        rows.append(dict(observed_analysts=len(last),events_7d=len(new),
                         mean_rating=np.mean([e['rating'] for e in last.values()]) if last else np.nan,
                         mean_target_upside=np.mean(targets)/price-1 if targets else np.nan,
                         target_dispersion=np.std(targets)/price if targets else np.nan,
                         mean_target_revision_7d=np.mean(revisions) if revisions else np.nan,
                         days_since_action=(cutoff-known[-1]['available']).total_seconds()/86400 if known else np.nan,
                         missing=float(not known)))
    return pd.DataFrame(rows,index=frame.index).add_prefix('tipranks_')
