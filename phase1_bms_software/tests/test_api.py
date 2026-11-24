import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import history, latest
from tests.test_contracts import sample

POST = "/api/v1/telemetry"


def test_at_01_valid_2s(client):
    response = client.post(POST, json=sample())
    assert response.status_code == 201
    assert response.json()["status"] == "accepted"
    assert response.json()["updated_latest"] is True
    assert len(history(client)["items"]) == 1


def test_at_02_valid_1s(client):
    assert client.post(POST, json=sample(cell_count=1, cell_voltages_v=[3.9])).status_code == 201
    assert latest(client)["cell_voltages_v"] == [3.9]


@pytest.mark.parametrize("broken", [
    {"cell_count": 1}, {"source": "UNKNOWN"}, {"schema_version": "2.0"},
    {"warnings": ["UNKNOWN"]}, {"validity": {"voltage": True}},
])
def test_at_03_schema_rejected_without_storage(client, broken):
    assert client.post(POST, json=sample(**broken)).status_code == 422
    assert history(client)["items"] == []


def test_at_03_missing_and_malformed_json(client):
    payload = sample()
    del payload["pack_current_a"]
    assert client.post(POST, json=payload).status_code == 422
    assert client.post(POST, content="{", headers={"Content-Type": "application/json"}).status_code == 422
    assert history(client)["items"] == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "0.7", True])
def test_at_04_invalid_numbers(client, value):
    # Raw JSON is intentional: JSON clients normally prohibit NaN/Infinity themselves.
    response = client.post(POST, content=json.dumps(sample(pack_current_a=value)),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert history(client)["items"] == []


def test_at_11_mode_mismatch(client):
    response = client.post(POST, json=sample(source="HARDWARE"))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "mode_mismatch"
    assert history(client)["items"] == []


@pytest.mark.parametrize("path", ["/api/v1/state/latest", "/api/v1/measurements", "/api/v1/warnings"])
def test_query_validation(client, path):
    for params in [{}, {"device_id": ""}, {"device_id": "bad id"}, {"device_id": "x"*65}]:
        assert client.get(path, params=params).status_code == 422


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 201}, {"limit": "nan"}, {"before_id": 0},
    {"before_id": 2**63}, {"before_id": "1.2"},
])
def test_pagination_rejects_invalid_query(client, params):
    for path in ["/api/v1/measurements", "/api/v1/warnings"]:
        assert client.get(path, params={"device_id": "esp32-s3-01", **params}).status_code == 422


def test_token_required_when_enabled(tmp_path, clock):
    settings = Settings(database_path=tmp_path / "token.sqlite3", device_token="test-secret")
    with TestClient(create_app(settings, clock=clock)) as api:
        for headers in [{}, {"X-Device-Token": "incorrect"}]:
            assert api.post(POST, json=sample(), headers=headers).status_code == 401
        assert history(api)["items"] == []
        assert api.post(POST, json=sample(), headers={"X-Device-Token": "test-secret"}).status_code == 201


def test_at_20_sqlite_unavailable_on_startup(tmp_path, clock):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("block")
    with TestClient(create_app(Settings(database_path=blocker / "db.sqlite3"), clock=clock)) as api:
        response = api.post(POST, json=sample())
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_unavailable"
        for path, params in [("/health", {}), ("/api/v1/state/latest", {"device_id": "x"}),
                             ("/api/v1/measurements", {"device_id": "x"}),
                             ("/api/v1/warnings", {"device_id": "x"})]:
            assert api.get(path, params=params).status_code == 503


def test_at_20_locked_write_is_503_and_recovers(client, settings):
    connection = sqlite3.connect(settings.database_path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        assert client.post(POST, json=sample()).status_code == 503
        assert history(client)["items"] == []
    finally:
        connection.rollback()
        connection.close()
    assert client.post(POST, json=sample()).status_code == 201


def test_openapi_health_and_documented_responses(client):
    assert client.get("/health").json() == {"status": "ok", "mode": "REPLAY", "database": "available"}
    schema = client.get("/openapi.json").json()
    assert schema["components"]["schemas"]["Telemetry"]["additionalProperties"] is False
    responses = schema["paths"][POST]["post"]["responses"]
    assert {"200", "201", "202", "401", "409", "422", "503"} <= responses.keys()
