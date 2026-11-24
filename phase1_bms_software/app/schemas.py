"""Version 1 HTTP contracts. No electrical operating thresholds are assumed."""
import math
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SQLITE_MAX_INTEGER = 2**63 - 1
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
SessionId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Counter = Annotated[int, Field(ge=0, le=SQLITE_MAX_INTEGER)]
Source = Literal["REPLAY", "HARDWARE"]
WarningCode = Literal[
    "CELL_OVERVOLTAGE", "CELL_UNDERVOLTAGE", "PACK_OVERCURRENT",
    "OVER_TEMPERATURE", "SENSOR_FAULT",
]
EstimationStatus = Literal["NOT_READY", "VALID", "INVALID_INPUT", "ERROR"]
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Validity(Contract):
    model_config = ConfigDict(strict=True)
    voltage: bool
    current: bool
    temperature: bool


class Telemetry(Contract):
    model_config = ConfigDict(strict=True)
    schema_version: Literal["1.0"]
    source: Source
    device_id: Identifier
    session_id: SessionId
    sequence_id: Counter
    uptime_ms: Counter
    cell_count: Annotated[int, Field(ge=1, le=2)]
    cell_voltages_v: Annotated[list[FiniteNumber | None], Field(min_length=1, max_length=2)]
    pack_current_a: FiniteNumber | None
    temperatures_c: Annotated[list[FiniteNumber | None], Field(min_length=1, max_length=64)]
    validity: Validity
    warnings: Annotated[list[WarningCode], Field(max_length=5)]

    @model_validator(mode="after")
    def check_groups(self) -> Self:
        if len(self.cell_voltages_v) != self.cell_count:
            raise ValueError("cell voltage vector length must equal cell_count")
        if self.validity.voltage and any(v is None for v in self.cell_voltages_v):
            raise ValueError("valid voltage requires every cell value")
        if self.validity.current and self.pack_current_a is None:
            raise ValueError("valid current requires a value")
        if self.validity.temperature and any(v is None for v in self.temperatures_c):
            raise ValueError("valid temperature requires every sensor value")
        if len(self.warnings) != len(set(self.warnings)):
            raise ValueError("warning codes must be unique")
        return self

    @property
    def is_valid(self) -> bool:
        return self.validity.voltage and self.validity.current and self.validity.temperature

    @property
    def pack_voltage_derived_v(self) -> float | None:
        if not self.validity.voltage:
            return None
        total = sum(self.cell_voltages_v)
        return total if math.isfinite(total) else None


class EstimationResult(Contract):
    value_pct: Annotated[float, Field(ge=0, le=100)] | None = None
    status: EstimationStatus = "NOT_READY"
    scope: Literal["CELL", "PACK"] | None = None
    algorithm: str = "UNIMPLEMENTED"
    version: str | None = None
    updated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def unavailable_has_no_value(self) -> Self:
        if self.status != "VALID" and self.value_pct is not None:
            raise ValueError("unavailable estimator must return null")
        if self.status == "VALID" and self.value_pct is None:
            raise ValueError("VALID requires a numerical value")
        return self


class Ack(Contract):
    status: Literal["accepted", "duplicate", "accepted_historical"]
    record_id: int
    updated_latest: bool
    server_received_at: AwareDatetime


class MeasurementRecord(Contract):
    id: int
    received_at_utc: AwareDatetime
    measurement_status: Literal["VALID", "INVALID_DATA"]
    payload: Telemetry


class MeasurementPage(Contract):
    items: list[MeasurementRecord]
    next_before_id: int | None


class WarningEvent(Contract):
    id: int
    device_id: str
    measurement_id: int
    warning_code: WarningCode
    transition: Literal["ACTIVATED", "CLEARED"]
    occurred_at_utc: AwareDatetime


class WarningPage(Contract):
    items: list[WarningEvent]
    next_before_id: int | None


class LatestState(Contract):
    device_id: str
    source: Source | None = None
    connectivity_status: Literal["NO_DATA", "LIVE", "STALE"] = "NO_DATA"
    measurement_status: Literal["VALID", "INVALID_DATA"] | None = None
    received_at_utc: AwareDatetime | None = None
    age_seconds: Annotated[float, Field(ge=0)] | None = None
    cell_count: Annotated[int, Field(ge=1, le=2)] | None = None
    cell_voltages_v: list[float | None] | None = None
    pack_voltage_derived_v: float | None = None
    pack_current_a: float | None = None
    temperatures_c: list[float | None] | None = None
    validity: Validity | None = None
    active_warnings: list[WarningCode] = Field(default_factory=list)
    soc: EstimationResult = Field(default_factory=EstimationResult)
    soh: EstimationResult = Field(default_factory=EstimationResult)


    @model_validator(mode="after")
    def check_state_completeness(self) -> Self:
        fields = (
            self.source, self.measurement_status, self.received_at_utc, self.age_seconds,
            self.cell_count, self.cell_voltages_v, self.temperatures_c, self.validity,
        )
        if self.connectivity_status == "NO_DATA":
            if (any(value is not None for value in fields) or self.active_warnings or
                    self.pack_current_a is not None or self.pack_voltage_derived_v is not None):
                raise ValueError("NO_DATA must contain null measurements and no warnings")
            return self
        if any(value is None for value in fields):
            raise ValueError("LIVE/STALE require complete source, quality, receipt and measurement fields")
        if len(self.cell_voltages_v) != self.cell_count or not 1 <= len(self.temperatures_c) <= 64:
            raise ValueError("state sensor vector lengths are invalid")
        if self.validity.voltage and any(value is None for value in self.cell_voltages_v):
            raise ValueError("valid voltage group requires values")
        if self.validity.current and self.pack_current_a is None:
            raise ValueError("valid current group requires a value")
        if self.validity.temperature and any(value is None for value in self.temperatures_c):
            raise ValueError("valid temperature group requires values")
        if not self.validity.voltage and self.pack_voltage_derived_v is not None:
            raise ValueError("invalid voltage group cannot have a derived pack voltage")
        valid = self.validity.voltage and self.validity.current and self.validity.temperature
        if self.measurement_status != ("VALID" if valid else "INVALID_DATA"):
            raise ValueError("measurement_status must match validity flags")
        return self


class ErrorDetail(Contract):
    code: str
    message: str


class ErrorResponse(Contract):
    detail: ErrorDetail


class Health(Contract):
    status: Literal["ok"] = "ok"
    mode: Source
    database: Literal["available"] = "available"
