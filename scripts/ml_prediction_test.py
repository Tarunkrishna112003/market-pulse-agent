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
                days.append({'date':d.date().isoformat(),'close':close,'open':close*.995,'low':close*.99,'high':close*1.01,'volume':100000,'closeMinute':960})
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
    def test_target_is_next_session_close_over_open_not_scan_price(self):
        c=self.company();target=c['daily'][50];target['open']=target['close']/0.95
        rows=ml.build_rows(c,17,[],datetime(2027,1,1,tzinfo=timezone.utc))
        matching=[r for r in rows if r['targetDate']==target['date']]
        self.assertTrue(any(r['date']==r['targetDate'] for r in matching))
        self.assertTrue(any(r['date']<r['targetDate'] for r in matching))
        for row in matching:self.assertAlmostEqual(row['y'],ml.math.log(0.95))
        preopen=next(r for r in matching if r['date']==r['targetDate'])
        before=list(preopen['x']);target['open']*=2;target['close']*=3
        revised=ml.build_rows(c,17,[],datetime(2027,1,1,tzinfo=timezone.utc))
        self.assertEqual(before,next(r['x'] for r in revised if r['date']==target['date'] and r['targetDate']==target['date']))
        del target['open']
        self.assertFalse(any(r['targetDate']==target['date'] for r in ml.build_rows(c,17,[],datetime(2027,1,1,tzinfo=timezone.utc))))

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
        context['lookback']=17;context['x'][8]=0.5;context['x'][-3]=1;context['x'][-2]=1;context['x'][-1]=1
        predictions,metric=ml.fit_window(rows,{'TEST':context},20)
        self.assertEqual(predictions['TEST']['forecastModel'],'supervised');self.assertEqual(predictions['TEST']['lookback'],17)
        self.assertEqual(metric['features'],'prices_and_news')
        self.assertLess(metric['meanAbsoluteError'],metric['naiveMeanAbsoluteError'])
        self.assertGreater(predictions['TEST']['estimatedPercent'],0)
        self.assertEqual(predictions['TEST']['returnBasis'],'open-to-close')
        self.assertNotIn('projectedClose',predictions['TEST'])
        self.assertNotIn('estimatedDollar',predictions['TEST'])
        for name in ['neural_network','random_forest','lstm','mathematical_formula','rf_lstm_math_ensemble']:
            self.assertTrue(any(r['model']==name and 'cvMAE' in r for r in metric['candidates']),name)
        self.assertEqual(len({r['targetDate'] for r in rows if r['date']>=metric['testStart']}),metric['testTradingDates'])
    def test_lstm_uses_ordered_sequence_and_artifact_roundtrip(self):
        import numpy as np
        import joblib
        import tempfile
        from forecast_models import LSTMRegressor,MathematicalForecast,SEQUENCE_START
        rng=np.random.default_rng(42);x=rng.normal(size=(256,len(ml.FEATURES)))
        y=0.01*(x[:,SEQUENCE_START+4]-x[:,SEQUENCE_START])
        model=LSTMRegressor(epochs=25).fit(x,y)
        self.assertLess(np.mean(np.abs(model.predict(x)-y)),np.mean(np.abs(y)))
        swapped=x.copy();swapped[:,SEQUENCE_START:SEQUENCE_START+5]=x[:,SEQUENCE_START:SEQUENCE_START+5][:,::-1]
        self.assertFalse(np.allclose(model.predict(x),model.predict(swapped)))
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'model.joblib';joblib.dump(model,path)
            np.testing.assert_allclose(model.predict(x),joblib.load(path).predict(x))
        formula=MathematicalForecast().fit(x,y);equation=formula.equation(ml.FEATURES)
        calculated=equation['intercept']+sum(x[:,i]*equation['coefficients'][name] for i,name in enumerate(ml.FEATURES))
        np.testing.assert_allclose(calculated,formula.predict(x),atol=1e-10)

    def test_exact_calendar_period_changes_model_features(self):
        c=self.company();date=c['daily'][90]['date'];price=c['daily'][89]['close']
        seventeen=ml.feature_vector(c,date,price,630,17,[])
        thirty=ml.feature_vector(c,date,price,630,30,[])
        self.assertEqual(seventeen[ml.FEATURES.index('calendar_days')],17)
        self.assertEqual(thirty[ml.FEATURES.index('calendar_days')],30)
        self.assertNotEqual(seventeen[ml.FEATURES.index('momentum')],thirty[ml.FEATURES.index('momentum')])
        self.assertIsNone(ml.feature_vector(c,date,price,630,1,[]))

    def test_year_of_periods_is_written_separately_for_full_universe(self):
        import json
        import tempfile
        import io
        import contextlib
        import numpy as np
        from unittest.mock import patch
        class ConstantModel:
            def predict(self,x):return np.full(len(x),0.01)
        metric={'features':'prices','validationPassed':False,'trainingRows':1000,'model':'fixture'}
        bundle={'model':ConstantModel(),'metrics':metric,'calibrationResidualQuantiles':[-0.02,0.02]}
        training=self.company();training['name']='Training Company'
        extra=self.company();extra.update(symbol='EXTRA',name='Other scanned company',inferenceOnly=True)
        for company in [training,extra]:company['forecastContext']={'state':'ready','basePrice':100,'baseDate':company['daily'][-2]['date'],'quoteAsOf':'2026-05-21T20:00:00Z','targetDate':'2026-05-22','inferenceDate':company['daily'][-1]['date'],'inferenceMinute':960}
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);dataset=root/'data.json';news=root/'news.json';output=root/'prediction-trained.json'
            dataset.write_text(json.dumps({'reportId':'year','generatedAt':'2027-01-01T00:00:00Z','availableLookback':365,'companies':[training,extra],'universe':[{'symbol':'TEST'},{'symbol':'EXTRA'},{'symbol':'MISSING'}],'market':[],'errors':[]}))
            news.write_text(json.dumps({'companies':[]}))
            with patch.object(ml.sys,'argv',['ml',str(dataset),str(news),str(output)]),patch.object(ml,'fit_window',return_value=({},metric)),patch('joblib.load',return_value=bundle),contextlib.redirect_stdout(io.StringIO()):ml.main()
            result=json.loads(output.read_text());self.assertEqual(len(result['supportedLookbacks']),365)
            self.assertEqual([r['symbol'] for r in result['rows']],['TEST'])
            self.assertEqual(len(result['rows'][0]['forecasts']),365)
            seventeen=json.loads((root/'predictions/17.json').read_text())
            self.assertEqual(len(seventeen['rows']),3)
            extra_forecast=next(r for r in seventeen['rows'] if r['symbol']=='EXTRA')
            self.assertEqual(extra_forecast['returnBasis'],'open-to-close')
            self.assertAlmostEqual(extra_forecast['estimatedPercent'],100*(ml.math.exp(0.01)-1))
            year=json.loads((root/'predictions/365.json').read_text())
            self.assertEqual(len(year['rows']),3)
            self.assertEqual(next(r for r in year['rows'] if r['symbol']=='MISSING')['state'],'no-signal')

    def test_insufficient_data_rejected(self):
        with self.assertRaises(ValueError):ml.time_partitions([])
if __name__=='__main__':unittest.main()
