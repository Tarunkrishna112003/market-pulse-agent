import unittest
from datetime import date,timedelta
from copy import deepcopy
import numpy as np
from forecast_runtime import calibrated_fit,window_rows,predict_runtime,MODEL_VERSION

class RuntimeTests(unittest.TestCase):
    def rows(self):
        rng=np.random.default_rng(15);rows=[]
        for i in range(100):
            day=(date(2026,1,1)+timedelta(days=i)).isoformat()
            for j in range(8):
                z=rng.normal(size=8)
                rows.append({'symbol':str(j),'date':day,'targetDate':day,'z':z.tolist(),'scale':.02,'y':float(.02*z[0])})
        return rows

    def test_purged_calibration_serialization_and_stock_sensitivity(self):
        import tempfile,joblib
        rows=self.rows();model,bounds=calibrated_fit(rows,'2026-04-11')
        self.assertLess(bounds['calibrationTrainingEnd'],bounds['calibrationStart'])
        self.assertLess(bounds['calibrationEnd'],'2026-04-11')
        prediction=model.predict(rows[-80:]);self.assertGreater(np.ptp(prediction),.001)
        with tempfile.TemporaryDirectory() as directory:
            joblib.dump(model,directory+'/model');loaded=joblib.load(directory+'/model')
            np.testing.assert_array_equal(prediction,loaded.predict(rows[-80:]))
        future=deepcopy(rows[-1]);future.update(date='2026-04-11',targetDate='2026-04-11',y=999.)
        other,_=calibrated_fit(rows+[future],'2026-04-11')
        np.testing.assert_array_equal(prediction,other.predict(rows[-80:]))

    def test_inference_adapter_preserves_probabilities_quantiles_and_dates(self):
        from unittest.mock import Mock
        model,_=calibrated_fit(self.rows(),'2026-04-11')
        builder=Mock();builder.enrich.side_effect=lambda row:{**row,'z':[1.]*8,'scale':.02}
        context={'inferenceDate':'2026-04-11','targetDate':'2026-04-11','baseDate':'2026-04-10',
                 'basePrice':100,'quoteAsOf':'2026-04-10T20:00:00Z','generatedAt':'2026-04-11T10:00:00Z','sessions':250,'x':[0.]*22}
        output=predict_runtime({'model':model,'metrics':{}},builder,{'A':context},365)['A']
        self.assertEqual(output['modelVersion'],MODEL_VERSION)
        self.assertEqual(output['targetDate'],'2026-04-11')
        self.assertFalse(output['validationPassed'])
        self.assertLessEqual(output['interval']['lowerPercent'],output['estimatedPercent'])
        self.assertLessEqual(output['estimatedPercent'],output['interval']['upperPercent'])
        self.assertTrue(0<=output['upProbability']<=1)

if __name__=='__main__':unittest.main()
