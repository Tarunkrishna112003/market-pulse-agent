import importlib.util
import pathlib
import unittest
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
spec=importlib.util.spec_from_file_location('prediction_ml',pathlib.Path(__file__).with_name('ml-prediction.py'))
ml=importlib.util.module_from_spec(spec);spec.loader.exec_module(ml)
class ForecastDataTests(unittest.TestCase):
    def company(self):
        days=[];close=100;d=datetime(2026,1,2)
        while len(days)<100:
            if d.weekday()<5:
                close*=1.005
                days.append({'date':d.date().isoformat(),'close':close,'low':close*.99,'high':close*1.01,'volume':100000,'closeMinute':960})
            d+=timedelta(days=1)
        bars=[{'date':x['date'],'timestamp':datetime.fromisoformat(x['date']).replace(tzinfo=ZoneInfo('America/New_York'),hour=10,minute=30).timestamp(),'close':x['close']*.995} for x in days]
        return {'symbol':'TEST','daily':days,'hourly':bars,'newsTimeline':[]}
    def test_future_prices_and_news_do_not_change_features(self):
        c=self.company();date=c['daily'][40]['date'];price=c['daily'][39]['close'];base=ml.feature_vector(c,date,price,630,20,[])
        c['daily'][40]['close']=99999;c['newsTimeline']=[{'date':date,'tone':100},{'date':'2099-01-01','tone':100}]
        self.assertEqual(base,ml.feature_vector(c,date,price,630,20,[]))
        c['newsTimeline'].append({'date':c['daily'][39]['date'],'tone':-5})
        self.assertEqual(ml.feature_vector(c,date,price,630,20,[])[-3],-5)
    def test_next_session_and_preopen_training_labels(self):
        c=self.company();rows=ml.build_rows(c,10,[],datetime(2027,1,1,tzinfo=timezone.utc));self.assertTrue(any(r['date']==r['targetDate'] for r in rows));self.assertTrue(any(r['date']<r['targetDate'] for r in rows))
        sample=next(r for r in rows if r['date']<r['targetDate']);future=next(d for d in c['daily'] if d['date']==sample['targetDate']);self.assertGreater(future['close'],0)
        early=ml.build_rows(c,10,[],datetime(2026,1,15,tzinfo=timezone.utc));self.assertTrue(all(r['targetDate']<'2026-01-15' for r in early))
    def test_chronological_partitions_are_purged(self):
        c=self.company();rows=[]
        for i,d in enumerate(c['daily'][:-1]):
            rows.extend({'date':d['date'],'targetDate':c['daily'][i+1]['date'],'x':[0]*len(ml.FEATURES),'y':0} for _ in range(10))
        train,cal,test,_=ml.time_partitions(rows)
        self.assertLess(max(r['targetDate'] for r in train),min(r['date'] for r in cal))
        self.assertLess(max(r['targetDate'] for r in cal),min(r['date'] for r in test))
        self.assertEqual(len({r['date'] for r in test}),10)
    def test_supervised_model_learns_signal_and_records_unseen_test(self):
        import random
        rnd=random.Random(42);c=self.company();rows=[]
        for i,day in enumerate(c['daily'][:-1]):
            for _ in range(10):
                x=[0.0]*len(ml.FEATURES);x[8]=rnd.uniform(-1,1);x[-3]=rnd.choice([-1,1]);x[-2]=x[-3];x[-1]=1
                y=0.01*x[8]+0.005*x[-3]+rnd.uniform(-0.0002,0.0002)
                rows.append({'symbol':'TEST','date':day['date'],'targetDate':c['daily'][i+1]['date'],'x':x,'y':y})
        context={'x':[0.0]*len(ml.FEATURES),'basePrice':100,'baseDate':'2026-06-01','quoteAsOf':'2026-06-01T20:00:00Z','targetDate':'2026-06-02','generatedAt':'2026-06-01T21:00:00Z','sessions':20}
        context['x'][8]=0.5;context['x'][-3]=1;context['x'][-2]=1;context['x'][-1]=1
        predictions,metric=ml.fit_window(rows,{'TEST':context},20)
        self.assertEqual(predictions['TEST']['forecastModel'],'supervised')
        self.assertEqual(metric['features'],'prices_and_news')
        self.assertLess(metric['meanAbsoluteError'],metric['naiveMeanAbsoluteError'])
        self.assertGreater(predictions['TEST']['estimatedPercent'],0)
        self.assertTrue(any(r['model']=='neural_network' for r in metric['candidates']))
        self.assertEqual(len({r['targetDate'] for r in rows if r['date']>=metric['testStart']}),metric['testTradingDates'])
    def test_insufficient_data_rejected(self):
        with self.assertRaises(ValueError):ml.time_partitions([])
if __name__=='__main__':unittest.main()
