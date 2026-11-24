"""Validate RT-Batt Parquet and JSON staged outputs without opening the source ZIP."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.parquet as pq


MEMBER_PATTERN = re.compile(r"our_data/(?P<cell>[1-9][0-9]*-[1-9][0-9]*)\.pkl")
EXPECTED_FIELDS = [
    pa.field("cell_id", pa.string(), nullable=False),
    pa.field("cycle_id", pa.int64(), nullable=False),
    pa.field("cycle_source_order", pa.int32(), nullable=False),
    pa.field("sample_index", pa.int32(), nullable=False),
    pa.field("raw_status", pa.string()),
    *(pa.field(name, pa.float64()) for name in ("time_s_raw", "voltage_v_raw", "current_ma_raw", "capacity_mah_raw")),
]
TRACE_SCHEMA = pa.schema(EXPECTED_FIELDS)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check_file(path, reference, expected_name):
    if reference["path"] != expected_name or not path.is_file():
        raise ValueError(f"Missing expected file {expected_name!r}")
    with path.open("rb") as stream:
        calculated = hashlib.file_digest(stream, "sha256").hexdigest()
    if calculated != reference["sha256"]:
        raise ValueError(f"SHA-256 mismatch: {expected_name}")


def verify_cell(directory, record):
    member = MEMBER_PATTERN.fullmatch(record["source_member"])
    if member is None or member["cell"] != record["cell_id"]:
        raise ValueError(f"Invalid source-to-staging mapping: {record['source_member']}")
    cell_id = record["cell_id"]
    trace_name = f"{cell_id}.parquet"
    summary_name = f"{cell_id}.json"
    trace = directory / trace_name
    summary = directory / summary_name
    check_file(trace, record["trace"], trace_name)
    check_file(summary, record["summary"], summary_name)
    with pq.ParquetFile(trace) as parquet:
        if parquet.schema_arrow != TRACE_SCHEMA:
            raise ValueError(f"Unexpected Parquet schema: {trace_name}")
        rows = 0
        cycles = set()
        for batch in parquet.iter_batches():
            if set(batch.column(0).unique().to_pylist()) != {cell_id}:
                raise ValueError(f"Unexpected cell ID in Parquet: {trace_name}")
            cycles.update(batch.column(1).unique().to_pylist())
            rows += batch.num_rows
    if rows <= 0 or rows != record["sample_rows"] or len(cycles) != record["cycle_count"]:
        raise ValueError(f"Unexpected row or cycle count in Parquet: {trace_name}")

    header = load_json(summary)
    points = header["dq_by_cycle_raw"]
    if (
        header["source_member"] != record["source_member"]
        or header["cell_id"] != cell_id
        or len(points) != record["dq_records"]
        or len({point["cycle_id"] for point in points}) != len(points)
    ):
        raise ValueError(f"Unexpected summary identity or record count: {summary_name}")
    for point in points:
        number = point["value"]
        if (
            type(point["cycle_id"]) is not int
            or point["cycle_id"] <= 0
            or (number is not None and (type(number) not in (int, float) or not math.isfinite(number)))
        ):
            raise ValueError(f"Invalid capacity observation in {summary_name}")
    return rows, len(cycles)


def verify_staging(directory, source, route):
    summary = load_json(directory / "conversion_manifest.json")
    candidate = route["candidate"]
    source_sha = source["publisher"]["sha256"]
    if any(
        summary[key] != expected
        for key, expected in {
            "source_doi": source["publisher"]["doi"],
            "source_sha256": source_sha,
            "converter_sha256": candidate["converter_sha256"],
            "dependency_lock_sha256": candidate["dependency_lock_sha256"],
            "package_versions": candidate["packages"],
            "trace_schema": {field.name: str(field.type) for field in TRACE_SCHEMA},
            "raw_order_and_sign_preserved": True,
        }.items()
    ):
        raise ValueError("Staging provenance or schema does not match the approved conversion inputs")
    source_files = {member["path"] for member in source["members"] if member["kind"] == "file"}
    records = summary["data_members"]
    if len(records) != len(source_files) or {record["source_member"] for record in records} != source_files:
        raise ValueError("Staging does not account for every source file exactly once")
    rows = cycles = 0
    expected_names = {"conversion_manifest.json"}
    for record in records:
        row_count, cycle_count = verify_cell(directory, record)
        rows += row_count
        cycles += cycle_count
        expected_names.update((record["trace"]["path"], record["summary"]["path"]))
    if (
        not rows
        or rows != summary["sample_rows"]
        or cycles != summary["cycles"]
        or {entry.name for entry in directory.iterdir()} != expected_names
    ):
        raise ValueError("Staging totals or file set do not match the manifest")
    return {"source_sha256": source_sha, "source_files": len(records), "sample_rows": rows, "cycles": cycles}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    arguments = parser.parse_args()
    result = verify_staging(arguments.staging, load_json(arguments.source_manifest), load_json(arguments.route))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
