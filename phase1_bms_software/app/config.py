"""Small environment configuration loader; no global mutable settings."""
import ipaddress
import os
from pathlib import Path
from typing import Annotated, Self
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.schemas import Source

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PositiveSeconds = Annotated[float, Field(gt=0, le=3600, allow_inf_nan=False)]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Source = "REPLAY"
    database_path: Path = PROJECT_ROOT / "data" / "pbl5.sqlite3"
    api_base_url: str = "http://127.0.0.1:8000"
    dashboard_poll_seconds: PositiveSeconds = 2
    stale_after_seconds: PositiveSeconds = 5
    device_token: SecretStr = SecretStr("")
    db_busy_timeout_ms: Annotated[int, Field(ge=1, le=10000)] = 1000

    @model_validator(mode="after")
    def validate_network_configuration(self) -> Self:
        url = urlsplit(self.api_base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("API URL must be an HTTP(S) URL without credentials")
        if url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("API URL must contain only an origin")
        try:
            port = url.port
            if port is not None and port == 0:
                raise ValueError("invalid port")
            address = ipaddress.ip_address(url.hostname) if url.hostname != "localhost" else None
        except ValueError as exc:
            raise ValueError("use localhost or a private/loopback IP address") from exc
        loopback = url.hostname == "localhost" or address.is_loopback
        token = self.device_token.get_secret_value()
        if (self.mode == "HARDWARE" or not loopback) and not token.strip():
            raise ValueError("HARDWARE/non-loopback requires PBL_DEVICE_TOKEN")
        if address and not (address.is_loopback or address.is_private):
            raise ValueError("public API hosts are outside Phase 1 scope")
        return self

    @classmethod
    def from_env(cls, env_file: Path | None = PROJECT_ROOT / ".env") -> Self:
        values = dict(dotenv_values(env_file)) if env_file is not None and env_file.exists() else {}
        values.update(os.environ)
        mapping = {
            "PBL_MODE": "mode", "PBL_DATABASE_PATH": "database_path",
            "PBL_API_BASE_URL": "api_base_url",
            "PBL_DASHBOARD_POLL_SECONDS": "dashboard_poll_seconds",
            "PBL_STALE_AFTER_SECONDS": "stale_after_seconds",
            "PBL_DEVICE_TOKEN": "device_token",
            "PBL_DB_BUSY_TIMEOUT_MS": "db_busy_timeout_ms",
        }
        settings = cls(**{field: values[key] for key, field in mapping.items() if values.get(key) is not None})
        if not settings.database_path.is_absolute():
            settings.database_path = PROJECT_ROOT / settings.database_path
        return settings
