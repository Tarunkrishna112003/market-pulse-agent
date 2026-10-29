import unittest
from copy import deepcopy
from datetime import date,timedelta
import tempfile
import joblib
import numpy as np
from stock_specific import DailyStockFeatures,JointReturnObjective,StockSpecificReturnModel,PerStockReturnModel


class StockSpecificTests(unittest.TestCase):
    def dataset(self):
        bars=[]
        for i in range(85):
            day=(date(2026,1,1)+timedelta(days=i)).isoformat();price=100*np.exp(.002*i+.02*np.sin(i))
            bars.append({'date':day,'open':price*.99,'close':price,'high':price*1.02,'low':price*.98,'volume':1000+i})
        return {'companies':[{'symbol':'A','sector':'Tech','sectorETF':'XLK','daily':deepcopy(bars)},
                             {'symbol':'B','sector':'Tech','sectorETF':'XLK','daily':[{**b,'close':b['close']*.98} for b in bars]}],
                'context':{s:{'daily':deepcopy(bars)} for s in ('^GSPC','^VIX','XLK')}}

    def test_target_and_future_prices_do_not_change_inputs(self):
        data=self.dataset();target=data['companies'][0]['daily'][-2]['date']
        original=DailyStockFeatures(data).features('A',target)
        changed=deepcopy(data)
        for company in changed['companies']+list(changed['context'].values()):
            for b in company['daily']:
                if b['date']>=target:b.update(open=1e6,close=1e-6,high=1e7,low=1e-7)
        np.testing.assert_array_equal(original['x'],DailyStockFeatures(changed).features('A',target)['x'])
        self.assertLess(original['lastInputDate'],target)
        self.assertGreater(np.max(abs(original['x']-DailyStockFeatures(data).features('B',target)['x'])),.1)

    def test_joint_loss_derivatives_and_weighting(self):
        y=np.array([-2.,-.5,.3,1.8,0.]);p=np.array([.3,-.2,.2,-1.,.1]);strength=.1
        def loss(v):return np.sqrt(1+(v-y)**2)-1+strength*np.logaddexp(0,-np.sign(y)*v)
        eps=1e-4;g,h=JointReturnObjective(strength)(y,p,None)
        np.testing.assert_allclose(g,(loss(p+eps)-loss(p-eps))/(2*eps),rtol=1e-6,atol=1e-7)
        np.testing.assert_allclose(h,(loss(p+eps)-2*loss(p)+loss(p-eps))/eps**2,rtol=1e-5,atol=1e-7)
        wg,wh=JointReturnObjective(strength)(y,p,np.full(5,2.))
        np.testing.assert_allclose(wg,2*g);np.testing.assert_allclose(wh,2*h)

    def test_sector_corporate_action_is_marked_missing(self):
        data=self.dataset();target=data['companies'][0]['daily'][-1]['date']
        data['context']['XLK']['warnings']=[{'date':data['context']['XLK']['daily'][-10]['date']}]
        builder=DailyStockFeatures(data);row=builder.features('A',target)
        self.assertEqual(row['x'][builder.names.index('sector_missing')],1)
        self.assertEqual(row['x'][builder.names.index('sector_momentum_1')],0)

    def test_individual_models_learn_different_patterns_from_identical_inputs(self):
        rows=[]
        for i in range(100):
            value=(-1 if i%2 else 1)*(1+i/100)
            for symbol,sign in [('A',1),('B',-1)]:
                rows.append({'symbol':symbol,'targetDate':(date(2026,1,2)+timedelta(days=i)).isoformat(),
                    'lastInputDate':(date(2026,1,1)+timedelta(days=i)).isoformat(),'x':np.array([value,0,0,0]),
                    'scale':2.,'actualPercent':sign*value*2})
        model=PerStockReturnModel().fit(rows,'2026-05-01',[])
        probe=[{**rows[0],'symbol':s} for s in ('A','B')]
        values=model.predict(probe);self.assertGreater(values[0],0);self.assertLess(values[1],0)
        np.testing.assert_allclose(model.feature_contributions(probe).sum(axis=1)*2,values)
        with self.assertRaises(ValueError):model.predict([{**probe[0],'symbol':'untrained'}])
        with self.assertRaises(ValueError):PerStockReturnModel().fit(rows,'2026-02-01',[])

    def test_learns_opposite_stock_patterns_and_serializes_without_a_sign_mix_rule(self):
        rng=np.random.default_rng(42);rows=[]
        for day in range(90):
            for stock in range(8):
                x=np.r_[rng.normal(size=5),stock,0].astype(np.float32)
                rows.append({'symbol':str(stock),'targetDate':(date(2026,1,2)+timedelta(days=day)).isoformat(),
                             'lastInputDate':(date(2026,1,1)+timedelta(days=day)).isoformat(),
                             'x':x,'scale':2.,'actualPercent':float(2*x[0])})
        model=StockSpecificReturnModel().fit(rows,'2026-05-01',[3])
        prediction=model.predict(rows)
        self.assertGreater(np.mean(np.sign(prediction)==np.sign([r['actualPercent'] for r in rows])),.9)
        self.assertLess(np.mean(abs(prediction-[r['actualPercent'] for r in rows])),1.)
        with tempfile.TemporaryDirectory() as folder:
            joblib.dump(model,folder+'/model');restored=joblib.load(folder+'/model')
            np.testing.assert_array_equal(prediction,restored.predict(rows))
        with self.assertRaises(ValueError):StockSpecificReturnModel().fit(rows,'2026-02-01',[])


if __name__=='__main__':unittest.main()
