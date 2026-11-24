# Implementation decisions and open questions

Authority remains PBL5-SD-001 v1.0. These are explicit technical clarifications; no product concept, logbook or battery design was changed.

| ID | Decision / reason | Consequence |
|---|---|---|
| D01 | Create pbl5-bms-software under the empty workspace; preserve root AGENTS.md. Read only the named blueprint in Downloads. | Blueprint's M0 reference to SAS v0.1 was not followed because user explicitly prohibited reading other Downloads documents. |
| D02 | Runtime tested on Windows, CPython 3.14.2. Python311 was available but cached binary UI dependencies matched 3.14. | Only 3.14.2 execution is verified. Python 3.11+ compatibility is not claimed as tested. WindowsApps python/py aliases failed; README supplies the actual executable path. |
| D03 | PyPI network access blocked; install compatible PyPI wheels from the existing local pip cache, using a workspace wheelhouse/cache. | No registry upload or global Python changes. Working direct pins and full transitive constraints recorded after execution. Online install NOT VERIFIED. |
| D04 | Pin Starlette 0.50.0 and AnyIO 4.13.0. | Newest cached combinations produced deprecation failures with warnings-as-errors. Selected pair passes tests with FastAPI 0.141.1. |
| D05 | ASCII identifiers use [A-Za-z0-9][A-Za-z0-9_.:-]*; device max64, session max128; temperatures max64; warning codes unique max5. | Blueprint left session and sensor-count bounds unspecified. These are transport/resource bounds, not hardware measurement limits. |
| D06 | sequence_id/uptime_ms and cursors limited to signed SQLite INTEGER maximum (2^63-1). | Avoid valid Python big integers overflowing sqlite3. No electrical threshold introduced. |
| D07 | Enforce uptime monotonic nondecreasing against nearest sequence predecessor/successor; inconsistent payload gets 409 uptime_regression. | Explicit extra conflict code resolves blueprint's monotonic uptime rule, including historical backfill. Equal uptime is allowed. |
| D08 | Add nullable validity to latest response. Page envelopes use items/next_before_id; measurement items carry nested payload. | Required for group-level invalid UI masking and a concrete cursor contract where blueprint omitted response details. |
| D09 | Duplicate equivalence is canonical validated JSON: sorted object keys, float normalization, array order preserved. | Duplicate ack returns original receipt time and never renews liveness. Changed array ordering is changed content. |
| D10 | Streamlit necessarily installs NumPy/pandas/requests and other rendering dependencies transitively. Application uses httpx consistently; no direct NumPy/requests use, scientific model packages, sklearn, SciPy or joblib. | Literal exclusion of all NumPy installations is incompatible with required Streamlit. Small justified dependency clarification only; no ML/numerical battery implementation. |
| D11 | SQLite uses native finite busy_timeout, no extra retry loop; transaction begins IMMEDIATE. Startup DB errors leave API running with 503 data/health errors. | Recoverable locked DB may work after lock release; a new inaccessible DB requiring schema initialization needs app restart after repair. |
| D12 | Fresh when age <= threshold, stale when age > threshold; normalize receipt timestamps to UTC; clamp negative age after wall-clock rollback. | Demo receipt-time state is not sensor/packet age. New/duplicate/historical semantics are independent. |
| D13 | New session starts an independent warning baseline. Emit ACTIVATED for its supplied codes and no CLEARED across restart. | Missing previous codes mean unknown/changed source state, not an observed physical recovery. |
| D14 | Invalid finite values remain in raw API records; dashboard masks whole invalid groups, including finite numbers. Derived pack sum overflow yields null. | Invalid values and unrepresentable derived sums never become zero or non-JSON infinity. No safety bounds added. |
| D15 | Token protects telemetry POST when configured. Private non-loopback URL/HARDWARE settings require nonblank token; reject public configured hosts. Read routes are local unauthenticated. | CLI Uvicorn host cannot be inferred by Settings. Only loopback commands are delivered; LAN/firewall/authentication transport review remains deferred. |
| D16 | Deterministic fixtures use fixed synthetic session IDs; rerunning is intentionally idempotent. | To demonstrate a fresh boot, copy a fixture and replace session_id consistently with a fresh ID. Never silently reuse a physical boot ID in future firmware. |
| D17 | Dashboard caches a complete valid response for the same API/device only. Unreachable, bad HTTP/JSON or invalid response becomes BACKEND_DISCONNECTED, stale/cached warnings explicitly last-known. | No cached LIVE badge while disconnected; a switched device has no inherited cache. |
| D18 | Streamlit AppTest verifies rendered elements and error paths. Browser host was unavailable and native app approval timed out. | Direct visual GUI inspection NOT VERIFIED; HTTP200 and AppTest do not imply browser visual QA. |
| D19 | No Git repo existed; no initialization/commits/worktrees or unrelated file changes. | Delivery consists of source + evidence in the workspace. |

| D20 | Replay demo speed bounded to 0.1..100 Hz, checked before sending. | Prevent reciprocal/sleep overflow for subnormal floats and impractical demo pauses; not an engineering sampling bound. |
| D21 | Validate conditional latest-state completeness and snapshot device consistency. | A malformed HTTP200 LIVE/STALE response becomes BACKEND_DISCONNECTED before caching/rendering, preserving the last good response. |

## Deferred decisions and work (Phase 2+ only)

- Estimator CELL/PACK scope and exact ECM/EKF/RF input/config models.
- ECM parameters, OCV curve, capacity, Coulomb Counting/1-RC ECM/EKF identification and validation.
- NASA/CALCE ingestion, RF features, artifact provenance, training/inference/evaluation and cell-separated datasets.
- Real sensor calibration, actual reference SoC/SoH, Lishen generalization and ER1–ER7 verification.
- AFE/protection circuitry, ESP32 sensor firmware, local warning delays/hysteresis and physical 1S/2S integration.
- Engineering sampling requirements, battery operating limits and protective thresholds.
- LAN binding, read-route access, firewall, token distribution/transport and physical integration approval.

No battery has been connected, charged, discharged, balanced, switched or tested by this software work. Synthetic results provide no accuracy/safety evidence.
