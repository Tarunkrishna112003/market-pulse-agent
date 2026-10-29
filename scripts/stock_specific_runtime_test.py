import json
from pathlib import Path
from datetime import date,timedelta
from copy import deepcopy
import tempfile
import unittest
import numpy as np
from stock_specific_runtime import train_and_predict,run


class LiveStockTests(unittest.TestCase):
    def dataset(self):
        companies=[];target=(date(2026,1,1)+timedelta(days=185)).isoformat()
        for symbol,sign in [('A',1),('B',-1)]:
            daily=[]
            for i in range(185):
                price=100*np.exp(.001*i+.01*np.sin(i));opening=price*np.exp(-sign*.005*np.cos(i))
                daily.append({'date':(date(2026,1,1)+timedelta(days=i)).isoformat(),'open':opening,'close':price,'low':min(opening,price)*.99,'high':max(opening,price)*1.01,'volume':1000+i})
            companies.append({'symbol':symbol,'name':symbol,'sector':'Tech','sectorETF':'XLK','daily':daily,'sharedTraining':True,
                'forecastContext':{'state':'ready','targetDate':target,'basePrice':daily[-1]['close'],'quoteAsOf':daily[-1]['date']}})
        return {'reportId':'live','generatedAt':target+'T10:00:00Z','companies':companies,
                'context':{s:{'daily':deepcopy(companies[0]['daily'])} for s in ('^GSPC','^VIX','XLK')},
                'universe':[{'symbol':'A'},{'symbol':'B'},{'symbol':'MISSING'}]}

    def test_both_model_choices_preserve_target_and_never_use_target_prices(self):
        for family in ('per-stock','direction-aware'):
            data=self.dataset();target=data['companies'][0]['forecastContext']['targetDate']
            with tempfile.TemporaryDirectory() as folder:
                config={'version':'new-test','family':family}
                forecasts,metrics=train_and_predict(data,config,folder)
                self.assertLess(metrics['trainingTargetEnd'],target)
                self.assertEqual(metrics['probabilityCalibration'],'none')
                for forecast in forecasts.values():
                    self.assertEqual(forecast['state'],'estimated');self.assertEqual(forecast['modelVersion'],'new-test')
                    self.assertEqual(forecast['targetDate'],target);self.assertFalse(forecast['validationPassed'])
                    self.assertEqual(forecast['estimates']['closeToClose']['state'],'no-signal')
                    self.assertNotIn('upProbability',forecast)
                poisoned=deepcopy(data)
                for c in poisoned['companies']+list(poisoned['context'].values()):
                    c['daily'].append({'date':target,'open':1e6,'close':1e-6,'low':1e-7,'high':1e7,'volume':1})
                other,_=train_and_predict(poisoned,config,folder)
                self.assertEqual([f['estimatedPercent'] for f in forecasts.values()],[f['estimatedPercent'] for f in other.values()])

    def test_stale_stock_gets_no_signal_and_no_legacy_fallback(self):
        data=self.dataset();data['companies'][1]['forecastContext']['state']='stale'
        with tempfile.TemporaryDirectory() as folder:
            forecasts,_=train_and_predict(data,{'version':'new','family':'per-stock'},folder)
        self.assertEqual(forecasts['B']['state'],'no-signal');self.assertNotIn('estimatedPercent',forecasts['B'])


if __name__=='__main__':unittest.main()
