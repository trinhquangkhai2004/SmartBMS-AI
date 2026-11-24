import unittest

import numpy as np

from scripts.p36_inputs import cell_weights, labels_from_summary
from scripts.train_p36 import cell_scores, weighted_bounds


class P36TrainingTests(unittest.TestCase):
    def test_weights_give_short_and_long_cells_equal_mass(self):
        np.testing.assert_array_equal(cell_weights(np.array([0, 2, 2, 2])), [2, 2/3, 2/3, 2/3])

    def test_label_policy_commissions_first_five_and_excludes_rejected_pair(self):
        summary = {"cell_id": "4-5", "dq_by_cycle_raw": [
            {"cycle_id": cycle, "value": dq} for cycle, dq in
            [(1, 2000), (2, 2100), (3, 2200), (4, 2300), (5, 2400), (6, 2310), (341, 1900)]
        ]}
        labels = labels_from_summary("4-5", summary)
        self.assertEqual(set(labels), {6})
        self.assertAlmostEqual(labels[6], 105.0)

    def test_label_rejects_duplicate_keys(self):
        record = {"cycle_id": 1, "value": 2200}
        with self.assertRaises(ValueError):
            labels_from_summary("1-1", {"cell_id": "1-1", "dq_by_cycle_raw": [record, record]})

    def test_weighted_cdf_preserves_small_cells_and_ignores_missing(self):
        x = np.array([[-100.], [np.nan]] + [[0.]] * 101)
        groups = np.array([1, 1] + [2] * 101)
        bound = weighted_bounds(x, groups, ["hi"])["hi"]
        self.assertEqual(bound["weighted"], [-100., 0.])
        self.assertEqual(bound["unweighted"], [0., 0.])
        self.assertEqual(bound["cells_with_finite"], 2)
        self.assertEqual(bound["missing"], 1)

    def test_macro_is_not_cycle_weighted_and_reports_per_cell_rmse(self):
        per_cell = cell_scores(np.array([0., 0., 0., 0.]), np.array([10., 0., 0., 2.]),
                               np.array(["short", "long", "long", "long"]))
        self.assertAlmostEqual(per_cell["long"]["mae_pp"], 2/3)
        self.assertAlmostEqual(per_cell["long"]["rmse_pp"], (4/3)**0.5)
        self.assertEqual(per_cell["short"]["mae_pp"], 10.)
