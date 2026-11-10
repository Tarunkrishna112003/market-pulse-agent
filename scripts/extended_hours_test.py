import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
from extended_hours import cutoff_at, extended_features, ExtendedStockFeatures
import stock_specific_test


class ExtendedHoursTests(unittest.TestCase):
    def bar(self, when, close=105, volume=100):
        stamp=datetime.fromisoformat(when).replace(tzinfo=ZoneInfo('America/New_York'))
        return dict(timestamp=stamp.timestamp(),open=100,high=max(106,close),low=99,
                    close=close,volume=volume,durationSeconds=3600)

    def data(self):
        prior=dict(date='2026-11-06',close=100,volume=1000,closeMinute=960)
        company=dict(daily=[prior],hourly=[self.bar('2026-11-06T16:00'),self.bar('2026-11-09T07:00')])
        return company,prior

    def test_cutoff_dst(self):
        self.assertEqual(cutoff_at('2026-10-30').utcoffset().total_seconds(),-7*3600)
        self.assertEqual(cutoff_at('2026-11-09').utcoffset().total_seconds(),-8*3600)
        self.assertEqual(cutoff_at('2026-11-09').astimezone(ZoneInfo('America/New_York')).hour,8)

    def test_target_post_cutoff_and_crossing_buckets_do_not_change_features(self):
        company,prior=self.data()
        expected=extended_features(company,prior,'2026-11-09',1)
        company['hourly'] += [self.bar('2026-11-09T07:30',9999),self.bar('2026-11-09T08:00',8888),
                              self.bar('2026-11-09T16:00',7777),self.bar('2026-11-06T15:00',6666)]
        company['daily'].append(dict(date='2026-11-09',close=999999,volume=999999999))
        self.assertEqual(expected,extended_features(company,prior,'2026-11-09',1))
        self.assertEqual(expected['pre_bars'],1)
        self.assertAlmostEqual(expected['pre_gap'],100*np.log(1.05))
        self.assertEqual(expected['pre_volume_ratio'],.1)

    def test_early_close_and_missing_activity(self):
        company,prior=self.data();prior['closeMinute']=780
        company['hourly']=[self.bar('2026-11-06T13:00'),self.bar('2026-11-09T07:00',volume=0)]
        result=extended_features(company,prior,'2026-11-09',1)
        self.assertEqual(result['post_bars'],1);self.assertEqual(result['pre_missing'],0)
        self.assertEqual(result['pre_volume_missing'],1)
        self.assertEqual(result['pre_vwap_missing'],1)
        self.assertGreater(result['pre_gap'],0)

    def test_builder_keeps_categorical_ids_last_and_daily_future_isolation(self):
        dataset=stock_specific_test.StockSpecificTests().dataset()
        target=dataset['companies'][0]['daily'][-2]['date']
        first=ExtendedStockFeatures(dataset);row=first.features('A',target)
        self.assertEqual(first.names[-2:],['symbol_id','sector_id'])
        self.assertEqual(len(first.names),len(row['x']))
        changed=deepcopy(dataset)
        for company in changed['companies']:
            for bar in company['daily']:
                if bar['date']>=target:bar.update(open=1,close=1000000,high=9999999,low=.1)
        np.testing.assert_array_equal(row['x'],ExtendedStockFeatures(changed).features('A',target)['x'])
        first.features('B',target)  # Repeated calls preserve the schema.


if __name__=='__main__':unittest.main()
