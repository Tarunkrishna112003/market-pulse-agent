import unittest
import numpy as np
from forecast_calibration import fit_calibration,apply_calibration,magnitude_blend


class MagnitudeCalibrationTests(unittest.TestCase):
    def fixture(self):
        predicted=np.tile([-.01,.01],30);truth=predicted*2
        return predicted,truth,['S'+str(i%2) for i in range(60)],[f'2026-08-{i//2+1:02}' for i in range(60)]

    def test_global_scale_learns_known_magnitude_error(self):
        p,y,symbols,dates=self.fixture()
        config=fit_calibration(p,y,symbols,dates,np.abs(y),'2026-09-01')
        self.assertEqual(config['scale'],2.)
        values=apply_calibration(p,symbols,np.abs(y),config)
        np.testing.assert_allclose(values['global_scale'],y)
        for v in values.values():np.testing.assert_array_equal(np.sign(v),np.sign(p))

    def test_future_and_repeated_labels_rejected(self):
        p,y,symbols,dates=self.fixture()
        with self.assertRaisesRegex(ValueError,'precede'):
            fit_calibration(p,y,symbols,dates,np.abs(y),'2026-08-15')
        dates[-1]=dates[1]
        with self.assertRaisesRegex(ValueError,'Repeated'):
            fit_calibration(p,y,symbols,dates,np.abs(y),'2026-09-01')

    def test_zero_and_wrong_direction_are_not_silently_relabelled(self):
        p=np.array([-.01,0.,.01]);magnitude=np.array([.03,.03,.03])
        for weight in [0,.25,.5,1]:
            adjusted=magnitude_blend(p,magnitude,weight)
            np.testing.assert_array_equal(np.sign(adjusted),np.sign(p))
        # Correct-direction conditional error must not hide worse overall error.
        truth=np.array([.03,0.,-.03])
        self.assertGreater(np.abs(truth-magnitude_blend(p,magnitude,1)).mean(),np.abs(truth-p).mean())

    def test_stock_scaling_is_shrunk_and_unseen_symbols_use_global(self):
        p,y,symbols,dates=self.fixture();y[:30]=p[:30]*5
        config=fit_calibration(p,y,symbols,dates,np.abs(y),'2026-09-01')
        self.assertTrue(all(.25<=v<=5 for v in config['stockScales'].values()))
        adjusted=apply_calibration(np.array([.01]),['UNSEEN'],np.array([.03]),config)
        self.assertAlmostEqual(adjusted['stock_scale'][0],.01*config['scale'])

    def test_nonfinite_calibration_rejected(self):
        p,y,symbols,dates=self.fixture();p[0]=np.nan
        with self.assertRaisesRegex(ValueError,'Nonfinite'):
            fit_calibration(p,y,symbols,dates,np.abs(y),'2026-09-01')


if __name__=='__main__':unittest.main()
