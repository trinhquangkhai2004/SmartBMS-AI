"""Convert the verified RT-Batt v2 archive in its approved Docker runtime."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import import_module
import json
import math
from numbers import Integral, Real
import os
from pathlib import Path
import pickle
import re
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from audit_rt_batt_source import EXPECTED_GLOBALS, PUBLISHER, validate_directory


SOURCE_MEMBER = re.compile(r"our_data/(?P<cell>[1-9][0-9]*-[1-9][0-9]*)\.pkl")
TRACE_COLUMNS = {
    "Time (s)": "time_s_raw",
    "Voltage (V)": "voltage_v_raw",
    "Current (mA)": "current_ma_raw",
    "Capacity (mAh)": "capacity_mah_raw",
}
TRACE_SCHEMA = pa.schema(
    [
        pa.field("cell_id", pa.string(), nullable=False),
        pa.field("cycle_id", pa.int64(), nullable=False),
        pa.field("cycle_source_order", pa.int32(), nullable=False),
        pa.field("sample_index", pa.int32(), nullable=False),
        pa.field("raw_status", pa.string()),
        *(pa.field(name, pa.float64()) for name in TRACE_COLUMNS.values()),
    ]
)


class SourceUnpickler(pickle.Unpickler):
    def __init__(self, stream, globals_by_name):
        super().__init__(stream)
        self.globals_by_name = globals_by_name

    def find_class(self, module, name):
        try:
            return self.globals_by_name[module, name]
        except KeyError:
            raise pickle.UnpicklingError(f"Unlisted global: {module}.{name}") from None


def resolve_expected_globals():
    objects = {}
    for qualified_name in sorted(EXPECTED_GLOBALS):
        module, name = qualified_name.rsplit(".", 1)
        objects[module, name] = getattr(import_module(module), name)
    return objects


def read_source_object(stream, globals_by_name):
    data = SourceUnpickler(stream, globals_by_name).load()
    if stream.read(1):
        raise ValueError("Pickle member has trailing data after STOP")
    return data


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def verify_official_source(path):
    if path.stat().st_size != PUBLISHER["size_bytes"] or sha256(path) != PUBLISHER["sha256"]:
        raise ValueError("ZIP does not match the official RT-Batt v2 size and SHA-256")


def approved_runtime(input_path, output_path, approval_path):
    if not approval_path.is_file():
        raise ValueError("D11 approval record is required")
    approval = json.loads(approval_path.read_text(encoding="utf-8-sig"))
    candidate = approval.get("candidate") or {}
    if (
        approval.get("approved") is not True
        or approval.get("decision_id") != "D11"
        or approval.get("conversion_route") != "LOCAL_DOCKER_HARDENED"
        or approval.get("archive_sha256") != PUBLISHER["sha256"]
        or not all(approval.get(key) for key in ("reviewer", "approved_at", "approval_evidence"))
        or candidate.get("converter_sha256") != sha256(Path(__file__))
        or candidate.get("dependency_lock_sha256") != sha256(Path("/app/requirements-linux-amd64.lock"))
    ):
        raise ValueError("D11 approval must identify this source, converter, dependency lock and reviewer")

    status = dict(line.split(":\t", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":\t" in line)
    if (
        os.geteuid() != 1000
        or os.getegid() != 1000
        or status.get("NoNewPrivs") != "1"
        or int(status.get("CapEff", "-1"), 16) != 0
        or set(os.listdir("/sys/class/net")) != {"lo"}
    ):
        raise ValueError("Docker runtime must be unprivileged, without Linux capabilities or networking")
    for path in (Path("/"), input_path, approval_path):
        if not os.statvfs(path).f_flag & os.ST_RDONLY:
            raise ValueError(f"Expected read-only filesystem for {path}")
    if not output_path.is_dir() or os.statvfs(output_path).f_flag & os.ST_RDONLY:
        raise ValueError("Expected a separate writable output directory")


def is_cycle_id(value):
    return isinstance(value, Integral) and not isinstance(value, (bool, np.bool_)) and 0 < value < 2**63


def parse_member(data, cell_id):
    if not isinstance(data, dict) or set(data) != {cell_id}:
        raise ValueError(f"Pickle cell key differs from ZIP member's cell ID {cell_id}")
    cell = data[cell_id]
    if not isinstance(cell, dict):
        raise ValueError(f"{cell_id}: expected a data mapping")
    cycles = cell.get("data")
    if not isinstance(cycles, dict) or not cycles or not all(is_cycle_id(key) for key in cycles):
        raise ValueError(f"{cell_id}: missing or invalid cycle mapping")

    dq_values = cell.get("dq", {})
    if not isinstance(dq_values, dict) or not all(is_cycle_id(key) for key in dq_values):
        raise ValueError(f"{cell_id}: expected dq as a cycle-to-capacity mapping")
    points = []
    for cycle_id, value in dq_values.items():
        if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)) or math.isinf(value):
            raise ValueError(f"{cell_id}/{cycle_id}: invalid dq value")
        points.append({"cycle_id": int(cycle_id), "value": None if math.isnan(value) else float(value)})
    return cycles, {
        "dq_by_cycle_raw": points,
        "other_cell_keys": sorted(str(key) for key in cell if key not in {"data", "dq"}),
    }


def trace_table(frame, cell_id, cycle_id, source_order):
    if not isinstance(frame, pd.DataFrame) or frame.empty or not frame.columns.is_unique:
        raise ValueError(f"{cell_id}/{cycle_id}: expected a non-empty frame with unique column names")
    missing = {"Status", *TRACE_COLUMNS} - set(frame.columns)
    if missing:
        raise ValueError(f"{cell_id}/{cycle_id}: missing columns {sorted(missing)}")
    statuses = []
    for value in frame["Status"]:
        if isinstance(value, str):
            statuses.append(value)
        elif value is None or value is pd.NA or (isinstance(value, Real) and math.isnan(value)):
            statuses.append(None)
        else:
            raise ValueError(f"{cell_id}/{cycle_id}: Status must be text or missing")
    length = len(frame)
    fields = [
        pa.repeat(cell_id, length),
        pa.repeat(int(cycle_id), length),
        pa.repeat(pa.scalar(source_order, type=pa.int32()), length),
        pa.array(np.arange(length, dtype=np.int32)),
        pa.array(statuses, type=pa.string()),
    ]
    for source_name in TRACE_COLUMNS:
        column = frame[source_name]
        if column.dtype.kind not in "iuf":
            raise ValueError(f"{cell_id}/{cycle_id}: {source_name} must be numeric")
        values = column.to_numpy(dtype=np.float64, na_value=np.nan)
        if np.isinf(values).any():
            raise ValueError(f"{cell_id}/{cycle_id}: {source_name} contains infinity")
        fields.append(pa.array(values, type=pa.float64(), from_pandas=True))
    return pa.Table.from_arrays(fields, schema=TRACE_SCHEMA)


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_cell(output, source_member, cell_id, cycles, summary):
    trace_path = output / f"{cell_id}.parquet"
    extra_columns = set()
    batch = []
    batch_rows = 0
    total_rows = 0
    with pq.ParquetWriter(trace_path, TRACE_SCHEMA, compression="zstd") as writer:
        for source_order, (cycle_id, frame) in enumerate(cycles.items()):
            table = trace_table(frame, cell_id, cycle_id, source_order)
            extra_columns.update(str(name) for name in frame.columns if name not in {"Status", *TRACE_COLUMNS})
            batch.append(table)
            batch_rows += table.num_rows
            total_rows += table.num_rows
            if batch_rows >= 64_000:
                writer.write_table(pa.concat_tables(batch))
                batch.clear()
                batch_rows = 0
        if batch:
            writer.write_table(pa.concat_tables(batch))

    with pq.ParquetFile(trace_path) as reader:
        if reader.schema_arrow != TRACE_SCHEMA:
            raise ValueError(f"{cell_id}: Parquet schema differs after readback")
        readback_rows = sum(batch.num_rows for batch in reader.iter_batches())
    if readback_rows != total_rows:
        raise ValueError(f"{cell_id}: Parquet row count differs after readback")

    summary_path = output / f"{cell_id}.json"
    header = {"source_member": source_member, "cell_id": cell_id, **summary}
    write_json(summary_path, header)
    if json.loads(summary_path.read_text(encoding="utf-8")) != header:
        raise ValueError(f"{cell_id}: JSON summary differs after readback")
    return {
        "source_member": source_member,
        "cell_id": cell_id,
        "cycle_count": len(cycles),
        "sample_rows": total_rows,
        "dq_records": len(summary["dq_by_cycle_raw"]),
        "extra_trace_columns": sorted(extra_columns),
        "trace": {"path": trace_path.name, "sha256": sha256(trace_path)},
        "summary": {"path": summary_path.name, "sha256": sha256(summary_path)},
    }


def convert(input_path, output_path):
    verify_official_source(input_path)
    final = output_path / "rt_batt_v2"
    if final.exists():
        raise ValueError(f"Staging already exists at {final}")
    globals_by_name = resolve_expected_globals()
    with ZipFile(input_path) as archive, TemporaryDirectory(prefix=".conversion-", dir=output_path) as working:
        entries = archive.infolist()
        validate_directory(entries)
        members = [entry for entry in entries if not entry.is_dir()]
        matches = [SOURCE_MEMBER.fullmatch(member.filename) for member in members]
        if len(members) != 77 or not all(matches):
            raise ValueError("Unexpected ZIP member inventory")
        work = Path(working) / "rt_batt_v2"
        work.mkdir()
        records = []
        for member, match in zip(members, matches):
            cell_id = match["cell"]
            with archive.open(member) as stream:
                source = read_source_object(stream, globals_by_name)
            cycles, summary = parse_member(source, cell_id)
            records.append(write_cell(work, member.filename, cell_id, cycles, summary))
            del source, cycles, summary
            print(f"{member.filename}: {records[-1]['sample_rows']} rows validated", flush=True)
        write_json(
            work / "conversion_manifest.json",
            {
                "source_doi": PUBLISHER["doi"],
                "source_sha256": PUBLISHER["sha256"],
                "converter_sha256": sha256(Path(__file__)),
                "dependency_lock_sha256": sha256(Path("/app/requirements-linux-amd64.lock")),
                "converted_at_utc": datetime.now(timezone.utc).isoformat(),
                "package_versions": {
                    "python": sys.version.split()[0], "numpy": np.__version__,
                    "pandas": pd.__version__, "pyarrow": pa.__version__,
                },
                "trace_schema": {field.name: str(field.type) for field in TRACE_SCHEMA},
                "raw_dq_unit": None,
                "raw_order_and_sign_preserved": True,
                "sample_rows": sum(record["sample_rows"] for record in records),
                "cycles": sum(record["cycle_count"] for record in records),
                "data_members": records,
            },
        )
        work.rename(final)
    print(final, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        approved_runtime(arguments.input, arguments.output, arguments.approval)
        convert(arguments.input, arguments.output)
    except (ValueError, OSError, pickle.UnpicklingError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
