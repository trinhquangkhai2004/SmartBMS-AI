from contextlib import closing
import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import history, latest
from tests.test_contracts import sample

POST = "/api/v1/telemetry"


def test_at_05_invalid_null_sensor_is_stored_and_flagged(client):
    payload = sample(temperatures_c=[None], warnings=["SENSOR_FAULT"],
                     validity={"voltage": True, "current": True, "temperature": False})
    assert client.post(POST, json=payload).status_code == 201
    state = latest(client)
    assert state["measurement_status"] == "INVALID_DATA"
    assert state["temperatures_c"] == [None]
    assert state["soc"]["status"] == state["soh"]["status"] == "NOT_READY"
    assert history(client)["items"][0]["measurement_status"] == "INVALID_DATA"


def test_invalid_voltage_never_has_derived_pack_voltage(client):
    client.post(POST, json=sample(cell_voltages_v=[3.9, None],
                                 validity={"voltage": False, "current": True, "temperature": True}))
    assert latest(client)["pack_voltage_derived_v"] is None


def test_at_12_injectable_clock_stale_boundary_and_last_known_warnings(client, clock):
    client.post(POST, json=sample(warnings=["SENSOR_FAULT"]))
    clock.advance(5)
    assert latest(client)["connectivity_status"] == "LIVE"
    clock.advance(0.001)
    state = latest(client)
    assert state["connectivity_status"] == "STALE"
    assert state["age_seconds"] == 5.001
    assert state["active_warnings"] == ["SENSOR_FAULT"]


def test_at_15_no_data_null_measurements(client):
    state = latest(client)
    assert state["connectivity_status"] == "NO_DATA"
    for key in ["source", "measurement_status", "received_at_utc", "age_seconds", "cell_count",
                "cell_voltages_v", "pack_voltage_derived_v", "pack_current_a", "temperatures_c", "validity"]:
        assert state[key] is None
    assert state["active_warnings"] == []


def test_at_16_estimators_always_not_ready_and_not_persisted(client, settings):
    for sequence in range(3):
        client.post(POST, json=sample(sequence_id=sequence, uptime_ms=sequence*1000))
    for kind in ["soc", "soh"]:
        assert latest(client)[kind] == {
            "value_pct": None, "status": "NOT_READY", "scope": None,
            "algorithm": "UNIMPLEMENTED", "version": None, "updated_at": None,
        }
    with closing(sqlite3.connect(settings.database_path, isolation_level=None)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM estimations").fetchone()[0] == 0


def test_at_17_restart_persists_latest_history_events_and_sessions(settings, clock):
    with TestClient(create_app(settings, clock=clock)) as first:
        first.post(POST, json=sample(session_id="old"))
        first.post(POST, json=sample(session_id="active", warnings=["SENSOR_FAULT"]))
    with TestClient(create_app(settings, clock=clock)) as second:
        assert latest(second)["active_warnings"] == ["SENSOR_FAULT"]
        assert len(history(second)["items"]) == 2
        assert second.post(POST, json=sample(session_id="old", sequence_id=9, uptime_ms=9000)).status_code == 202
        assert latest(second)["active_warnings"] == ["SENSOR_FAULT"]
