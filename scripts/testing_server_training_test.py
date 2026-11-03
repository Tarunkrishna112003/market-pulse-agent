import csv
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import hashlib
from types import SimpleNamespace
import unittest
from datetime import date,timedelta
from unittest.mock import patch
import numpy as np
from testing_server_training import (require_runner, merge_registry, init_stage, ingest_csv, read_bars,
    choose_training_indices, validation_dates, promotion_allowed, train_candidate, build_examples, recover_model_pointer, github_command)


class ContinualTrainingTests(unittest.TestCase):
    def test_laptop_cannot_download_or_train_real_archive(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'GitHub-hosted'):
                require_runner()

    def test_symbol_ids_never_shift_when_universe_grows(self):
        old={'CRDO':0,'NVDA':1}
        new=merge_registry(old,['AAPL','CRDO','NVDA'])
        self.assertEqual(new,{'CRDO':0,'NVDA':1,'AAPL':2})
        self.assertEqual(old,{'CRDO':0,'NVDA':1})

    def test_runner_stage_handles_repeated_and_corrected_csv_without_changing_original(self):
        connection=sqlite3.connect(':memory:');init_stage(connection)
        header='symbol,interval,timestamp,session_date,open,high,low,close,volume,adjusted_close,corporate_actions,observed_at,source\n'
        old=header+'CRDO,1d,1,2026-10-30,100,110,90,105,1000,105,[],2026-10-31T00:00:00Z,fixture\n'
        new=header+'CRDO,1d,1,2026-10-30,100,110,90,106,1000,106,[],2026-11-01T00:00:00Z,fixture\n'
        intra=header+'CRDO,5m,2,2026-10-30,100,110,90,999,1000,105,[],2026-11-02T00:00:00Z,fixture\n'
        for text in [old,new,old,intra,new]:ingest_csv(connection,io.StringIO(text))
        bars=read_bars(connection,'CRDO',{'2026-10-30':'2026-11-02'})
        self.assertEqual(len(bars),1);self.assertEqual(bars[0]['close'],106)
        self.assertIn(',105,',old)

    def test_replay_covers_old_years_and_recent_rows_with_a_bounded_budget(self):
        chosen=choose_training_indices(list(range(10000)),128)
        self.assertLessEqual(len(chosen),128);self.assertEqual(chosen[0],0)
        self.assertEqual(chosen[-32:],list(range(9968,10000)))
        self.assertEqual(validation_dates(['2026-10-29','2026-10-30'],'2026-10-29'),['2026-10-30'])
        self.assertEqual(validation_dates(['2026-10-30'],'2026-10-30'),[])

    def test_promotion_needs_lower_error_without_lower_direction_accuracy(self):
        parent={'maePoints':2.,'directionAccuracy':.6}
        self.assertFalse(promotion_allowed({'maePoints':1.,'directionAccuracy':.5},parent))
        self.assertFalse(promotion_allowed({'maePoints':3.,'directionAccuracy':.7},parent))
        self.assertTrue(promotion_allowed({'maePoints':1.9,'directionAccuracy':.6},parent))

    def test_real_feature_builder_uses_completed_prior_sessions_with_fixed_ids(self):
        connection=sqlite3.connect(':memory:');init_stage(connection)
        days=[];day=date(2024,1,2)
        while len(days)<130:
            if day.weekday()<5:days.append(day.isoformat())
            day+=timedelta(days=1)
        for symbol in ['A','B','^GSPC','^VIX','XLK']:
            for i,day in enumerate(days):
                price=100+np.sin(i/3)+i*.05
                connection.execute('INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?)',(symbol,day,price,price+2,price-2,price+np.sin(i)*.2,10000+i,0,'2026-11-01T00:00:00Z'))
        connection.commit()
        universe={'stocks':[{'symbol':'A','sector':'Technology'},{'symbol':'B','sector':'Technology'}]}
        with patch('testing_server_training.subprocess.check_output',return_value='2024-07-03'):
            train,validation,inference,metadata=build_examples(connection,universe,{'symbolIds':{'B':0,'A':1}})
        self.assertTrue(train);self.assertTrue(validation);self.assertEqual(len(inference),2)
        self.assertEqual(metadata['symbolIds'],{'B':0,'A':1})
        self.assertLess(max(r['targetDate'] for r in train),min(r['targetDate'] for r in validation))
        self.assertTrue(all(r['lastInputDate']<r['targetDate'] for r in train+validation+inference))

    def test_missing_pointer_recovers_accepted_immutable_model_without_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'saved.txt';path.write_bytes(b'unchanged model weights')
            metadata={'release':'testing-stock-models-202611','modelAsset':'saved.txt','modelSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'metrics':{'accept':True}}
            uploads=[]
            archive=SimpleNamespace(release_tags=lambda:['testing-stock-models-202611'],assets=lambda tag:[{'name':'evaluation-saved.json'}],json=lambda tag,name:metadata,download=lambda tag,name:path,upload=lambda *a,**k:uploads.append((a,k)))
            self.assertEqual(recover_model_pointer(archive),metadata);self.assertEqual(len(uploads),1);self.assertTrue(uploads[0][1]['mutable'])

    def test_service_failure_retries_but_a_missing_asset_is_not_hidden(self):
        responses=[SimpleNamespace(returncode=1,stdout='',stderr='HTTP 500'),SimpleNamespace(returncode=0,stdout='saved',stderr='')]
        with patch('testing_server_training.subprocess.run',side_effect=responses),patch('testing_server_training.time.sleep') as sleep:
            self.assertEqual(github_command(['release','view','fixture']),'saved');sleep.assert_called_once_with(2)

    def test_checkpoint_continuation_adds_trees_preserves_parent_and_excludes_validation(self):
        rng=np.random.default_rng(45);rows=[]
        for day in range(100):
            for symbol in range(12):
                x=np.r_[rng.normal(size=4),symbol,0].astype(np.float32)
                rows.append(dict(symbol=str(symbol),targetDate=(date(2025,1,2)+timedelta(days=day)).isoformat(),
                    lastInputDate=(date(2025,1,1)+timedelta(days=day)).isoformat(),x=x,scale=1.,actualPercent=float(x[0])))
        names=['f0','f1','f2','f3','symbol_id','sector_id']
        train=[r for r in rows if r['targetDate']<'2025-04-01']
        validation=[r for r in rows if r['targetDate']>='2025-04-01']
        model,metrics=train_candidate(train,validation,names,rounds=10)
        self.assertFalse(metrics['continuedFromCheckpoint']);self.assertLess(metrics['trainingTargetEnd'],metrics['validationStart'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'parent.txt';model.save_model(str(path));original=path.read_bytes()
            continued,new=train_candidate(train,validation,names,path,rounds=5)
            self.assertTrue(new['continuedFromCheckpoint']);self.assertGreater(continued.num_trees(),model.num_trees());self.assertEqual(path.read_bytes(),original)
            with self.assertRaisesRegex(ValueError,'overlap'):
                train_candidate(rows,validation,names,path,rounds=5)


if __name__=='__main__':unittest.main()
