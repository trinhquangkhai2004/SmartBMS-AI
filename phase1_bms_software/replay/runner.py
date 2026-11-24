"""Replay a fixed JSONL fixture through POST /api/v1/telemetry."""
import argparse
import math
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Callable

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.schemas import Ack, Telemetry


class ReplayError(ValueError):
    pass


def parse_rate(value: str | float) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("rate-hz must be a finite number in [0.1, 100]") from exc
    if not math.isfinite(rate) or not 0.1 <= rate <= 100:
        raise ValueError("rate-hz must be a finite number in [0.1, 100]")
    return rate


def load_records(path: Path) -> list[Telemetry]:
    records = []
    try:
        with path.open(encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    payload = Telemetry.model_validate_json(line)
                    if payload.source != "REPLAY":
                        raise ValueError("replay accepts only source=REPLAY")
                except (ValidationError, ValueError) as exc:
                    raise ReplayError(f"{path.name}: invalid synthetic telemetry at line {line_number}") from exc
                records.append(payload)
    except OSError as exc:
        raise ReplayError(f"Cannot read replay fixture: {path.name}") from exc
    if not records:
        raise ReplayError("Replay fixture contains no records")
    return records


def run_replay(records: list[Telemetry], url: str, rate_hz: float, *,
               token: str = "", client: httpx.Client | None = None,
               sleep: Callable[[float], None] = time.sleep) -> list[Ack]:
    rate = parse_rate(rate_hz)
    if any(record.source != "REPLAY" for record in records):
        raise ReplayError("Replay accepts only source=REPLAY")
    results = []
    headers = {"X-Device-Token": token} if token else {}
    manager = nullcontext(client) if client is not None else httpx.Client(timeout=3, trust_env=False)
    with manager as http:
        for index, record in enumerate(records):
            try:
                response = http.post(url.rstrip("/") + "/api/v1/telemetry",
                                     json=record.model_dump(mode="json"), headers=headers)
                response.raise_for_status()
                ack = Ack.model_validate(response.json())
                expected = {"accepted": 201, "duplicate": 200, "accepted_historical": 202}[ack.status]
                if response.status_code != expected:
                    raise ValueError("HTTP status does not match acknowledgement")
            except (httpx.HTTPError, ValueError) as exc:
                raise ReplayError(f"Replay stopped at record {index + 1}; no successful acknowledgement") from exc
            results.append(ack)
            if index + 1 < len(records):
                sleep(1 / rate)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SIMULATED DATA only; deterministic HTTP replay")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--url", default=None)
    parser.add_argument("--rate-hz", type=float, default=1, help="Demo speed [0.1, 100], not a sampling specification")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        rate = parse_rate(args.rate_hz)
        records = load_records(args.file)
        print(f"SIMULATED DATA | source=REPLAY | {len(records)} fixed records | {rate:g} Hz demo")
        results = run_replay(records, args.url or settings.api_base_url, rate,
                             token=settings.device_token.get_secret_value())
        for result in results:
            print(f"{result.status} record_id={result.record_id} updated_latest={result.updated_latest}")
    except (ReplayError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Replay interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
