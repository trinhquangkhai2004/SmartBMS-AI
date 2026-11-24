"""F3.4 output validation wrapping the exact frozen P3.6/P3.7 EvaluationGuard.

Preserves 100% parity with src/soh/evaluation_guard.py (never reimplements OOD,
sigma, jump, or resync thresholds), adds online wall-clock staleness (D13),
per-cell last_valid_at persistence, and emits the full P3.8 response contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from src.soh.evaluation_guard import EvaluationGuard
from src.soh.inference import (
    ChargeSessionInput,
    FrozenSoHInferenceEngine,
    RawInferenceOutcome,
    SchemaMismatchError,
    SecurityError,
)
from src.soh.ood import (
    OFFLINE_STALE_MODE,
    ONLINE_STALE_MODE,
    WallClockStalePolicy,
    evaluate_freshness,
    parse_aware_utc,
)


CONTRACT_VERSION = "p3.8-v1"


def _iso_utc(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt is not None else None


def _normalize_cell_id(cell_id: Any) -> str | None:
    if isinstance(cell_id, str) and cell_id.strip():
        return cell_id
    return None


def _normalize_cycle_id(cycle_id: Any) -> int | None:
    if isinstance(cycle_id, int) and not isinstance(cycle_id, bool) and cycle_id >= 0:
        return cycle_id
    return None


def _finite_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return float(value)
    return None


class SoHOutputValidator:
    """F3.4 validator owning per-cell EvaluationGuard state and last_valid_at metadata."""

    def __init__(
        self,
        engine: FrozenSoHInferenceEngine,
        *,
        stale_policy: WallClockStalePolicy | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> None:
        self.engine = engine
        self.stale_policy = stale_policy or WallClockStalePolicy(
            max_observation_age_seconds=float(
                engine.manifest.get("online_stale_policy", {}).get("max_observation_age_seconds", 86400.0)
            ),
            max_future_skew_seconds=float(
                engine.manifest.get("online_stale_policy", {}).get("max_future_skew_seconds", 5.0)
            ),
        )
        guard_snapshot = snapshot.get("guard") if snapshot else None
        self.guard = EvaluationGuard(engine.ood_policy, snapshot=guard_snapshot)
        self.last_valid_at_by_cell: dict[str, str | None] = dict(
            (snapshot or {}).get("last_valid_at_by_cell", {})
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "guard": self.guard.snapshot(),
            "last_valid_at_by_cell": dict(self.last_valid_at_by_cell),
        }

    def _held_state(self, cell_id: str | None, now_dt: datetime | None) -> tuple[float | None, int | None, int, str | None, float | None]:
        if cell_id is None:
            return None, None, 0, None, None
        state = self.guard.states.get(cell_id)
        if state is None or state.model_version != self.engine.model_version:
            return None, None, 0, None, None
        last_at_iso = self.last_valid_at_by_cell.get(cell_id)
        last_age = None
        if last_at_iso is not None and now_dt is not None:
            last_dt = parse_aware_utc(last_at_iso)
            if last_dt is not None:
                last_age = max(0.0, (now_dt - last_dt).total_seconds())
        return state.baseline, state.baseline_cycle, state.baseline_version, last_at_iso, last_age

    def validate_outcome(
        self,
        outcome: RawInferenceOutcome,
        *,
        now_utc: datetime | str | None = None,
        offline_cycle_replay: bool = False,
    ) -> dict[str, Any]:
        """Apply freshness + frozen EvaluationGuard and emit the P3.8 response contract."""
        ref_dt: datetime | None = None
        if not offline_cycle_replay:
            if now_utc is None:
                ref_dt = datetime.now(timezone.utc)
            else:
                try:
                    ref_dt = parse_aware_utc(now_utc)
                except (TypeError, ValueError):
                    ref_dt = None

        obs_dt: datetime | None = None
        try:
            obs_dt = parse_aware_utc(outcome.observed_at)
        except (TypeError, ValueError):
            obs_dt = None

        normalized_cell_id = _normalize_cell_id(outcome.cell_id)
        normalized_cycle_id = _normalize_cycle_id(outcome.cycle_id)
        pre_guard_status = outcome.pre_guard_status
        pre_guard_reasons = list(outcome.pre_guard_reasons)
        if pre_guard_status is None and normalized_cell_id is None:
            pre_guard_status = "INVALID_INPUT"
            if "MISSING_CELL_ID" not in pre_guard_reasons:
                pre_guard_reasons.append("MISSING_CELL_ID")

        # Pre-guard hard rejections (unsupported device domain or malformed F3.1 input)
        if pre_guard_status in {"NOT_VALIDATED_FOR_DEVICE", "INVALID_INPUT"}:
            last_soh, last_cycle, base_ver, last_at_iso, last_age = self._held_state(normalized_cell_id, ref_dt)
            display_mode = "HELD_STALE" if last_soh is not None else "UNAVAILABLE"
            return {
                "contract_version": CONTRACT_VERSION,
                "cell_id": normalized_cell_id,
                "charge_operation_id": outcome.charge_operation_id,
                "cycle_id": normalized_cycle_id,
                "soh_percent": None,
                "status": pre_guard_status,
                "reason_codes": pre_guard_reasons,
                "last_valid_soh_percent": last_soh,
                "last_valid_at": last_at_iso,
                "last_valid_cycle": last_cycle,
                "last_valid_age_seconds": last_age,
                "observed_at": _iso_utc(obs_dt),
                "model_version": self.engine.model_version,
                "feature_schema_version": self.engine.feature_schema_version,
                "training_domain": self.engine.training_domain,
                "soh_reference_definition": self.engine.soh_reference_definition,
                "baseline_version": base_ver,
                "display_mode": display_mode,
                "f3_to_f2_capacity_feedback": False,
                "hardware_validated": False,
                "diagnostics": {
                    "raw_soh_percent": _finite_or_none(outcome.raw_soh_percent),
                    "sigma_trees_pp": _finite_or_none(outcome.sigma_trees_pp),
                    "feature_values": {k: _finite_or_none(v) for k, v in outcome.feature_values.items()},
                    "feature_missing_reasons": dict(outcome.feature_missing_reasons),
                    "ood_violated_features": list(outcome.ood_violated_features),
                    "stale_mode": OFFLINE_STALE_MODE if offline_cycle_replay else ONLINE_STALE_MODE,
                    "observation_age_seconds": None,
                    "previous_baseline_pp": None,
                    "confirmation_count": None,
                    "guard_status": None,
                },
            }

        # Preserve caller-supplied invalid now_utc so evaluate_freshness flags UNTRUSTED_REFERENCE_CLOCK
        # instead of silently falling back to datetime.now(timezone.utc).
        freshness = evaluate_freshness(
            outcome.observed_at,
            now_utc if now_utc is not None else ref_dt,
            offline_cycle_replay=offline_cycle_replay,
            policy=self.stale_policy,
        )

        guard_res = self.guard.evaluate(
            outcome.cell_id,
            self.engine.model_version,
            outcome.cycle_id,
            outcome.primary_vector,
            outcome.raw_soh_percent,
            outcome.sigma_trees_pp,
            history_valid=outcome.history_valid,
            stale=freshness.is_stale,
        )

        guard_status = guard_res["status"]
        public_status = "STALE" if guard_status == "STALE_INPUT" else guard_status

        reason_codes: list[str] = []
        if guard_res.get("reason"):
            reason_codes.append(guard_res["reason"])
        if freshness.is_stale and freshness.reason_code and freshness.reason_code not in reason_codes:
            reason_codes.append(freshness.reason_code)
        for code in outcome.pre_guard_reasons:
            if code not in reason_codes:
                reason_codes.append(code)
        if public_status == "MISSING_FEATURE":
            for feat, reason in sorted(outcome.feature_missing_reasons.items()):
                reason_codes.append(f"{feat}:{reason}")
        elif public_status == "OUT_OF_DOMAIN":
            for feat in outcome.ood_violated_features:
                reason_codes.append(f"OOD_FEATURE:{feat}")
        elif public_status == "MODEL_UNCERTAIN" and "TREE_DISPERSION_EXCEEDED" not in reason_codes:
            if outcome.sigma_trees_pp is not None:
                reason_codes.append("TREE_DISPERSION_EXCEEDED")

        obs_iso = _iso_utc(obs_dt)
        if public_status == "VALID":
            self.last_valid_at_by_cell[outcome.cell_id] = obs_iso
        elif self.guard.states.get(outcome.cell_id) is None or self.guard.states[outcome.cell_id].baseline is None:
            self.last_valid_at_by_cell[outcome.cell_id] = None

        last_at_iso = self.last_valid_at_by_cell.get(outcome.cell_id)
        last_age = None
        if last_at_iso is not None and ref_dt is not None:
            last_dt = parse_aware_utc(last_at_iso)
            if last_dt is not None:
                last_age = max(0.0, (ref_dt - last_dt).total_seconds())

        last_valid_soh = guard_res["last_valid_soh"]
        display_mode = (
            "CURRENT_VALID"
            if public_status == "VALID"
            else "HELD_STALE"
            if last_valid_soh is not None
            else "UNAVAILABLE"
        )

        return {
            "contract_version": CONTRACT_VERSION,
            "cell_id": outcome.cell_id,
            "charge_operation_id": outcome.charge_operation_id,
            "cycle_id": outcome.cycle_id,
            "soh_percent": guard_res["soh_percent"] if public_status == "VALID" else None,
            "status": public_status,
            "reason_codes": reason_codes,
            "last_valid_soh_percent": last_valid_soh,
            "last_valid_at": last_at_iso,
            "last_valid_cycle": guard_res["last_valid_cycle"],
            "last_valid_age_seconds": last_age,
            "observed_at": obs_iso,
            "model_version": self.engine.model_version,
            "feature_schema_version": self.engine.feature_schema_version,
            "training_domain": self.engine.training_domain,
            "soh_reference_definition": self.engine.soh_reference_definition,
            "baseline_version": guard_res["baseline_version"],
            "display_mode": display_mode,
            "f3_to_f2_capacity_feedback": False,
            "hardware_validated": False,
            "diagnostics": {
                "raw_soh_percent": _finite_or_none(outcome.raw_soh_percent),
                "sigma_trees_pp": _finite_or_none(outcome.sigma_trees_pp),
                "feature_values": {k: _finite_or_none(v) for k, v in outcome.feature_values.items()},
                "feature_missing_reasons": dict(outcome.feature_missing_reasons),
                "ood_violated_features": list(outcome.ood_violated_features),
                "stale_mode": freshness.stale_mode,
                "observation_age_seconds": freshness.age_seconds,
                "previous_baseline_pp": guard_res.get("previous_baseline_pp"),
                "confirmation_count": guard_res.get("confirmation_count"),
                "guard_status": guard_status,
            },
        }

    def evaluate_session(
        self,
        session: ChargeSessionInput,
        *,
        now_utc: datetime | str | None = None,
        offline_cycle_replay: bool = False,
    ) -> dict[str, Any]:
        """Full F3.1 -> F3.2 -> F3.3 -> F3.4 pipeline for one charge session."""
        outcome = self.engine.infer_session(session)
        return self.validate_outcome(
            outcome,
            now_utc=now_utc,
            offline_cycle_replay=offline_cycle_replay,
        )

    def evaluate_extracted_features(
        self,
        cell_id: str,
        cycle_id: int,
        feature_map: dict[str, float | None],
        *,
        charge_operation_id: str | None = None,
        observed_at: datetime | str | None = None,
        now_utc: datetime | str | None = None,
        history_valid: bool = True,
        offline_cycle_replay: bool = False,
    ) -> dict[str, Any]:
        """Run F3.3 -> F3.4 directly from pre-extracted primary features (for exact P3.7 parity check)."""
        raw_soh, sigma, vector, violated = self.engine.predict_from_features(feature_map)
        missing = {
            name: "MISSING_OR_NONFINITE"
            for name, val in zip(self.engine.primary_features, vector)
            if val is None or not isfinite(val)
        }
        outcome = RawInferenceOutcome(
            cell_id=cell_id,
            charge_operation_id=charge_operation_id,
            cycle_id=cycle_id,
            observed_at=observed_at,
            pre_guard_status=None,
            pre_guard_reasons=(),
            history_valid=history_valid,
            feature_values={k: feature_map.get(k) for k in self.engine.primary_features},
            primary_vector=vector,
            feature_missing_reasons=missing,
            ood_violated_features=violated,
            raw_soh_percent=raw_soh,
            sigma_trees_pp=sigma,
        )
        return self.validate_outcome(
            outcome,
            now_utc=now_utc,
            offline_cycle_replay=offline_cycle_replay,
        )


def build_not_ready_response(
    cell_id: str | None,
    status: str,
    reason_codes: list[str],
    *,
    charge_operation_id: str | None = None,
    cycle_id: int | None = None,
    observed_at: str | None = None,
    feature_schema_version: str = "UNVERIFIED",
    training_domain: str = "RT-Batt LFP, 30C experimental domain",
    soh_reference_definition: str = "cell_relative_operational_capacity (100 * Q_discharge_next / median(Q_1..Q_5))",
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "cell_id": _normalize_cell_id(cell_id),
        "charge_operation_id": charge_operation_id,
        "cycle_id": _normalize_cycle_id(cycle_id),
        "soh_percent": None,
        "status": status,
        "reason_codes": list(reason_codes),
        "last_valid_soh_percent": None,
        "last_valid_at": None,
        "last_valid_cycle": None,
        "last_valid_age_seconds": None,
        "observed_at": observed_at,
        "model_version": None,
        "feature_schema_version": feature_schema_version,
        "training_domain": training_domain,
        "soh_reference_definition": soh_reference_definition,
        "baseline_version": 0,
        "display_mode": "UNAVAILABLE",
        "f3_to_f2_capacity_feedback": False,
        "hardware_validated": False,
        "diagnostics": {
            "raw_soh_percent": None,
            "sigma_trees_pp": None,
            "feature_values": {},
            "feature_missing_reasons": {},
            "ood_violated_features": [],
            "stale_mode": ONLINE_STALE_MODE,
            "observation_age_seconds": None,
            "previous_baseline_pp": None,
            "confirmation_count": None,
            "guard_status": None,
        },
    }


def load_validator_safe(
    manifest_path: Path,
    *,
    project_root: Path | None = None,
    stale_policy: WallClockStalePolicy | None = None,
    snapshot: dict[str, Any] | None = None,
) -> tuple[SoHOutputValidator | None, str | None, list[str]]:
    """Safe loader returning explicit MODEL_NOT_READY / MODEL_SCHEMA_MISMATCH status instead of silently falling back."""
    try:
        engine = FrozenSoHInferenceEngine(manifest_path, project_root=project_root)
        return SoHOutputValidator(engine, stale_policy=stale_policy, snapshot=snapshot), None, []
    except SecurityError as exc:
        return None, "MODEL_NOT_READY", ["UNTRUSTED_OR_CORRUPTED_ARTIFACT", str(exc)]
    except SchemaMismatchError as exc:
        return None, "MODEL_SCHEMA_MISMATCH", ["SCHEMA_OR_BUDGET_MISMATCH", str(exc)]
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
        return None, "INFERENCE_ERROR", [type(exc).__name__, str(exc)]

