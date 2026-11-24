import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import run_heldout as driver
from src.cc import score_populations
from src.development_data import DevelopmentRun
from src.ekf import FixedRC, OCV
from src.final_evaluation import record_once, run_verdict, sha


class FinalEvaluationTests(unittest.TestCase):
    def test_threshold_is_inclusive_and_requires_every_event(self):
        score = {'FULL_DYNAMIC': {'MAX_abs_pp': 10.0, 'numerator': 7, 'denominator': 7}}
        self.assertEqual(run_verdict(score, True, 6, 6), 'ER4_PASS')
        self.assertEqual(run_verdict(score, True, 5, 6), 'ER4_NOT_ASSESSABLE')
        self.assertEqual(run_verdict(score, False, 6, 6), 'ER4_NOT_ASSESSABLE')
        score['FULL_DYNAMIC']['MAX_abs_pp'] = 10.0000001
        self.assertEqual(run_verdict(score, True, 6, 6), 'ER4_FAIL')

    def test_duplicate_claim_preserves_first_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'claim.json'
            record_once(p, {'first': True})
            before = p.read_bytes()
            with self.assertRaises(FileExistsError):
                record_once(p, {'first': False})
            self.assertEqual(p.read_bytes(), before)

    def test_loaded_polarization_and_no_double_update(self):
        run = DevelopmentRun('fixture', 'held_out_test', np.arange(3), np.array([0.,1.,2.]),
                             np.array([1.,1.,1.]), np.array([3.3,3.29,3.28]),
                             np.array(['FIRST','MEASUREMENT','MEASUREMENT']), .5, 2.)
        plan = {'scenarios': {'nominal': {}, 'bias': {'current_bias_a':.05}}}
        config = dict(seed=42, selected={'p0_diag':[.01,.01], 'q_per_s_diag':[1e-8,1e-8], 'r_v2':.01},
                      max_gap_active_s=5., approval_record_id='fixture', current_range_a=None)
        with tempfile.TemporaryDirectory() as tmp, patch.object(driver, 'OUT', Path(tmp)):
            evidence = driver.evaluate_run(0, run, np.full(3, .5), {'quality':'VALID'}, config,
                                           OCV([0,1], [3,4]), FixedRC(.1,.03,700,2.), plan)
        nominal = evidence['scenarios']['nominal']
        self.assertAlmostEqual(nominal['initial_vrc_v'], .1)
        self.assertEqual(nominal['initial_voltage_corrections'], 0)
        self.assertEqual(nominal['EKF']['FULL_DYNAMIC']['numerator'], 3)
        self.assertEqual(nominal['EKF']['NON_FLAGGED']['denominator'], 1)

    def test_repeated_call_does_not_reopen_claimed_workbook(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dummy = root/'raw.zip'
            dummy.write_bytes(b'opaque fixture')
            record = dict(archive=dummy.name, archive_sha256=sha(dummy), split={'file_sha256':'fixture'},
                          window={'dynamic_start_row':'3', 'dynamic_end_row':'5'})
            sources = {name:record for name in ('a','b','c','d')}
            snapshot = {'sources':sources}
            protocol = {'run_order':list(sources)}
            lock = root/'locked_protocol.json'
            record_once(lock, {'snapshot':snapshot})
            (root/'configs').mkdir()
            record_once(root/'configs/p25_development_search.json', {'scenarios':{'nominal':{}}})
            fake_contract = snapshot, protocol, {}, None, SimpleNamespace(capacity_ah=2.)
            with (patch.object(driver, 'ROOT', root), patch.object(driver, 'OUT', root),
                  patch.object(driver, 'LOCK', lock), patch.object(driver, 'prerequisites', return_value=fake_contract),
                  patch.object(driver, 'reference_and_signals', side_effect=ValueError('invalid fixture')) as read):
                first = driver.evaluate('p22', root, sha(lock))
                second = driver.evaluate('p22', root, sha(lock))
                self.assertEqual(read.call_count, 4)
                self.assertEqual(first, second)
                self.assertEqual(first['ER4'], 'ER4_NOT_ASSESSABLE')
                with self.assertRaises(PermissionError):
                    driver.evaluate('p22', root, 'wrong-hash')


if __name__ == '__main__':
    unittest.main()
