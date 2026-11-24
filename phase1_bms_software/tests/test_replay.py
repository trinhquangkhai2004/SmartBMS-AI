import json
from pathlib import Path

import httpx
import pytest

from replay.runner import ReplayError, load_records, parse_rate, run_replay
from tests.conftest import history, latest, warnings

DATA = Path(__file__).resolve().parents[1] / "sample_data"


def bridge(api):
    def handle(request):
        return api.request(request.method, str(request.url), content=request.content, headers=request.headers)
    return httpx.Client(transport=httpx.MockTransport(handle), base_url="http://testserver")


@pytest.mark.parametrize("filename,count", [("telemetry_1s.jsonl", 1), ("telemetry_2s.jsonl", 2),
                                           ("telemetry_invalid.jsonl", 2)])
def test_fixtures_are_deterministic_synthetic_and_valid(filename, count):
    records = load_records(DATA / filename)
    assert len(records) >= 3
    assert {r.source for r in records} == {"REPLAY"}
    assert {r.cell_count for r in records} == {count}
    assert [r.sequence_id for r in records] == sorted({r.sequence_id for r in records})


def test_replay_posts_public_endpoint_and_duplicate_is_idempotent(client):
    records = load_records(DATA / "telemetry_2s.jsonl")
    delays = []
    with bridge(client) as http:
        results = run_replay(records, "http://testserver", 2, client=http, sleep=delays.append)
        assert [r.status for r in results] == ["accepted"] * len(records)
        duplicates = run_replay(records, "http://testserver", 100, client=http, sleep=lambda _: None)
    assert all(r.status == "duplicate" for r in duplicates)
    assert delays == [0.5] * (len(records) - 1)
    assert len(history(client)["items"]) == len(records)
    assert latest(client)["source"] == "REPLAY"
    assert [event["transition"] for event in warnings(client)["items"]] == ["CLEARED", "ACTIVATED"]


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "101", "abc"])
def test_rate_must_be_bounded_and_finite(value):
    with pytest.raises(ValueError):
        parse_rate(value)


def test_loader_rejects_invalid_json_and_hardware_before_post(tmp_path):
    file = tmp_path / "bad.jsonl"
    for text in ['{', '{"source":"HARDWARE"}']:
        file.write_text(text)
        with pytest.raises(ReplayError, match="line 1"):
            load_records(file)


def test_replay_stops_on_http_error_and_invalid_ack():
    records = load_records(DATA / "telemetry_1s.jsonl")
    for response in [httpx.Response(409, json={"detail": {"code": "identity_conflict"}}),
                     httpx.Response(503, json={}), httpx.Response(201, json={})]:
        with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as http:
            with pytest.raises(ReplayError):
                run_replay(records, "http://testserver", 1, client=http, sleep=lambda _: None)


def test_replay_headers_and_request_path():
    records = load_records(DATA / "telemetry_1s.jsonl")[:1]
    def handle(request):
        assert request.url.path == "/api/v1/telemetry"
        assert request.headers["X-Device-Token"] == "demo-token"
        assert json.loads(request.content)["source"] == "REPLAY"
        return httpx.Response(201, json={"status": "accepted", "record_id": 1, "updated_latest": True,
                                        "server_received_at": "2026-11-11T10:00:00Z"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        assert len(run_replay(records, "http://testserver", 1, token="demo-token", client=http)) == 1
