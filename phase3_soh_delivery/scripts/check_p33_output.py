"""Read back and reconcile every P3.3 draft label and trace key."""

import argparse
from collections import Counter
import csv
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
from statistics import median

import pyarrow.parquet as pq


RELEASE = "DRAFT_PENDING_D02_D03_REVIEW"
TARGET = "cell_relative_operational_capacity"


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file,"sha256").hexdigest()


def rows(path):
    with pq.ParquetFile(path) as parquet:
        if parquet.schema_arrow.metadata[b"release_status"].decode()!=RELEASE:
            raise ValueError("Draft release information absent in Parquet metadata")
        for batch in parquet.iter_batches(batch_size=2048):
            yield from batch.to_pylist()


def position(event):
    return event["cycle_source_order"],event["sample_index"]


def check_label(trace,label,commissioning):
    cell = label["cell_id"]
    feature = label["feature_available_at"]
    observed = label["label_observed_at"]
    ref = label["qref_available_at"]
    if not all(event["cell_id"]==cell for event in (feature,observed,ref)):
        raise ValueError(f"Availability crosses cells: {cell}")
    if ref!=commissioning or not position(ref)<=position(feature)<position(observed) or label["cycle_id"]<=5:
        raise ValueError(f"Draft label crosses commissioning or timing boundary: {cell}/{label['cycle_id']}")
    if ref["cycle_id"]!=5 or label["qref_source_cycle_ids"]!=[1,2,3,4,5]:
        raise ValueError(f"Commissioning event differs from approved-to-review window: {cell}")
    q = label["q_observed_ah"]
    qref = label["q_ref_ah"]
    if not math.isfinite(q) or not math.isfinite(qref) or min(q,qref)<=0:
        raise ValueError(f"Nonpositive or nonfinite capacity: {cell}")
    if (not math.isclose(q,trace["paired_dq_raw_mah"]/1000.0,rel_tol=1e-12,abs_tol=0)
            or not math.isclose(label["soh_ref_percent"],100*q/qref,rel_tol=1e-12,abs_tol=0)):
        raise ValueError(f"Unit conversion or SoH mismatch: {cell}")
    if label["release_status"]!=RELEASE or label["target_semantics"]!=TARGET:
        raise ValueError("Draft scope or target interpretation differs")
    if any(trace[key]!=value for key,value in label.items()):
        raise ValueError("Label Parquet differs from its trace row")


def check(root,inputs):
    summary_path = root/"p3_3_audit_summary.json"
    trace_path = root/"cycle_label_pairing.parquet"
    label_path = root/"soh_labels.parquet"
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    by_cell = {cell["cell_id"]:cell for cell in summary["cells"]}
    inventory = inputs/"cell_cycle_inventory.csv"
    if digest(inventory)!=summary["p32_inventory_sha256"]:
        raise ValueError("Source inventory differs")
    labels = rows(label_path)
    counts = Counter()
    keys, cells_with_labels, commissioning_events = set(), set(), {}
    per_cell = {}
    above_100 = 0
    with inventory.open(encoding="utf-8",newline="") as source:
        for trace, raw in zip_longest(rows(trace_path),csv.DictReader(source)):
            if trace is None or raw is None:
                raise ValueError("Trace parquet source row count differs")
            cell = raw["cell_id"]
            key = cell,int(raw["cycle_id"])
            if key in keys or (trace["cell_id"],trace["cycle_id"])!=key:
                raise ValueError(f"Trace identity repeated or differs: {key}")
            keys.add(key)
            status = trace["label_status"]
            counts[status] += 1
            per_cell.setdefault(cell,Counter())[status] += 1
            if trace["release_status"]!=RELEASE:
                raise ValueError("Trace release state differs")
            eligible = raw["pair_status"]=="READY_FOR_P3_3_AUDIT"
            if eligible!=trace["d03_pair_valid"]:
                raise ValueError(f"Unexpected D03 validity change at {key}")
            # Exact source-event equality, including seconds within each cycle.
            for column in ("feature_available_at","discharge_start_at","label_observed_at"):
                expected = json.loads(raw[column]) if raw[column] else None
                if trace[column]!=expected:
                    raise ValueError(f"Trace event differs at {key}/{column}")
            if key[1]==5:
                commissioning_events[cell]=trace["label_observed_at"]
            if status!="LABEL_DRAFT_READY":
                if trace["soh_ref_percent"] is not None or not trace["reason"]:
                    raise ValueError(f"Excluded trace has a label or lacks a reason: {key}")
                continue
            candidate = next(labels,None)
            if candidate is None or candidate["cell_id"]!=cell or candidate["cycle_id"]!=key[1]:
                raise ValueError(f"Missing label: {key}")
            check_label(trace,candidate,commissioning_events[cell])
            if candidate["q_ref_ah"]!=median(by_cell[cell]["early_discharge_ah"]):
                raise ValueError(f"Commissioning median differs: {cell}")
            cells_with_labels.add(cell)
            above_100 += candidate["soh_ref_percent"]>100
    if next(labels,None) is not None:
        raise ValueError("Unexpected additional labels")
    for cell, results in per_cell.items():
        if dict(results)!=by_cell[cell]["label_counts"]:
            raise ValueError(f"Per-cell dispositions differ: {cell}")
    if dict(counts)!=summary["totals"]["disposition"] or above_100!=summary["totals"]["above_100_percent"]:
        raise ValueError("Summary label totals differ")
    if by_cell["7-5"]["status"]!="QREF_COMMISSIONING_BLOCKED" or "7-5" in cells_with_labels:
        raise ValueError("Contested cell 7-5 entered the review-only labels")
    base = by_cell["1-1"]["reference_probe_cycle_6"]
    if not (base is not None and math.isclose(base["q_ref_ah"],1.1725066444444444,abs_tol=1e-12)
            and math.isclose(base["soh_ref_percent"],99.89595510276096,abs_tol=1e-9)):
        raise ValueError("Reference case does not reproduce")
    return {
        "status":"PASS","release_status":RELEASE,"trace_rows":len(keys),
        "labels":counts["LABEL_DRAFT_READY"],"cells_with_labels":len(cells_with_labels),
        "above_100_percent":above_100,"disposition":dict(counts),
        "output_sha256":{path.name:digest(path) for path in (summary_path,trace_path,label_path)},
    }


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--inputs",type=Path,required=True)
    arguments = parser.parse_args()
    print(json.dumps(check(arguments.root,arguments.inputs),ensure_ascii=False))
