import unittest
from copy import deepcopy
import numpy as np
import pandas as pd
from personal_crdo_sources import sec_records,sec_features,parse_tipranks_events,tipranks_features


class SourceTimingTests(unittest.TestCase):
    def fixture(self):
        index=pd.MultiIndex.from_arrays([pd.to_datetime(['2026-02-02','2026-02-03','2026-02-12']),['CRDO']*3],names=['datetime','instrument'])
        frame=pd.DataFrame(index=index)
        bars=pd.DataFrame({'Close':100.},index=pd.bdate_range('2025-01-01','2026-02-12'))
        row=dict(val=100,accn='original',filed='2026-02-02',start='2025-10-01',end='2025-12-31',form='10-Q')
        facts={'cik':1807794,'facts':{'us-gaap':{'Revenues':{'units':{'USD':[row]}}}}}
        return frame,bars,facts

    def test_filing_date_is_not_available_at_that_morning_and_amendment_is_not_backfilled(self):
        frame,bars,payload=self.fixture()
        original=sec_records(payload)
        before,audit=sec_features(frame,bars,original)
        self.assertEqual(before.iloc[0]['sec_log_quarter_revenue_missing'],1)
        self.assertAlmostEqual(before.iloc[1]['sec_log_quarter_revenue'],np.log1p(100))
        changed=deepcopy(payload)
        changed['facts']['us-gaap']['Revenues']['units']['USD'].append(dict(
            val=999,accn='amended',filed='2026-02-10',start='2025-10-01',end='2025-12-31',form='10-Q/A'))
        after,_=sec_features(frame,bars,sec_records(changed))
        pd.testing.assert_frame_equal(before.iloc[:2],after.iloc[:2])
        self.assertAlmostEqual(after.iloc[2]['sec_log_quarter_revenue'],np.log1p(999))

    def test_dated_public_actions_are_deduplicated_and_current_day_excluded(self):
        html='''<table><tr><th>Analyst Profile</th><th>Price Target</th><th>Position</th><th>Date▼</th></tr>
          <tr><td>Analyst A</td><td>$100→$120</td><td>buy</td><td>02/02/26</td></tr></table>'''
        events=parse_tipranks_events(html+html)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['target'],120)
        self.assertEqual(events[0]['previousTarget'],100)
        frame,bars,_=self.fixture()
        values=tipranks_features(frame,bars,events)
        self.assertEqual(values.iloc[0]['tipranks_missing'],1)
        self.assertEqual(values.iloc[1]['tipranks_observed_analysts'],1)
        poison=parse_tipranks_events(html.replace('02/02/26','02/10/26').replace('$120','$999'))
        after=tipranks_features(frame,bars,events+poison)
        pd.testing.assert_frame_equal(values.iloc[:2],after.iloc[:2])


if __name__=='__main__':unittest.main()
