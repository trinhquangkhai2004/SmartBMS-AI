"""Build review-only RT-Batt SoH capacity labels from the verified P3.2 inventory."""

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass
from itertools import groupby, islice
import json
import math
from pathlib import Path
from statistics import median

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from audit_rt_batt_cycles import (
    DQ_MATCH_MAH, PROFILE_TOLERANCE_C, audit_cycle, discharge_profile,
    index_dq, iter_cycles, load_json, sha256,
)


WINDOW = (1, 2, 3, 4, 5)
RELEASE = "DRAFT_PENDING_D02_D03_REVIEW"
TARGET = "cell_relative_operational_capacity"
BATTERYML_SOURCE = (
    "https://github.com/microsoft/BatteryML/blob/"
    "2861ae3b8c79938c7fc8e6fe9986b799ca71c7dd/batteryml/preprocess/preprocess_HUST.py#L63-L66"
)


@dataclass(frozen=True)
class Event:
    cell_id: str
    cycle_id: int
    cycle_source_order: int
    operation_number: int
    sample_index: int
    time_s_raw: float

    @property
    def order(self):
        # Raw elapsed seconds restart. They are valid only inside their own cycle.
        return self.cycle_source_order, self.sample_index

    @property
    def operation_id(self):
        return f"{self.cell_id}:{self.cycle_id}:{self.operation_number}"


def finite(raw):
    if raw in (None, ""):
        return None
    number = float(raw)
    return number if math.isfinite(number) else None


def parse_event(text):
    if not text:
        return None
    raw = json.loads(text)
    if not isinstance(raw, dict):
        return None
    try:
        event = Event(**raw)
    except TypeError:
        return None
    keys = (event.cycle_id, event.cycle_source_order, event.operation_number, event.sample_index)
    if (not isinstance(event.cell_id,str) or not event.cell_id or any(type(key) is not int or key < 0 for key in keys)
            or type(event.time_s_raw) not in (int,float) or finite(event.time_s_raw) is None):
        return None
    return event


def validate_pair(row, feature, start, label, dq, counter):
    if row["pair_status"] != "READY_FOR_P3_3_AUDIT":
        return row["pair_reason"] or "P32_PAIR_REVIEW"
    if row["pair_geometry"] != "SAME_CYCLE" or row["discharge_cycle_id"] != row["cycle_id"]:
        return "SAME_CYCLE_PAIR_NOT_PROVEN"
    expected = row["cell_id"], int(row["cycle_id"]), int(row["cycle_source_order"])
    if any(event is None or (event.cell_id,event.cycle_id,event.cycle_source_order) != expected
           for event in (feature,start,label)):
        return "PAIR_EVENT_KEY_MISMATCH"
    if not (feature.order < start.order < label.order and
            feature.time_s_raw < start.time_s_raw < label.time_s_raw and
            feature.operation_number < start.operation_number == label.operation_number):
        return "PAIR_TIMELINE_INVALID"
    if dq is None or counter is None or dq <= 0 or counter <= 0:
        return "OBSERVED_CAPACITY_INVALID"
    if abs(dq-counter) > DQ_MATCH_MAH:
        return "DQ_COUNTER_MISMATCH"
    if row["capacity_counter_reset_count"] != "0":
        return "CAPACITY_COUNTER_RESET"
    return None


def parse_pair(row):
    feature, start, label = (parse_event(row[key]) for key in ("feature_available_at","discharge_start_at","label_observed_at"))
    dq, counter = (finite(row[key]) for key in ("paired_dq_raw","capacity_counter_delta_mah"))
    reason = validate_pair(row,feature,start,label,dq,counter)
    return {
        "cell_id": row["cell_id"], "cycle_id": int(row["cycle_id"]),
        "cycle_source_order": int(row["cycle_source_order"]), "source_member": row["source_member"],
        "protocol_id": row["protocol_id"] or None, "feature": feature,
        "discharge_start": start, "label": label, "valid_pair": reason is None,
        "paired_dq_raw_mah": dq, "capacity_counter_delta_mah": counter,
        "q_observed_ah": dq/1000.0 if dq is not None and dq>0 else None,
        "discharge_last_voltage_v": finite(row["discharge_cutoff_v"]),
        "pair_review_reason": reason, "p32_status": row["pair_status"],
        "p32_diagnostics": sorted(json.loads(row["diagnostic_counts"] or "{}")),
    }


def commission(cell, pairs, traces):
    if any(pair["cell_id"] != cell for pair in pairs):
        raise ValueError("Commissioning only accepts records from the same cell")
    early = pairs[:len(WINDOW)]
    reasons = []
    cycle_ids = [item["cycle_id"] for item in early]
    if len(early) < len(WINDOW):
        reasons.append("FEWER_THAN_FIVE_EARLY_CYCLES")
    elif tuple(cycle_ids) != WINDOW or [item["cycle_source_order"] for item in early] != list(range(len(WINDOW))):
        reasons.append("EARLY_CYCLES_NOT_CONSECUTIVE_1_TO_5")
    if any(not item["valid_pair"] for item in early):
        reasons.append("EARLY_DISCHARGE_PAIR_INVALID")
    if len({item["protocol_id"] for item in early}) != 1 or any(not item["protocol_id"] for item in early):
        reasons.append("EARLY_PROFILE_NOT_IDENTIFIED")
    trace_keys = [(t["cycle_id"],t["source_order"]) for t in traces[:len(WINDOW)]]
    if trace_keys != [(row["cycle_id"],row["cycle_source_order"]) for row in early]:
        reasons.append("EARLY_TRACE_KEYS_DO_NOT_MATCH")
    else:
        reasons.extend(sorted({reason for trace in traces[:len(WINDOW)] for reason in trace["review_reasons"]}))
    if cell == "7-5":
        reasons.append("BATTERYML_EARLY_CYCLE_REVIEW")

    capacities = [item["q_observed_ah"] for item in early]
    candidate = median(capacities) if len(capacities)==len(WINDOW) and all(q is not None and q>0 for q in capacities) else None
    low = min(capacities) if candidate is not None else None
    high = max(capacities) if candidate is not None else None
    return {
        "cell_id": cell, "status": "QREF_COMMISSIONING_BLOCKED" if reasons else "QREF_PROVISIONAL",
        "reasons": reasons, "source_cycle_ids": cycle_ids,
        "early_discharge_ah": capacities,
        "window_median_for_review_ah": candidate, "min_ah": low, "max_ah": high,
        "relative_spread_percent": 100*(high-low)/candidate if candidate is not None else None,
        "q_ref_ah": candidate if not reasons else None,
        "qref_available_at": early[-1]["label"] if not reasons else None,
    }


def make_label(pair, reference):
    if pair["cell_id"] != reference["cell_id"]:
        raise ValueError("Label and reference must belong to the same cell")
    q_ref = reference["q_ref_ah"]
    q_observed = pair["q_observed_ah"]
    available = reference["qref_available_at"]
    feature, label = pair["feature"], pair["label"]
    status = "LABEL_DRAFT_READY"
    reason = None
    soh = None
    if not pair["valid_pair"]:
        status = "P32_PAIR_REVIEW" if pair["p32_status"] != "READY_FOR_P3_3_AUDIT" else "D03_PAIR_INVALID"
        reason = pair["pair_review_reason"]
    elif reference["status"] != "QREF_PROVISIONAL" or available is None or q_ref is None or not math.isfinite(q_ref) or q_ref<=0:
        status = "QREF_COMMISSIONING_BLOCKED"
        reason = ",".join(reference["reasons"]) or "QREF_INVALID"
    elif feature.order < available.order:
        status = "COMMISSIONING_WARMUP"
        reason = "QREF_AVAILABLE_ONLY_AFTER_FIFTH_DISCHARGE"
    else:
        # Valid pairs already prove feature < label inside one cycle.
        soh = 100*q_observed/q_ref

    return {
        **{key:pair[key] for key in (
            "cell_id","cycle_id","cycle_source_order","source_member","protocol_id",
            "p32_status","p32_diagnostics","pair_review_reason","paired_dq_raw_mah",
            "capacity_counter_delta_mah","q_observed_ah","discharge_last_voltage_v",
        )},
        "d03_pair_valid": pair["valid_pair"],
        "charge_operation_id": feature.operation_id if feature is not None else None,
        "discharge_operation_id": label.operation_id if label is not None else None,
        "feature_available_at": asdict(feature) if feature is not None else None,
        "discharge_start_at": asdict(pair["discharge_start"]) if pair["discharge_start"] is not None else None,
        "label_observed_at": asdict(label) if label is not None else None,
        "qref_available_at": asdict(available) if available is not None else None,
        "qref_source_cycle_ids": reference["source_cycle_ids"],
        "commissioning_status": reference["status"],
        "q_ref_ah": q_ref, "soh_ref_percent": soh,
        "label_status": status, "reason": reason, "target_semantics": TARGET,
    }



DISCHARGE_LABELS = tuple(f"Constant current discharge_{i}" for i in range(4))


def inspect_early_trace(cell, pairs, staging, member, protocol):
    signal_file = staging/member["trace"]["path"]
    dq_file = staging/member["summary"]["path"]
    for file,key in ((signal_file,"trace"),(dq_file,"summary")):
        if sha256(file)!=member[key]["sha256"]:
            raise ValueError(f"Verified staging artifact changed: {file.name}")
    header = load_json(dq_file)
    if header["cell_id"]!=cell or header["source_member"]!=member["source_member"]:
        raise ValueError(f"Staged summary points to wrong cell or member: {cell}")
    dq_values, duplicates = index_dq(header)
    reference_c = json.loads(protocol["measured_rates_c"]) if protocol["measured_rates_c"] else None
    results = []
    for table,pair in zip(islice(iter_cycles(signal_file),7),pairs[:7]):
        cycle = table["cycle_id"][0].as_py()
        order = table["cycle_source_order"][0].as_py()
        q_dq = finite(dq_values.get(cycle))
        check,_ = audit_cycle(table,q_dq)
        charges = [part for part in check["operations"] if part["phase"]=="charge"]
        discharges = [part for part in check["operations"] if part["phase"]=="discharge"]
        charge = charges[0] if len(charges)==1 else None
        discharge = discharges[0] if len(discharges)==1 else None
        profile = discharge_profile(table,1.1)
        reasons = []
        if check["cell_id"]!=cell or (cycle,order)!=(pair["cycle_id"],pair["cycle_source_order"]):
            reasons.append("STAGING_PAIR_KEY_MISMATCH")
        if cycle in duplicates or q_dq is None or q_dq!=pair["paired_dq_raw_mah"]:
            reasons.append("EARLY_DQ_SOURCE_MISMATCH")
        if (
            profile is None or not isinstance(reference_c,list) or len(reference_c)!=4
            or any(abs(measured-reference)>PROFILE_TOLERANCE_C for measured,reference in zip(profile,reference_c))
            or not protocol["protocol_id"] or protocol["protocol_id"]!=pair["protocol_id"]
        ):
            reasons.append("EARLY_PROFILE_INCONSISTENT")
        trace_interval = None
        integral_delta = None
        if discharge is None:
            reasons.append("EARLY_DISCHARGE_NOT_UNIQUE")
        else:
            first, last = discharge["first_sample"], discharge["last_sample"]
            labels = table["raw_status"].slice(first,last-first+1).to_pylist()
            stage_order = tuple(name for name,_ in groupby(labels))
            if stage_order!=DISCHARGE_LABELS:
                reasons.append("EARLY_DISCHARGE_STAGE_ORDER_INVALID")
            if not discharge["trace_ok"] or discharge["time_gap_count"] or discharge["capacity_counter_reset_count"]:
                reasons.append("EARLY_DISCHARGE_CLOCK_OR_CAPACITY_REVIEW")
            cutoff = discharge["last_voltage_v"]
            if cutoff is None or cutoff <= 0:
                reasons.append("EARLY_LAST_DISCHARGE_VOLTAGE_INVALID")
            counter = discharge["capacity_counter_delta_mah"]
            if counter is None or q_dq is None or abs(counter-q_dq)>DQ_MATCH_MAH:
                reasons.append("EARLY_DISCHARGE_COUNTER_MISMATCH")
            if counter is not None and discharge["integral_mah"] is not None:
                integral_delta = discharge["integral_mah"]-counter
            trace_interval = [first,last]
        results.append({
            "cycle_id":cycle,"source_order":order,"review_reasons":reasons,
            "n_staging_rows":table.num_rows,"q_dq_mah":q_dq,"rates_measured_c":profile,
            "charge_samples":charge["samples"] if charge else None,
            "charge_duration_s":charge["last_time_s"]-charge["first_time_s"] if charge and charge["last_time_s"] is not None and charge["first_time_s"] is not None else None,
            "charge_median_step_s":charge["median_positive_step_s"] if charge else None,
            "charge_max_step_s":charge["max_positive_step_s"] if charge else None,
            "charge_n_large_gaps":charge["time_gap_count"] if charge else None,
            "discharge_samples":discharge["samples"] if discharge else None,
            "discharge_last_voltage_v":discharge["last_voltage_v"] if discharge else None,
            "discharge_end_time_s":discharge["last_time_s"] if discharge else None,
            "discharge_median_step_s":discharge["median_positive_step_s"] if discharge else None,
            "discharge_max_step_s":discharge["max_positive_step_s"] if discharge else None,
            "discharge_n_large_gaps":discharge["time_gap_count"] if discharge else None,
            "integral_minus_counter_mah":integral_delta,
            "trace_discharge_samples":trace_interval,
        })
    return results


EVENT_SCHEMA = pa.struct([
    ("cell_id",pa.string()),("cycle_id",pa.int64()),("cycle_source_order",pa.int32()),
    ("operation_number",pa.int32()),("sample_index",pa.int32()),("time_s_raw",pa.float64()),
])
PAIR_SCHEMA = pa.schema([
    ("cell_id",pa.string()),("cycle_id",pa.int64()),("cycle_source_order",pa.int32()),
    ("source_member",pa.string()),("protocol_id",pa.string()),
    ("p32_status",pa.string()),("p32_diagnostics",pa.list_(pa.string())),
    ("pair_review_reason",pa.string()),("d03_pair_valid",pa.bool_()),
    ("charge_operation_id",pa.string()),("discharge_operation_id",pa.string()),
    ("feature_available_at",EVENT_SCHEMA),("discharge_start_at",EVENT_SCHEMA),
    ("label_observed_at",EVENT_SCHEMA),("qref_available_at",EVENT_SCHEMA),
    ("qref_source_cycle_ids",pa.list_(pa.int64())),
    ("paired_dq_raw_mah",pa.float64()),("capacity_counter_delta_mah",pa.float64()),
    ("q_observed_ah",pa.float64()),("q_ref_ah",pa.float64()),
    ("discharge_last_voltage_v",pa.float64()),("soh_ref_percent",pa.float64()),
    ("commissioning_status",pa.string()),("label_status",pa.string()),("reason",pa.string()),
    ("target_semantics",pa.string()),("release_status",pa.string()),
])
LABEL_FIELDS = (
    "cell_id","cycle_id","cycle_source_order","source_member","protocol_id",
    "charge_operation_id","discharge_operation_id","feature_available_at","discharge_start_at",
    "label_observed_at","qref_available_at","qref_source_cycle_ids",
    "q_observed_ah","q_ref_ah","soh_ref_percent","target_semantics","release_status",
)


def read_inputs(inputs, staging):
    certified = load_json(inputs/"p3_2_readback.json")
    milestone = next(m for m in load_json(inputs/"p3_milestone_status.json")["milestones"] if m["milestone_id"]=="P3.2")
    if certified["status"]!="PASS" or milestone["status"]!="PASS":
        raise ValueError("P3.2 verified completion is required")
    for name in ("cell_cycle_inventory.csv","protocol_inventory.csv","p3_2_audit_summary.json"):
        if sha256(inputs/name)!=certified["output_sha256"][name]:
            raise ValueError(f"P3.2 input SHA-256 differs: {name}")
    staging_file = staging/"conversion_manifest.json"
    p32 = load_json(inputs/"p3_2_audit_summary.json")
    if sha256(staging_file)!=p32["source_manifest_sha256"]:
        raise ValueError("Staging manifest differs from P3.2")
    members = load_json(staging_file)["data_members"]
    with (inputs/"protocol_inventory.csv").open(encoding="utf-8",newline="") as file:
        records = list(csv.DictReader(file))
    protocols = {item["cell_id"]:item for item in records}
    by_cell = {item["cell_id"]:item for item in members}
    if set(protocols)!=set(by_cell) or len(protocols)!=len(records) or len(by_cell)!=len(members):
        raise ValueError("Protocol or staging cell identities differ")
    return certified,p32,by_cell,protocols


def label_cell(cell, raw, staging, member, protocol):
    pairs = [parse_pair(row) for row in raw]
    keys = [pair["cycle_id"] for pair in pairs]
    if len(pairs)!=member["cycle_count"] or len(keys)!=len(set(keys)):
        raise ValueError(f"Repeated or missing P3.2 cycles: {cell}")
    if [pair["cycle_source_order"] for pair in pairs]!=list(range(len(pairs))):
        raise ValueError(f"Unexpected P3.2 source cycle order: {cell}")
    if any(pair["source_member"]!=member["source_member"] for pair in pairs):
        raise ValueError(f"P3.2 member identity differs: {cell}")
    early = inspect_early_trace(cell,pairs,staging,member,protocol)
    ref = commission(cell,pairs,early)
    records = [{**make_label(pair,ref),"release_status":RELEASE} for pair in pairs]
    labels = [record for record in records if record["label_status"]=="LABEL_DRAFT_READY"]
    ref["qref_available_at"] = asdict(ref["qref_available_at"]) if ref["qref_available_at"] is not None else None
    stats = {
        **ref, "trace_file":member["trace"]["path"], "trace_sha256":member["trace"]["sha256"],
        "dq_file":member["summary"]["path"], "dq_sha256":member["summary"]["sha256"],
        "profile_id":protocol["protocol_id"] or None, "profile_status":protocol["profile_status"],
        "temperature_chamber_c":finite(protocol["temperature_chamber_c"]),
        "input_cycles":len(pairs),"d03_pairs":sum(pair["valid_pair"] for pair in pairs),
        "first_label_cycle_id":labels[0]["cycle_id"] if labels else None,
        "count_over_100":sum(row["soh_ref_percent"]>100 for row in labels),
        "label_counts":dict(Counter(row["label_status"] for row in records)),
        "early_trace_records":early,
        "reference_probe_cycle_6":next((row for row in labels if cell=="1-1" and row["cycle_id"]==6),None),
    }
    return records,labels,stats


def build(inputs,staging,out):
    audit,p32,members,protocols = read_inputs(inputs,staging)
    metadata = {
        b"release_status": RELEASE.encode(), b"target_semantics": TARGET.encode(),
        b"allowed_consumer": b"label protocol review only; split/training requires D02/D03 sign-off",
        b"source_archive_sha256": p32["source_sha256"].encode(),
        b"p32_inventory_sha256": audit["output_sha256"]["cell_cycle_inventory.csv"].encode(),
        b"availability_axis": b"same-cell (cycle_source_order, sample_index)",
    }
    schema = PAIR_SCHEMA.with_metadata(metadata)
    label_schema = pa.schema([schema.field(field) for field in LABEL_FIELDS],metadata=metadata)
    out.mkdir(parents=True,exist_ok=False)
    cells = []
    label_values = []
    with (inputs/"cell_cycle_inventory.csv").open(encoding="utf-8",newline="") as source, \
            pq.ParquetWriter(out/"cycle_label_pairing.parquet",schema,compression="zstd") as trace_writer, \
            pq.ParquetWriter(out/"soh_labels.parquet",label_schema,compression="zstd") as label_writer:
        for cell, raw in groupby(csv.DictReader(source),key=lambda row:row["cell_id"]):
            records,labels,stats = label_cell(cell,raw,staging,members[cell],protocols[cell])
            trace_writer.write_table(pa.Table.from_pylist(records,schema=schema))
            if labels:
                label_writer.write_table(pa.Table.from_pylist(labels,schema=label_schema))
            cells.append(stats)
            label_values.extend(item["soh_ref_percent"] for item in labels)
    if len(cells)!=len(members) or {c["cell_id"] for c in cells}!=set(members):
        raise ValueError("Draft audit does not cover each staged cell once")
    counts = Counter()
    for cell in cells:
        counts.update(cell["label_counts"])
    if sum(counts.values())!=audit["unique_cycle_keys"] or sum(cell["d03_pairs"] for cell in cells)!=audit["candidate_pairs"]:
        raise ValueError("D03 candidate/parquet counts differ from audited P3.2")
    values = np.asarray(label_values)
    summary = {
        "release_status":RELEASE,"target_semantics":TARGET,"source_sha256":p32["source_sha256"],
        "p32_inventory_sha256":audit["output_sha256"]["cell_cycle_inventory.csv"],
        "p32_protocol_sha256":audit["output_sha256"]["protocol_inventory.csv"],
        "staging_manifest_sha256":p32["source_manifest_sha256"],"batteryml_7_5_reference":BATTERYML_SOURCE,
        "totals":{"cells":len(cells),"source_cycles":sum(counts.values()),"d03_pairs":audit["candidate_pairs"],
                  "cells_with_provisional_reference":sum(cell["status"]=="QREF_PROVISIONAL" for cell in cells),
                  "labels":len(values),"above_100_percent":int((values>100).sum()),"disposition":dict(counts)},
        "target_distribution_percent":{},
        "cells":cells,
    }
    if len(values):
        summary["target_distribution_percent"] = {name:float(np.quantile(values,q)) for name,q in (
            ("min",0),("p01",.01),("median",.5),("p95",.95),("p99",.99),("max",1))}
    (out/"p3_3_audit_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(summary["totals"],ensure_ascii=False),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs",type=Path,required=True)
    parser.add_argument("--staging",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    options = parser.parse_args()
    build(options.inputs,options.staging,options.out)


if __name__=="__main__":
    main()
