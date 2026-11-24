"""Read-only compatibility adapter for single-cell offline Phase 1 REPLAY windows."""
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from app.schemas import EstimationResult, Telemetry
from src.ekf import EKF


@dataclass(frozen=True)
class ReplayConfig:
    device_id: str
    session_id: str
    first_sequence_id: int
    initial_soc_fraction: float
    initial_vrc_v: float
    make_ekf: Callable[[], EKF]


@dataclass(frozen=True)
class ReplayResult:
    estimation: EstimationResult
    diagnostics: dict


def _project(row: dict) -> EstimationResult:
    status = {
        "VALID": "VALID",
        "INVALID_INPUT": "INVALID_INPUT",
        "OUT_OF_DOMAIN": "INVALID_INPUT",
        "GAP_UNOBSERVED": "NOT_READY",
        "NOT_READY": "NOT_READY",
        "NUMERICAL_ERROR": "ERROR",
    }.get(row["status"], "ERROR")
    # Phase 1 cannot carry the model warning alongside an apparently valid value.
    if status == "VALID" and row["LOW_SOC_MODEL_UNCERTAIN"] is not False:
        status = "NOT_READY"
    return EstimationResult(
        status=status, value_pct=row["soc_pct"] if status == "VALID" else None,
        scope="CELL", algorithm="OFFLINE_EKF_1RC", version=row["model_version"],
    )


class Phase1ReplayAdapter:
    """Stateless per request. Use replay() to retain every Phase 2 diagnostic."""

    def replay(self, measurement_window: Iterable[Telemetry], config: ReplayConfig) -> Iterator[ReplayResult]:
        ekf = config.make_ekf()
        ekf.reset(config.initial_soc_fraction, config.initial_vrc_v, run_id=config.session_id)
        expected_id = config.first_sequence_id
        last_uptime_ms = None
        for sample in measurement_window:
            if not (isinstance(sample, Telemetry) and sample.source == "REPLAY"
                    and sample.cell_count == 1 and len(sample.temperatures_c) == 1
                    and sample.device_id == config.device_id and sample.session_id == config.session_id
                    and sample.sequence_id == expected_id and sample.is_valid
                    and (last_uptime_ms is None or sample.uptime_ms >= last_uptime_ms)):
                yield ReplayResult(
                    EstimationResult(status="INVALID_INPUT", scope="CELL",
                                     algorithm="OFFLINE_EKF_1RC", version=ekf.model_version),
                    {"status": "INVALID_INPUT", "sequence_id": getattr(sample, "sequence_id", None),
                     "reason": "Invalid sensor group, unsupported source/scope, or discontinuous replay window"},
                )
                return
            row = ekf.update(sample.uptime_ms / 1000, sample.pack_current_a,
                             sample.cell_voltages_v[0], temperature_c=sample.temperatures_c[0])
            row["sequence_id"] = sample.sequence_id
            row["device_id"] = sample.device_id
            yield ReplayResult(_project(row), row)
            expected_id += 1
            last_uptime_ms = sample.uptime_ms

    def estimate(self, measurement_window, config) -> EstimationResult:
        """Implements app.estimators.SoCEstimator. Phase 1 itself passes config=None."""
        if config is None or measurement_window is None:
            return EstimationResult()
        if not isinstance(config, ReplayConfig):
            raise TypeError("Offline replay requires ReplayConfig")
        last = EstimationResult()
        for step in self.replay(measurement_window, config):
            last = step.estimation
        return last
