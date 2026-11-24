from contextlib import closing
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from tests.conftest import history, latest, warnings
from tests.test_contracts import sample

POST = "/api/v1/telemetry"


def test_at_06_identical_duplicate(client, clock):
    original = client.post(POST, json=sample(warnings=["SENSOR_FAULT"])).json()
    clock.advance(10)
    duplicate = client.post(POST, json=sample(warnings=["SENSOR_FAULT"]))
    assert duplicate.status_code == 200
    assert duplicate.json() == {**original, "status": "duplicate", "updated_latest": False}
    assert len(history(client)["items"]) == 1
    assert len(warnings(client)["items"]) == 1
    assert latest(client)["connectivity_status"] == "STALE"


def test_at_07_conflict_preserves_original(client):
    client.post(POST, json=sample())
    response = client.post(POST, json=sample(pack_current_a=8.1))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "identity_conflict"
    assert len(history(client)["items"]) == 1
    assert latest(client)["pack_current_a"] == 0.72


def test_at_08_older_sequence_historical_without_events_or_refresh(client, clock):
    client.post(POST, json=sample(sequence_id=10, uptime_ms=10000))
    clock.advance(6)
    response = client.post(POST, json=sample(sequence_id=3, uptime_ms=3000, warnings=["SENSOR_FAULT"]))
    assert response.status_code == 202
    assert response.json()["status"] == "accepted_historical"
    assert response.json()["updated_latest"] is False
    assert latest(client)["active_warnings"] == []
    assert latest(client)["connectivity_status"] == "STALE"
    assert warnings(client)["items"] == []
    assert len(history(client)["items"]) == 2


def test_at_09_retired_session_cannot_reactivate(client):
    client.post(POST, json=sample(session_id="old"))
    client.post(POST, json=sample(session_id="new", cell_voltages_v=[4.0, 4.0]))
    response = client.post(POST, json=sample(session_id="old", sequence_id=99, uptime_ms=99000,
                                          warnings=["SENSOR_FAULT"]))
    assert response.status_code == 202
    assert latest(client)["cell_voltages_v"] == [4, 4]
    assert warnings(client)["items"] == []


def test_at_10_new_session_resets_sequence_without_artificial_clear(client):
    client.post(POST, json=sample(sequence_id=100, uptime_ms=100000, warnings=["SENSOR_FAULT"]))
    response = client.post(POST, json=sample(session_id="reboot", sequence_id=0, uptime_ms=0))
    assert response.status_code == 201
    assert response.json()["updated_latest"] is True
    assert latest(client)["active_warnings"] == []
    assert [e["transition"] for e in warnings(client)["items"]] == ["ACTIVATED"]


def test_at_13_warning_add_remove(client):
    for sequence, codes in enumerate([[], ["OVER_TEMPERATURE"], []]):
        assert client.post(POST, json=sample(sequence_id=sequence, uptime_ms=sequence*1000,
                                             warnings=codes)).status_code == 201
    events = warnings(client)["items"]
    assert [e["transition"] for e in events] == ["CLEARED", "ACTIVATED"]
    assert all(e["warning_code"] == "OVER_TEMPERATURE" for e in events)
    assert latest(client)["active_warnings"] == []


def test_at_14_repeated_warning_does_not_repeat_event(client):
    for sequence in range(3):
        client.post(POST, json=sample(sequence_id=sequence, uptime_ms=sequence*1000,
                                     warnings=["SENSOR_FAULT"]))
    assert len(warnings(client)["items"]) == 1


def test_concurrent_identical_requests_are_atomic(client):
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: client.post(POST, json=sample(warnings=["SENSOR_FAULT"])), range(6)))
    # Bounded SQLite busy timeout may reject a writer; retrying it remains idempotent.
    assert sum(r.status_code == 201 for r in responses) == 1
    assert all(r.status_code in {200, 201, 503} for r in responses)
    assert len(history(client)["items"]) == 1
    assert len(warnings(client)["items"]) == 1


def test_pagination_and_device_isolation(client):
    for sequence in range(5):
        client.post(POST, json=sample(sequence_id=sequence, uptime_ms=sequence*1000,
                                     warnings=["SENSOR_FAULT"] if sequence % 2 else []))
    client.post(POST, json=sample(device_id="other-device"))
    first = history(client, limit=2)
    second = history(client, limit=2, before_id=first["next_before_id"])
    last = history(client, limit=2, before_id=second["next_before_id"])
    ids = [r["id"] for page in [first, second, last] for r in page["items"]]
    assert ids == sorted(set(ids), reverse=True)
    assert len(ids) == 5 and last["next_before_id"] is None
    first_events = warnings(client, limit=2)
    last_events = warnings(client, limit=2, before_id=first_events["next_before_id"])
    assert len(first_events["items"]) == len(last_events["items"]) == 2
    assert last_events["next_before_id"] is None
    assert latest(client, "other-device")["connectivity_status"] == "LIVE"


def test_write_failure_rolls_back_entire_ingestion(client, settings):
    with closing(sqlite3.connect(settings.database_path, isolation_level=None)) as connection:
        connection.execute("""CREATE TRIGGER reject_events BEFORE INSERT ON warning_events
                              BEGIN SELECT RAISE(ABORT, 'test rollback'); END""")
    assert client.post(POST, json=sample(warnings=["SENSOR_FAULT"])).status_code == 503
    assert history(client)["items"] == []
    assert latest(client)["connectivity_status"] == "NO_DATA"


def test_uptime_order_consistency(client):
    client.post(POST, json=sample(sequence_id=10, uptime_ms=10000))
    for payload in [sample(sequence_id=11, uptime_ms=1), sample(sequence_id=9, uptime_ms=20000)]:
        response = client.post(POST, json=payload)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "uptime_regression"
    assert len(history(client)["items"]) == 1
