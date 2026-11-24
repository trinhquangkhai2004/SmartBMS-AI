import httpx
import pytest
from streamlit.testing.v1 import AppTest

from dashboard.client import fetch_snapshot
from replay.runner import parse_rate
from tests.test_contracts import sample
from tests.test_dashboard import APP
from tests.test_replay import bridge


def test_incomplete_live_response_becomes_disconnected_and_preserves_good_snapshot(client, monkeypatch):
    client.post("/api/v1/telemetry", json=sample())
    with bridge(client) as http:
        good = fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
    monkeypatch.setattr("dashboard.client.fetch_snapshot", lambda *args, **kwargs: good)
    dashboard = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not dashboard.exception
    def bad_poll(*args, **kwargs):
        def malformed(request):
            if request.url.path.endswith("/latest"):
                return httpx.Response(200, json={"device_id": "esp32-s3-01", "connectivity_status": "LIVE"})
            return httpx.Response(200, json={"items": [], "next_before_id": None})
        with httpx.Client(transport=httpx.MockTransport(malformed)) as http:
            return fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
    monkeypatch.setattr("dashboard.client.fetch_snapshot", bad_poll)
    dashboard.run()
    assert not dashboard.exception
    assert any("BACKEND_DISCONNECTED" in error.value for error in dashboard.error)
    assert sum(metric.value == "NOT_READY" for metric in dashboard.metric) == 2
    assert any("last-known" in caption.value.lower() for caption in dashboard.caption)


@pytest.mark.parametrize("value", [5e-324, 1e-300, 0.001, 0.099])
def test_unpractical_replay_rate_rejected_before_sending(value):
    with pytest.raises(ValueError):
        parse_rate(value)


def test_dashboard_does_not_accept_wrong_device_response():
    def wrong_device(request):
        if request.url.path.endswith("/latest"):
            return httpx.Response(200, json={"device_id": "other-device", "connectivity_status": "NO_DATA"})
        return httpx.Response(200, json={"items": [], "next_before_id": None})
    with httpx.Client(transport=httpx.MockTransport(wrong_device)) as http:
        with pytest.raises(ValueError):
            fetch_snapshot("http://testserver", "esp32-s3-01", 50, client=http)
