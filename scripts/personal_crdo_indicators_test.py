import unittest
import numpy as np
import pandas as pd
from personal_crdo_indicators import indicators, session_vwap_features


class IndicatorTimingTest(unittest.TestCase):
    def bars(self):
        dates = pd.bdate_range('2024-01-01', periods=300)
        close = 100+np.arange(300)*.1+np.sin(np.arange(300))
        return pd.DataFrame(dict(Open=close-.1, High=close+1, Low=close-1,
                                 Close=close, Volume=np.full(300, 1000)), index=dates)

    def test_current_and_future_prices_cannot_change_prediction_features(self):
        bars = self.bars()
        original = indicators(bars)
        changed = bars.copy()
        changed.iloc[250:] *= 2
        pd.testing.assert_frame_equal(original.iloc[:251], indicators(changed).iloc[:251])
        self.assertTrue(np.isfinite(original.iloc[200:].to_numpy()).all())
        self.assertAlmostEqual(original.iloc[250].sma200_distance,
                               bars.Close.iloc[249]/bars.Close.iloc[50:250].mean()-1)

    def test_vwap_regular_session_and_previous_day_only(self):
        daily = self.bars().iloc[:3]
        day = daily.index[0].strftime('%Y-%m-%d')
        times = pd.DatetimeIndex([day+' 08:00', day+' 09:30', day+' 09:35'], tz='America/New_York')
        intra = pd.DataFrame(dict(High=[999, 10, 20], Low=[999, 10, 20],
                                  Close=[999, 10, 20], Volume=[99999, 100, 300]), index=times)
        result = session_vwap_features(daily, intra)
        self.assertTrue(pd.isna(result.iloc[0].previous_session_vwap_distance))
        self.assertAlmostEqual(result.iloc[1].previous_session_vwap_distance, daily.Close.iloc[0]/17.5-1)
        self.assertEqual(result.iloc[2].previous_session_vwap_missing, 1)


if __name__=='__main__':
    unittest.main()
