"""Receipt-time freshness and current-state projection."""
from app.estimators import SoCEstimator, SoHEstimator
from app.ingestion import Clock
from app.repository import Repository
from app.schemas import EstimationResult, LatestState


def latest_state(repo: Repository, device_id: str, clock: Clock, stale_after_seconds: float,
                 soc: SoCEstimator, soh: SoHEstimator) -> LatestState:
    record = repo.latest(device_id)
    if record is None:
        return LatestState(device_id=device_id)
    telemetry = record.payload
    age = max(0.0, (clock() - record.received_at_utc).total_seconds())
    # Invalid measurements never enter an estimator. No artificial parameters/history.
    soc_result = soc.estimate([telemetry], None) if telemetry.is_valid else EstimationResult()
    soh_result = soh.estimate(None, None) if telemetry.is_valid else EstimationResult()
    return LatestState(
        device_id=device_id, source=telemetry.source,
        connectivity_status="STALE" if age > stale_after_seconds else "LIVE",
        measurement_status=record.measurement_status, received_at_utc=record.received_at_utc,
        age_seconds=age, cell_count=telemetry.cell_count,
        cell_voltages_v=telemetry.cell_voltages_v,
        pack_voltage_derived_v=telemetry.pack_voltage_derived_v,
        pack_current_a=telemetry.pack_current_a, temperatures_c=telemetry.temperatures_c,
        validity=telemetry.validity, active_warnings=telemetry.warnings,
        soc=soc_result, soh=soh_result,
    )
