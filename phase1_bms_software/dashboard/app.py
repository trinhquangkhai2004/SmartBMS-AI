"""Streamlit entrypoint. All telemetry arrives via the versioned HTTP API."""
import sys
from datetime import datetime, timezone
from pathlib import Path

# Streamlit runs this file by path; ensure the backend package wins over this app.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import streamlit as st
from pydantic import TypeAdapter, ValidationError

from app.config import Settings
from app.schemas import Identifier
from dashboard.client import chart_rows, fetch_snapshot


def show_dashboard():
    st.set_page_config(page_title="PBL5 BMS · Phase 1", page_icon="🔋", layout="wide")
    st.title("PBL5 | AI-Based Battery Management System")
    st.caption("Software Phase 1 · source-supplied telemetry and warnings · no battery control")
    try:
        settings = Settings.from_env()
    except ValueError:
        st.error("CONFIGURATION_ERROR · Check .env settings.")
        return
    if settings.mode == "REPLAY":
        st.warning("SIMULATED DATA · REPLAY · All fixture measurements and warnings are fictitious.")
    st.caption("SoC/SoH are unimplemented. Hardware protection is independent of this application.")
    device_id = st.sidebar.text_input("Device ID", value="esp32-s3-01")
    limit = st.sidebar.slider("History samples", min_value=1, max_value=200, value=50)
    st.sidebar.caption(f"Polling every {settings.dashboard_poll_seconds:g} s · demo setting")
    st.sidebar.caption(f"Stale after {settings.stale_after_seconds:g} s · receipt time, not sensor age")
    try:
        # Apply the same identifier rule without fabricating a telemetry payload.
        TypeAdapter(Identifier).validate_python(device_id)
    except ValidationError:
        st.error("Enter a valid ASCII device identifier (1–64 characters).")
        return

    @st.fragment(run_every=settings.dashboard_poll_seconds)
    def live_panel():
        st.button("Refresh")
        cache_key = (settings.api_base_url, device_id)
        disconnected = False
        try:
            snapshot = fetch_snapshot(settings.api_base_url, device_id, limit)
            success_at = datetime.now(timezone.utc)
            st.session_state["last_snapshot"] = (cache_key, snapshot, success_at)
        except (httpx.HTTPError, ValueError):
            disconnected = True
            st.error("BACKEND_DISCONNECTED · No complete valid API response. Retrying on the next poll.")
            cached = st.session_state.get("last_snapshot")
            if cached is None or cached[0] != cache_key:
                st.caption("Last successful response: unavailable for this device.")
                return
            _, snapshot, success_at = cached
            st.caption(f"Last successful response: {success_at.isoformat()} · last-known values below.")

        state = snapshot.state
        if state.source == "REPLAY" and settings.mode != "REPLAY":
            st.warning("SIMULATED DATA · Actual API source is REPLAY.")
        st.caption(f"Actual source: {state.source or 'NO_DATA'} · Device: {state.device_id}")
        if state.connectivity_status == "NO_DATA":
            st.info("NO_DATA · No telemetry has been received for this device.")
        else:
            age = state.age_seconds
            if disconnected:
                age = max(0, (datetime.now(timezone.utc) - state.received_at_utc).total_seconds())
            text = f"{'BACKEND_DISCONNECTED' if disconnected else state.connectivity_status} · Sample receipt age: {age:.1f} s"
            if disconnected or state.connectivity_status == "STALE":
                st.warning(text)
            else:
                st.info(text)
            st.caption(f"Backend receipt UTC: {state.received_at_utc.isoformat()} · Quality: {state.measurement_status}")
            if state.measurement_status == "INVALID_DATA":
                st.error("INVALID_DATA · Flagged sensor groups are invalid; charts mask them as gaps.")
            validity = state.validity
            metrics = []
            for index, value in enumerate(state.cell_voltages_v):
                metrics.append((f"Cell {index + 1} (V)", value if validity.voltage else None))
            metrics.append(("Pack voltage (V, derived)", state.pack_voltage_derived_v))
            metrics.append(("Current (A; + discharge / − charge)", state.pack_current_a if validity.current else None))
            for index, value in enumerate(state.temperatures_c):
                metrics.append((f"Temperature {index + 1} (°C)", value if validity.temperature else None))
            columns = st.columns(3)
            for index, (label, value) in enumerate(metrics):
                columns[index % 3].metric(label, f"{value:.3f}" if value is not None else "UNAVAILABLE")
            st.caption("Unavailable/invalid readings are never mapped to zero. Pack voltage is DERIVED.")
        panels = st.columns(2)
        for column, label in zip(panels, ["SoC", "SoH"]):
            column.metric(label, "NOT_READY")
            column.caption("value_pct: null · UNIMPLEMENTED · scope undecided")

        last_known = disconnected or state.connectivity_status == "STALE"
        if state.active_warnings:
            qualifier = "last-known" if last_known else "current"
            st.warning(f"Source-supplied warnings ({qualifier}): " + ", ".join(state.active_warnings))
        else:
            st.info("Source-supplied warnings (last-known): none" if last_known else "Source-supplied warnings: none")
        st.caption("Warning flags are supplied by the source. They do not certify battery safety.")

        for title, rows in zip(
            ["Cell voltages (V)", "Pack current (A)", "Temperatures (°C)"],
            chart_rows(snapshot.history).values(),
        ):
            st.subheader(title)
            if rows:
                series = sorted({key for row in rows for key in row if key != "Received at UTC"})
                st.line_chart(rows, x="Received at UTC", y=series)
            else:
                st.caption("No history.")
        st.caption("Charts use backend receipt UTC; history includes delayed/inactive-session records. Invalid groups are gaps.")
        st.subheader("Recent source warning transitions")
        if snapshot.events.items:
            st.dataframe([event.model_dump(mode="json") for event in snapshot.events.items], hide_index=True)
        else:
            st.caption("No warning transitions recorded.")

    live_panel()


if __name__ == "__main__":
    show_dashboard()
