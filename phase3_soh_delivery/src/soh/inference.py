"""F3.1 input validation, F3.2 feature extraction, and F3.3 frozen RF inference.

Loads only trusted local artifacts whose SHA-256 hashes match artifacts/soh/model_manifest.json.
Never loads raw .pkl datasets or unverified joblib files.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from math import isfinite
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np

from src.soh.feature_extractor import FAST, TOP, extract_charge
from src.soh.ood import (
    ensure_local_trusted_path,
    load_verified_ood_policy,
    sha256_file,
    violated_weighted_features,
)


SUPPORTED_DOMAIN_ID = "RT_BATT_LFP_30C"
SUPPORTED_CELL_MODEL = "A123_APR18650M1A"
TRAINING_DOMAIN_LABEL = "RT-Batt LFP, 30C experimental domain"
DEFAULT_REFERENCE_DEFINITION = "cell_relative_operational_capacity (100 * Q_discharge_next / median(Q_1..Q_5))"


class SecurityError(RuntimeError):
    """Raised when an untrusted, remote, pickle, or hash-mismatched artifact is requested."""


class SchemaMismatchError(ValueError):
    """Raised when frozen model, feature schema, or guard policy disagree."""


@dataclass(frozen=True)
class ChargeSessionInput:
    """Validated end-of-charge input for one physical cell (canonical F2/F3 units)."""

    cell_id: str
    cycle_id: int
    time_s: Sequence[float]
    voltage_v: Sequence[float]
    current_a: Sequence[float]
    status: Sequence[str]
    charge_operation_id: str | None = None
    observed_at: datetime | str | None = None
    domain_id: str | None = None
    chemistry: str | None = None
    cell_model: str | None = None
    nominal_capacity_ah: float | None = None
    history_valid: bool = True


@dataclass(frozen=True)
class RawInferenceOutcome:
    cell_id: str
    charge_operation_id: str | None
    cycle_id: int | None
    observed_at: datetime | str | None
    pre_guard_status: str | None
    pre_guard_reasons: tuple[str, ...]
    history_valid: bool
    feature_values: dict[str, float | None]
    primary_vector: tuple[float | None, ...]
    feature_missing_reasons: dict[str, str]
    ood_violated_features: tuple[str, ...]
    raw_soh_percent: float | None
    sigma_trees_pp: float | None


def tree_dispersion_pp(model: Any, x: np.ndarray) -> np.ndarray:
    """Population standard deviation across RF trees using streaming Welford (parity with P3.6/P3.7)."""
    mean = np.zeros(len(x), dtype=np.float64)
    second = np.zeros(len(x), dtype=np.float64)
    for k, tree in enumerate(model.estimators_, 1):
        pred = tree.predict(x, check_input=False)
        delta = pred - mean
        mean += delta / k
        second += delta * (pred - mean)
    return np.sqrt(np.maximum(second / len(model.estimators_), 0.0))


def validate_device_domain(session: ChargeSessionInput, manifest: dict) -> tuple[bool, tuple[str, ...]]:
    """P3-IT-03 guard: strict fail-closed allowlist check against manifest-supported device metadata."""
    expected_domain = str(manifest.get("supported_domain_id", SUPPORTED_DOMAIN_ID)).strip()
    expected_chem = str(manifest.get("supported_chemistry", "LFP")).strip().upper()
    expected_model = str(manifest.get("supported_cell_model", SUPPORTED_CELL_MODEL)).strip()
    expected_cap = float(manifest.get("supported_nominal_capacity_ah", 1.1))
    reasons: list[str] = []
    if session.domain_id is None or (isinstance(session.domain_id, str) and not session.domain_id.strip()):
        reasons.append("MISSING_DOMAIN_ID")
    elif not isinstance(session.domain_id, str) or session.domain_id.strip() != expected_domain:
        reasons.append(f"UNSUPPORTED_DOMAIN:{session.domain_id}")
    if session.chemistry is None or (isinstance(session.chemistry, str) and not session.chemistry.strip()):
        reasons.append("MISSING_CHEMISTRY")
    elif not isinstance(session.chemistry, str) or session.chemistry.strip().upper() != expected_chem:
        reasons.append(f"UNSUPPORTED_CHEMISTRY:{session.chemistry}")
    if session.cell_model is None or (isinstance(session.cell_model, str) and not session.cell_model.strip()):
        reasons.append("MISSING_CELL_MODEL")
    elif not isinstance(session.cell_model, str) or session.cell_model.strip().upper() != expected_model.upper():
        reasons.append(f"UNVALIDATED_DEVICE:{session.cell_model}")
    if session.nominal_capacity_ah is None:
        reasons.append("MISSING_NOMINAL_CAPACITY_AH")
    elif (
        isinstance(session.nominal_capacity_ah, bool)
        or not isinstance(session.nominal_capacity_ah, (int, float))
        or not isfinite(session.nominal_capacity_ah)
        or abs(float(session.nominal_capacity_ah) - expected_cap) > 0.15
    ):
        reasons.append(f"UNVALIDATED_NOMINAL_CAPACITY_AH:{session.nominal_capacity_ah}")
    return (len(reasons) == 0, tuple(reasons))


def validate_charge_session_f31(session: ChargeSessionInput) -> tuple[str | None, tuple[str, ...]]:
    """F3.1 validation: cell ID, cycle order key, full charge session history, sign and units."""
    if not isinstance(session.cell_id, str) or not session.cell_id.strip():
        return "INVALID_INPUT", ("MISSING_CELL_ID",)
    if not isinstance(session.cycle_id, int) or isinstance(session.cycle_id, bool) or session.cycle_id < 0:
        return "INVALID_INPUT", ("INVALID_CYCLE_ID",)
    if not session.history_valid:
        return "INSUFFICIENT_HISTORY", ("HISTORY_MARKED_INCOMPLETE",)

    n_t, n_v, n_i, n_s = len(session.time_s), len(session.voltage_v), len(session.current_a), len(session.status)
    if not (n_t == n_v == n_i == n_s):
        return "INVALID_INPUT", ("ARRAY_LENGTH_MISMATCH",)
    if n_t < 6:
        return "INSUFFICIENT_HISTORY", ("SINGLE_OR_SHORT_SAMPLE_NOT_VALID_CHARGE_SESSION",)

    t = np.asarray(session.time_s, dtype=float)
    v = np.asarray(session.voltage_v, dtype=float)
    amps = np.asarray(session.current_a, dtype=float)
    st = np.asarray(session.status)
    if not (np.isfinite(t).all() and np.isfinite(v).all() and np.isfinite(amps).all()):
        return "INVALID_INPUT", ("NONFINITE_SENSOR_VALUES",)
    if np.any(np.diff(t) <= 0):
        return "INVALID_INPUT", ("NONINCREASING_TIME_S",)
    if np.any(amps >= 0):
        return "INVALID_INPUT", ("NONNEGATIVE_CHARGE_CURRENT_SIGN_VIOLATION",)
    if not np.isin(st, [FAST, TOP]).all():
        return "INVALID_INPUT", ("UNSUPPORTED_OR_DISCHARGE_STAGE_IN_CHARGE_INPUT",)
    return None, ()


def load_verified_manifest(manifest_path: Path) -> tuple[Path, dict]:
    try:
        resolved = ensure_local_trusted_path(manifest_path)
    except (ValueError, FileNotFoundError) as exc:
        raise SecurityError(str(exc)) from exc
    manifest = json.loads(resolved.read_text(encoding="utf-8"))
    required_keys = {
        "manifest_version",
        "model_version",
        "feature_schema_version",
        "primary_features",
        "training_domain",
        "soh_reference_definition",
        "supported_domain_id",
        "supported_chemistry",
        "supported_cell_model",
        "artifacts",
        "deployment_budget_bytes",
    }
    missing = required_keys - set(manifest)
    if missing:
        raise SchemaMismatchError(f"Model manifest missing required fields: {sorted(missing)}")
    return resolved, manifest


class FrozenSoHInferenceEngine:
    """F3.1 + F3.2 + F3.3 inference engine backed exclusively by hash-verified frozen artifacts."""

    def __init__(self, manifest_path: Path, project_root: Path | None = None) -> None:
        resolved_manifest, self.manifest = load_verified_manifest(manifest_path)
        self.project_root = (project_root or resolved_manifest.parents[2]).resolve()
        self.manifest_path = resolved_manifest

        artifacts = self.manifest["artifacts"]
        self._verify_code_bindings(artifacts)

        schema_entry = artifacts["feature_schema"]
        schema_path = self._resolve_verified_artifact(schema_entry["path"], schema_entry["sha256"])
        self.feature_schema = json.loads(schema_path.read_text(encoding="utf-8"))

        ood_entry = artifacts["ood_policy"]
        ood_path = self._resolve_verified_artifact(ood_entry["path"], ood_entry["sha256"])
        try:
            self.ood_policy = load_verified_ood_policy(ood_path, ood_entry["sha256"])
        except ValueError as exc:
            raise SecurityError(str(exc)) from exc

        self.primary_features = tuple(self.manifest["primary_features"])
        if tuple(self.feature_schema["primary_features"]) != self.primary_features:
            raise SchemaMismatchError("Feature schema primary_features mismatch with model_manifest.json")
        if tuple(self.ood_policy["primary_features"]) != self.primary_features:
            raise SchemaMismatchError("OOD policy primary_features mismatch with model_manifest.json")
        if self.feature_schema.get("version") != self.manifest["feature_schema_version"]:
            raise SchemaMismatchError("Feature schema version mismatch with model_manifest.json")

        model_entry = artifacts["rf_model"]
        model_path = self._resolve_verified_artifact(model_entry["path"], model_entry["sha256"])
        self.model_size_bytes = model_path.stat().st_size
        budget = int(self.manifest["deployment_budget_bytes"])
        if self.model_size_bytes > budget:
            raise SchemaMismatchError(
                f"DEPLOYMENT_BUDGET_BLOCKED: RF artifact {self.model_size_bytes} > {budget} bytes"
            )
        self.model = joblib.load(model_path)
        if getattr(self.model, "n_features_in_", None) != len(self.primary_features):
            raise SchemaMismatchError(
                f"Model expects {getattr(self.model, 'n_features_in_', None)} features, "
                f"schema defines {len(self.primary_features)}"
            )

        self.model_version: str = self.manifest["model_version"]
        self.feature_schema_version: str = self.manifest["feature_schema_version"]
        self.training_domain: str = self.manifest["training_domain"]
        self.soh_reference_definition: str = self.manifest["soh_reference_definition"]

    def _resolve_verified_artifact(self, relative_or_abs: str, expected_sha256: str) -> Path:
        if "://" in relative_or_abs:
            raise SecurityError(f"Remote artifact URI is forbidden: {relative_or_abs}")
        raw_path = Path(relative_or_abs)
        if raw_path.suffix.lower() in {".pkl", ".pickle"}:
            raise SecurityError(f"Raw pickle artifact is forbidden: {relative_or_abs}")
        candidate = raw_path if raw_path.is_absolute() else (self.project_root / raw_path)
        try:
            resolved = ensure_local_trusted_path(candidate)
        except (ValueError, FileNotFoundError) as exc:
            raise SecurityError(str(exc)) from exc
        actual = sha256_file(resolved)
        if actual != expected_sha256:
            raise SecurityError(
                f"Artifact SHA-256 mismatch for {relative_or_abs}: expected {expected_sha256}, got {actual}"
            )
        return resolved

    def _verify_code_bindings(self, artifacts: dict) -> None:
        for key in ("feature_extractor", "evaluation_guard"):
            if key not in artifacts:
                raise SchemaMismatchError(f"Manifest missing frozen code binding: {key}")
            entry = artifacts[key]
            self._resolve_verified_artifact(entry["path"], entry["sha256"])

    def predict_from_features(self, feature_map: dict[str, float | None]) -> tuple[float | None, float | None, tuple[float | None, ...], tuple[str, ...]]:
        """Direct F3.3 RF inference from an already extracted feature map (exact P3.6/P3.7 parity)."""
        vector = tuple(
            None if feature_map.get(name) is None else float(feature_map[name])
            for name in self.primary_features
        )
        violated = tuple(violated_weighted_features(vector, self.ood_policy))
        if any(v is None or not isfinite(v) for v in vector):
            return None, None, vector, violated
        x = np.ascontiguousarray(np.asarray([vector], dtype=np.float32))
        raw_pred = float(self.model.predict(x)[0])
        sigma = float(tree_dispersion_pp(self.model, x)[0])
        return (
            raw_pred if isfinite(raw_pred) else None,
            sigma if isfinite(sigma) else None,
            vector,
            violated,
        )

    def infer_session(self, session: ChargeSessionInput) -> RawInferenceOutcome:
        """Run F3.1 -> F3.2 -> F3.3 for a single cell end-of-charge session."""
        domain_ok, domain_reasons = validate_device_domain(session, self.manifest)
        if not domain_ok:
            return RawInferenceOutcome(
                cell_id=session.cell_id,
                charge_operation_id=session.charge_operation_id,
                cycle_id=session.cycle_id if isinstance(session.cycle_id, int) and not isinstance(session.cycle_id, bool) and session.cycle_id >= 0 else None,
                observed_at=session.observed_at,
                pre_guard_status="NOT_VALIDATED_FOR_DEVICE",
                pre_guard_reasons=domain_reasons,
                history_valid=session.history_valid,
                feature_values={name: None for name in self.primary_features},
                primary_vector=tuple(None for _ in self.primary_features),
                feature_missing_reasons={},
                ood_violated_features=(),
                raw_soh_percent=None,
                sigma_trees_pp=None,
            )

        f31_status, f31_reasons = validate_charge_session_f31(session)
        if f31_status is not None:
            return RawInferenceOutcome(
                cell_id=session.cell_id,
                charge_operation_id=session.charge_operation_id,
                cycle_id=session.cycle_id if isinstance(session.cycle_id, int) and not isinstance(session.cycle_id, bool) and session.cycle_id >= 0 else None,
                observed_at=session.observed_at,
                pre_guard_status=f31_status,
                pre_guard_reasons=f31_reasons,
                history_valid=f31_status != "INSUFFICIENT_HISTORY",
                feature_values={name: None for name in self.primary_features},
                primary_vector=tuple(None for _ in self.primary_features),
                feature_missing_reasons={},
                ood_violated_features=(),
                raw_soh_percent=None,
                sigma_trees_pp=None,
            )

        extracted, missing_notes = extract_charge(
            session.time_s,
            session.voltage_v,
            session.current_a,
            session.status,
        )
        primary_map = {name: extracted.get(name) for name in self.primary_features}
        primary_missing = {k: v for k, v in missing_notes.items() if k in self.primary_features}
        raw_soh, sigma, vector, violated = self.predict_from_features(primary_map)
        return RawInferenceOutcome(
            cell_id=session.cell_id,
            charge_operation_id=session.charge_operation_id,
            cycle_id=session.cycle_id,
            observed_at=session.observed_at,
            pre_guard_status=None,
            pre_guard_reasons=(),
            history_valid=True,
            feature_values=primary_map,
            primary_vector=vector,
            feature_missing_reasons=primary_missing,
            ood_violated_features=violated,
            raw_soh_percent=raw_soh,
            sigma_trees_pp=sigma,
        )

