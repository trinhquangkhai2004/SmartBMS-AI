# PBL5 BMS · Software Phase 1

Working local FastAPI + SQLite + Streamlit prototype for deterministic synthetic telemetry. Authority: PBL5_SOFTWARE_DESIGN_BLUEPRINT_v1.md v1.0.

**SIMULATED DATA: every supplied fixture uses source=REPLAY. SoC and SoH always show NOT_READY with value_pct=null.** This application records source-supplied warnings; it does not implement physical battery protection or validated abnormal-condition detection.

## Windows PowerShell setup

Run in D:\Study\PBL5\pbl5-bms-software. Verified environment: Windows, Python **3.14.2**. WindowsApps python/py aliases were inaccessible on this machine, so the tested interpreter path is explicit:

```powershell
Set-Location 'D:\Study\PBL5\pbl5-bms-software'
& 'C:\Users\quang\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m venv .venv-py314
.\.venv-py314\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

On another Windows PC, replace that interpreter path with your installed Python 3.14 executable. The implementation targets Python 3.11+, but only 3.14.2 was executed here. requirements.txt pins direct dependencies and applies requirements.lock.txt constraints for the tested full environment.

**Online package download is NOT VERIFIED:** the agent sandbox blocked PyPI sockets. Installation was actually completed offline using cached PyPI wheels. The generated .wheelhouse and .uv-cache are local ignored setup artifacts, not source dependencies. On this machine the verified offline equivalent is:

```powershell
Set-Location 'D:\Study\PBL5\pbl5-bms-software'
$env:UV_CACHE_DIR = (Join-Path (Get-Location) '.uv-cache')
uv pip install --offline --no-index --find-links .wheelhouse --python .venv-py314\Scripts\python.exe -r requirements.txt
.\.venv-py314\Scripts\python.exe -m pip check
```

Activation is optional. All following commands invoke the venv executable directly, so PowerShell execution-policy changes are unnecessary.

## Start backend (terminal 1)

```powershell
Set-Location 'D:\Study\PBL5\pbl5-bms-software'
.\.venv-py314\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

API docs: http://127.0.0.1:8000/docs. Health: http://127.0.0.1:8000/health.
Database defaults to data/pbl5.sqlite3; relative database paths are resolved against the project directory. SQLite schema is created on backend startup. Stop using Ctrl+C.

## Start dashboard (terminal 2)

```powershell
Set-Location 'D:\Study\PBL5\pbl5-bms-software'
.\.venv-py314\Scripts\python.exe -m streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

Open http://127.0.0.1:8501 in a browser. The page polls FastAPI, prominently labels SIMULATED DATA, and shows source, receipt age, connection/quality, group-masked measurements, derived pack voltage, source warning state/events, three history charts and NOT_READY estimators. No battery control buttons exist. Stop using Ctrl+C.

## Replay (terminal 3)

```powershell
Set-Location 'D:\Study\PBL5\pbl5-bms-software'
.\.venv-py314\Scripts\python.exe -m replay.runner --file sample_data/telemetry_2s.jsonl --url http://127.0.0.1:8000 --rate-hz 1
.\.venv-py314\Scripts\python.exe -m replay.runner --file sample_data/telemetry_1s.jsonl --url http://127.0.0.1:8000 --rate-hz 1
.\.venv-py314\Scripts\python.exe -m replay.runner --file sample_data/telemetry_invalid.jsonl --url http://127.0.0.1:8000 --rate-hz 1
```

Demo rate is bounded to 0.1..100 Hz; default 1 Hz. Each file has a distinct fixed synthetic session ID. 2S has five samples with a fictitious OVER_TEMPERATURE warning activated then cleared. 1S has three samples. Invalid-sensor replay has four samples: valid, invalid null temperature with SENSOR_FAULT, invalid voltage/current, then valid recovery. Inspect the dashboard during replay to see intermediate transitions.

Rerunning the same fixture returns duplicate and does not refresh latest/freshness. This is intentional idempotence. For another fresh demo, copy the fixture and change all its session_id values consistently to a new synthetic ID. A retired session stays historical. Fixtures contain no real measurements or experimentally justified safe operating limits.

## Query state, history and warnings

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 5
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/state/latest?device_id=esp32-s3-01' -TimeoutSec 5 | ConvertTo-Json -Depth 6
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/measurements?device_id=esp32-s3-01&limit=50' -TimeoutSec 5 | ConvertTo-Json -Depth 8
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/warnings?device_id=esp32-s3-01&limit=50' -TimeoutSec 5 | ConvertTo-Json -Depth 6
```

## Tests

```powershell
Set-Location 'D:\Study\PBL5\pbl5-bms-software'
.\.venv-py314\Scripts\python.exe -m pytest -q
.\.venv-py314\Scripts\python.exe -m pip check
.\.venv-py314\Scripts\python.exe -m compileall -q app dashboard replay tests
```

Tests use temporary database files and an injectable clock for deterministic stale cases. No developer/demo DB is opened by test fixtures. AT-01..AT-20 mappings, exact executed commands/results and limitations are in [docs/VERIFICATION.md](docs/VERIFICATION.md). GUI visual inspection is NOT VERIFIED because computer-use approval timed out; actual Streamlit AppTest and HTTP serving are tested separately.

## Configuration

| Setting | Default / meaning |
|---|---|
| PBL_MODE | REPLAY; source must match; HARDWARE reserved for future integration |
| PBL_DATABASE_PATH | ./data/pbl5.sqlite3 |
| PBL_API_BASE_URL | http://127.0.0.1:8000 |
| PBL_DASHBOARD_POLL_SECONDS | 2; allowed >0 through 3600 |
| PBL_STALE_AFTER_SECONDS | 5; stale when receipt age > threshold |
| PBL_DEVICE_TOKEN | blank only for local replay; when set replay sends X-Device-Token and ingestion requires it |
| PBL_DB_BUSY_TIMEOUT_MS | 1000; range 1..10000 |

Environment variables override .env. Demo timings are not engineering sampling/safety requirements. Sample age is server receipt age, so a delayed source packet can be older than it appears. STALE warnings are explicitly last-known; backend connection failure is BACKEND_DISCONNECTED. Invalid numeric/null groups are hidden as unavailable/gaps, not zero.

Only loopback bindings above are supported by this Phase 1 handoff. Read APIs have no authentication. Private-LAN access, firewall, device-token transport and actual hardware input require a separate review. The software cannot infer a manually overridden Uvicorn bind address.

## Source tree

```text
pbl5-bms-software/
  app/
    __init__.py  main.py  config.py  schemas.py  api.py
    ingestion.py  repository.py  state.py  estimators.py
  dashboard/
    __init__.py  app.py  client.py
  replay/
    __init__.py  runner.py
  sample_data/
    telemetry_1s.jsonl  telemetry_2s.jsonl  telemetry_invalid.jsonl
  tests/
    conftest.py  test_contracts.py  test_api.py  test_ingestion.py
    test_state.py  test_replay.py  test_dashboard.py
    test_regressions.py  test_review_fixes.py  test_runtime.py
  docs/
    ARCHITECTURE.md  DATA_CONTRACT.md  API.md  decisions.md
    VERIFICATION.md  plan.md
  .env.example  .gitignore  pytest.ini
  requirements.txt  requirements.lock.txt  README.md
```

## Limits and deferred work

No ECM/EKF, RF, NASA/CALCE processing, capacity/OCV curves or numerical SoC/SoH is implemented. Estimator inputs and CELL/PACK scope remain undecided. estimations storage is reserved and stays empty. NumPy/pandas/requests are required transitively by Streamlit; application HTTP uses httpx and no numerical battery model is added.

No real ESP32 firmware, calibration, hardware protection, charging/discharging, balancing or battery integration was performed. ER accuracy/safety requirements are unverified and cannot be validated by synthetic replay. History contains receipt-ordered records from all sessions; it is not source-time chronology. No data retention, production migration/backup tooling or public deployment is included.

See [architecture/data flow](docs/ARCHITECTURE.md), [data contract](docs/DATA_CONTRACT.md), [API](docs/API.md) and [decisions/deferred work](docs/decisions.md).
