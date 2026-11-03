import unittest
import numpy as np
import pandas as pd
from personal_qlib_crdo_rolling import context_samples,rolling_splits


class RollingTimingTests(unittest.TestCase):
    def test_context_cannot_leak_target_day_and_test_folds_do_not_overlap(self):
        dates=pd.bdate_range('2022-01-01',periods=900)
        close=100+np.arange(900)*.1+np.sin(np.arange(900))
        bars=pd.DataFrame(dict(Open=close-.2,Close=close,High=close+1,Low=close-1,
                               Volume=1000+np.arange(900)),index=dates)
        context={symbol:bars.copy() for symbol in ('QQQ','SOXX','VIX')}
        before=context_samples(bars,context)
        for values in context.values():values.loc[dates[800]:,'Close']*=2
        after=context_samples(bars,context)
        pd.testing.assert_series_equal(before.loc[(dates[800],'CRDO'),'feature'],
                                       after.loc[(dates[800],'CRDO'),'feature'])
        self.assertEqual(set(before.index.get_level_values('instrument')),{'CRDO'})
        tested=[]
        for train,valid,test in rolling_splits(before,folds=6,train_size=504):
            self.assertEqual(len(valid),60)
            self.assertEqual(len(test),30)
            self.assertLessEqual(len(train),504)
            self.assertLess(train.index[-1][0],valid.index[0][0])
            self.assertLess(valid.index[-1][0],test.index[0][0])
            tested.extend(test.index)
        self.assertEqual(len(tested),180)
        self.assertEqual(len(set(tested)),180)
        train,valid,test=next(rolling_splits(before))
        self.assertEqual(len(train),len(before)-90)
        self.assertEqual(train.index[0],before.index[0])
        self.assertEqual(len(test),30)


if __name__=='__main__':unittest.main()
