import unittest
from dataclasses import replace

import numpy as np

from src.development_data import DevelopmentRun
from src.ekf import FixedRC, OCV
from run_ekf import candidate_grid, convergence_seconds, inputs_for_scenario, replay, selection_key, read_json, ROOT


def fixture():
    return DevelopmentRun("fixture", "validation", np.arange(4), np.array([3.,4.,4.,5.]),
                          np.array([0.,1.,1.,0.]), np.array([3.5,3.4,3.4,3.45]),
                          np.array(["FIRST","MEASUREMENT","DUPLICATE_OBSERVATION","MEASUREMENT"]), .5, 2.)


class ReplayTests(unittest.TestCase):
    def test_noise_consistent_and_reproducible_at_duplicates(self):
        run = fixture()
        scenario = {"voltage_noise_sd_v":.01, "current_noise_sd_a":.02}
        a = inputs_for_scenario(run, scenario, seed=4)
        b = inputs_for_scenario(run, scenario, seed=4)
        for x,y in zip(a[1:],b[1:]):
            np.testing.assert_array_equal(x,y)
            self.assertEqual(x[1], x[2])
        self.assertEqual(run.voltage_v[1], 3.4)
        self.assertIsNone(inputs_for_scenario(replace(run, prior_soc=.85), {"prior_offset_pp":20}, seed=4))

    def test_convergence_resets_on_missing_or_gap(self):
        self.assertEqual(convergence_seconds([0,30,59,60], [3,3,2,1], 35), 0.)
        self.assertIsNone(convergence_seconds([0,30,59,60], [3,np.nan,2,1], 35))
        self.assertIsNone(convergence_seconds([0,100], [0,0], 5))
        self.assertEqual(convergence_seconds([0,1,31,61], [8,2,1,0], 35), 1.)

    def test_dev_selection_full_window_coverage_precedes_error(self):
        def result(n, m, rmse, worst):
            return {"FULL_DYNAMIC":{"numerator":n, "denominator":m, "RMSE_pp":rmse, "MAX_abs_pp":worst}}
        full = [result(100,100,4,8),result(50,50,4,9)]
        partial = [result(99,100,1,2),result(50,50,1,2)]
        self.assertLess(selection_key(full, 0), selection_key(partial, 1))
        self.assertLess(selection_key(full, 0), selection_key(full, 1))

    def test_grid_and_paired_baseline_inputs(self):
        plan = read_json(ROOT/"configs/p25_development_search.json")
        grid = list(candidate_grid(plan))
        self.assertEqual(len(grid), 8)
        run = fixture()
        prior, current, voltage = inputs_for_scenario(run, {"prior_offset_pp":10,"current_bias_a":.1},seed=0)
        result, cc, events = replay(run, prior, current, voltage, grid[0], FixedRC(.1,.03,700,2),
                                    OCV([0,1],[3,4]), 5., "fixture", None)
        self.assertAlmostEqual(cc[0], .6)
        self.assertAlmostEqual(events[0]["z_pred"], .6)
        self.assertAlmostEqual(cc[-1], .6-(.1+1.1)/7200)
        self.assertEqual(len(result), len(events))
        self.assertFalse(events[2]["corrected"])

    def test_first_voltage_used_in_polarization_prior_is_not_corrected_twice(self):
        run = fixture()
        cfg = next(candidate_grid(read_json(ROOT/"configs/p25_development_search.json")))
        z, _, rows = replay(run,.6,run.current_a,run.voltage_v,cfg,FixedRC(.1,.03,700,2),
                            OCV([0,1],[3,4]),5.,"fixture",None,vrc0=.1,first_voltage_used_for_prior=True)
        self.assertEqual(z[0], .6)
        self.assertFalse(rows[0]["corrected"])
        self.assertIsNone(rows[0]["innovation_v"])
        self.assertEqual(rows[0]["p_zz"],cfg["p0_diag"][0])
        self.assertTrue(rows[1]["corrected"])
