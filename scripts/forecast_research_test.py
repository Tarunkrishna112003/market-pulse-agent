import unittest
from datetime import datetime,timedelta
from copy import deepcopy
import numpy as np
from forecast_features import PastFeatureBuilder,RECENT_NAMES
from forecast_research import target_weights,ForecastExperiment,weighted_quantile,select_joint


class ForecastResearchTests(unittest.TestCase):
    def fixture(self):
        daily=[]
        for i in range(160):
            date=(datetime(2026,1,1)+timedelta(days=i)).date().isoformat();close=100+i*.2+np.sin(i)
            daily.append({'date':date,'open':close*(1+.002*np.cos(i)),'close':close,'high':close*1.01,'low':close*.99,'volume':1000+i})
        return {'symbol':'TEST','daily':daily}

    def test_derived_features_ignore_target_and_future_prices(self):
        company=self.fixture();market=deepcopy(company['daily']);target=company['daily'][100]['date']
        row={'symbol':'TEST','date':target,'targetDate':target,'x':[0.]*22,'y':0.}
        expected=PastFeatureBuilder([company],market,['TEST']).enrich(row)
        for bar in company['daily']+market:
            if bar['date']>=target:bar.update(open=1e8,close=1,high=1e9,low=.001,volume=1e20)
        actual=PastFeatureBuilder([company],market,['TEST']).enrich(row)
        np.testing.assert_array_equal(expected['z'],actual['z'])
        self.assertEqual(expected['scale'],actual['scale'])
        self.assertEqual(len(expected['z']),19+len(RECENT_NAMES)+5+1)

    def test_group_weights_do_not_multiply_repeated_labels(self):
        rows=[{'symbol':'A','date':'2026-01-02','targetDate':'2026-01-02'},
              *[{'symbol':'A','date':'2026-01-01','targetDate':'2026-01-02'} for _ in range(3)],
              {'symbol':'B','date':'2026-01-02','targetDate':'2026-01-02'}]
        weights=target_weights(rows,'2026-01-03')
        self.assertAlmostEqual(weights[:4].sum(),weights[4])
        self.assertAlmostEqual(weights[0],weights[1]*2)
        with self.assertRaises(ValueError):target_weights(rows,'2026-01-02')

    def test_classifier_median_respects_probability_and_signed_magnitude(self):
        model=ForecastExperiment('direction_logistic');model.probability_calibrator=None
        model.raw_probability=lambda rows:np.array([.8,.2,.5])
        model.distributions={True:(np.array([.01,.02,.03]),np.ones(3)),False:(np.array([.01,.02,.03]),np.ones(3))}
        p=model.predict_quantile([{'scale':1.}]*3)
        self.assertGreater(p[0],0);self.assertLess(p[1],0);self.assertEqual(p[2],0)
        self.assertAlmostEqual(p[0],-p[1])

    def test_joint_selection_requires_both_error_and_direction_gain(self):
        truth=np.array([.03,-.03,.03,-.03]);reference=np.array([.01,.01,.01,.01])
        candidates={'large_wrong':np.array([.03,.03,.03,.03]),'better_both':truth*.8}
        self.assertEqual(select_joint(truth,candidates,reference),'better_both')
        self.assertEqual(select_joint(truth,{'large_wrong':candidates['large_wrong']},reference),'v7_reference')

    def test_all_learners_fit_and_predict_finite_values(self):
        from forecast_research import RECIPES
        rng=np.random.default_rng(42);rows=[]
        for i in range(240):
            z=rng.normal(size=30);y=.01*z[0]+rng.normal(scale=.002)
            rows.append({'symbol':'TEST','date':f'2026-01-{i%20+1:02}','targetDate':f'2026-01-{i%20+1:02}','z':z.tolist(),'scale':.02,'y':y,'recentMedian':.001,'recentMean':.002})
        for name in RECIPES:
            model=ForecastExperiment(name).fit(rows,'2026-02-01')
            self.assertTrue(np.isfinite(model.predict(rows[:10])).all(),name)

    def test_controlled_ablation_matches_equivalent_main_model(self):
        from forecast_ablation import AblationModel
        rng=np.random.default_rng(19);rows=[]
        for i in range(180):
            z=rng.normal(size=30);rows.append({'symbol':'TEST','date':'2026-01-02','targetDate':'2026-01-02','z':z.tolist(),'x':z[:22].tolist(),'scale':.02,'y':float(.01*z[0])})
        for kind,recipe in [('ridge','ridge_recent'),('median','boosted_median_recent')]:
            main=ForecastExperiment(recipe).fit(rows,'2026-02-01')
            control=AblationModel(kind,'recent',True).fit(rows,'2026-02-01')
            np.testing.assert_allclose(main.predict(rows),control.predict(rows),atol=1e-12)


if __name__=='__main__':unittest.main()
