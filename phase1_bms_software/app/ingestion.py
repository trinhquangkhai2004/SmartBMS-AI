"""Atomic identity, session progression and source-supplied warning transitions."""
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone

from app.repository import Repository
from app.schemas import Ack, Source, Telemetry

Clock = Callable[[], datetime]


class IngestionConflict(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def ingest(repo: Repository, payload: Telemetry, mode: Source, clock: Clock) -> Ack:
    if payload.source != mode:
        raise IngestionConflict("mode_mismatch", "Telemetry source must match PBL_MODE")
    canonical = json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with repo.transaction() as connection:
        existing = connection.execute(
            """SELECT id, payload_sha256, received_at_utc FROM measurements
               WHERE device_id=? AND session_id=? AND sequence_id=?""",
            (payload.device_id, payload.session_id, payload.sequence_id),
        ).fetchone()
        if existing:
            if existing["payload_sha256"] != digest:
                raise IngestionConflict("identity_conflict", "Identity already has different telemetry")
            return Ack(status="duplicate", record_id=existing["id"], updated_latest=False,
                       server_received_at=existing["received_at_utc"])

        runtime = connection.execute(
            "SELECT * FROM device_runtime WHERE device_id=?", (payload.device_id,),
        ).fetchone()
        seen = connection.execute(
            "SELECT 1 FROM measurements WHERE device_id=? AND session_id=? LIMIT 1",
            (payload.device_id, payload.session_id),
        ).fetchone()
        new_session = not seen
        update_latest = (
            runtime is None or new_session or
            (runtime["active_session_id"] == payload.session_id and
             payload.sequence_id > runtime["latest_sequence_id"])
        )

        # Enforce monotonic uptime in sequence order, including backfilled records.
        previous = connection.execute(
            """SELECT uptime_ms FROM measurements WHERE device_id=? AND session_id=?
               AND sequence_id < ? ORDER BY sequence_id DESC LIMIT 1""",
            (payload.device_id, payload.session_id, payload.sequence_id),
        ).fetchone()
        following = connection.execute(
            """SELECT uptime_ms FROM measurements WHERE device_id=? AND session_id=?
               AND sequence_id > ? ORDER BY sequence_id ASC LIMIT 1""",
            (payload.device_id, payload.session_id, payload.sequence_id),
        ).fetchone()
        if ((previous and previous["uptime_ms"] > payload.uptime_ms) or
                (following and following["uptime_ms"] < payload.uptime_ms)):
            raise IngestionConflict("uptime_regression", "Uptime must be monotonic in session sequence order")

        received_at = clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("ingestion clock must return timezone-aware datetimes")
        received_at = received_at.astimezone(timezone.utc)
        timestamp = received_at.isoformat()
        cursor = connection.execute(
            """INSERT INTO measurements
               (device_id, session_id, sequence_id, uptime_ms, source, cell_count,
                payload_json, payload_sha256, is_valid, received_at_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payload.device_id, payload.session_id, payload.sequence_id, payload.uptime_ms,
             payload.source, payload.cell_count, canonical, digest, int(payload.is_valid), timestamp),
        )
        record_id = cursor.lastrowid
        if update_latest:
            old_codes = set()
            if runtime and not new_session:
                old_row = connection.execute(
                    "SELECT payload_json FROM measurements WHERE id=?", (runtime["latest_measurement_id"],),
                ).fetchone()
                old_codes = set(json.loads(old_row["payload_json"])["warnings"])
            new_codes = set(payload.warnings)
            # A new session has an unknown prior physical state: never synthesize clears.
            for transition, codes in [("ACTIVATED", new_codes - old_codes), ("CLEARED", old_codes - new_codes)]:
                for code in sorted(codes):
                    connection.execute(
                        """INSERT INTO warning_events
                           (device_id, measurement_id, warning_code, transition, occurred_at_utc)
                           VALUES (?, ?, ?, ?, ?)""",
                        (payload.device_id, record_id, code, transition, timestamp),
                    )
            connection.execute(
                """INSERT INTO device_runtime
                   (device_id, active_session_id, latest_sequence_id, latest_measurement_id, last_received_at_utc)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(device_id) DO UPDATE SET
                   active_session_id=excluded.active_session_id, latest_sequence_id=excluded.latest_sequence_id,
                   latest_measurement_id=excluded.latest_measurement_id,
                   last_received_at_utc=excluded.last_received_at_utc""",
                (payload.device_id, payload.session_id, payload.sequence_id, record_id, timestamp),
            )
        return Ack(status="accepted" if update_latest else "accepted_historical",
                   record_id=record_id, updated_latest=update_latest, server_received_at=received_at)
