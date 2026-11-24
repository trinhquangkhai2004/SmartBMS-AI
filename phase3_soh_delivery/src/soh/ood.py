"""OOD policy loading, feature bound inspection, and D13 wall-clock staleness checks.

Never modifies or reimplements frozen EvaluationGuard thresholds; reads the signed
artifacts/soh/ood_policy.json verified by SHA-256 and provides wall-clock freshness
evaluation required for P3.8 online runtime (D13 follow-up).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path


OFFLINE_STALE_MODE = "NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY"
ONLINE_STALE_MODE = "ONLINE_WALL_CLOCK"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_local_trusted_path(path: Path, *, allow_pickle: bool = False) -> Path:
    raw = str(path)
    if "://" in raw:
        raise ValueError(f"Remote artifact URI is forbidden: {raw}")
    if not allow_pickle and path.suffix.lower() in {".pkl", ".pickle"}:
        raise ValueError(f"Raw pickle access is forbidden after P3.1: {raw}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Trusted artifact not found: {resolved}")
    return resolved


def load_verified_ood_policy(path: Path, expected_sha256: str) -> dict:
    resolved = ensure_local_trusted_path(path)
    actual = sha256_file(resolved)
    if actual != expected_sha256:
        raise ValueError(f"OOD policy SHA-256 mismatch: expected {expected_sha256}, got {actual}")
    policy = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or "primary_features" not in policy or "feature_bounds" not in policy:
        raise ValueError("Malformed OOD policy payload")
    return policy


def violated_weighted_features(features: list[float | None] | tuple[float | None, ...], policy: dict) -> list[str]:
    names = policy["primary_features"]
    bounds = policy["feature_bounds"]
    breached: list[str] = []
    if len(features) != len(names):
        return breached
    for name, value in zip(names, features):
        if value is None or not isfinite(value):
            continue
        low, high = bounds[name]["weighted"]
        if value < low or value > high:
            breached.append(name)
    return breached


@dataclass(frozen=True)
class WallClockStalePolicy:
    """D13 online wall-clock freshness contract for end-of-charge SoH observations."""

    max_observation_age_seconds: float = 86400.0
    max_future_skew_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isfinite(self.max_observation_age_seconds) or self.max_observation_age_seconds <= 0:
            raise ValueError("max_observation_age_seconds must be finite and > 0")
        if not isfinite(self.max_future_skew_seconds) or self.max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be finite and >= 0")


@dataclass(frozen=True)
class FreshnessCheck:
    is_stale: bool
    stale_mode: str
    age_seconds: float | None
    reason_code: str | None


def parse_aware_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("Timestamp must be datetime, ISO-8601 string, or None")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def evaluate_freshness(
    observed_at: datetime | str | None,
    now_utc: datetime | str | None,
    *,
    offline_cycle_replay: bool = False,
    policy: WallClockStalePolicy | None = None,
) -> FreshnessCheck:
    """Determine stale flag for EvaluationGuard.

    Offline RT-Batt cycle replay explicitly returns stale=False with
    NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY (D13). Online mode requires timezone-aware
    timestamps and marks missing, naive, future-skewed, or expired observations STALE.
    """
    if offline_cycle_replay:
        return FreshnessCheck(False, OFFLINE_STALE_MODE, None, None)

    active_policy = policy or WallClockStalePolicy()
    if observed_at is None:
        return FreshnessCheck(True, ONLINE_STALE_MODE, None, "MISSING_OBSERVED_AT_TIMESTAMP")
    try:
        obs_dt = parse_aware_utc(observed_at)
    except (TypeError, ValueError):
        return FreshnessCheck(True, ONLINE_STALE_MODE, None, "UNTRUSTED_OBSERVED_AT_TIMESTAMP")

    try:
        ref_dt = parse_aware_utc(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return FreshnessCheck(True, ONLINE_STALE_MODE, None, "UNTRUSTED_REFERENCE_CLOCK")

    delta_seconds = (ref_dt - obs_dt).total_seconds()
    if delta_seconds < -active_policy.max_future_skew_seconds:
        return FreshnessCheck(True, ONLINE_STALE_MODE, 0.0, "FUTURE_OBSERVED_AT_TIMESTAMP")

    age = max(0.0, delta_seconds)
    if age > active_policy.max_observation_age_seconds:
        return FreshnessCheck(True, ONLINE_STALE_MODE, age, "WALL_CLOCK_STALE")
    return FreshnessCheck(False, ONLINE_STALE_MODE, age, None)

