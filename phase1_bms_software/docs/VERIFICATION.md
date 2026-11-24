# Phase 1 verification evidence

Executed on Windows / CPython 3.14.2 in this workspace on 2026-11-11. Only the named Downloads blueprint was read. No hardware, real battery, logbook or ML work was performed.

## Final automated result

Working directory: D:\Study\PBL5\pbl5-bms-software.

```powershell
.\.venv-py314\Scripts\python.exe -m pytest -q
```

Actual output:

```text
........................................................................ [ 65%]
......................................                                   [100%]
110 passed in 27.96s
```

Exit code 0. pytest.ini treats Python warnings as errors. Streamlit AppTest emits its expected bare-mode ScriptRunContext log warning during tests; it is captured by pytest, not suppressed or treated as browser visual verification.

The tests use pytest temporary SQLite files. Stale tests use a fake injectable clock, not wall-clock sleeps. test_runtime.py launches an actual Uvicorn subprocess on a temporary loopback port, communicates through real HTTP, restarts the process against its temporary SQLite file, then verifies disconnected dashboard handling after termination. It cleans up its own subprocess.

## Acceptance coverage

| ID | Executed test / evidence | Result |
|---|---|---|
| AT-01 | test_api.py::test_at_01_valid_2s | PASS: 201, one stored record |
| AT-02 | test_api.py::test_at_02_valid_1s | PASS: one-cell vector |
| AT-03 | test_at_03_schema_rejected_without_storage; test_at_03_missing_and_malformed_json | PASS: 422, no rows |
| AT-04 | test_api.py::test_at_04_invalid_numbers + parametrized strict contract tests | PASS: NaN/±Infinity/string/bool rejected |
| AT-05 | test_state.py::test_at_05_invalid_null_sensor_is_stored_and_flagged | PASS: accepted INVALID_DATA; NOT_READY |
| AT-06 | test_ingestion.py::test_at_06_identical_duplicate | PASS: same row/timestamp, no freshness/event change |
| AT-07 | test_ingestion.py::test_at_07_conflict_preserves_original | PASS: 409 identity_conflict, original retained |
| AT-08 | test_at_08_older_sequence_historical_without_events_or_refresh | PASS: 202; current state/events/freshness unchanged |
| AT-09 | test_at_09_retired_session_cannot_reactivate | PASS: historical only |
| AT-10 | test_at_10_new_session_resets_sequence_without_artificial_clear | PASS: reboot resets sequence; no fabricated clear |
| AT-11 | test_api.py::test_at_11_mode_mismatch | PASS: 409, no row |
| AT-12 | test_at_12_injectable_clock_stale_boundary_and_last_known_warnings | PASS: exactly5s LIVE;5.001s STALE |
| AT-13 | test_ingestion.py::test_at_13_warning_add_remove | PASS: one ACTIVATED, one CLEARED |
| AT-14 | test_ingestion.py::test_at_14_repeated_warning_does_not_repeat_event | PASS: one event across repeats |
| AT-15 | test_state.py::test_at_15_no_data_null_measurements | PASS: nulls and NO_DATA |
| AT-16 | test_at_16_estimators_always_not_ready_and_not_persisted | PASS: both null/NOT_READY, estimations empty |
| AT-17 | test_at_17_restart_persists_latest_history_events_and_sessions + test_runtime.py | PASS: app restart and actual process restart |
| AT-18 | test_dashboard.py::test_at_18_dashboard_disconnected_does_not_crash + cache regressions + runtime disconnect | PASS: AppTest renders BACKEND_DISCONNECTED |
| AT-19 | test_at_19_replay_api_storage_dashboard_end_to_end + test_runtime.py | PASS: fixture, HTTP ingestion/storage/state/events and rendered Streamlit charts |
| AT-20 | test_at_20_sqlite_unavailable_on_startup; test_at_20_locked_write_is_503_and_recovers | PASS: 503, no false success |

AT-18/19 PASS describes executed AppTest and HTTP behavior. Direct human-style browser visual inspection remains NOT VERIFIED.

Additional executed checks cover atomic rollback via an aborting SQLite trigger, concurrent retries, pagination/device isolation, source token authentication, uptime-order conflicts, SQLite counter overflow bounds, invalid finite sensor values masked as null chart data, UTC normalization, incomplete/wrong-device API responses, and subnormal replay rates.

## Test-first and review evidence

- Contract tests first failed because app.config was not implemented; then 36 passed.
- Backend tests first failed because app.main was not implemented, after selecting compatible library versions.
- Backend group: 80 passed after fixing two unclosed SQLite connections in tests (sqlite3 context manager commits but does not close; explicit closing added).
- Replay/UI tests first failed because replay.runner/dashboard.client did not exist. An AppTest element assertion was corrected after inspecting the installed Streamlit node type vega_lite_chart; 99 tests then passed.
- UTC-offset clock regression: 1 failed / 3 passed, then 4 passed after normalizing receipt timestamps to UTC.
- Independent read-only review found incomplete LIVE responses could crash UI (Important), and subnormal replay rates could overflow sleep (Minor). Both were reproduced before fixes. Added wrong-device response regression at the same boundary: 6 failed, then 6 passed after fixes.
- Final complete suite including actual-process integration: 110 passed. No unresolved correctness finding from that review remains.

## Dependency and import verification

```powershell
$env:UV_CACHE_DIR = 'D:\Study\PBL5\pbl5-bms-software\.uv-cache'
uv pip install --offline --no-index --find-links .wheelhouse --python .venv-py314\Scripts\python.exe -r requirements.txt
.\.venv-py314\Scripts\python.exe -m pip check
.\.venv-py314\Scripts\python.exe -m compileall -q app dashboard replay tests
.\.venv-py314\Scripts\python.exe -m replay.runner --help
```

Executed results: requirements installation checked 9 direct pinned packages; pip check: **No broken requirements found**. compileall completed without output. CLI help displayed file, URL and bounded [0.1,100] demo rate. requirements.lock.txt records the complete installed transitive versions. Dependency metadata install is not a security audit.

## Separate live demo

Backend was actually started with:

```powershell
$env:PBL_DATABASE_PATH = './.runtime/e2e.sqlite3'
.\.venv-py314\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Observed Uvicorn startup: application startup complete; running on http://127.0.0.1:8000.

Executed replay:

```powershell
.\.venv-py314\Scripts\python.exe -m replay.runner --file sample_data/telemetry_2s.jsonl --url http://127.0.0.1:8000 --rate-hz 100
.\.venv-py314\Scripts\python.exe -m replay.runner --file sample_data/telemetry_1s.jsonl --url http://127.0.0.1:8000 --rate-hz 100
.\.venv-py314\Scripts\python.exe -m replay.runner --file sample_data/telemetry_invalid.jsonl --url http://127.0.0.1:8000 --rate-hz 100
```

Observed all 12 records accepted: IDs1..5 (2S),6..8 (1S),9..12 (invalid/recovery). After 2S replay, live HTTP queries reported health ok/REPLAY, LIVE/VALID, history count5, one OVER_TEMPERATURE ACTIVATED event and one CLEARED event. SoC and SoH both returned NOT_READY/null, algorithm UNIMPLEMENTED, scope/version/updated_at null. Derived pack voltage was7.720000000000001V (ordinary floating-point sum; UI formats it). No accuracy assertion follows.

Streamlit actually started using the README loopback command, reported URL http://127.0.0.1:8501, and its root HTTP request returned200. The separate actual-process test verifies the final code paths after review fixes; the live demo's initial server had started before those fixes. Demo processes were stopped after inspection attempts.

## NOT VERIFIED / deferred

- **Direct browser GUI visual inspection:** browser access host unavailable. Native Chrome app access required computer-use approval which timed out; no screenshot or visual layout success is claimed.
- **Online PyPI install:** sandbox outbound socket denied. Offline cache installation and dependency checks succeeded.
- **Other Python versions/platforms:** only Windows CPython3.14.2 executed.
- **Real batteries, ESP32, calibration, protection and engineering safety/accuracy requirements:** outside Phase1; none tested.
- **ECM/EKF, RF/NASA/CALCE training/inference, real SoC/SoH outputs:** deferred; no numerical estimator exists.
- **LAN/public deployment, firewall and production access controls:** not performed.

Synthetic replay proves software flow only. It cannot establish ER1–ER7 battery accuracy or physical safety.
