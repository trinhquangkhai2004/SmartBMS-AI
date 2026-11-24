from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app.estimators import NotReadyEstimator
from app.main import create_app
from dashboard.client import fetch_snapshot
from tests.test_contracts import sample
from tests.test_dashboard import APP
from tests.test_replay import bridge


def test_invalid_measurements_do_not_reach_estimator_interfaces(settings, clock):
    class RejectInput:
        def estimate(self, data, config):
            raise AssertionError("invalid measurements reached an estimator")
    with TestClient(create_app(settings, clock=clock, soc=RejectInput(), soh=RejectInput())) as api:
        api.post("/api/v1/telemetry", json=sample(
            temperatures_c=[None], validity={"voltage": True, "current": True, "temperature": False}))
        state = api.get("/api/v1/state/latest", params={"device_id": "esp32-s3-01"}).json()
        assert state["soc"]["status"] == state["soh"]["status"] == "NOT_READY"


def test_not_ready_adapter_exact_result():
    assert NotReadyEstimator().estimate(None, None).value_pct is None
    assert NotReadyEstimator().estimate(None, None).status == "NOT_READY"


def test_dashboard_cached_values_disconnect_and_device_change(client, monkeypatch):
    import httpx
    client.post("/api/v1/telemetry", json=sample(warnings=["SENSOR_FAULT"]))
    with bridge(client) as http:
        snapshot = fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
    monkeypatch.setattr("dashboard.client.fetch_snapshot", lambda *args, **kwargs: snapshot)
    dashboard = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not dashboard.exception
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr("dashboard.client.fetch_snapshot", offline)
    dashboard.run()
    assert not dashboard.exception
    assert any("BACKEND_DISCONNECTED" in error.value for error in dashboard.error)
    assert any("last-known" in warning.value.lower() for warning in dashboard.warning)
    assert not any(info.value.startswith("LIVE") for info in dashboard.info)
    dashboard.sidebar.text_input[0].set_value("other-device").run()
    assert not dashboard.exception
    assert len(dashboard.metric) == 0


def test_server_receipt_timestamp_is_utc_even_with_offset_clock(settings):
    clock = lambda: datetime(2026, 11, 11, 17, 0, tzinfo=timezone(timedelta(hours=7)))
    with TestClient(create_app(settings, clock=clock)) as api:
        result = api.post("/api/v1/telemetry", json=sample())
        assert result.status_code == 201
        assert result.json()["server_received_at"] == "2026-11-11T10:00:00Z"
