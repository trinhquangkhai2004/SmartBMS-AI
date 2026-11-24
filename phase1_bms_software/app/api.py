"""Versioned HTTP routing and stable error contracts."""
import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response

from app.config import Settings
from app.estimators import SoCEstimator, SoHEstimator
from app.ingestion import Clock, IngestionConflict, ingest
from app.repository import Repository
from app.schemas import (
    Ack, Counter, ErrorResponse, Health, Identifier, LatestState,
    MeasurementPage, Telemetry, WarningPage,
)
from app.state import latest_state

DeviceQuery = Annotated[Identifier, Query()]
LimitQuery = Annotated[int, Query(ge=1, le=200)]
CursorQuery = Annotated[Counter | None, Query(ge=1)]
ERRORS = {503: {"model": ErrorResponse, "description": "SQLite unavailable"}}


def build_router(repo: Repository, settings: Settings, clock: Clock,
                 soc: SoCEstimator, soh: SoHEstimator) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/telemetry", response_model=Ack, status_code=201,
        responses={
            **ERRORS, 200: {"model": Ack, "description": "Identical duplicate"},
            202: {"model": Ack, "description": "Historical only"},
            409: {"model": ErrorResponse, "description": "Identity, mode or uptime conflict"},
            401: {"model": ErrorResponse, "description": "Missing or invalid configured token"},
        },
    )
    def post_telemetry(
        payload: Telemetry, response: Response,
        x_device_token: Annotated[str | None, Header()] = None,
    ):
        expected = settings.device_token.get_secret_value()
        if expected and not secrets.compare_digest(expected.encode(), (x_device_token or "").encode()):
            raise HTTPException(401, detail={"code": "unauthorized", "message": "A valid device token is required"})
        try:
            result = ingest(repo, payload, settings.mode, clock)
        except IngestionConflict as exc:
            raise HTTPException(409, detail={"code": exc.code, "message": exc.message}) from exc
        response.status_code = {"accepted": 201, "duplicate": 200, "accepted_historical": 202}[result.status]
        return result

    @router.get("/api/v1/state/latest", response_model=LatestState, responses=ERRORS)
    def get_latest(device_id: DeviceQuery):
        return latest_state(repo, device_id, clock, settings.stale_after_seconds, soc, soh)

    @router.get("/api/v1/measurements", response_model=MeasurementPage, responses=ERRORS)
    def get_measurements(device_id: DeviceQuery, limit: LimitQuery = 50, before_id: CursorQuery = None):
        items, cursor = repo.measurements(device_id, limit, before_id)
        return MeasurementPage(items=items, next_before_id=cursor)

    @router.get("/api/v1/warnings", response_model=WarningPage, responses=ERRORS)
    def get_warnings(device_id: DeviceQuery, limit: LimitQuery = 50, before_id: CursorQuery = None):
        items, cursor = repo.warning_events(device_id, limit, before_id)
        return WarningPage(items=items, next_before_id=cursor)

    @router.get("/health", response_model=Health, responses=ERRORS)
    def health():
        repo.check_health()
        return Health(mode=settings.mode)

    return router
