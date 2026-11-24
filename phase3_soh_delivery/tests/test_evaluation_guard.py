import unittest

from src.soh.evaluation_guard import EvaluationGuard


POLICY = {
    "release_status": "CANDIDATE_PENDING_REVIEW",
    "primary_features": ["hi"],
    "feature_bounds": {"hi": {"weighted": [0., 10.]}},
    "min_feature_violations": 1,
    "sigma_threshold_pp": 4.,
    "delta_max_pp": 5.,
    "resync_confirm_k": 2,
    "resync_stability_pp": 2.,
    "max_confirmation_gap_cycles": 2,
}


class EvaluationGuardTests(unittest.TestCase):
    def apply(self, guard, cycle, predicted=90., hi=5., sigma=1., **kwargs):
        return guard.evaluate("1-1", "model", cycle, [hi], predicted, sigma, **kwargs)

    def test_stable_large_jump_resyncs_and_is_auditable_after_restart(self):
        guard = EvaluationGuard(POLICY)
        self.assertEqual(self.apply(guard, 1)["status"], "VALID")
        jump = self.apply(guard, 2, 83.)
        self.assertEqual((jump["status"], jump["soh_percent"]), ("SOH_JUMP_ANOMALY", None))
        restored = EvaluationGuard(POLICY, guard.snapshot())
        recovered = self.apply(restored, 3, 83.6)
        self.assertEqual(recovered["reason"], "SOH_BASELINE_RESYNCED")
        self.assertEqual(recovered["previous_baseline_pp"], 90.)
        self.assertEqual(recovered["confirmation_count"], 2)
        self.assertEqual(recovered["soh_percent"], 83.6)

    def test_ood_precedes_sigma_and_clears_pending(self):
        guard = EvaluationGuard(POLICY)
        self.apply(guard, 1)
        self.apply(guard, 2, 83.)
        self.assertEqual(self.apply(guard, 3, 83.6, hi=11., sigma=9.)["status"], "OUT_OF_DOMAIN")
        self.assertEqual(self.apply(guard, 4, 83.4)["status"], "SOH_JUMP_ANOMALY")
        self.assertEqual(self.apply(guard, 5, 83.2, sigma=9.)["status"], "MODEL_UNCERTAIN")

    def test_gap_and_out_of_order_cannot_confirm(self):
        guard = EvaluationGuard(POLICY)
        self.apply(guard, 1)
        self.apply(guard, 2, 83.)
        self.assertEqual(self.apply(guard, 5, 83.6)["status"], "SOH_JUMP_ANOMALY")
        self.assertEqual(self.apply(guard, 4, 83.4)["status"], "STALE_INPUT")
        self.assertEqual(self.apply(guard, 6, 83.5)["reason"], "SOH_BASELINE_RESYNCED")

    def test_return_to_baseline_clears_pending(self):
        guard = EvaluationGuard(POLICY)
        self.apply(guard, 1)
        self.apply(guard, 2, 83.)
        self.assertEqual(self.apply(guard, 3, 89.)["status"], "VALID")
        self.assertEqual(self.apply(guard, 4, 83.5)["status"], "SOH_JUMP_ANOMALY")

    def test_missing_or_stale_clears_pending_and_keeps_baseline(self):
        for metadata, status in [({"history_valid": False}, "INSUFFICIENT_HISTORY"),
                                 ({"stale": True}, "STALE_INPUT")]:
            guard = EvaluationGuard(POLICY)
            self.apply(guard, 1)
            self.apply(guard, 2, 83.)
            self.assertEqual(self.apply(guard, 3, 83.6, **metadata)["status"], status)
            self.assertEqual(self.apply(guard, 4, 83.5)["status"], "SOH_JUMP_ANOMALY")

    def test_cells_and_model_versions_do_not_share_state(self):
        guard = EvaluationGuard(POLICY)
        self.apply(guard, 1)
        self.apply(guard, 2, 83.)
        for cell, version in [("1-2", "model"), ("1-1", "model-v2")]:
            self.assertEqual(guard.evaluate(cell, version, 3, [5.], 83.6, 1.)["status"], "VALID")

    def test_unstable_candidate_starts_new_pending_sequence(self):
        guard = EvaluationGuard(POLICY)
        self.apply(guard, 1)
        self.apply(guard, 2, 83.)
        self.assertEqual(self.apply(guard, 3, 80.)["status"], "SOH_JUMP_ANOMALY")
        self.assertEqual(self.apply(guard, 4, 81.)["reason"], "SOH_BASELINE_RESYNCED")

    def test_nonfinite_required_values_never_return_valid(self):
        guard = EvaluationGuard(POLICY)
        self.assertEqual(self.apply(guard, 1, hi=float("nan"))["status"], "MISSING_FEATURE")
        self.assertEqual(self.apply(guard, 2, sigma=float("nan"))["status"], "MODEL_UNCERTAIN")
