import importlib.util
import pathlib
import tempfile
import unittest
from datetime import datetime,timedelta
from unittest.mock import patch
import numpy as np

spec=importlib.util.spec_from_file_location('paired_comparison',pathlib.Path(__file__).with_name('compare-forecast-models.py'))
comparison=importlib.util.module_from_spec(spec);spec.loader.exec_module(comparison)


class PairedComparisonTests(unittest.TestCase):
    def test_magnitude_gain_when_correct_does_not_hide_wrong_direction_cost(self):
        rows=[{'actualPercent':3.,'methods':{'raw':1.,'scaled':2.}},
              {'actualPercent':-3.,'methods':{'raw':1.,'scaled':2.}}]
        raw=comparison.score(rows,'raw');scaled=comparison.score(rows,'scaled')
        self.assertEqual(raw['directionAccuracy'],.5)
        self.assertEqual(scaled['directionAccuracy'],.5)
        self.assertEqual(raw['meanAbsoluteError'],3.)
        self.assertEqual(scaled['meanAbsoluteError'],3.)
        self.assertLess(scaled['correctDirectionMAE'],raw['correctDirectionMAE'])
        self.assertGreater(scaled['wrongDirectionMAE'],raw['wrongDirectionMAE'])

    def test_calibration_model_trains_before_calibration_labels(self):
        rows=[]
        for i in range(50):
            date=(datetime(2026,6,1)+timedelta(days=i)).date().isoformat()
            for symbol in ['A','B']:
                x=[0.]*22;x[8]=i
                rows.append({'symbol':symbol,'date':date,'targetDate':date,'x':x,'y':.01})
        class ConstantModel:
            def predict(self,x):return np.zeros(len(x))
        observed=[]
        def fit(template,train,variant,kind):
            observed.extend(train);return ConstantModel()
        with patch.object(comparison,'fit_base',side_effect=fit):
            config=comparison.prepare_calibration('2026-07-21',rows,'v7',None,'prices')
        self.assertLess(max(r['targetDate'] for r in observed),config['targetStart'])
        self.assertLess(config['targetEnd'],config['cutoff'])
        self.assertEqual(config['samples'],60)

    def test_paired_report_matches_by_stock_and_date_and_preserves_inputs(self):
        import contextlib,io,json
        frozen=[];actual=[]
        for date in ['2026-08-19','2026-08-20']:
            for symbol,value in [('A',3.),('B',-3.)]:
                frozen.append({'date':date,'symbol':symbol,'methods':{'v7_unadjusted':.5,'v8_unadjusted':1.,'v8_global_scale':2.}})
                actual.append({'date':date,'symbol':symbol,'actualPercent':value})
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(comparison,'OUTPUT',pathlib.Path(directory)),contextlib.redirect_stdout(io.StringIO()):
                result=comparison.report(frozen,{'entries':list(reversed(actual)),'caveats':[]})
            self.assertEqual(result['summary']['v8_unadjusted']['samples'],4)
            self.assertEqual(result['summary']['v8_unadjusted']['meanAbsoluteError'],3.)
            self.assertTrue((pathlib.Path(directory)/'comparison.csv').exists())
            self.assertTrue((pathlib.Path(directory)/'report.md').exists())
        self.assertTrue(all('actualPercent' not in row for row in frozen))


if __name__=='__main__':unittest.main()
