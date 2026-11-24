"""P3.8 verification tests: UT-011/UT-11, UT-12, P3-MT-05, P3-IT-01..03, P3-SEC-01 & parity."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
import pyarrow.parquet as pq

from src.soh.evaluation_guard import EvaluationGuard
from src.soh.f5_adapter import F5AdapterConfig, F5SoHAdapter
from src.soh.feature_extractor import FAST, TOP
from src.soh.inference import (
    ChargeSessionInput,
    FrozenSoHInferenceEngine,
    SchemaMismatchError,
    SecurityError,
)
from src.soh.ood import WallClockStalePolicy, parse_aware_utc, sha256_file
from src.soh.output_validation import SoHOutputValidator


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts/soh/model_manifest.json"
SCHEMA_CONTRACT = ROOT / "contracts/soh_inference.schema.json"
PHASE2_ROOT = ROOT.parent / "phase2_soc_delivery"


def _synthetic_charge_session(
    cell_id: str = "1-1",
    cycle_id: int = 10,
    *,
    observed_at: datetime | str | None = None,
    domain_id: str = "RT_BATT_LFP_30C",
    chemistry: str = "LFP",
    cell_model: str = "A123_APR18650M1A",
    nominal_capacity_ah: float = 1.1,
    history_valid: bool = True,
    scale_cc_fast_s: float = 550.0,
    scale_topup_s: float = 320.0,
    scale_cv_s: float = 240.0,
) -> ChargeSessionInput:
    """Build a physically valid canonical RT-Batt-like charge trace (I < 0)."""
    t_fast = np.linspace(0.0, scale_cc_fast_s, 30)
    v_fast = np.linspace(3.10, 3.60, len(t_fast))
    i_fast = np.full(len(t_fast), -5.5)
    s_fast = [FAST] * len(t_fast)

    t_top = np.linspace(t_fast[-1] + 5.0, t_fast[-1] + 5.0 + scale_topup_s, 25)
    v_top = np.linspace(3.40, 3.595, len(t_top))
    i_top = np.full(len(t_top), -1.1)

    t_cv = np.linspace(t_top[-1] + 5.0, t_top[-1] + 5.0 + scale_cv_s, 20)
    v_cv = np.full(len(t_cv), 3.600)
    i_cv = np.linspace(-1.02, -0.055, len(t_cv))

    t = np.concatenate([t_fast, t_top, t_cv])
    v = np.concatenate([v_fast, v_top, v_cv])
    i = np.concatenate([i_fast, i_top, i_cv])
    s = s_fast + [TOP] * (len(t_top) + len(t_cv))
    return ChargeSessionInput(
        cell_id=cell_id,
        cycle_id=cycle_id,
        charge_operation_id=f"{cell_id}-chg-{cycle_id}",
        time_s=t.tolist(),
        voltage_v=v.tolist(),
        current_a=i.tolist(),
        status=s,
        observed_at=observed_at or datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc),
        domain_id=domain_id,
        chemistry=chemistry,
        cell_model=cell_model,
        nominal_capacity_ah=nominal_capacity_ah,
        history_valid=history_valid,
    )


def _check_json_type(value: object, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise AssertionError(f"Unsupported schema type: {expected}")


def _validate_against_schema(value: object, schema: dict, path: str = "$") -> list[str]:
    """Full Draft 2020-12 validator covering all keywords used in contracts/soh_inference.schema.json."""
    errors: list[str] = []
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_check_json_type(value, t) for t in allowed):
            errors.append(f"{path}: expected type {allowed}, got {type(value).__name__} ({value!r})")
            return errors
    if "const" in schema:
        expected = schema["const"]
        if value != expected or type(value) is not type(expected):
            errors.append(f"{path}: expected const {expected!r}, got {value!r}")
    if "enum" in schema:
        if not any(value == item and type(value) is type(item) for item in schema["enum"]):
            errors.append(f"{path}: value {value!r} not in enum {schema['enum']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: string length {len(value)} < minLength {schema['minLength']}")
        if schema.get("format") == "date-time":
            try:
                if parse_aware_utc(value) is None:
                    errors.append(f"{path}: invalid date-time {value!r}")
            except (TypeError, ValueError) as exc:
                errors.append(f"{path}: invalid date-time {value!r} ({exc})")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value {value!r} < minimum {schema['minimum']!r}")
    if isinstance(value, list) and "items" in schema:
        for idx, item in enumerate(value):
            errors.extend(_validate_against_schema(item, schema["items"], f"{path}[{idx}]"))
    if isinstance(value, dict):
        for req in schema.get("required", ()):
            if req not in value:
                errors.append(f"{path}: missing required key {req!r}")
        props = schema.get("properties", {})
        addl = schema.get("additionalProperties", True)
        for key, val in value.items():
            if key in props:
                errors.extend(_validate_against_schema(val, props[key], f"{path}.{key}"))
            elif addl is False:
                errors.append(f"{path}: unexpected additional property {key!r}")
            elif isinstance(addl, dict):
                errors.extend(_validate_against_schema(val, addl, f"{path}.{key}"))
    for branch in schema.get("allOf", ()):
        if "if" in branch:
            cond_errors = _validate_against_schema(value, branch["if"], path)
            if not cond_errors:
                if "then" in branch:
                    errors.extend(_validate_against_schema(value, branch["then"], path))
            else:
                if "else" in branch:
                    errors.extend(_validate_against_schema(value, branch["else"], path))
        else:
            errors.extend(_validate_against_schema(value, branch, path))
    return errors


def _assert_contract(tc: unittest.TestCase, response: dict) -> None:
    contract = json.loads(SCHEMA_CONTRACT.read_text(encoding="utf-8"))
    # Ensure strict JSON serialization (no NaN/Inf)
    json.dumps(response, allow_nan=False)
    schema_errors = _validate_against_schema(response, contract)
    tc.assertEqual(schema_errors, [], f"JSON Schema violations: {schema_errors}")
    try:
        import jsonschema  # type: ignore
    except ImportError:
        jsonschema = None
    if jsonschema is not None:
        jsonschema.Draft202012Validator(contract, format_checker=jsonschema.FormatChecker()).validate(response)


def _load_real_cell_cycle_session(
    cell_id: str = "1-1",
    cycle_id: int = 6,
    *,
    observed_at: datetime | str | None = None,
    domain_id: str = "RT_BATT_LFP_30C",
    chemistry: str = "LFP",
    cell_model: str = "A123_APR18650M1A",
    nominal_capacity_ah: float = 1.1,
) -> ChargeSessionInput:
    trace_path = ROOT / f"data/staging/rt_batt_v2/{cell_id}.parquet"
    trace_tbl = pq.read_table(
        trace_path,
        columns=["cycle_id", "raw_status", "time_s_raw", "voltage_v_raw", "current_ma_raw"],
        filters=[("cycle_id", "=", cycle_id), ("raw_status", "in", [FAST, TOP])],
    )
    return ChargeSessionInput(
        cell_id=cell_id,
        cycle_id=cycle_id,
        charge_operation_id=f"{cell_id}-chg-{cycle_id}",
        time_s=trace_tbl["time_s_raw"].to_numpy().tolist(),
        voltage_v=trace_tbl["voltage_v_raw"].to_numpy().tolist(),
        current_a=(-trace_tbl["current_ma_raw"].to_numpy() / 1000.0).tolist(),
        status=trace_tbl["raw_status"].to_pylist(),
        observed_at=observed_at or datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc),
        domain_id=domain_id,
        chemistry=chemistry,
        cell_model=cell_model,
        nominal_capacity_ah=nominal_capacity_ah,
    )


class P38InferenceAndIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = FrozenSoHInferenceEngine(MANIFEST, project_root=ROOT)

    # UT-011 / UT-11: Frozen RF load, hash verification, feature order, deterministic prediction & budget
    def test_ut011_frozen_rf_load_deterministic_and_budget(self) -> None:
        self.assertLessEqual(self.engine.model_size_bytes, 50_000_000)
        self.assertEqual(
            self.engine.primary_features,
            ("delta_q_350_358_ah", "q_cc_ah", "q_cv_ah", "q_cv_over_q_cc"),
        )
        feat = {
            "delta_q_350_358_ah": 0.030,
            "q_cc_ah": 1.020,
            "q_cv_ah": 0.032,
            "q_cv_over_q_cc": 0.032 / 1.020,
        }
        p1, s1, _, _ = self.engine.predict_from_features(feat)
        reloaded = FrozenSoHInferenceEngine(MANIFEST, project_root=ROOT)
        p2, s2, _, _ = reloaded.predict_from_features(feat)
        self.assertIsNotNone(p1)
        self.assertIsNotNone(s1)
        self.assertTrue(isfinite(p1) and isfinite(s1))
        self.assertAlmostEqual(p1, p2, places=10)
        self.assertAlmostEqual(s1, s2, places=10)

    # UT-12: OOD, sigma, stale wall-clock (D13), non-finite, missing HI, single-sample rejection
    def test_ut12_output_validation_ood_stale_and_insufficient_history(self) -> None:
        validator = SoHOutputValidator(
            self.engine,
            stale_policy=WallClockStalePolicy(max_observation_age_seconds=3600.0, max_future_skew_seconds=5.0),
        )
        t0 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
        in_domain = {
            "delta_q_350_358_ah": 0.030,
            "q_cc_ah": 1.020,
            "q_cv_ah": 0.032,
            "q_cv_over_q_cc": 0.032 / 1.020,
        }
        r1 = validator.evaluate_extracted_features("1-1", 10, in_domain, observed_at=t0, now_utc=t0 + timedelta(seconds=60))
        _assert_contract(self, r1)
        self.assertEqual(r1["status"], "VALID")
        self.assertIn("BASELINE_INITIALIZED", r1["reason_codes"])

        # Wall-clock stale (> 3600 s) -> STALE, soh_percent=null, held value preserved with age
        r_stale = validator.evaluate_extracted_features(
            "1-1", 11, in_domain, observed_at=t0, now_utc=t0 + timedelta(seconds=7200)
        )
        _assert_contract(self, r_stale)
        self.assertEqual(r_stale["status"], "STALE")
        self.assertIn("WALL_CLOCK_STALE", r_stale["reason_codes"])
        self.assertEqual(r_stale["display_mode"], "HELD_STALE")
        self.assertEqual(r_stale["last_valid_soh_percent"], r1["soh_percent"])
        self.assertAlmostEqual(r_stale["last_valid_age_seconds"], 7200.0)

        # Missing/naive/future timestamp in online mode -> STALE
        r_missing_ts = validator.evaluate_extracted_features("1-1", 12, in_domain, observed_at=None, now_utc=t0)
        _assert_contract(self, r_missing_ts)
        self.assertEqual(r_missing_ts["status"], "STALE")
        self.assertIn("MISSING_OBSERVED_AT_TIMESTAMP", r_missing_ts["reason_codes"])

        r_naive_ts = validator.evaluate_extracted_features(
            "1-1", 13, in_domain, observed_at="2026-11-23T08:00:00", now_utc=t0
        )
        _assert_contract(self, r_naive_ts)
        self.assertEqual(r_naive_ts["status"], "STALE")
        self.assertIn("UNTRUSTED_OBSERVED_AT_TIMESTAMP", r_naive_ts["reason_codes"])

        # D13 regression: valid observed_at + naive/malformed caller now_utc -> STALE + UNTRUSTED_REFERENCE_CLOCK
        for bad_now in ("2026-11-23T08:01:00", datetime(2026, 11, 23, 8, 1), "not-a-timestamp"):
            r_bad_ref = validator.evaluate_extracted_features(
                "1-1", 13, in_domain, observed_at=t0, now_utc=bad_now
            )
            _assert_contract(self, r_bad_ref)
            self.assertEqual(r_bad_ref["status"], "STALE")
            self.assertIsNone(r_bad_ref["soh_percent"])
            self.assertIn("UNTRUSTED_REFERENCE_CLOCK", r_bad_ref["reason_codes"])
            self.assertIsNone(r_bad_ref["last_valid_age_seconds"])

        # D13 default boundaries (86400 s age, 5 s future skew) and omitted now_utc fallback
        default_validator = SoHOutputValidator(self.engine)
        r_at_86400 = default_validator.evaluate_extracted_features(
            "1-1-d13", 10, in_domain, observed_at=t0, now_utc=t0 + timedelta(seconds=86400)
        )
        _assert_contract(self, r_at_86400)
        self.assertEqual(r_at_86400["status"], "VALID")

        r_at_86401 = default_validator.evaluate_extracted_features(
            "1-1-d13", 11, in_domain, observed_at=t0, now_utc=t0 + timedelta(seconds=86401)
        )
        _assert_contract(self, r_at_86401)
        self.assertEqual(r_at_86401["status"], "STALE")
        self.assertIn("WALL_CLOCK_STALE", r_at_86401["reason_codes"])

        r_future_5 = default_validator.evaluate_extracted_features(
            "1-1-d13", 12, in_domain, observed_at=t0 + timedelta(seconds=5), now_utc=t0
        )
        _assert_contract(self, r_future_5)
        self.assertEqual(r_future_5["status"], "VALID")

        r_future_6 = default_validator.evaluate_extracted_features(
            "1-1-d13", 13, in_domain, observed_at=t0 + timedelta(seconds=6), now_utc=t0
        )
        _assert_contract(self, r_future_6)
        self.assertEqual(r_future_6["status"], "STALE")
        self.assertIn("FUTURE_OBSERVED_AT_TIMESTAMP", r_future_6["reason_codes"])

        r_omitted_now = default_validator.evaluate_extracted_features(
            "1-1-d13-live", 14, in_domain, observed_at=datetime.now(timezone.utc), now_utc=None
        )
        _assert_contract(self, r_omitted_now)
        self.assertEqual(r_omitted_now["status"], "VALID")

        r_future_ts = validator.evaluate_extracted_features(
            "1-1", 14, in_domain, observed_at=t0 + timedelta(seconds=30), now_utc=t0
        )
        _assert_contract(self, r_future_ts)
        self.assertEqual(r_future_ts["status"], "STALE")
        self.assertIn("FUTURE_OBSERVED_AT_TIMESTAMP", r_future_ts["reason_codes"])

        # OOD (>= 2 weighted feature bounds breached) -> OUT_OF_DOMAIN, soh_percent=null
        ood_feat = {
            "delta_q_350_358_ah": 0.001,
            "q_cc_ah": 0.200,
            "q_cv_ah": 0.032,
            "q_cv_over_q_cc": 0.032 / 0.200,
        }
        r_ood = validator.evaluate_extracted_features("1-1", 15, ood_feat, observed_at=t0, now_utc=t0)
        _assert_contract(self, r_ood)
        self.assertEqual(r_ood["status"], "OUT_OF_DOMAIN")
        self.assertGreaterEqual(len(r_ood["diagnostics"]["ood_violated_features"]), 2)

        # Missing / NaN feature -> MISSING_FEATURE
        nan_feat = dict(in_domain, q_cv_ah=float("nan"))
        r_nan = validator.evaluate_extracted_features("1-1", 16, nan_feat, observed_at=t0, now_utc=t0)
        _assert_contract(self, r_nan)
        self.assertEqual(r_nan["status"], "MISSING_FEATURE")

        # Single instantaneous V/I/T sample -> INSUFFICIENT_HISTORY (never runs SoH on 1 sample)
        single = ChargeSessionInput(
            cell_id="1-1",
            cycle_id=17,
            time_s=[0.0],
            voltage_v=[3.55],
            current_a=[-1.1],
            status=[TOP],
            observed_at=t0,
            domain_id="RT_BATT_LFP_30C",
            chemistry="LFP",
            cell_model="A123_APR18650M1A",
            nominal_capacity_ah=1.1,
        )
        r_single = validator.evaluate_session(single, now_utc=t0)
        _assert_contract(self, r_single)
        self.assertEqual(r_single["status"], "INSUFFICIENT_HISTORY")

        # Positive current during charge -> INVALID_INPUT (sign convention check)
        wrong_sign = _synthetic_charge_session(cell_id="1-1", cycle_id=18, observed_at=t0)
        wrong_sign = ChargeSessionInput(
            cell_id=wrong_sign.cell_id,
            cycle_id=wrong_sign.cycle_id,
            time_s=wrong_sign.time_s,
            voltage_v=wrong_sign.voltage_v,
            current_a=[-x for x in wrong_sign.current_a],
            status=wrong_sign.status,
            observed_at=t0,
            domain_id=wrong_sign.domain_id,
            chemistry=wrong_sign.chemistry,
            cell_model=wrong_sign.cell_model,
            nominal_capacity_ah=wrong_sign.nominal_capacity_ah,
        )
        r_sign = validator.evaluate_session(wrong_sign, now_utc=t0)
        _assert_contract(self, r_sign)
        self.assertEqual(r_sign["status"], "INVALID_INPUT")
        self.assertIn("NONNEGATIVE_CHARGE_CURRENT_SIGN_VIOLATION", r_sign["reason_codes"])

    # P3-MT-05: No-deadlock jump recovery after skipped INSUFFICIENT_HISTORY sessions & restart
    def test_p3_mt_05_jump_resync_after_skipped_sessions_and_restart(self) -> None:
        dev_rows = pq.read_table(
            ROOT / "data/features/soh_feature_table.parquet",
            filters=[("cell_id", "=", "1-1")],
        ).to_pylist()
        primary = self.engine.primary_features
        high_soh = {f: dev_rows[0][f] for f in primary}
        # Pick a real degraded late-life cycle of cell 1-1 that is in-domain and differs by > 5 pp
        low_soh = None
        high_pred, _, _, _ = self.engine.predict_from_features(high_soh)
        for cand in reversed(dev_rows):
            fmap = {f: cand[f] for f in primary}
            pred, sigma, vec, _ = self.engine.predict_from_features(fmap)
            if (
                pred is not None
                and sigma is not None
                and abs(pred - high_pred) > 8.0
                and EvaluationGuard(self.engine.ood_policy).model_status(vec, sigma) is None
            ):
                low_soh = fmap
                break
        self.assertIsNotNone(low_soh, "Expected a real degraded in-domain cycle in dev cell 1-1")

        validator = SoHOutputValidator(self.engine)
        t0 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
        r_init = validator.evaluate_extracted_features("1-1-sim", 10, high_soh, observed_at=t0, now_utc=t0)
        self.assertEqual(r_init["status"], "VALID")

        # Skipped sessions marked INSUFFICIENT_HISTORY cannot resync
        r_skip = validator.evaluate_extracted_features(
            "1-1-sim", 50, low_soh, observed_at=t0 + timedelta(hours=1), now_utc=t0 + timedelta(hours=1), history_valid=False
        )
        self.assertEqual(r_skip["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(r_skip["last_valid_soh_percent"], r_init["soh_percent"])

        # First valid prediction after large true degradation jump -> SOH_JUMP_ANOMALY (pending k=1)
        r_jump1 = validator.evaluate_extracted_features(
            "1-1-sim", 51, low_soh, observed_at=t0 + timedelta(hours=2), now_utc=t0 + timedelta(hours=2)
        )
        _assert_contract(self, r_jump1)
        self.assertEqual(r_jump1["status"], "SOH_JUMP_ANOMALY")
        self.assertIsNone(r_jump1["soh_percent"])
        self.assertEqual(r_jump1["display_mode"], "HELD_STALE")
        self.assertEqual(r_jump1["diagnostics"]["confirmation_count"], 1)

        # Persist state across restart and receive K=2nd stable eligible observation -> VALID + SOH_BASELINE_RESYNCED
        snap = validator.snapshot()
        restored = SoHOutputValidator(self.engine, snapshot=snap)
        r_resync = restored.evaluate_extracted_features(
            "1-1-sim", 52, low_soh, observed_at=t0 + timedelta(hours=3), now_utc=t0 + timedelta(hours=3)
        )
        _assert_contract(self, r_resync)
        self.assertEqual(r_resync["status"], "VALID")
        self.assertIn("SOH_BASELINE_RESYNCED", r_resync["reason_codes"])
        self.assertEqual(r_resync["baseline_version"], 2)
        self.assertEqual(r_resync["diagnostics"]["confirmation_count"], 2)
        self.assertAlmostEqual(r_resync["diagnostics"]["previous_baseline_pp"], r_init["soh_percent"])
        self.assertGreater(abs(r_resync["soh_percent"] - r_init["soh_percent"]), 5.0)

    # P3-IT-01: F3 -> F5 monitoring display & Phase 1 SoHEstimator compatibility
    def test_p3_it_01_f3_to_f5_and_phase1_compat(self) -> None:
        cfg = F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT)
        adapter = F5SoHAdapter(cfg)
        self.assertTrue(adapter.is_ready)

        # Phase 1 default call pattern (historical_data=None, config=None) -> NOT_READY
        p1_empty = adapter.estimate(None, None)
        status_val = p1_empty["status"] if isinstance(p1_empty, dict) else p1_empty.status
        self.assertEqual(status_val, "NOT_READY")

        t0 = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
        session = _synthetic_charge_session(cell_id="1-1", cycle_id=20, observed_at=t0)
        resp = adapter.evaluate_charge_session(session, now_utc=t0 + timedelta(seconds=10))
        _assert_contract(self, resp)
        self.assertEqual(resp["status"], "VALID")

        display_ok = adapter.to_f5_display_record(resp, now_utc=t0 + timedelta(seconds=10))
        self.assertEqual(display_ok["display_mode"], "CURRENT_VALID")
        self.assertEqual(display_ok["current_soh_percent"], resp["soh_percent"])
        self.assertIsNone(display_ok["held_last_valid_soh_percent"])
        self.assertAlmostEqual(display_ok["last_valid_age_seconds"], 10.0)

        # P3-IT-01 regression: re-displaying the exact same VALID response at 24h vs 25h with no new charge
        display_24h = adapter.to_f5_display_record(resp, now_utc=t0 + timedelta(seconds=86400))
        self.assertEqual(display_24h["status"], "VALID")
        self.assertEqual(display_24h["display_mode"], "CURRENT_VALID")
        self.assertEqual(display_24h["current_soh_percent"], resp["soh_percent"])
        self.assertIsNone(display_24h["held_last_valid_soh_percent"])
        self.assertAlmostEqual(display_24h["last_valid_age_seconds"], 86400.0)

        for display_25h in (
            adapter.to_f5_display_record(resp, now_utc=t0 + timedelta(hours=25)),
            F5SoHAdapter.to_f5_display_record(resp, now_utc=t0 + timedelta(hours=25)),
        ):
            self.assertEqual(display_25h["status"], "STALE")
            self.assertEqual(display_25h["display_mode"], "HELD_STALE")
            self.assertIsNone(display_25h["current_soh_percent"])
            self.assertEqual(display_25h["held_last_valid_soh_percent"], resp["soh_percent"])
            self.assertAlmostEqual(display_25h["last_valid_age_seconds"], 90000.0)
            self.assertIn("WALL_CLOCK_STALE", display_25h["reason_codes"])

        # Naive display-time reference clock must also demote VALID to HELD_STALE
        display_naive_now = adapter.to_f5_display_record(resp, now_utc="2026-11-24T10:00:00")
        self.assertEqual(display_naive_now["status"], "STALE")
        self.assertEqual(display_naive_now["display_mode"], "HELD_STALE")
        self.assertIsNone(display_naive_now["current_soh_percent"])
        self.assertEqual(display_naive_now["held_last_valid_soh_percent"], resp["soh_percent"])
        self.assertIn("UNTRUSTED_REFERENCE_CLOCK", display_naive_now["reason_codes"])

        # Follow-up stale session -> F5 separates current (null) vs held_last_valid_soh_percent
        stale_session = _synthetic_charge_session(cell_id="1-1", cycle_id=21, observed_at=t0)
        resp_stale = adapter.evaluate_charge_session(stale_session, now_utc=t0 + timedelta(days=3))
        _assert_contract(self, resp_stale)
        display_stale = adapter.to_f5_display_record(resp_stale, now_utc=t0 + timedelta(days=3))
        self.assertEqual(display_stale["status"], "STALE")
        self.assertEqual(display_stale["display_mode"], "HELD_STALE")
        self.assertIsNone(display_stale["current_soh_percent"])
        self.assertEqual(display_stale["held_last_valid_soh_percent"], resp["soh_percent"])
        self.assertGreater(display_stale["last_valid_age_seconds"], 86400.0)

    # P3-IT-02: F3 -> F2 capacity feedback disabled (D09) and Phase 2 Q_model/ER4 artifacts untouched
    def test_p3_it_02_f3_to_f2_feedback_disabled_and_phase2_immutable(self) -> None:
        with self.assertRaises(ValueError):
            F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT, f3_to_f2_capacity_feedback=True)

        p2_files = [
            PHASE2_ROOT / "artifacts/capacity_metadata.json",
            PHASE2_ROOT / "results/p25/ekf_config.json",
            PHASE2_ROOT / "results/p26/metrics.json",
        ]
        existing_p2 = [p for p in p2_files if p.is_file()]
        before_hashes = {p: sha256_file(p) for p in existing_p2}

        adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT))
        t0 = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
        resp = adapter.evaluate_charge_session(_synthetic_charge_session(observed_at=t0), now_utc=t0)
        self.assertIs(resp["f3_to_f2_capacity_feedback"], False)

        after_hashes = {p: sha256_file(p) for p in existing_p2}
        self.assertEqual(before_hashes, after_hashes)

    # P3-IT-03: Device domain guard enforces strict allowlist (rejects Lishen AND unknown cell_model)
    def test_p3_it_03_device_domain_guard_rejects_lishen_and_unknown_model(self) -> None:
        adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT))
        t0 = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
        lishen = _synthetic_charge_session(
            cell_id="lishen-2s1p-cell1",
            cycle_id=1,
            observed_at=t0,
            domain_id="LISHEN_2S1P_LAB",
            chemistry="NMC",
            cell_model="Lishen_LR18650_2S1P",
            nominal_capacity_ah=2.5,
        )
        resp = adapter.evaluate_charge_session(lishen, now_utc=t0)
        _assert_contract(self, resp)
        self.assertEqual(resp["status"], "NOT_VALIDATED_FOR_DEVICE")
        self.assertIsNone(resp["soh_percent"])
        self.assertEqual(resp["display_mode"], "UNAVAILABLE")
        self.assertIs(resp["hardware_validated"], False)

        # Real cell 1-1 cycle 6: supported model returns VALID; changing only cell_model -> UNKNOWN must fail allowlist
        real_valid = _load_real_cell_cycle_session("1-1", 6, observed_at=t0)
        resp_valid = adapter.evaluate_charge_session(real_valid, now_utc=t0 + timedelta(seconds=5))
        _assert_contract(self, resp_valid)
        self.assertEqual(resp_valid["status"], "VALID")
        self.assertIsNotNone(resp_valid["soh_percent"])

        for bad_model, expected_reason in (
            ("UNKNOWN", "UNVALIDATED_DEVICE:UNKNOWN"),
            ("", "MISSING_CELL_MODEL"),
            ("A123_OTHER", "UNVALIDATED_DEVICE:A123_OTHER"),
        ):
            unknown_adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT))
            real_unknown = _load_real_cell_cycle_session("1-1", 6, observed_at=t0, cell_model=bad_model)
            resp_unknown = unknown_adapter.evaluate_charge_session(real_unknown, now_utc=t0 + timedelta(seconds=5))
            _assert_contract(self, resp_unknown)
            self.assertEqual(resp_unknown["status"], "NOT_VALIDATED_FOR_DEVICE")
            self.assertIsNone(resp_unknown["soh_percent"])
            self.assertEqual(resp_unknown["display_mode"], "UNAVAILABLE")
            self.assertIn(expected_reason, resp_unknown["reason_codes"])

        # Fail-closed P3-IT-03 regression: omitting all 4 device metadata fields on real cell 1-1 cycle 6 must NOT default to RT-Batt/A123
        missing_meta_adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT))
        omitted_meta_session = ChargeSessionInput(
            cell_id=real_valid.cell_id,
            cycle_id=real_valid.cycle_id,
            charge_operation_id="1-1-chg-6-missing-meta",
            time_s=real_valid.time_s,
            voltage_v=real_valid.voltage_v,
            current_a=real_valid.current_a,
            status=real_valid.status,
            observed_at=t0,
        )
        resp_missing_meta = missing_meta_adapter.evaluate_charge_session(
            omitted_meta_session, now_utc=t0 + timedelta(seconds=5)
        )
        _assert_contract(self, resp_missing_meta)
        self.assertEqual(resp_missing_meta["status"], "NOT_VALIDATED_FOR_DEVICE")
        self.assertIsNone(resp_missing_meta["soh_percent"])
        self.assertEqual(resp_missing_meta["display_mode"], "UNAVAILABLE")
        self.assertEqual(
            resp_missing_meta["reason_codes"],
            [
                "MISSING_DOMAIN_ID",
                "MISSING_CHEMISTRY",
                "MISSING_CELL_MODEL",
                "MISSING_NOMINAL_CAPACITY_AH",
            ],
        )

        # Partial metadata (omitting any single field) must also fail closed
        for omitted_field, expected_code in (
            ("domain_id", "MISSING_DOMAIN_ID"),
            ("chemistry", "MISSING_CHEMISTRY"),
            ("cell_model", "MISSING_CELL_MODEL"),
            ("nominal_capacity_ah", "MISSING_NOMINAL_CAPACITY_AH"),
        ):
            kwargs = {
                "domain_id": "RT_BATT_LFP_30C",
                "chemistry": "LFP",
                "cell_model": "A123_APR18650M1A",
                "nominal_capacity_ah": 1.1,
            }
            kwargs.pop(omitted_field)
            partial_session = ChargeSessionInput(
                cell_id=real_valid.cell_id,
                cycle_id=real_valid.cycle_id,
                time_s=real_valid.time_s,
                voltage_v=real_valid.voltage_v,
                current_a=real_valid.current_a,
                status=real_valid.status,
                observed_at=t0,
                **kwargs,
            )
            resp_partial = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT)).evaluate_charge_session(
                partial_session, now_utc=t0 + timedelta(seconds=5)
            )
            _assert_contract(self, resp_partial)
            self.assertEqual(resp_partial["status"], "NOT_VALIDATED_FOR_DEVICE")
            self.assertIsNone(resp_partial["soh_percent"])
            self.assertIn(expected_code, resp_partial["reason_codes"])

    # F3 -> F5 contract regression: empty/whitespace cell_id returns schema-valid INVALID_INPUT with cell_id=null
    def test_f3_to_f5_error_response_contract_for_missing_cell_id(self) -> None:
        adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT))
        t0 = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
        for bad_cell_id in ("", "   "):
            session = _synthetic_charge_session(cell_id=bad_cell_id, cycle_id=1, observed_at=t0)
            resp = adapter.evaluate_charge_session(session, now_utc=t0)
            _assert_contract(self, resp)
            self.assertEqual(resp["status"], "INVALID_INPUT")
            self.assertIsNone(resp["cell_id"])
            self.assertIsNone(resp["soh_percent"])
            self.assertEqual(resp["display_mode"], "UNAVAILABLE")
            self.assertIn("MISSING_CELL_ID", resp["reason_codes"])

        # Negative meta-check: confirm our full schema validator rejects empty string cell_id and VALID with null cell_id
        contract = json.loads(SCHEMA_CONTRACT.read_text(encoding="utf-8"))
        bad_empty = dict(resp, cell_id="")
        self.assertTrue(_validate_against_schema(bad_empty, contract))
        valid_resp = adapter.evaluate_charge_session(_synthetic_charge_session(cell_id="1-1", cycle_id=2, observed_at=t0), now_utc=t0)
        _assert_contract(self, valid_resp)
        bad_valid_null = dict(valid_resp, cell_id=None)
        self.assertTrue(_validate_against_schema(bad_valid_null, contract))

    # P3-SEC-01: Reject tampered hash, remote URI, raw .pkl, and schema mismatch
    def test_p3_sec_01_rejects_tampered_untrusted_or_pickle_artifacts(self) -> None:
        base_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="p38-sec-") as tmp:
            tmp_dir = Path(tmp)
            # 1. Tampered RF SHA-256
            bad_hash = json.loads(json.dumps(base_manifest))
            bad_hash["artifacts"]["rf_model"]["sha256"] = "0" * 64
            bad_hash_path = tmp_dir / "bad_hash_manifest.json"
            bad_hash_path.write_text(json.dumps(bad_hash), encoding="utf-8")
            with self.assertRaises(SecurityError):
                FrozenSoHInferenceEngine(bad_hash_path, project_root=ROOT)

            # Safe adapter returns MODEL_NOT_READY without crashing
            bad_adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=bad_hash_path, project_root=ROOT))
            self.assertFalse(bad_adapter.is_ready)
            resp = bad_adapter.evaluate_charge_session(_synthetic_charge_session())
            _assert_contract(self, resp)
            self.assertEqual(resp["status"], "MODEL_NOT_READY")

            # 2. Remote URI rejected
            remote_m = json.loads(json.dumps(base_manifest))
            remote_m["artifacts"]["rf_model"]["path"] = "https://example.com/rf_model.joblib"
            remote_path = tmp_dir / "remote_manifest.json"
            remote_path.write_text(json.dumps(remote_m), encoding="utf-8")
            with self.assertRaises(SecurityError):
                FrozenSoHInferenceEngine(remote_path, project_root=ROOT)

            # 3. Raw .pkl rejected
            pkl_m = json.loads(json.dumps(base_manifest))
            pkl_m["artifacts"]["rf_model"]["path"] = "data/raw/rt_batt/v2/1-1.pkl"
            pkl_path = tmp_dir / "pkl_manifest.json"
            pkl_path.write_text(json.dumps(pkl_m), encoding="utf-8")
            with self.assertRaises(SecurityError):
                FrozenSoHInferenceEngine(pkl_path, project_root=ROOT)

            # 4. Feature order mismatch rejected with SchemaMismatchError
            bad_schema = json.loads(json.dumps(base_manifest))
            bad_schema["primary_features"] = list(reversed(bad_schema["primary_features"]))
            bad_schema_path = tmp_dir / "bad_schema_manifest.json"
            bad_schema_path.write_text(json.dumps(bad_schema), encoding="utf-8")
            with self.assertRaises(SchemaMismatchError):
                FrozenSoHInferenceEngine(bad_schema_path, project_root=ROOT)

    # Parity test: Packaged F3.3 + F3.4 matches frozen P3.6/P3.7 EvaluationGuard replay exactly
    def test_packaged_f34_matches_p37_saved_predictions_subset(self) -> None:
        pred_path = ROOT / "reports/P3_7_HELDOUT_PREDICTIONS.parquet"
        if not pred_path.is_file():
            self.skipTest("P3.7 saved predictions parquet not present")
        table = pq.read_table(pred_path, filters=[("cell_id", "=", "8-6")]).to_pylist()
        validator = SoHOutputValidator(self.engine)
        direct_guard = EvaluationGuard(self.engine.ood_policy)
        for row in table[:100]:
            feats = {name: row[name] for name in self.engine.primary_features}
            res = validator.evaluate_extracted_features(
                row["cell_id"], row["cycle_id"], feats, offline_cycle_replay=True
            )
            ref = direct_guard.evaluate(
                row["cell_id"],
                self.engine.model_version,
                row["cycle_id"],
                [row[name] for name in self.engine.primary_features],
                row["rf_raw"],
                row["sigma_trees_pp"],
                stale=False,
            )
            self.assertEqual(res["diagnostics"]["guard_status"], row["status"])
            self.assertEqual(res["diagnostics"]["guard_status"], ref["status"])
            self.assertAlmostEqual(res["diagnostics"]["raw_soh_percent"], row["rf_raw"], places=10)
            self.assertAlmostEqual(res["diagnostics"]["sigma_trees_pp"], row["sigma_trees_pp"], places=10)
            if row["soh_percent"] is None:
                self.assertIsNone(res["soh_percent"])
            else:
                self.assertAlmostEqual(res["soh_percent"], row["soh_percent"], places=10)


if __name__ == "__main__":
    unittest.main()

