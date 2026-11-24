"""SQLite persistence. Connections belong to one unit of work, never to a process."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.schemas import MeasurementRecord, Telemetry, WarningEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    sequence_id INTEGER NOT NULL CHECK(sequence_id >= 0),
    uptime_ms INTEGER NOT NULL CHECK(uptime_ms >= 0),
    source TEXT NOT NULL CHECK(source IN ('REPLAY','HARDWARE')),
    cell_count INTEGER NOT NULL CHECK(cell_count IN (1,2)),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    is_valid INTEGER NOT NULL CHECK(is_valid IN (0,1)),
    received_at_utc TEXT NOT NULL,
    UNIQUE(device_id, session_id, sequence_id)
);
CREATE INDEX IF NOT EXISTS ix_measurements_device_id_desc ON measurements(device_id, id DESC);
CREATE TABLE IF NOT EXISTS device_runtime (
    device_id TEXT PRIMARY KEY,
    active_session_id TEXT NOT NULL,
    latest_sequence_id INTEGER NOT NULL,
    latest_measurement_id INTEGER NOT NULL,
    last_received_at_utc TEXT NOT NULL,
    FOREIGN KEY(latest_measurement_id) REFERENCES measurements(id)
);
CREATE TABLE IF NOT EXISTS warning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    measurement_id INTEGER NOT NULL,
    warning_code TEXT NOT NULL,
    transition TEXT NOT NULL CHECK(transition IN ('ACTIVATED','CLEARED')),
    occurred_at_utc TEXT NOT NULL,
    FOREIGN KEY(measurement_id) REFERENCES measurements(id)
);
CREATE INDEX IF NOT EXISTS ix_warning_events_device_id_desc ON warning_events(device_id, id DESC);
CREATE TABLE IF NOT EXISTS estimations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('SOC','SOH')),
    value_pct REAL,
    status TEXT NOT NULL,
    scope TEXT,
    algorithm TEXT NOT NULL,
    model_version TEXT,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY(measurement_id) REFERENCES measurements(id)
);
"""


def measurement_record(row: sqlite3.Row) -> MeasurementRecord:
    return MeasurementRecord(
        id=row["id"], received_at_utc=row["received_at_utc"],
        measurement_status="VALID" if row["is_valid"] else "INVALID_DATA",
        payload=Telemetry.model_validate_json(row["payload_json"]),
    )


class Repository:
    def __init__(self, path: Path, busy_timeout_ms: int = 1000):
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path, timeout=self.busy_timeout_ms / 1000, isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms:d}")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")

    def check_health(self) -> None:
        with self.connection() as connection:
            connection.execute("SELECT id FROM measurements LIMIT 1").fetchone()
            connection.execute("SELECT device_id FROM device_runtime LIMIT 1").fetchone()
            connection.execute("SELECT id FROM warning_events LIMIT 1").fetchone()
            connection.execute("SELECT id FROM estimations LIMIT 1").fetchone()

    def latest(self, device_id: str) -> MeasurementRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                """SELECT m.* FROM device_runtime r JOIN measurements m
                   ON r.latest_measurement_id=m.id WHERE r.device_id=?""", (device_id,),
            ).fetchone()
            return measurement_record(row) if row else None

    def measurements(self, device_id: str, limit: int, before_id: int | None):
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM measurements WHERE device_id=?
                   AND (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?""",
                (device_id, before_id, before_id, limit + 1),
            ).fetchall()
        items = [measurement_record(row) for row in rows[:limit]]
        return items, items[-1].id if len(rows) > limit else None

    def warning_events(self, device_id: str, limit: int, before_id: int | None):
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM warning_events WHERE device_id=?
                   AND (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?""",
                (device_id, before_id, before_id, limit + 1),
            ).fetchall()
        items = [WarningEvent(**dict(row)) for row in rows[:limit]]
        return items, items[-1].id if len(rows) > limit else None
