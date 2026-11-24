"""Real loopback HTTP/process acceptance; no hardware and no developer database."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from replay.runner import load_records, run_replay

ROOT = Path(__file__).resolve().parents[1]


def test_real_process_replay_dashboard_restart_and_disconnect(tmp_path, monkeypatch):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("PBL_MODE", "REPLAY")
    monkeypatch.setenv("PBL_API_BASE_URL", url)
    monkeypatch.setenv("PBL_DEVICE_TOKEN", "")
    monkeypatch.setenv("PBL_DATABASE_PATH", str(tmp_path / "runtime.sqlite3"))
    environment = os.environ.copy()
    process = None
    log_path = tmp_path / "backend.log"

    def start(log):
        child = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(port), "--workers", "1"],
            cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 15
        with httpx.Client(timeout=0.5, trust_env=False) as http:
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise AssertionError(f"Uvicorn exited; see {log_path}")
                try:
                    if http.get(url + "/health").status_code == 200:
                        return child
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
        child.terminate()
        child.wait(timeout=5)
        raise AssertionError(f"Uvicorn did not become healthy; see {log_path}")

    def stop(child):
        child.terminate()
        child.wait(timeout=5)

    with log_path.open("w", encoding="utf-8") as log:
        try:
            process = start(log)
            with httpx.Client(timeout=2, trust_env=False) as http:
                records = load_records(ROOT / "sample_data/telemetry_2s.jsonl")
                acknowledgements = run_replay(records, url, 100, client=http, sleep=lambda _: None)
                assert all(ack.status == "accepted" for ack in acknowledgements)
                state = http.get(url + "/api/v1/state/latest", params={"device_id": "esp32-s3-01"}).json()
                assert state["source"] == "REPLAY" and state["connectivity_status"] == "LIVE"
                assert state["soc"]["value_pct"] is state["soh"]["value_pct"] is None
                events = http.get(url + "/api/v1/warnings", params={"device_id": "esp32-s3-01"}).json()
                assert [e["transition"] for e in events["items"]] == ["CLEARED", "ACTIVATED"]
                dashboard = AppTest.from_file(str(ROOT / "dashboard/app.py"), default_timeout=20).run()
                assert not dashboard.exception
                assert len(dashboard.get("vega_lite_chart")) == 3
                assert any("SIMULATED DATA" in element.value for element in dashboard.warning)

                run_replay(load_records(ROOT / "sample_data/telemetry_1s.jsonl"), url, 100,
                           client=http, sleep=lambda _: None)
                state = http.get(url + "/api/v1/state/latest", params={"device_id": "esp32-s3-01"}).json()
                assert state["cell_count"] == 1 and len(state["cell_voltages_v"]) == 1

                invalid = load_records(ROOT / "sample_data/telemetry_invalid.jsonl")
                run_replay(invalid[:2], url, 100, client=http, sleep=lambda _: None)
                dashboard.run()
                assert not dashboard.exception
                assert any("INVALID_DATA" in error.value for error in dashboard.error)
                assert any(metric.value == "UNAVAILABLE" for metric in dashboard.metric)
                run_replay(invalid[2:], url, 100, client=http, sleep=lambda _: None)
                assert http.get(url + "/api/v1/measurements",
                                params={"device_id": "esp32-s3-01"}).json()["items"].__len__() == 12

            stop(process)
            process = None
            process = start(log)
            with httpx.Client(timeout=2, trust_env=False) as http:
                state = http.get(url + "/api/v1/state/latest", params={"device_id": "esp32-s3-01"}).json()
                assert state["measurement_status"] == "VALID" and state["cell_count"] == 2
                duplicates = run_replay(invalid, url, 100, client=http, sleep=lambda _: None)
                assert all(ack.status == "duplicate" for ack in duplicates)
            dashboard.run()
            assert not dashboard.exception
            stop(process)
            process = None
            dashboard.run()
            assert not dashboard.exception
            assert any("BACKEND_DISCONNECTED" in error.value for error in dashboard.error)
        finally:
            if process is not None and process.poll() is None:
                stop(process)
