from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from dashboard.client import chart_rows, fetch_snapshot
from replay.runner import load_records, run_replay
from tests.test_contracts import sample
from tests.test_replay import bridge

APP = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
DATA = APP.parents[1] / "sample_data"


def app_test():
    return AppTest.from_file(str(APP), default_timeout=20)


def test_at_18_dashboard_disconnected_does_not_crash(monkeypatch):
    def unreachable(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr("dashboard.client.fetch_snapshot", unreachable)
    dashboard = app_test().run()
    assert not dashboard.exception
    assert any("BACKEND_DISCONNECTED" in element.value for element in dashboard.error)
    assert any("SIMULATED DATA" in element.value for element in dashboard.warning)


def test_at_19_replay_api_storage_dashboard_end_to_end(client, monkeypatch):
    with bridge(client) as http:
        records = load_records(DATA / "telemetry_2s.jsonl")
        run_replay(records, "http://testserver", 100, client=http, sleep=lambda _: None)
        snapshot = fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
        assert len(snapshot.history.items) == len(records)
        assert len(snapshot.events.items) == 2
        monkeypatch.setattr("dashboard.client.fetch_snapshot", lambda *args, **kwargs: snapshot)
        dashboard = app_test().run()
    assert not dashboard.exception
    assert any("SIMULATED DATA" in element.value for element in dashboard.warning)
    assert sum(metric.value == "NOT_READY" for metric in dashboard.metric) == 2
    assert any("LIVE" in element.value for element in dashboard.info)
    assert len(dashboard.get("vega_lite_chart")) == 3


def test_invalid_sensor_values_are_gaps(client):
    client.post("/api/v1/telemetry", json=sample(
        temperatures_c=[99.0, None], pack_current_a=8.8, cell_voltages_v=[4.2, 4.1],
        validity={"voltage": False, "current": False, "temperature": False}))
    with bridge(client) as http:
        snapshot = fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
    rows = chart_rows(snapshot.history)
    assert rows["voltage"][0]["Cell 1 (V)"] is None
    assert rows["current"][0]["Current (A)"] is None
    assert rows["temperature"][0]["Sensor 1 (°C)"] is None


def test_dashboard_stale_warnings_are_last_known(client, clock, monkeypatch):
    client.post("/api/v1/telemetry", json=sample(warnings=["SENSOR_FAULT"]))
    clock.advance(6)
    with bridge(client) as http:
        snapshot = fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
    monkeypatch.setattr("dashboard.client.fetch_snapshot", lambda *args, **kwargs: snapshot)
    dashboard = app_test().run()
    assert not dashboard.exception
    assert any("last-known" in element.value.lower() for element in dashboard.warning)
    assert any("STALE" in element.value for element in dashboard.warning)


def test_dashboard_no_data_has_no_zero_estimate(client, monkeypatch):
    with bridge(client) as http:
        snapshot = fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
    monkeypatch.setattr("dashboard.client.fetch_snapshot", lambda *args, **kwargs: snapshot)
    dashboard = app_test().run()
    assert not dashboard.exception
    assert any("NO_DATA" in element.value for element in dashboard.info)
    assert sum(metric.value == "NOT_READY" for metric in dashboard.metric) == 2
    assert not any(metric.value == "0%" for metric in dashboard.metric)


def test_bad_api_json_is_caught():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="not json"))) as http:
        try:
            fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed API JSON must not be presented as a successful poll")
