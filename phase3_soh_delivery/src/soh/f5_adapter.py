"""F3 -> F5 monitoring adapter and read-only Phase 1 SoHEstimator compatibility bridge.

Enforces D09 (f3_to_f2_capacity_feedback = False in v1): F3 never mutates F2 Q_model,
never silently clips relative SoH > 100%, and never presents held/stale estimates as VALID.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.soh.inference import ChargeSessionInput
from src.soh.ood import (
    OFFLINE_STALE_MODE,
    WallClockStalePolicy,
    evaluate_freshness,
    parse_aware_utc,
)
from src.soh.output_validation import (
    SoHOutputValidator,
    build_not_ready_response,
    load_validator_safe,
)


def project_f5_display_record(
    response: dict[str, Any],
    now_utc: datetime | str | None = None,
    *,
    stale_policy: WallClockStalePolicy | None = None,
    offline_cycle_replay: bool | None = None,
) -> dict[str, Any]:
    """Project validated F3 response to F5 monitoring view, recomputing freshness at read/display time."""
    diagnostics = response.get("diagnostics") or {}
    is_offline = (
        diagnostics.get("stale_mode") == OFFLINE_STALE_MODE
        if offline_cycle_replay is None
        else offline_cycle_replay
    )

    ref_dt: datetime | None = None
    if not is_offline:
        if now_utc is None:
            ref_dt = datetime.now(timezone.utc)
        else:
            try:
                ref_dt = parse_aware_utc(now_utc)
            except (TypeError, ValueError):
                ref_dt = None

    last_valid_at = response["last_valid_at"]
    last_valid_age = response["last_valid_age_seconds"]
    if not is_offline:
        if ref_dt is not None and last_valid_at is not None:
            try:
                last_dt = parse_aware_utc(last_valid_at)
                last_valid_age = max(0.0, (ref_dt - last_dt).total_seconds()) if last_dt is not None else None
            except (TypeError, ValueError):
                last_valid_age = None
        elif ref_dt is None:
            last_valid_age = None

    status = response["status"]
    reason_codes = list(response["reason_codes"])

    if status == "VALID":
        if is_offline:
            current_soh = response["soh_percent"]
            held_soh = None
            display_mode = "CURRENT_VALID"
        else:
            valid_ts = last_valid_at or response["observed_at"]
            freshness = evaluate_freshness(
                valid_ts,
                now_utc if now_utc is not None else ref_dt,
                offline_cycle_replay=False,
                policy=stale_policy,
            )
            if freshness.is_stale:
                status = "STALE"
                held_soh = (
                    response["soh_percent"]
                    if response["soh_percent"] is not None
                    else response["last_valid_soh_percent"]
                )
                current_soh = None
                display_mode = "HELD_STALE" if held_soh is not None else "UNAVAILABLE"
                if freshness.reason_code and freshness.reason_code not in reason_codes:
                    reason_codes.append(freshness.reason_code)
                if last_valid_age is None and freshness.age_seconds is not None:
                    last_valid_age = freshness.age_seconds
            else:
                current_soh = response["soh_percent"]
                held_soh = None
                display_mode = "CURRENT_VALID"
                if last_valid_age is None and freshness.age_seconds is not None:
                    last_valid_age = freshness.age_seconds
    else:
        current_soh = None
        held_soh = response["last_valid_soh_percent"]
        display_mode = "HELD_STALE" if held_soh is not None else "UNAVAILABLE"

    return {
        "cell_id": response["cell_id"],
        "charge_operation_id": response["charge_operation_id"],
        "cycle_id": response["cycle_id"],
        "current_soh_percent": current_soh,
        "held_last_valid_soh_percent": held_soh,
        "status": status,
        "display_mode": display_mode,
        "reason_codes": reason_codes,
        "observed_at": response["observed_at"],
        "last_valid_at": last_valid_at,
        "last_valid_age_seconds": last_valid_age,
        "model_version": response["model_version"],
        "feature_schema_version": response["feature_schema_version"],
        "training_domain": response["training_domain"],
        "soh_reference_definition": response["soh_reference_definition"],
        "f3_to_f2_capacity_feedback": False,
        "hardware_validated": False,
    }


class _F5DisplayProjector:
    """Allows calling to_f5_display_record on both F5SoHAdapter instances and the class."""

    def __get__(self, instance: F5SoHAdapter | None, owner: type[F5SoHAdapter]):
        if instance is None:
            return project_f5_display_record

        def _bound(
            response: dict[str, Any],
            now_utc: datetime | str | None = None,
            *,
            stale_policy: WallClockStalePolicy | None = None,
            offline_cycle_replay: bool | None = None,
        ) -> dict[str, Any]:
            effective_policy = stale_policy or (
                instance.validator.stale_policy if instance.validator is not None else instance.config.stale_policy
            )
            effective_offline = (
                instance.config.offline_cycle_replay if offline_cycle_replay is None else offline_cycle_replay
            )
            return project_f5_display_record(
                response,
                now_utc=now_utc,
                stale_policy=effective_policy,
                offline_cycle_replay=effective_offline,
            )

        return _bound


@dataclass(frozen=True)
class F5AdapterConfig:
    """Configuration for F3 -> F5 runtime inference; F3 -> F2 feedback is hard-disabled in v1."""

    manifest_path: Path
    project_root: Path | None = None
    stale_policy: WallClockStalePolicy | None = None
    offline_cycle_replay: bool = False
    f3_to_f2_capacity_feedback: bool = False

    def __post_init__(self) -> None:
        if self.f3_to_f2_capacity_feedback:
            raise ValueError("D09 violation: f3_to_f2_capacity_feedback must remain False in Phase 3 v1")


class F5SoHAdapter:
    """F3 -> F5 monitoring adapter consuming F3.4 validated responses."""

    def __init__(self, config: F5AdapterConfig, *, snapshot: dict[str, Any] | None = None) -> None:
        self.config = config
        self.validator, self.init_status, self.init_reasons = load_validator_safe(
            config.manifest_path,
            project_root=config.project_root,
            stale_policy=config.stale_policy,
            snapshot=snapshot,
        )

    @property
    def is_ready(self) -> bool:
        return self.validator is not None

    def snapshot(self) -> dict[str, Any] | None:
        return self.validator.snapshot() if self.validator is not None else None

    def evaluate_charge_session(
        self,
        session: ChargeSessionInput,
        *,
        now_utc: datetime | str | None = None,
    ) -> dict[str, Any]:
        if self.validator is None:
            obs_iso = None
            try:
                parsed = parse_aware_utc(session.observed_at)
                obs_iso = parsed.isoformat() if parsed is not None else None
            except (TypeError, ValueError):
                obs_iso = None
            return build_not_ready_response(
                session.cell_id,
                self.init_status or "MODEL_NOT_READY",
                self.init_reasons or ["NO_VALIDATED_MODEL_ARTIFACT"],
                charge_operation_id=session.charge_operation_id,
                cycle_id=session.cycle_id if isinstance(session.cycle_id, int) and not isinstance(session.cycle_id, bool) and session.cycle_id >= 0 else None,
                observed_at=obs_iso,
            )
        return self.validator.evaluate_session(
            session,
            now_utc=now_utc,
            offline_cycle_replay=self.config.offline_cycle_replay,
        )

    to_f5_display_record = _F5DisplayProjector()

    def estimate(self, historical_data: Any, config: Any = None) -> dict[str, Any]:
        """Phase 1 app.estimators.SoHEstimator compatible projection (without mutating Phase 1).

        If Phase 1 app.schemas.EstimationResult is importable, returns an EstimationResult instance;
        otherwise returns an equivalent dictionary with the exact Phase 1 fields.
        Note: Phase 1 EstimationResult caps value_pct <= 100. Relative SoH > 100% is never silently
        clipped; it is projected to NOT_READY in the strict Phase 1 schema while preserved unclipped
        in evaluate_charge_session() / to_f5_display_record().
        """
        result_cls = _try_import_phase1_estimation_result()

        def _make(status: str, value_pct: float | None, version: str | None, updated_at: datetime | None):
            payload = dict(
                value_pct=value_pct,
                status=status,
                scope="CELL" if version is not None else None,
                algorithm="RF_CHARGE_HI_P3" if version is not None else "UNIMPLEMENTED",
                version=version,
                updated_at=updated_at,
            )
            return result_cls(**payload) if result_cls is not None else payload

        if historical_data is None or config is None:
            return _make("NOT_READY", None, None, None)

        if not isinstance(historical_data, ChargeSessionInput):
            return _make("INVALID_INPUT", None, self.validator.engine.model_version if self.validator else None, None)

        now_utc = config.get("now_utc") if isinstance(config, dict) else getattr(config, "now_utc", None)
        response = self.evaluate_charge_session(historical_data, now_utc=now_utc)
        version = response["model_version"]
        obs_dt = parse_aware_utc(response["observed_at"]) if response["observed_at"] else None

        status = response["status"]
        value = response["soh_percent"]
        if status == "VALID" and value is not None:
            if 0.0 <= value <= 100.0:
                return _make("VALID", float(value), version, obs_dt)
            # Never silently clip SoH > 100% into Phase 1's [0, 100] contract.
            return _make("NOT_READY", None, version, obs_dt)

        mapped = {
            "INVALID_INPUT": "INVALID_INPUT",
            "OUT_OF_DOMAIN": "INVALID_INPUT",
            "NOT_VALIDATED_FOR_DEVICE": "INVALID_INPUT",
            "MODEL_NOT_READY": "NOT_READY",
            "INSUFFICIENT_HISTORY": "NOT_READY",
            "MISSING_FEATURE": "NOT_READY",
            "MODEL_UNCERTAIN": "NOT_READY",
            "SOH_JUMP_ANOMALY": "NOT_READY",
            "STALE": "NOT_READY",
            "RESYNC_REVIEW_REQUIRED": "NOT_READY",
            "MODEL_SCHEMA_MISMATCH": "ERROR",
            "INFERENCE_ERROR": "ERROR",
        }.get(status, "ERROR")
        return _make(mapped, None, version, obs_dt)


def _try_import_phase1_estimation_result():
    try:
        from app.schemas import EstimationResult  # type: ignore
        return EstimationResult
    except Exception:
        return None

