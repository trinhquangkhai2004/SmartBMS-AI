"""App factory with injectable settings/clock, including recoverable database failures."""
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import build_router
from app.config import Settings
from app.estimators import NotReadyEstimator, SoCEstimator, SoHEstimator
from app.ingestion import Clock
from app.repository import Repository

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_app(settings: Settings | None = None, clock: Clock = utc_now,
               soc: SoCEstimator | None = None, soh: SoHEstimator | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    repo = Repository(settings.database_path, settings.db_busy_timeout_ms)

    @asynccontextmanager
    async def lifespan(application):
        try:
            repo.initialize()
        except (sqlite3.Error, OSError):
            logger.error("SQLite initialization unavailable; data endpoints will return 503")
        yield

    application = FastAPI(
        title="PBL5 BMS Software Phase 1", version="1.0",
        description="Synthetic telemetry prototype. No battery control or validated estimators.",
        lifespan=lifespan,
    )
    application.state.repository = repo

    async def database_error(request: Request, exc: Exception):
        logger.error("SQLite unit of work unavailable (%s)", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": {
            "code": "database_unavailable", "message": "SQLite unavailable; operation not acknowledged",
        }})

    application.add_exception_handler(sqlite3.Error, database_error)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Preserve FastAPI's validation detail shape without echoing payloads,
        # tokens, NaN/Infinity, or unserializable ValueError context.
        details = [{key: item[key] for key in ("type", "loc", "msg")} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": details})

    application.include_router(build_router(
        repo, settings, clock, soc or NotReadyEstimator(), soh or NotReadyEstimator(),
    ))
    return application


app = create_app()
