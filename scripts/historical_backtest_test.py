import importlib.util
import pathlib
import unittest
from copy import deepcopy
from datetime import datetime,timedelta

spec=importlib.util.spec_from_file_location('historical_backtest',pathlib.Path(__file__).with_name('historical-backtest.py'))
backtest=importlib.util.module_from_spec(spec);spec.loader.exec_module(backtest)


class HistoricalReplayTests(unittest.TestCase):
    def test_training_cutoff_filters_future_labels_and_old_hourly_rows(self):
        rows=[
            {'date':'2026-10-12','targetDate':'2026-10-13'},
            {'date':'2026-10-13','targetDate':'2026-10-13'},
            {'date':'2026-10-12','targetDate':'2026-10-12'},
            {'date':'2025-10-12','targetDate':'2025-10-12'},
            {'date':'2025-10-13','targetDate':'2025-10-13'},
            {'date':'2026-01-02','targetDate':'2026-01-05'},
            {'date':'2026-01-05','targetDate':'2026-01-05'}]
        selected=backtest.training_rows(rows,'2026-10-13')
        self.assertEqual(selected,[rows[2],rows[4],rows[6]])

    def fixture(self):
        daily=[];date=datetime(2025,9,1)
        while date.date().isoformat()<='2026-10-14':
            if date.weekday()<5:
                daily.append({'date':date.date().isoformat(),'open':100,'close':101+len(daily)/10,'low':99,'high':150,'volume':1000})
            date+=timedelta(days=1)
        return {'symbol':'TEST','daily':daily,'hourly':[],'newsTimeline':[]}

    def test_target_and_future_prices_cannot_change_context(self):
        company=self.fixture();market=deepcopy(company['daily'])
        expected=backtest.prediction_context(company,market,'2026-10-13')
        for item in company['daily']+market:
            if item['date']>='2026-10-13':item.update(open=1e9,close=1,high=1e12,volume=1e20)
        company['newsTimeline']=[{'date':'2026-10-12','tone':999}]
        self.assertEqual(expected,backtest.prediction_context(company,market,'2026-10-13'))
        self.assertEqual(expected['lastInputDate'],'2026-10-12')
        self.assertEqual(expected['informationCutoff'],'2026-10-13T13:00:00+00:00')

    def test_comparison_uses_frozen_prediction_and_target_open_close(self):
        companies=[{'symbol':'TEST','daily':[{'date':'2026-10-13','open':200,'close':206}]}]
        frozen=[{'date':'2026-10-13','symbol':'TEST','predictedPercent':2.0,'medianBaselinePercent':0.,'lowerPercent':-1,'upperPercent':4}]
        original=deepcopy(frozen)
        results=backtest.finalize(frozen,companies)
        self.assertEqual(frozen,original)
        self.assertAlmostEqual(results[0]['actualPercent'],3.)
        self.assertAlmostEqual(results[0]['errorPoints'],1.)
        self.assertTrue(results[0]['directionCorrect'])
        self.assertEqual(backtest.summarize(results)['comparisons'],1)

    def test_missing_input_or_label_is_not_fabricated(self):
        company=self.fixture()
        company['daily']=[d for d in company['daily'] if d['date']!='2026-10-12']
        market=self.fixture()['daily']
        self.assertIsNone(backtest.prediction_context(company,market,'2026-10-13'))
        frozen=[{'date':'2026-10-13','symbol':'TEST','predictedPercent':2.}]
        self.assertEqual(backtest.finalize(frozen,[{'symbol':'TEST','daily':[]}])[0]['status'],'actual-unavailable')

    def test_full_replay_and_resume_preserve_frozen_predictions(self):
        import contextlib,io,json,tempfile
        from argparse import Namespace
        from unittest.mock import patch
        import numpy as np
        class ConstantModel:
            def predict(self,x):return np.zeros(len(x))
        selection={'model':'fixture','features':'prices','ensembleWeights':{'ridge_1':1.}}
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);output=root/'results'
            companies=[{**self.fixture(),'symbol':f'S{i}','name':f'Stock {i}'} for i in range(25)]
            (root/'historical-data.json').write_text(json.dumps({'companies':companies,'downloadedAt':'fixture','caveats':[]}))
            (root/'market.json').write_text(json.dumps({'daily':companies[0]['daily']}))
            (root/'cohort.json').write_text(json.dumps({'stocks':[{'symbol':c['symbol'],'name':c['name']} for c in companies]}))
            args=Namespace(input=str(root),output=str(output),start='2026-10-13',end='2026-10-14',training_days=365,retune_every=10)
            with patch.object(backtest,'choose',return_value=(None,selection)),patch.object(backtest,'fit_model',return_value=ConstantModel()),contextlib.redirect_stdout(io.StringIO()):
                first=backtest.run(args)
                frozen=(output/'predictions-2026-10-13.json').read_bytes()
                second=backtest.run(args)
            self.assertEqual(first['summary'],second['summary'])
            self.assertEqual(second['summary']['comparisons'],50)
            self.assertEqual(frozen,(output/'predictions-2026-10-13.json').read_bytes())
            for row in json.loads(frozen):
                self.assertNotIn('actualPercent',row)
                self.assertLess(row['trainingTargetEnd'],row['date'])
                self.assertLess(row['lastInputDate'],row['date'])
            self.assertTrue((output/'results.csv').exists())
            self.assertTrue((output/'report.md').exists())


if __name__=='__main__':unittest.main()
