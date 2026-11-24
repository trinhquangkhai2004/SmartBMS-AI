from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_contracts import sample


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=tmp_path / "test.sqlite3", db_busy_timeout_ms=30)


@pytest.fixture
def client(settings, clock):
    with TestClient(create_app(settings, clock=clock)) as value:
        yield value


@pytest.fixture
def payload():
    return sample()


def latest(client, device_id="esp32-s3-01"):
    return client.get("/api/v1/state/latest", params={"device_id": device_id}).json()


def history(client, **params):
    return client.get("/api/v1/measurements", params={"device_id": "esp32-s3-01", **params}).json()


def warnings(client, **params):
    return client.get("/api/v1/warnings", params={"device_id": "esp32-s3-01", **params}).json()
