"""Offline contract smoke tests. Set PYTHONPATH to the actual Phase 1 repo."""
import importlib.util
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("app"), "Requires the separate Phase 1 repository")
class Phase1AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import schemas
        from src.ekf import EKF, FixedRC, OCV
        from src.phase1_adapter import Phase1ReplayAdapter, ReplayConfig

        fixture_path = Path(schemas.__file__).resolve().parents[1] / "sample_data" / "telemetry_1s.jsonl"
        cls.samples = [schemas.Telemetry.model_validate_json(line)
                       for line in fixture_path.read_text(encoding="utf-8").splitlines()]
        cls.config = ReplayConfig(
            cls.samples[0].device_id, cls.samples[0].session_id,
            cls.samples[0].sequence_id, 0.5, 0.0,
            lambda: EKF(FixedRC(0.1, 0.03, 700, 2), OCV([0, 1], [3, 4]),
                        p0_diag=(0.01, 0.001), q_per_s_diag=(1e-7, 2e-6),
                        r_v2=0.0025, max_gap_active_s=3.0,
                        model_version="synthetic-interface-test", approval_record_id="test-only"),
        )
        cls.adapter = Phase1ReplayAdapter()

    def changed(self, sample, **updates):
        from app.schemas import Telemetry
        return Telemetry.model_validate({**sample.model_dump(), **updates})

    def test_native_fixture_remains_outside_calibration_temperature(self):
        rows = list(self.adapter.replay(self.samples, self.config))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r.diagnostics["status"] == "OUT_OF_DOMAIN" for r in rows))
        self.assertTrue(all(r.estimation.status == "INVALID_INPUT" and r.estimation.value_pct is None
                            for r in rows))
        self.assertEqual(self.adapter.estimate([self.samples[0]], None).status, "NOT_READY")

    def test_actual_phase1_state_projection_without_offline_config(self):
        from datetime import datetime, timezone
        from unittest.mock import Mock
        from app.estimators import NotReadyEstimator
        from app.schemas import MeasurementRecord
        from app.state import latest_state

        sample = self.samples[0]
        now = datetime(2026, 11, 19, tzinfo=timezone.utc)
        repo = Mock()
        repo.latest.return_value = MeasurementRecord(id=1, received_at_utc=now,
                                                     measurement_status="VALID", payload=sample)
        state = latest_state(repo, sample.device_id, lambda: now, 5, self.adapter, NotReadyEstimator())
        self.assertEqual(state.connectivity_status, "LIVE")
        self.assertEqual((state.soc.status, state.soc.value_pct), ("NOT_READY", None))
        self.assertEqual(state.active_warnings, sample.warnings)

    def test_synthetic_25c_window_uses_real_time_current_and_contract(self):
        from app.schemas import EstimationResult
        samples = [self.changed(s, temperatures_c=[25.0]) for s in self.samples]
        steps = list(self.adapter.replay(samples, self.config))
        self.assertEqual([r.diagnostics["dt_s"] for r in steps], [0.0, 1.0, 1.0])
        self.assertAlmostEqual(steps[1].diagnostics["z_pred"],
                               steps[0].estimation.value_pct / 100 - 0.72 / 7200)
        last = self.adapter.estimate(samples, self.config)
        self.assertEqual(last, steps[-1].estimation)
        self.assertEqual(last, EstimationResult.model_validate_json(last.model_dump_json()))
        self.assertEqual((last.status, last.scope, last.updated_at), ("VALID", "CELL", None))
        self.assertEqual(self.adapter.estimate([], self.config).status, "NOT_READY")

    def test_flag_is_visible_offline_and_never_enters_phase1_warning_enum(self):
        sample = self.changed(self.samples[0], temperatures_c=[25.0], cell_voltages_v=[3.29759])
        (step,) = self.adapter.replay([sample], self.config)
        self.assertEqual((step.estimation.status, step.estimation.value_pct), ("NOT_READY", None))
        self.assertEqual(step.diagnostics["status"], "VALID")
        self.assertIsNotNone(step.diagnostics["soc_pct"])
        self.assertIs(step.diagnostics["LOW_SOC_MODEL_UNCERTAIN"], True)
        self.assertEqual(sample.warnings, [])
        threshold = self.changed(sample, cell_voltages_v=[3.2976])
        self.assertEqual(self.adapter.estimate([threshold], self.config).status, "VALID")

    def test_rejects_unsupported_or_discontinuous_data(self):
        s = self.samples[0]
        invalid = s.validity.model_dump()
        invalid["voltage"] = False
        for edits in [
            {"source": "HARDWARE"}, {"cell_count": 2, "cell_voltages_v": [3.8, 3.8]},
            {"temperatures_c": [25, 25]}, {"device_id": "other"}, {"session_id": "new"},
            {"validity": invalid}, {"sequence_id": 8},
        ]:
            with self.subTest(edits=edits):
                result = self.adapter.estimate([self.changed(s, **edits)], self.config)
                self.assertEqual((result.status, result.value_pct), ("INVALID_INPUT", None))
        for bad_window in [[s, s], [s, self.samples[2]],
                           [self.changed(s, uptime_ms=1001), self.samples[1]]]:
            self.assertEqual(self.adapter.estimate(bad_window, self.config).status, "INVALID_INPUT")

    def test_unobserved_gap_requires_prior(self):
        samples = [self.changed(s, temperatures_c=[25.0], uptime_ms=t)
                   for s, t in zip(self.samples, [0, 5000, 6000])]
        rows = list(self.adapter.replay(samples, self.config))
        self.assertEqual([r.diagnostics["status"] for r in rows],
                         ["VALID", "GAP_UNOBSERVED", "NOT_READY"])
        self.assertEqual([r.estimation.status for r in rows], ["VALID", "NOT_READY", "NOT_READY"])
