# HTTP/JSON contract v1.0

Authority: blueprint Section 5/6/7. Actual validated schemas are available at /openapi.json and /docs.

## Telemetry request (all fields required)

| Field | Type and rule |
|---|---|
| schema_version | String, exactly "1.0" |
| source | "REPLAY" or "HARDWARE"; must match PBL_MODE |
| device_id | ASCII identifier, 1..64; starts alphanumeric, remaining alphanumeric / underscore / dot / colon / hyphen |
| session_id | Same identifier alphabet, 1..128; fresh per source boot |
| sequence_id | Strict integer, 0..9223372036854775807, monotonic within session |
| uptime_ms | Strict integer in same range; monotonic nondecreasing in sequence order |
| cell_count | Strict integer 1 or 2; booleans rejected |
| cell_voltages_v | Required vector of finite JSON numbers/null; length exactly cell_count; V |
| pack_current_a | Finite JSON number/null; A; positive discharge, negative charge |
| temperatures_c | 1..64 finite JSON numbers/null; degrees Celsius; placement/config TBD |
| validity | Exactly voltage/current/temperature boolean fields; no coercion |
| warnings | 0..5 unique warning codes from the closed set below |

Unknown object fields, numeric strings, bool-as-number, NaN and infinities are rejected with 422. A true validity group requires every value in that group to be non-null and finite. False validity groups may contain null or finite values; they are stored verbatim, never mapped to zero. INVALID_DATA is accepted telemetry, not a schema failure.

Allowed source-supplied warning codes:
CELL_OVERVOLTAGE, CELL_UNDERVOLTAGE, PACK_OVERCURRENT, OVER_TEMPERATURE, SENSOR_FAULT.
New codes require a versioned contract change. No software thresholds infer these flags.

```json
{"schema_version":"1.0","source":"REPLAY","device_id":"esp32-s3-01","session_id":"synthetic-demo-001","sequence_id":0,"uptime_ms":0,"cell_count":2,"cell_voltages_v":[3.91,3.89],"pack_current_a":0.72,"temperatures_c":[29.4,30.1],"validity":{"voltage":true,"current":true,"temperature":true},"warnings":[]}
```

All values above are fictitious. No electrical operating range, cell capacity or calibrated accuracy is asserted.

## Stored history

```json
{"id":1,"received_at_utc":"2026-11-11T10:00:00Z","measurement_status":"VALID","payload":{"schema_version":"1.0","source":"REPLAY","device_id":"esp32-s3-01","session_id":"synthetic-demo-001","sequence_id":0,"uptime_ms":0,"cell_count":2,"cell_voltages_v":[3.91,3.89],"pack_current_a":0.72,"temperatures_c":[29.4,30.1],"validity":{"voltage":true,"current":true,"temperature":true},"warnings":[]}}
```

The stored payload is canonical validated JSON (sorted keys, compact separators, normalized numeric fields). Server assigns received_at_utc in UTC. Identity is (device_id, session_id, sequence_id). Exact duplicate means equal canonical content; array order remains significant. Duplicates return the original record ID and receipt timestamp and do not refresh freshness.

## Latest state

Fields: device_id; source; connectivity_status; measurement_status; received_at_utc; age_seconds; cell_count; cell_voltages_v; pack_voltage_derived_v; pack_current_a; temperatures_c; validity; active_warnings; soc; soh.

- NO_DATA: every nullable measurement/quality/source/time field null; active_warnings empty.
- LIVE: age_seconds <= stale threshold. STALE: age_seconds > threshold.
- Age uses server UTC clock and current measurement receipt time, clamped to zero for backward wall-clock movement. It does not measure source packet latency or the battery's actual measurement age.
- VALID/INVALID_DATA uses validity flags independently of freshness.
- pack_voltage_derived_v sums the voltage group only when valid. Invalid voltage or floating-point sum overflow yields null. It is never a separately measured voltage.
- Raw finite invalid values remain available in latest/history with validity flags; the dashboard hides invalid groups from summary numbers/charts.
- STALE active_warnings are last-known source flags. Historical samples and duplicates do not change this set.
- validity is an additive response field needed for per-group invalid presentation; see decisions.md.

## Estimation result

```json
{"value_pct":null,"status":"NOT_READY","scope":null,"algorithm":"UNIMPLEMENTED","version":null,"updated_at":null}
```

Both SoC and SoH return this exact placeholder. The shared future result schema reserves status VALID, INVALID_INPUT, ERROR, scope CELL/PACK and nullable metadata. Unavailable results cannot contain percentages; VALID would require a finite percentage in 0..100. No future estimator is implemented or wired in Phase 1. estimations table remains empty.

## Session and warnings

First encounter of a session for a device activates it. The pointer advances only for a higher sequence in that active session. Earlier sequences and already-observed inactive sessions are stored historical with 202. Unknown sessions are assumed fresh boots; there is no boot ordering/authentication beyond this assumption.

Uptime is checked against nearest stored predecessor/successor in the same session; inconsistency is 409 uptime_regression and no write. Equal uptimes are allowed. New session counters restart at zero.

Within an active session, warning set deltas generate exactly ACTIVATED/CLEARED events. A new session starts its own warning baseline: supplied codes produce ACTIVATED; missing codes from the old session never produce artificial CLEARED events. Historical packets and duplicate retries generate no transitions.

No sampling, voltage/current/temperature safety threshold, SoC scope or model input contract is invented.
