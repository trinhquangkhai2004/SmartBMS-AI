# Local API v1

Base: http://127.0.0.1:8000. UTF-8 JSON. OpenAPI: /openapi.json; interactive docs: /docs. One worker. Loopback-only replay startup is documented in README.

| Method/path | Success | Error |
|---|---|---|
| POST /api/v1/telemetry | 201 accepted, 200 duplicate, 202 accepted_historical | 401 token; 409 conflict; 422 validation; 503 DB |
| GET /api/v1/state/latest?device_id=... | 200 LatestState, including NO_DATA | 422 query; 503 DB |
| GET /api/v1/measurements?device_id=...&limit=50&before_id=... | 200 MeasurementPage | 422 query; 503 DB |
| GET /api/v1/warnings?device_id=...&limit=50&before_id=... | 200 WarningPage | 422 query; 503 DB |
| GET /health | 200 health | 503 DB |

device_id is required and follows DATA_CONTRACT.md. limit is 1..200, default 50. before_id is optional, integer 1..9223372036854775807.

## Acknowledgement

```json
{"status":"accepted","record_id":123,"updated_latest":true,"server_received_at":"2026-11-11T10:00:00Z"}
```

For duplicate and historical responses, updated_latest is false. Duplicate uses original timestamp and record ID. Successful write acknowledgement is issued only after the entire ingestion transaction commits.

## Pages

Both history routes return {"items":[...],"next_before_id":123}. Items are descending SQLite ID, filtered by device. The cursor is the last returned item ID when more items exist; null at end. Pass it as before_id for the next page; the comparison is exclusive. Measurement IDs reflect arrival order, including historical packets.

Measurements contain id, received_at_utc, measurement_status and nested payload. Warning items contain id, device_id, measurement_id, warning_code, transition and occurred_at_utc. See schemas and DATA_CONTRACT.md.

## Stable errors

```json
{"detail":{"code":"identity_conflict","message":"Identity already has different telemetry"}}
```

| HTTP/code | Meaning / recovery |
|---|---|
| 401 unauthorized | Configured X-Device-Token missing/wrong; no write |
| 409 mode_mismatch | Payload source differs from configured PBL_MODE; no write |
| 409 identity_conflict | Same identity, changed canonical content; preserve original |
| 409 uptime_regression | Uptime contradicts session sequence order; correct source/session |
| 503 database_unavailable | Database unavailable/locked; transaction not acknowledged |

422 preserves FastAPI's detail array (type, loc, msg). Input and exception context are omitted to avoid echoing secrets, malformed large payloads or non-JSON NaN/Infinity. Structurally malformed requests never reach storage.

SQLite busy_timeout is bounded (default 1000 ms; allowed 1..10000). There is no endless retry. A client may retry a transient failure using the exact same identity/content; uniqueness ensures idempotence. If the connection drops after commit, retry may return duplicate instead of accepted.

## Authentication and network scope

X-Device-Token is required on telemetry POST when PBL_DEVICE_TOKEN is nonblank. Reads remain local unauthenticated in this prototype. HARDWARE mode and a configured non-loopback private API URL require a nonblank token; this is an interface guard, not a LAN deployment approval. Dashboard/replay use httpx, short timeouts and trust_env=False to avoid sending local requests via ambient proxy settings.

The application cannot infer a user-selected Uvicorn bind address. Follow the provided 127.0.0.1 commands. LAN use, access to read endpoints, firewall rules, token transport and all physical integration are deferred for explicit review. No public deployment or hardware instructions are provided.

## Health response

```json
{"status":"ok","mode":"REPLAY","database":"available"}
```

Health checks that required SQLite tables are readable. It does not certify that future writes will succeed or that any battery/device/model is healthy.
