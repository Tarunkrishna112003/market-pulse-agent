import unittest
import numpy as np
import pandas as pd
from personal_qlib_crdo import make_samples, split_samples, train_neural_blocks


class TimingTests(unittest.TestCase):
    def test_backprop_preserves_optimizer_and_visits_all_rows(self):
        import torch
        torch.manual_seed(42)
        network = torch.nn.Linear(2,1)
        optimizer = torch.optim.Adam(network.parameters(),lr=.01)
        x = torch.randn(129,2)
        y = 2*x[:,0] - x[:,1]
        visits = []
        hook = network.register_forward_pre_hook(
            lambda model, args: visits.append(len(args[0])) if model.training else None)
        initial = network.weight.detach().clone()
        selected, result = train_neural_blocks(network,optimizer,x,y,x[:30],y[:30])
        hook.remove()
        self.assertEqual(len(result['runs']),10)
        self.assertEqual(result['runs'][-1]['cumulativeEpochs'],50)
        self.assertEqual(sum(visits),50*len(x))
        self.assertEqual(int(optimizer.state[network.weight]['step']),100)
        self.assertFalse(torch.equal(initial,network.weight))
        self.assertLess(result['runs'][-1]['trainMSE'],result['initialTrainMSE'])
        self.assertIsNot(selected,network)
        selected_again, continued = train_neural_blocks(
            network,optimizer,x,y,x[:30],y[:30],start_epoch=50,previous_best=(selected,result))
        self.assertEqual(continued['runs'][0]['run'],11)
        self.assertEqual(continued['runs'][-1]['cumulativeEpochs'],100)
        self.assertEqual(int(optimizer.state[network.weight]['step']),200)
        self.assertLessEqual(continued['bestValidationMSE'],result['bestValidationMSE'])

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
