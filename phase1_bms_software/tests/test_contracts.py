import copy
import json

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import EstimationResult, Telemetry


def sample(**updates):
    payload = {
        "schema_version": "1.0", "source": "REPLAY", "device_id": "esp32-s3-01",
        "session_id": "boot-001", "sequence_id": 0, "uptime_ms": 0,
        "cell_count": 2, "cell_voltages_v": [3.91, 3.89],
        "pack_current_a": 0.72, "temperatures_c": [29.4, 30.1],
        "validity": {"voltage": True, "current": True, "temperature": True},
        "warnings": [],
    }
    payload.update(updates)
    return payload


def test_valid_1s_2s_and_integer_measurements():
    assert Telemetry.model_validate(sample()).is_valid
    assert Telemetry.model_validate(sample(cell_count=1, cell_voltages_v=[4])).is_valid


@pytest.mark.parametrize("updates", [
    {"cell_count": 1}, {"cell_count": True}, {"cell_count": "2"},
    {"sequence_id": -1}, {"sequence_id": 1.2}, {"sequence_id": True},
    {"sequence_id": 2**63}, {"uptime_ms": 2**63},
    {"pack_current_a": "0.72"}, {"pack_current_a": True},
    {"pack_current_a": float("nan")}, {"pack_current_a": float("inf")},
    {"cell_voltages_v": [float("-inf"), 3.9]},
    {"temperatures_c": []}, {"temperatures_c": ["29"]},
    {"cell_voltages_v": [None, 3.9]}, {"pack_current_a": None},
    {"temperatures_c": [None]}, {"source": "simulated"},
    {"schema_version": "2.0"}, {"device_id": ""}, {"device_id": "đevice"},
    {"device_id": "x" * 65}, {"device_id": "bad id"},
    {"session_id": ""}, {"session_id": "bad\nboot"},
    {"warnings": ["UNKNOWN"]}, {"warnings": ["SENSOR_FAULT", "SENSOR_FAULT"]},
    {"extra": 1},
    {"validity": {"voltage": 1, "current": True, "temperature": True}},
    {"validity": {"voltage": True, "current": True, "temperature": True, "x": True}},
])
def test_rejects_malformed_contract(updates):
    with pytest.raises(ValidationError):
        Telemetry.model_validate(sample(**updates))


def test_every_telemetry_field_is_required():
    for field in sample():
        payload = copy.deepcopy(sample())
        del payload[field]
        with pytest.raises(ValidationError):
            Telemetry.model_validate(payload)


def test_invalid_group_accepts_null_and_never_coerces_it():
    telemetry = Telemetry.model_validate(sample(
        temperatures_c=[None],
        validity={"voltage": True, "current": True, "temperature": False},
    ))
    assert not telemetry.is_valid
    assert json.loads(telemetry.model_dump_json())["temperatures_c"] == [None]


def test_estimation_placeholder_exact_contract():
    assert EstimationResult().model_dump(mode="json") == {
        "value_pct": None, "status": "NOT_READY", "scope": None,
        "algorithm": "UNIMPLEMENTED", "version": None, "updated_at": None,
    }
    with pytest.raises(ValidationError):
        EstimationResult(value_pct=float("nan"))
    with pytest.raises(ValidationError):
        EstimationResult(value_pct=50)


def test_settings_defaults_and_bounds(monkeypatch):
    for key in ["PBL_MODE", "PBL_DATABASE_PATH", "PBL_API_BASE_URL",
                "PBL_DASHBOARD_POLL_SECONDS", "PBL_STALE_AFTER_SECONDS", "PBL_DEVICE_TOKEN"]:
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env(env_file=None)
    assert settings.mode == "REPLAY"
    assert settings.stale_after_seconds == 5
    assert settings.dashboard_poll_seconds == 2
    for updates in [dict(stale_after_seconds=0), dict(dashboard_poll_seconds=float("nan")),
                    dict(mode="UNKNOWN"), dict(mode="HARDWARE", device_token=""),
                    dict(api_base_url="https://example.com")]:
        with pytest.raises(ValidationError):
            Settings(**updates)
