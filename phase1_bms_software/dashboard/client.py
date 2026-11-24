"""Validated HTTP snapshots and quality-masked chart data."""
from contextlib import nullcontext
from dataclasses import dataclass

import httpx

from app.schemas import LatestState, MeasurementPage, WarningPage


@dataclass(frozen=True)
class Snapshot:
    state: LatestState
    history: MeasurementPage
    events: WarningPage


def fetch_snapshot(url: str, device_id: str, limit: int, *, client: httpx.Client | None = None) -> Snapshot:
    manager = nullcontext(client) if client is not None else httpx.Client(timeout=2, trust_env=False)
    with manager as http:
        def fetch(path, model, **extra):
            response = http.get(url.rstrip("/") + path, params={"device_id": device_id, **extra})
            response.raise_for_status()
            return model.model_validate(response.json())
        snapshot = Snapshot(
            state=fetch("/api/v1/state/latest", LatestState),
            history=fetch("/api/v1/measurements", MeasurementPage, limit=limit),
            events=fetch("/api/v1/warnings", WarningPage, limit=limit),
        )
        if (snapshot.state.device_id != device_id or
                any(row.payload.device_id != device_id for row in snapshot.history.items) or
                any(event.device_id != device_id for event in snapshot.events.items)):
            raise ValueError("API response device does not match requested device")
        return snapshot


def chart_rows(history: MeasurementPage) -> dict[str, list[dict]]:
    groups = {"voltage": [], "current": [], "temperature": []}
    # History's API order is descending ID; chart time explicitly uses receipt UTC.
    for record in reversed(history.items):
        payload = record.payload
        base = {"Received at UTC": record.received_at_utc}
        groups["voltage"].append({
            **base, **{f"Cell {index + 1} (V)": value if payload.validity.voltage else None
                       for index, value in enumerate(payload.cell_voltages_v)},
        })
        groups["current"].append({
            **base, "Current (A)": payload.pack_current_a if payload.validity.current else None,
        })
        groups["temperature"].append({
            **base, **{f"Sensor {index + 1} (°C)": value if payload.validity.temperature else None
                       for index, value in enumerate(payload.temperatures_c)},
        })
    return groups
