import inspect
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.cc import coulomb_count, score_populations
from src.development_data import DevelopmentRun, RUN_IDS, classify_clock, load_development_runs


class CoulombTests(unittest.TestCase):
    def test_constant_discharge_rests_and_charging(self):
        for current in (0.5, 0.0, -0.5):
            with self.subTest(current=current):
                z = coulomb_count([0, 600], [current, 123], 1.0, 0.5)
                np.testing.assert_allclose(z, [0.5, 0.5 - current / 6])

    def test_subdivision_and_current_bias(self):
        time = [10, 40, 70, 100, 130]
        clean = coulomb_count(time, [1.0] * 5, 2.0, 0.6)
        biased = coulomb_count(time, [1.2] * 5, 2.0, 0.6)
        np.testing.assert_allclose(clean[-1], coulomb_count([10, 130], [1, 0], 2, 0.6)[-1])
        np.testing.assert_allclose(biased - clean, -0.2 * (np.array(time) - 10) / 7200)

    def test_zoh_duplicate_and_range_excursion(self):
        z = coulomb_count([0, 0, 3600, 3600, 7200], [99, 1, 1, -2, 0], 1, 0.5)
        np.testing.assert_allclose(z, [0.5, 0.5, -0.5, -0.5, 1.5])

    def test_reject_invalid_inputs(self):
        for args in (([], [], 1, .5), ([1, 0], [0, 0], 1, .5),
                     ([0], [np.nan], 1, .5), ([0], [0], 0, .5),
                     ([0], [0], 1, 1.1), ([0], [], 1, .5), ([np.inf], [0], 1, .5)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                coulomb_count(*args)

    def test_prior_equivalence_and_no_reference_input(self):
        self.assertEqual(tuple(inspect.signature(coulomb_count).parameters),
                         ('time_s', 'current_a', 'capacity_ah', 'prior_soc'))
        a, b = [coulomb_count([0, 3, 12], [-1, 1, 0], 1.5, p) for p in (.4, .5)]
        self.assertEqual(a[0], .4)
        np.testing.assert_allclose(b - a, .1)

    def test_future_currents_do_not_change_past_states(self):
        a = coulomb_count([0, 1, 2, 3], [1, 2, 3, 4], 1, .5)
        b = coulomb_count([0, 1, 2, 3], [1, 2, -30, -40], 1, .5)
        np.testing.assert_array_equal(a[:3], b[:3])

    def test_reference_and_future_counters_excluded_from_runtime_record(self):
        self.assertEqual(set(DevelopmentRun.__annotations__), {
            'run_id', 'role', 'row', 'time_s', 'current_a', 'voltage_v', 'clock_event', 'prior_soc', 'capacity_ah'})
        self.assertEqual([name.split('_')[-2] for name in RUN_IDS], ['DST', 'DST', 'FUDS', 'FUDS'])

    def test_modified_archive_rejected_before_any_member_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'modified.zip'
            archive.write_bytes(b'modified test fixture')
            accesses = []
            with self.assertRaisesRegex(ValueError, 'archive SHA-256'):
                list(load_development_runs(archive, audit=accesses.append))
            self.assertEqual(accesses, [])

    def test_clock_classification(self):
        kinds = classify_clock([0, 1, 1, 1, 1], [0, 1, 1, 1, 2], [4, 3, 3, 3, 2],
                               [1, 1, 1, 2, 3], [1] * 5)
        self.assertEqual(kinds.tolist(), ['FIRST', 'MEASUREMENT', 'DUPLICATE_OBSERVATION',
                                          'ZERO_DT_STEP_TRANSITION_SAME_SIGNAL', 'ZERO_DT_NEW_TRANSITION'])
        with self.assertRaises(ValueError):
            classify_clock([0, 0], [1, 2], [4, 4], [1, 1], [1, 1])

    def test_population_boundary_and_missing_denominators(self):
        m = score_populations([.5, .6, np.nan], [.5, .5, .5], [3.2976, 2.50, 3.4])
        self.assertEqual(m['FULL_DYNAMIC']['denominator'], 3)
        self.assertEqual(m['FULL_DYNAMIC']['numerator'], 2)
        self.assertAlmostEqual(m['FULL_DYNAMIC']['MAX_abs_pp'], 10.0)
        self.assertEqual(m['NON_FLAGGED']['denominator'], 2)
        self.assertEqual(m['NON_FLAGGED']['numerator'], 1)
        self.assertEqual(m['flagged_count'], 1)
        empty = score_populations([0], [0], [3.2])['NON_FLAGGED']
        self.assertIsNone(empty['MAE_pp'])
        self.assertEqual(empty['denominator'], 0)


if __name__ == '__main__':
    unittest.main()
