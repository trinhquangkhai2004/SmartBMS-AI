"""Synthetic 1-RC tests. No field measurements or reference trajectories are read."""
import math
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.ekf import EKF, OCV, FixedRC


def estimator(z=0.5, vrc=0.0, **options):
    args = dict(p0_diag=(0.01, 0.001), q_per_s_diag=(1e-7, 2e-6),
                r_v2=0.0025, max_gap_active_s=3.0,
                model_version="synthetic", approval_record_id="unit-test")
    args.update(options)
    ocv = args.pop("ocv", OCV([0, 0.5, 1], [3, 3.5, 4]))
    ekf = EKF(FixedRC(0.1, 0.03, 700, 2), ocv, **args)
    ekf.reset(z, vrc, run_id="synthetic-run")
    return ekf


class StreamingEKFTests(unittest.TestCase):
    def test_first_observation_and_current_alignment(self):
        e = estimator()
        r0 = e.update(1000, 2, 3.3)
        self.assertEqual(r0["status"], "VALID")
        self.assertEqual(r0["z_pred"], 0.5)
        self.assertAlmostEqual(r0["innovation_v"], 0)
        a = math.exp(-2/21)
        z = 0.5 - 4/7200
        vrc = 0.03 * (1-a)*2
        voltage = 3 + z - vrc + 0.1
        r1 = e.update(1002, -1, voltage)
        self.assertAlmostEqual(r1["z_pred"], z)
        self.assertAlmostEqual(r1["voltage_pred_v"], voltage)
        self.assertAlmostEqual(r1["soc_pct"], 100*z)

    def test_duplicate_transition_and_no_extra_charge(self):
        e = estimator()
        a = e.update(0, 0, 3.5, step=1)
        for kw in (dict(step=1), dict(step=2)):
            repeated = e.update(0, 0, 3.5, **kw)
            self.assertFalse(repeated["corrected"])
            self.assertEqual(repeated["p_zz"], a["p_zz"])
        changed = e.update(0, 2, 3.3, step=3)
        self.assertTrue(changed["corrected"])
        self.assertEqual(changed["z_pred"], a["soc_pct"]/100)
        self.assertFalse(e.update(0, 2, 3.3, step=3)["corrected"])
        self.assertAlmostEqual(e.update(1, 0, 3.5)["z_pred"], 0.5-2/7200)

    def test_unobserved_gap_requires_prior_and_verified_rest_decays(self):
        for current in (0, 1.4):
            e = estimator()
            e.update(0, current, 3.5-0.1*current)
            self.assertEqual(e.update(60, current, 3.5)["status"], "GAP_UNOBSERVED")
            self.assertEqual(e.update(61, 0, 3.5)["status"], "NOT_READY")
            e.reset(0.3, run_id="reset")
            self.assertAlmostEqual(e.update(200, 0, 3.3)["soc_pct"], 30)
        e = estimator(vrc=0.1)
        e.update(0, 0, 3.4)
        end = 3.5-0.1*math.exp(-60/21)
        r = e.update(60, 1, end-0.1, interval="verified_rest")
        self.assertAlmostEqual(r["voltage_pred_v"], end-0.1)
        self.assertAlmostEqual(r["z_pred"], 0.5)

    def test_same_time_current_change_is_kept_for_next_interval(self):
        e = estimator()
        e.update(0, 0, 3.5, step=1)
        self.assertFalse(e.update(0, 1, 3.4, step=1)["corrected"])
        self.assertAlmostEqual(e.update(1, 0, 3.5)["z_pred"], 0.5-1/7200)

    def test_accepts_source_verified_transition_without_step_renumbering(self):
        e = estimator()
        e.update(0, 0, 3.5, clock_event="FIRST")
        self.assertTrue(e.update(0, 1, 3.4, clock_event="ZERO_DT_NEW_TRANSITION")["corrected"])
        self.assertFalse(e.update(0, 1, 3.4, clock_event="DUPLICATE_OBSERVATION")["corrected"])

    def test_verified_constant_load_and_active_current_domain(self):
        e = estimator(current_range_a=(-2, 2))
        e.update(0, 1, 3.4)
        row = e.update(60, 3, 3., interval="verified_constant_current")
        self.assertEqual(row["status"], "OUT_OF_DOMAIN")
        self.assertAlmostEqual(row["z_pred"], 0.5-60/7200)

    def test_missing_voltage_same_time_keeps_status_and_missing_temperature_degrades(self):
        e = estimator()
        e.update(10, 0, 3.5)
        r = e.update(10, 0, None)
        self.assertEqual(r["status"], "INVALID_INPUT")
        self.assertIsNone(r["warning_flag"])
        self.assertEqual(e.update(11, 1, 3.4, temperature_c=0)["status"], "OUT_OF_DOMAIN")
        self.assertEqual(e.update(12, 1, 3.4, temperature_c=None)["status"], "INVALID_INPUT")

    def test_nonfinite_reset_backwards_and_missing_current(self):
        e = estimator()
        e.update(0, 0, 3.5)
        self.assertEqual(e.update(-1, 0, 3.5)["status"], "INVALID_INPUT")
        r = e.update(1, 1, float("nan"))
        self.assertEqual(r["status"], "INVALID_INPUT")
        self.assertIsNone(r["LOW_SOC_MODEL_UNCERTAIN"])
        self.assertAlmostEqual(e.update(2, 0, 3.5)["z_pred"], 0.5-1/7200)
        self.assertEqual(e.update(3, None, 3.5)["status"], "INVALID_INPUT")
        self.assertEqual(e.update(4, 1, 3.5)["status"], "NOT_READY")
        with self.assertRaises(ValueError):
            e.reset(float("nan"), run_id="invalid")

    def test_voltage_flag_does_not_change_kalman_gain_or_covariance(self):
        for v, flag in [(3.29759, True), (3.29760, False), (3.29761, False), (2.50, True)]:
            e = estimator()
            r = e.update(0, 0, v)
            expected_gain = 0.01/(0.01+0.001+0.0025)
            self.assertEqual(r["status"], "VALID")
            self.assertIs(r["LOW_SOC_MODEL_UNCERTAIN"], flag)
            self.assertAlmostEqual(r["z_unconstrained"], 0.5+expected_gain*(v-3.5))
            self.assertAlmostEqual(r["p_zz"], (1-expected_gain)*0.01)

    def test_physical_projection_and_separate_ocv_domain(self):
        e = estimator()
        r = e.update(0, 0, 5)
        self.assertGreater(r["z_unconstrained"], 1)
        self.assertTrue(r["boundary_projected"])
        self.assertGreater(r["boundary_overshoot"], 0)
        self.assertEqual(e.update(1, 0, 4)["z_pred"], 1)
        e = estimator(z=0.15, ocv=OCV([0.2, 0.8], [3.2, 3.8]))
        result = e.update(0, -1, 3.15)
        self.assertEqual(result["status"], "OUT_OF_DOMAIN")
        self.assertFalse(result["corrected"])
        self.assertIsNone(result["innovation_v"])

    def test_pchip_derivative_jacobians_and_plateau(self):
        curve = OCV([0, 0.2, 0.5, 0.8, 1], [3, 3.5, 3.5, 3.65, 4.2])
        for z in (0.12, 0.3, 0.53, 0.75, 0.92):
            h = 1e-6
            voltage, slope = curve.evaluate(z)
            numerical = (curve.evaluate(z+h)[0]-curve.evaluate(z-h)[0])/(2*h)
            self.assertAlmostEqual(slope, numerical, places=7)
        self.assertAlmostEqual(curve.evaluate(0.3)[1], 0.0)
        with self.assertRaises(ValueError):
            curve.evaluate(1.00001)
        e = estimator(ocv=curve)
        r = e.update(0, 1, 3.4)
        self.assertEqual(r["h_z"], curve.evaluate(0.5)[1])
        self.assertEqual(r["h_vrc"], -1)
        next_r = e.update(2, 0, 3.5)
        h = 1e-6
        def predicted(z, vrc):
            a = math.exp(-2/(0.03*700))
            return (z-2/7200, a*vrc+0.03*(1-a))
        self.assertAlmostEqual((predicted(.5+h, .1)[0]-predicted(.5-h, .1)[0])/(2*h),1)
        self.assertAlmostEqual((predicted(.5,.1+h)[1]-predicted(.5,.1-h)[1])/(2*h),
                               next_r["f_vrc"])

    def test_finite_psd_and_run_isolation(self):
        e = estimator()
        for j in range(300):
            r = e.update(j*0.5, math.sin(j), 3.5+0.07*math.cos(j))
            a,b,c = (r[key] for key in ("p_zz", "p_zv", "p_vv"))
            self.assertTrue(all(map(math.isfinite, (a,b,c))))
            self.assertGreaterEqual(min(a,c,a*c-b*b), -1e-16)
        e.reset(.1, run_id="second")
        self.assertAlmostEqual(e.update(5000, 0, 3.1)["soc_pct"], 10)

    def test_default_denial_source_integrity_gates_and_audit(self):
        from src.ekf import load_research_ecm
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            candidate = folder/"ecm_params.json"
            candidate.write_text(json.dumps({"lock_status":"NEEDS_REVIEW_NOT_RELEASED",
                                              "synthetic":True}), encoding="utf-8")
            audit = folder/"guard.jsonl"
            pin = hashlib.sha256(candidate.read_bytes()).hexdigest()
            approval = dict(approval_record_id="unit-test", decision="APPROVED_CONDITIONAL",
                            approval_source="synthetic fixture", scope=["P2.4","P2.5"],
                            scientific_release=False, conditional_execution_allowed=True,
                            ecm_sha256=pin)
            policy = dict(approval_record_id="unit-test", warning_threshold_v=3.2976,
                          scientific_release=False, ecm_sha256=pin)
            args = dict(approval=approval, policy=policy, profile="DST", audit_log=audit)
            with self.assertRaises(PermissionError):
                load_research_ecm(candidate, **args)
            with self.assertRaises(PermissionError):
                load_research_ecm(candidate, **{**args, "profile":"US06"}, research_opt_in=True)
            data = load_research_ecm(candidate, **args, research_opt_in=True)
            self.assertIs(data["synthetic"], True)
            before = candidate.read_bytes()
            candidate.write_bytes(before + b" ")
            with self.assertRaises(ValueError):
                load_research_ecm(candidate, **args, research_opt_in=True)
            entries = [json.loads(s) for s in audit.read_text().splitlines()]
            self.assertEqual([r["decision"] for r in entries],["DENY","DENY","ALLOW","DENY"])
            self.assertEqual(entries[2]["actual_ecm_sha256"], pin)
            self.assertEqual(candidate.read_bytes(), before + b" ")


if __name__ == "__main__":
    unittest.main()
