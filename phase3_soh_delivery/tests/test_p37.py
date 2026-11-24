import unittest

from scripts.p37_metrics import acceptance, describe, band


CRITERIA = dict(max_abs_error_pp=10., raw_coverage_global_min=.99,
                raw_coverage_per_cell_min=.95, valid_coverage_global_min=.85,
                low_valid_diagnostic_below=.90, band_cutoff_percent=80.)


class HeldoutMetricsTests(unittest.TestCase):
    def test_missing_impaired_and_flagged_rows_remain_in_denominator(self):
        rows = [dict(soh_ref_percent=90., rf_raw=91., soh_percent=91., status="VALID", cell_id="A"),
                dict(soh_ref_percent=90., rf_raw=101., soh_percent=None, status="OUT_OF_DOMAIN", cell_id="A"),
                dict(soh_ref_percent=90., rf_raw=None, soh_percent=None, status="MISSING_FEATURE", cell_id="A")]
        m = describe(rows)
        self.assertEqual((m["eligible"], m["raw_count"], m["valid_count"]), (3, 2, 1))
        self.assertAlmostEqual(m["raw_coverage"], 2/3)
        self.assertAlmostEqual(m["valid_coverage"], 1/3)
        self.assertEqual(m["raw_max_pp"], 11.)
        self.assertEqual(m["valid_max_pp"], 1.)
        self.assertEqual(acceptance(m, {"A": m}, CRITERIA)["status"], "ER5_NOT_MET")

    def test_exact_thresholds_are_inclusive_and_no_cell_valid_coverage_floor(self):
        global_stats = dict(raw_coverage=.99, valid_coverage=.85)
        cells = {"A": dict(raw_coverage=.95, valid_coverage=.10, raw_max_pp=10., valid_max_pp=10.),
                 "B": dict(raw_coverage=1., valid_coverage=.99, raw_max_pp=10., valid_max_pp=9.)}
        self.assertEqual(acceptance(global_stats, cells, CRITERIA)["status"], "ER5_PASS")

    def test_each_cell_has_independent_raw_and_valid_max(self):
        global_stats = dict(raw_coverage=1., valid_coverage=.9)
        cells = {"A": dict(raw_coverage=1., valid_coverage=.9, raw_max_pp=10.01, valid_max_pp=1.)}
        result = acceptance(global_stats, cells, CRITERIA)
        self.assertEqual(result["status"], "ER5_NOT_MET")
        self.assertEqual(result["failures"], ["A.raw_max_pp"])

    def test_no_valid_on_a_cell_leaves_max_unassessable(self):
        counts = dict(raw_coverage=1., valid_coverage=.9)
        cells = {"A": dict(raw_coverage=1., valid_coverage=0., raw_max_pp=2., valid_max_pp=None)}
        self.assertEqual(acceptance(counts, cells, CRITERIA)["status"], "ER5_NOT_ASSESSABLE")

    def test_band_uses_reference_at_inclusive_boundary(self):
        self.assertEqual(band(80., 80.), "SOH_GE_80")
        self.assertEqual(band(79.99, 80.), "SOH_LT_80")
