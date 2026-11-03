import unittest
import numpy as np
import pandas as pd
from personal_qlib_crdo import make_samples, split_samples


class TimingTests(unittest.TestCase):
    def test_target_day_prices_cannot_change_target_day_features(self):
        dates = pd.bdate_range('2020-01-01', periods=500)
        close = 100 + np.arange(500) * .1 + np.sin(np.arange(500))
        bars = pd.DataFrame(dict(Open=close-.2, Close=close, High=close+1, Low=close-1,
                                 Volume=1000+np.arange(500)),index=dates)
        before = make_samples(bars)
        changed = bars.copy()
        changed.loc[dates[450]:, ['Open','Close','High','Low','Volume']] *= 2
        after = make_samples(changed)
        pd.testing.assert_series_equal(before.loc[(dates[450],'CRDO'),'feature'],
                                       after.loc[(dates[450],'CRDO'),'feature'])
        train, valid, test = split_samples(before)
        self.assertEqual(len(test),30)
        self.assertEqual(len(valid),60)
        self.assertLess(train.index[-1][0],valid.index[0][0])
        self.assertLess(valid.index[-1][0],test.index[0][0])


if __name__ == '__main__':
    unittest.main()
