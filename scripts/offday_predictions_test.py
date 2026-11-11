import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from offday_predictions import merge_forecast, score_record, update_store
from extended_hours import extended_features, cutoff_at


class OffdayArchiveTests(unittest.TestCase):
    def test_first_estimate_is_preserved_and_unavailable_can_retry(self):
        first={'state':'estimated','estimatedPercent':1.25,'generatedAt':'first','actualPercent':None}
        later={'state':'estimated','estimatedPercent':-2,'generatedAt':'later'}
        self.assertEqual(merge_forecast(first,later),first)
        self.assertEqual(merge_forecast({'state':'unavailable'},later),later)

    def test_actual_waits_for_close_and_does_not_depend_on_prediction(self):
        record={'targetDate':'2026-11-12','estimatedPercent':1,'state':'estimated'}
        calendar={'2026-11-12':{'closeMinute':960}}
        bar={'open':100,'close':102,'low':99,'high':103}
        self.assertEqual(score_record(record,bar,calendar,datetime(2026,11,12,20,tzinfo=timezone.utc)),record)
        result=score_record(record,bar,calendar,datetime(2026,11,12,21,20,tzinfo=timezone.utc))
        self.assertAlmostEqual(result['actualPercent'],2)
        self.assertAlmostEqual(result['errorPoints'],1)
        self.assertTrue(result['directionCorrect'])
        unavailable=score_record({**record,'state':'unavailable','estimatedPercent':None},bar,calendar,datetime(2026,11,12,21,20,tzinfo=timezone.utc))
        self.assertAlmostEqual(unavailable['actualPercent'],2)
        self.assertNotIn('directionCorrect',unavailable)

    def test_store_retains_each_day_each_stock_and_never_backfills_before_activation(self):
        control={'phase':'morning','today':'2026-11-12','activationDate':'2026-11-12',
                 'universe':[{'symbol':'AAA','name':'First Company','exchange':'NASDAQ'},{'symbol':'BBB','name':'Second Company','exchange':'NYSE'}],
                 'sourceReportId':'synthetic','calendar':{'2026-11-12':{'closeMinute':960},'2026-11-13':{'closeMinute':960}}}
        now=datetime(2026,11,12,14,tzinfo=timezone.utc)
        def candidate(symbol,day,percent):
            return {'symbol':symbol,'targetDate':day,'state':'estimated','estimatedPercent':percent,'actualPercent':None}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            update_store(folder,control,{},[candidate('AAA','2026-11-12',1),candidate('BBB','2026-11-12',-1),candidate('AAA','2026-11-11',99)],{},now)
            control['today']='2026-11-13'
            update_store(folder,control,{},[candidate('AAA','2026-11-12',999),candidate('AAA','2026-11-13',2)],{},now)
            saved=json.loads((folder/'stocks/AAA.json').read_text())
            self.assertEqual([r['targetDate'] for r in saved['records']],['2026-11-13','2026-11-12'])
            self.assertEqual(saved['records'][1]['estimatedPercent'],1)
            self.assertTrue((folder/'stocks/BBB.json').exists())
            self.assertEqual(json.loads((folder/'index.json').read_text())['sessions'],['2026-11-12','2026-11-13'])

    def test_cutoff_blocks_future_and_crossing_hourly_bars(self):
        def bar(when,price):
            return {'timestamp':datetime.fromisoformat(when).timestamp(),'open':price,'close':price,'high':price,'low':price,'volume':0}
        prior={'date':'2026-11-11','close':100,'closeMinute':960,'volume':1000}
        company={'daily':[prior], 'hourly':[bar('2026-11-11T16:00:00-05:00',101),bar('2026-11-12T07:00:00-05:00',102)]}
        expected=extended_features(company,prior,'2026-11-12',1)
        company['hourly'] += [bar('2026-11-12T07:30:00-05:00',999),bar('2026-11-12T08:00:00-05:00',888)]
        self.assertEqual(extended_features(company,prior,'2026-11-12',1),expected)
        self.assertEqual(expected['pre_missing'],0)
        self.assertEqual(expected['pre_volume_missing'],1)
        self.assertEqual(cutoff_at('2026-10-30').utcoffset().total_seconds(),-7*3600)
        self.assertEqual(cutoff_at('2026-11-12').utcoffset().total_seconds(),-8*3600)


if __name__=='__main__':unittest.main()
