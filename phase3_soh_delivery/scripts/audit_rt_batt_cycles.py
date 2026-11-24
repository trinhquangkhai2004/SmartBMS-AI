"""Audit RT-Batt cycles from the approved staging Parquet/JSON."""

from collections import Counter
from itertools import chain, islice
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from trace_staged_charge_discharge import classify


PHASE_OTHER, PHASE_CHARGE, PHASE_DISCHARGE, PHASE_REST = range(4)
PHASES = ("other", "charge", "discharge", "rest")
SIGNALS = ("time_s_raw", "voltage_v_raw", "current_ma_raw", "capacity_mah_raw")
DQ_MATCH_MAH = 1e-6
VOLTAGE_JUMP_V = 0.20
WINDOW_V = (3.45, 3.60)
PROFILE_TOLERANCE_C = 0.15
PROFILE_CYCLES = 5


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def read_json(path):
    return Path(path).read_text(encoding="utf-8-sig")


def iter_cycles(path, batch_size=32768):
    """Keep the last partial cycle across RecordBatch and Parquet row-group boundaries."""
    order = None
    pieces = []
    with pq.ParquetFile(path) as source:
        for batch in source.iter_batches(batch_size=batch_size):
            orders = batch.column("cycle_source_order").to_numpy(zero_copy_only=False)
            splits = np.r_[0, np.flatnonzero(orders[1:] != orders[:-1]) + 1, len(orders)]
            for lo, hi in zip(splits, splits[1:]):
                current = int(orders[lo])
                if order is not None and current != order:
                    if current != order + 1:
                        raise ValueError(f"Invalid staged cycle source order: {order} -> {current}")
                    yield pa.Table.from_batches(pieces).combine_chunks()
                    pieces = []
                order = current
                pieces.append(batch.slice(int(lo), int(hi - lo)))
    if pieces:
        yield pa.Table.from_batches(pieces).combine_chunks()


def index_dq(summary):
    values, duplicates, seen = {}, set(), set()
    for item in summary["dq_by_cycle_raw"]:
        cycle_id = item["cycle_id"]
        if cycle_id in seen:
            duplicates.add(cycle_id)
            values.pop(cycle_id, None)
            continue
        seen.add(cycle_id)
        values[cycle_id] = item["value"]
    return values, duplicates


def phase_id(status):
    found = classify(status)
    return PHASES.index(found) if found in PHASES else PHASE_OTHER


def finite(value):
    return float(value) if np.isfinite(value) else None


def event(cycle, operation, end=False):
    key, time = ("last_sample", "last_time_s") if end else ("first_sample", "first_time_s")
    return {"cell_id": cycle["cell_id"], "cycle_id": cycle["cycle_id"],
            "cycle_source_order": cycle["cycle_source_order"], "operation_number": operation["operation_number"],
            "sample_index": operation[key], "time_s_raw": operation[time]}


def issues_at(issues, indices, reason, impact, field):
    for index in indices:
        issues.append({"sample_index": int(index), "reason": reason, "impact": impact, "field": field})


def read_signals(table, issues):
    arrays, signal_counts = {}, {}
    for field in SIGNALS:
        column = table[field].chunk(0)
        values = column.to_numpy(zero_copy_only=False)
        null = column.is_null().to_numpy(zero_copy_only=False) if column.null_count else np.zeros(len(values), bool)
        arrays[field] = values
        signal_counts[field] = {}
        bad_masks = {"null": null, "nan": np.isnan(values) & ~null, "inf": np.isinf(values)}
        for name, mask in bad_masks.items():
            signal_counts[field][name] = int(mask.sum())
            impact = "CAPACITY_ENDPOINT_OR_COUNTER_REVIEW" if field == "capacity_mah_raw" else "SIGNAL_REVIEW"
            issues_at(issues, np.flatnonzero(mask), f"SIGNAL_{name.upper()}", impact, field)
    return arrays, signal_counts


def summarize_operation(number, phase, lo, hi, time, volt, current, capacity, local_status, issues):
    t, v, i, q = (series[lo:hi] for series in (time, volt, current, capacity))
    n = hi - lo
    dt = np.diff(t)
    positive_dt = dt[np.isfinite(dt) & (dt > 0)]
    cadence = float(np.median(positive_dt)) if len(positive_dt) else None
    gap_limit = max(30.0, 5.0 * cadence) if cadence is not None else 30.0
    duplicates = np.isfinite(dt) & (dt == 0)
    reversals = np.isfinite(dt) & (dt < 0)
    gaps = np.isfinite(dt) & (dt > gap_limit)
    jumps = (np.abs(np.diff(v)) > VOLTAGE_JUMP_V) & (local_status[:-1] == local_status[1:]) & np.isfinite(v[:-1]) & np.isfinite(v[1:])
    wrong = (i < 0) if phase == "charge" else (i > 0) if phase == "discharge" else np.zeros(n, bool)
    for reason, mask, field, impact in (
        ("TIME_DUPLICATE", duplicates, "time_s_raw", "OPERATION_CLOCK_REVIEW"),
        ("TIME_REVERSED", reversals, "time_s_raw", "OPERATION_CLOCK_REVIEW"),
        ("TIME_GAP", gaps, "time_s_raw", "INTERVAL_EXCLUDED_FROM_INTEGRAL"),
        ("VOLTAGE_JUMP", jumps, "voltage_v_raw", "DIAGNOSTIC"),
    ):
        issues_at(issues, np.flatnonzero(mask) + lo + 1, reason, impact, field)
    issues_at(issues, np.flatnonzero(wrong & np.isfinite(i)) + lo, "WRONG_CURRENT_SIGN", "OPERATION_SIGNAL_REVIEW", "current_ma_raw")
    trace_ok = n >= 2 and np.isfinite(t).all() and np.isfinite(v).all() and np.isfinite(i).all() and not (duplicates.any() or reversals.any() or (wrong & np.isfinite(i)).any())
    finite_v = v[np.isfinite(v)]
    vmax = float(finite_v.max()) if len(finite_v) else None
    vmin = float(finite_v.min()) if len(finite_v) else None
    band = False
    if phase == "charge" and trace_ok:
        lower = np.flatnonzero(v <= WINDOW_V[0])
        if len(lower):
            start = int(lower[0])
            high = np.flatnonzero(v[start:] >= WINDOW_V[1])
            band = bool(len(high) and not gaps[start:start+int(high[0])].any())
    result = {
        "operation_number": number, "phase": phase, "samples": n,
        "first_sample": lo, "last_sample": hi - 1, "first_time_s": finite(t[0]), "last_time_s": finite(t[-1]),
        "first_voltage_v": finite(v[0]), "last_voltage_v": finite(v[-1]), "min_voltage_v": vmin, "max_voltage_v": vmax,
        "median_positive_step_s": cadence, "max_positive_step_s": float(positive_dt.max()) if len(positive_dt) else None,
        "time_duplicate_count": int(duplicates.sum()), "time_reversed_count": int(reversals.sum()),
        "time_gap_count": int(gaps.sum()), "voltage_jump_count": int(jumps.sum()),
        "wrong_sign_count": int((wrong & np.isfinite(i)).sum()), "zero_current_count": int((i == 0).sum()),
        "trace_ok": bool(trace_ok), "charge_window_observed": band,
    }
    if phase == "discharge":
        reset = np.isfinite(q[:-1]) & np.isfinite(q[1:]) & (np.diff(q) > DQ_MATCH_MAH)
        issues_at(issues, np.flatnonzero(reset) + lo + 1, "CAPACITY_COUNTER_RESET", "CAPACITY_TARGET_REVIEW", "capacity_mah_raw")
        valid = np.isfinite(dt) & (dt > 0) & ~gaps & np.isfinite(i[:-1]) & np.isfinite(i[1:]) & (i[:-1] <= 0) & (i[1:] <= 0)
        contribution = -(i[:-1][valid] + i[1:][valid]) * 0.5 * dt[valid] / 3600.0
        result.update(
            capacity_counter_delta_mah=finite(q[0] - q[-1]),
            capacity_counter_reset_count=int(reset.sum()), capacity_samples_nonfinite=int((~np.isfinite(q)).sum()),
            integral_mah=float(contribution.sum()) if valid.any() else None,
            integral_skipped_intervals=len(dt) - int(valid.sum()),
            integral_used_intervals=int(valid.sum()),
        )
    return result


def audit_cycle(table, dq):
    cell, cycle, order = (table[field][0].as_py() for field in ("cell_id","cycle_id","cycle_source_order"))
    if pc.count_distinct(table["cell_id"]).as_py() != 1 or pc.count_distinct(table["cycle_id"]).as_py() != 1:
        raise ValueError("Cycle must refer to exactly one cell and cycle ID")
    if not np.array_equal(table["sample_index"].chunk(0).to_numpy(), np.arange(table.num_rows)):
        raise ValueError(f"Invalid staging sample order in {cell}/{cycle}")

    statuses = pc.dictionary_encode(table["raw_status"].chunk(0))
    names = statuses.dictionary.to_pylist()
    status_codes = pc.fill_null(statuses.indices, -1).to_numpy()
    phase_codes = np.asarray([PHASE_OTHER, *map(phase_id, names)], dtype=np.int8)[status_codes+1]
    splits = np.r_[0, np.flatnonzero(phase_codes[1:] != phase_codes[:-1]) + 1, table.num_rows]
    issues = []
    arrays, signal_counts = read_signals(table, issues)
    time, volt, current, capacity = (arrays[field] for field in SIGNALS)
    phases = [summarize_operation(n, PHASES[phase_codes[lo]], int(lo), int(hi), time, volt, current, capacity,
                                  status_codes[lo:hi], issues) for n,(lo,hi) in enumerate(zip(splits,splits[1:]))]
    counts = np.bincount(status_codes+1, minlength=len(names)+1)
    status_counts = {(name if name is not None else "<null>"): int(count) for name,count in zip([None,*names], counts) if count}
    result = {
        "cell_id": cell, "cycle_id": cycle, "cycle_source_order": order, "sample_rows": table.num_rows,
        "dq_raw": dq, "operations": phases, "signal_counts": signal_counts,
        "status_sample_counts": status_counts, "issues": issues,
        "wrong_sign_count": sum(op["wrong_sign_count"] for op in phases),
        "zero_current_count": sum(op["zero_current_count"] for op in phases),
        "first_time_s": finite(time[0]), "last_time_s": finite(time[-1]),
    }
    return result, phase_codes


def target_reason(charge, discharge, target_dq):
    if not charge["trace_ok"] or not discharge["trace_ok"]:
        return "CHARGE_OR_DISCHARGE_SIGNAL_REVIEW"
    if target_dq is None:
        return "DQ_MISSING_OR_DUPLICATE"
    if not math.isfinite(target_dq) or target_dq <= 0:
        return "DQ_NONPOSITIVE_OR_NONFINITE"
    if discharge["capacity_counter_reset_count"]:
        return "CAPACITY_COUNTER_RESET"
    counter = discharge["capacity_counter_delta_mah"]
    if counter is None or counter <= 0 or discharge["capacity_samples_nonfinite"]:
        return "CAPACITY_COUNTER_INCOMPLETE"
    if abs(target_dq - counter) > DQ_MATCH_MAH:
        return "DQ_COUNTER_MISMATCH"
    return None


def annotate_pairs(cycles):
    if len({row["cell_id"] for row in cycles}) > 1:
        raise ValueError("Pairing requires records from the same cell")
    flattened = []
    clock_continuous = True
    for position, cycle in enumerate(cycles):
        counts = Counter(op["phase"] for op in cycle["operations"])
        cycle["phase_counts"] = dict(counts)
        cycle["clock_relation_to_previous"] = "FIRST"
        if position:
            left, right = cycles[position-1]["last_time_s"], cycle["first_time_s"]
            latest = "UNKNOWN" if left is None or right is None else "RESET" if right < left else "EQUAL" if right == left else "INCREASE"
            cycle["clock_relation_to_previous"] = latest
            clock_continuous &= latest == "INCREASE"
        # Keep rests in the operation inventory. They do not interrupt the next active phase.
        flattened.extend((cycle, op) for op in cycle["operations"] if op["phase"] != "rest")
        cycle.update(pair_status="REVIEW", pair_reason="MISSING_CHARGE_SESSION",
                     pair_geometry="UNPAIRED", feature_available_at=None, label_observed_at=None)
        if counts["charge"] > 1:
            cycle["pair_reason"] = "MULTIPLE_CHARGE_SESSIONS"
        elif counts["charge"] == 1:
            cycle["pair_reason"] = "MISSING_SUBSEQUENT_DISCHARGE"
    for n, (cycle, charge) in enumerate(flattened):
        if charge["phase"] != "charge" or cycle["phase_counts"]["charge"] != 1:
            continue
        cycle["feature_available_at"] = event(cycle, charge, end=True)
        if n + 1 == len(flattened):
            continue
        target, discharge = flattened[n+1]
        if discharge["phase"] != "discharge":
            cycle["pair_reason"] = "UNCLASSIFIED_INTERVENING_PHASE" if discharge["phase"] == "other" else "NEXT_PHASE_IS_CHARGE"
            continue
        if target["phase_counts"]["discharge"] != 1:
            cycle["pair_reason"] = "MULTIPLE_DISCHARGE_SESSIONS"
            continue
        same_cycle = target is cycle
        if not same_cycle and (
            not clock_continuous
            or target["cycle_source_order"] != cycle["cycle_source_order"]+1
            or target["cycle_id"] != cycle["cycle_id"]+1
        ):
            cycle["pair_reason"] = "CROSS_CYCLE_CLOCK_NOT_PROVEN"
            continue
        end, start = charge["last_time_s"], discharge["first_time_s"]
        if end is None or start is None or end >= start:
            cycle["pair_reason"] = "NONINCREASING_CHARGE_TO_DISCHARGE_TIME"
            continue
        cycle["pair_geometry"] = "SAME_CYCLE" if same_cycle else "CROSS_CYCLE"
        cycle["discharge_start_at"] = event(target, discharge)
        cycle["label_observed_at"] = event(target, discharge, end=True)
        cycle["discharge_cycle_id"] = target["cycle_id"]
        cycle["paired_dq_raw"] = target["dq_raw"]
        for field in ("capacity_counter_delta_mah","capacity_counter_reset_count","integral_mah","integral_skipped_intervals","integral_used_intervals"):
            cycle[field] = discharge[field]
        cycle["dq_counter_abs_diff_mah"] = (abs(target["dq_raw"] - discharge["capacity_counter_delta_mah"])
            if target["dq_raw"] is not None and math.isfinite(target["dq_raw"]) and discharge["capacity_counter_delta_mah"] is not None else None)
        integral = discharge["integral_mah"]
        ref = discharge["capacity_counter_delta_mah"]
        cycle["integral_minus_counter_mah"] = integral - ref if integral is not None and ref is not None else None
        cycle["integral_abs_pct_of_counter"] = abs((integral - ref)/ref)*100 if integral is not None and ref is not None and ref > 0 else None
        reason = target_reason(charge, discharge, target["dq_raw"])
        cycle["pair_status"] = "REVIEW" if reason else "READY_FOR_P3_3_AUDIT"
        cycle["pair_reason"] = reason


def canonical_table(table, record, phase_codes, source_sha, protocol_id):
    row_count = table.num_rows
    slices = [(op["phase"], op["samples"], op["operation_number"]) for op in record["operations"]]
    cell, cycle = record["cell_id"], record["cycle_id"]
    operation_id = pa.concat_arrays([pa.repeat(f"{cell}:{cycle}:{number}", n) for _,n,number in slices])
    operation_type = pa.concat_arrays([pa.repeat(phase if phase != "rest" else "other", n) for phase,n,_ in slices])
    phase = pc.take(pa.array(PHASES), pa.array(phase_codes))
    charge_stage = pa.concat_arrays([pa.repeat("UNKNOWN", n) if name == "charge" else pa.nulls(n, pa.string()) for name,n,_ in slices])
    fields = {key: table[key] for key in ("cell_id","cycle_id","cycle_source_order","sample_index","raw_status")}
    fields.update(operation_id=operation_id, operation_type=operation_type, phase=phase, charge_stage=charge_stage,
                  time_s=table["time_s_raw"], voltage_v=table["voltage_v_raw"],
                  current_a=pc.multiply(table["current_ma_raw"], -0.001),
                  capacity_counter_ah=pc.multiply(table["capacity_mah_raw"], 0.001),
                  temperature_c=pa.nulls(row_count, pa.float64()),
                  protocol_id=pa.repeat(protocol_id,row_count) if protocol_id is not None else pa.nulls(row_count,pa.string()),
                  source_archive_sha256=pa.repeat(source_sha,row_count),
                  quality_status=pa.repeat("SIGNAL_REVIEW" if record["issues"] else "AUDITED",row_count))
    return pa.table(fields).replace_schema_metadata({
        b"current_sign_convention": b"DISCHARGE_POSITIVE_CHARGE_NEGATIVE",
        b"temperature_provenance": b"no staging temperature channel; null",
        b"ordering": b"cell_id, cycle_source_order, sample_index; raw clock stays within cycle",
        b"quality_reason_join": b"manifests/cell_cycle_inventory.csv and reports/rejected_records.csv",
        b"source_doi": b"10.17632/nsc7hnsg4s.2",
    })


def check_reference_cycle(staging):
    table = next(iter_cycles(staging/"1-1.parquet", batch_size=257))
    dq,_ = index_dq(json.loads(read_json(staging/"1-1.json")))
    record,_ = audit_cycle(table,dq[1])
    annotate_pairs([record])
    charge, discharge = record["operations"]
    observed = (record["cell_id"],record["cycle_id"],charge["samples"],discharge["samples"],
                charge["last_sample"],discharge["first_sample"],charge["last_time_s"],discharge["first_time_s"],
                discharge["last_sample"],discharge["last_time_s"])
    if observed != ("1-1",1,383,453,382,383,1927,1933,835,4179):
        raise ValueError(f"Reference RT-Batt cycle changed: {observed}")
    for name in ("capacity_counter_delta_mah","dq_raw"):
        if not math.isclose(record[name],1174.2992,abs_tol=DQ_MATCH_MAH):
            raise ValueError(f"Reference discharge capacity changed: {name}")
    if not math.isclose(record["integral_mah"],1181.6323125,abs_tol=DQ_MATCH_MAH) or record["wrong_sign_count"]:
        raise ValueError("Reference sign or discharge integral changed")
    return True



def load_json(path):
    return json.loads(read_json(path))


def discharge_profile(table, nominal_ah):
    rates = []
    status = table["raw_status"].chunk(0)
    current = table["current_ma_raw"].chunk(0)
    for stage in range(4):
        selected = pc.filter(current, pc.equal(status, f"Constant current discharge_{stage}")).to_numpy(zero_copy_only=False)
        values = selected[np.isfinite(selected) & (selected < 0)]
        if len(values) < 2:
            return None
        rates.append(float(np.median(-values) / (1000.0 * nominal_ah)))
    return rates


def audit_protocol(cell_id, initial, reference):
    expected = reference["discharge_rates_c_by_cell"].get(cell_id)
    profiles = [rates for table in initial if (rates := discharge_profile(table, reference["nominal_capacity_ah"])) is not None]
    result = {
        "cell_id": cell_id, "protocol_id": None, "source_url": reference["source_url"],
        "source_sha256": reference["source_sha256"], "reference_rates_c": expected,
        "measured_rates_c": None, "profile_status": "INSUFFICIENT_EARLY_CYCLES",
        "early_cycles_checked": len(initial), "early_cycles_with_four_stages": len(profiles),
        "source_matching_cycles": 0, "temperature_chamber_c": reference["temperature_chamber_c"],
    }
    if not profiles:
        return result
    rates = np.asarray(profiles)
    medians = np.median(rates, axis=0)
    rounded = np.rint(medians).astype(int)
    result["measured_rates_c"] = medians.tolist()
    if expected is not None:
        agrees = np.abs(rates - np.asarray(expected)) <= PROFILE_TOLERANCE_C
        result["source_matching_cycles"] = int(np.all(agrees, axis=1).sum())
    if len(profiles) < min(3, len(initial)) or (rounded < 1).any() or (np.abs(rates-rounded) > PROFILE_TOLERANCE_C).any():
        result["profile_status"] = "EARLY_TRACE_PROFILE_UNRESOLVED"
        return result
    result["protocol_id"] = "RT_BATT_OBSERVED_" + "-".join(f"{level}C" for level in rounded)
    result["profile_status"] = (
        "REFERENCE_MATCH" if expected == rounded.tolist() else
        "FOURTH_STAGE_REFERENCE_CONFLICT" if expected is not None and expected[:3] == rounded[:3].tolist() else
        "OTHER_REFERENCE_CONFLICT" if expected is not None else "OBSERVED_ONLY"
    )
    return result


def describe(values):
    if not values:
        return {"count": 0, "median": None, "p95": None, "max": None}
    return {"count":len(values), "median":float(np.median(values)), "p95":float(np.quantile(values,.95)), "max":float(max(values))}


def summarize_cell(cycles, protocol, dq, duplicates):
    ids = {item["cycle_id"] for item in cycles}
    extra = sorted((set(dq) | duplicates) - ids)
    labels = {}
    for row in cycles:
        for status, count in row["status_sample_counts"].items():
            entry = labels.setdefault(status, {"samples":0,"cycles":0})
            entry["samples"] += count
            entry["cycles"] += 1
    diagnostics = Counter(issue["reason"] for row in cycles for issue in row["issues"])
    signal_totals = {field: {state: sum(row["signal_counts"][field][state] for row in cycles)
                              for state in ("null","nan","inf")} for field in SIGNALS}
    ready = [row for row in cycles if row["pair_status"]=="READY_FOR_P3_3_AUDIT"]
    delta = [row["dq_counter_abs_diff_mah"] for row in cycles if row.get("dq_counter_abs_diff_mah") is not None]
    integrated = [row for row in cycles if row.get("integral_minus_counter_mah") is not None
                  and row["integral_skipped_intervals"]==0 and row["capacity_counter_reset_count"]==0
                  and row["integral_abs_pct_of_counter"] is not None]
    largest = sorted(integrated,key=lambda row: (-abs(row["integral_minus_counter_mah"]),row["cycle_source_order"]))[:5]
    ops = [op for row in cycles for op in row["operations"]]
    charge = [op for op in ops if op["phase"]=="charge"]
    cutoff = [op["last_voltage_v"] for op in ops if op["phase"]=="discharge" and op["last_voltage_v"] is not None]
    charge_max = [op["max_voltage_v"] for op in charge if op["max_voltage_v"] is not None]
    sampling = [op["median_positive_step_s"] for op in charge if op["median_positive_step_s"] is not None]
    return {
        "cell_id": cycles[0]["cell_id"], "cycles":len(cycles), "staged_samples":sum(row["sample_rows"] for row in cycles),
        "ready_pairs":len(ready), "review_cycles":len(cycles)-len(ready),
        "cycles_with_usable_charge": sum(any(op["phase"]=="charge" and op["trace_ok"] for op in row["operations"]) for row in cycles),
        "pair_geometry":dict(Counter(row["pair_geometry"] for row in cycles)),
        "review_reasons":dict(Counter(row["pair_reason"] for row in cycles if row["pair_reason"])),
        "clock_boundaries":dict(Counter(row["clock_relation_to_previous"] for row in cycles)),
        "status_labels":labels,"diagnostics":dict(diagnostics),"signal_counts":signal_totals,
        "zero_current_samples":sum(row["zero_current_count"] for row in cycles),"dq_keys":len(dq)+len(duplicates),
        "dq_missing_cycle_ids":sorted(ids-(set(dq)|duplicates)), "dq_duplicate_cycle_ids":sorted(duplicates),
        "dq_extra_cycle_ids":extra, "dq_null_cycle_ids":sorted(key for key,value in dq.items() if value is None),
        "dq_counter_abs_diff_mah":describe(delta),
        "integral_counter_abs_diff_mah":describe([abs(row["integral_minus_counter_mah"]) for row in integrated]),
        "integral_counter_abs_pct":describe([row["integral_abs_pct_of_counter"] for row in integrated]),
        "partial_integral_pairs":sum(row.get("integral_skipped_intervals",0)>0 for row in cycles),
        "integral_top": [{key:row.get(key) for key in (
            "cell_id","cycle_id","discharge_cycle_id","capacity_counter_delta_mah","paired_dq_raw","integral_mah",
            "integral_minus_counter_mah","integral_abs_pct_of_counter","label_observed_at")} for row in largest],
        "charge_window_sessions":sum(op["charge_window_observed"] for op in charge),
        "charge_session_count":len(charge), "charge_max_voltage_v":max(charge_max,default=None),
        "discharge_cutoff_min_v":min(cutoff,default=None), "discharge_cutoff_max_v":max(cutoff,default=None),
        "charge_sampling_median_s":float(np.median(sampling)) if sampling else None,
        "protocol_id":protocol["protocol_id"], "protocol_status":protocol["profile_status"],
    }


INVENTORY_FIELDS = (
    "cell_id","cycle_id","cycle_source_order","source_member","protocol_id","sample_rows","charge_samples","discharge_samples",
    "rest_samples","other_samples","charge_sessions","discharge_sessions","rest_sessions","other_sessions",
    "clock_relation_to_previous","first_time_s","last_time_s","dq_status","dq_raw","pair_geometry","pair_status","pair_reason",
    "feature_available_at","discharge_start_at","label_observed_at","discharge_cycle_id","paired_dq_raw",
    "capacity_counter_delta_mah","capacity_counter_reset_count","dq_counter_abs_diff_mah",
    "integral_mah","integral_used_intervals","integral_skipped_intervals","integral_minus_counter_mah","integral_abs_pct_of_counter",
    "wrong_sign_count","zero_current_count","charge_window_sessions","charge_max_voltage_v","discharge_cutoff_v",
    "raw_status_sample_counts","signal_counts","diagnostic_counts","operations",
)
ISSUE_FIELDS = ("cell_id","cycle_id","cycle_source_order","sample_index","field","reason","impact")
PROTOCOL_FIELDS = (
    "cell_id","protocol_id","profile_status","reference_rates_c","measured_rates_c","early_cycles_checked",
    "early_cycles_with_four_stages","source_matching_cycles","temperature_chamber_c","source_sha256","source_url",
    "cycles_covered","sample_rows_covered",
)


def inventory_row(cycle, source_member, protocol, dq, duplicates):
    row = {key:cycle.get(key) for key in INVENTORY_FIELDS}
    cycle_id = cycle["cycle_id"]
    row["dq_status"] = ("DUPLICATE" if cycle_id in duplicates else "MISSING" if cycle_id not in dq
                        else "NULL" if dq[cycle_id] is None else "PRESENT")
    row.update(source_member=source_member,protocol_id=protocol["protocol_id"])
    for phase in PHASES:
        row[f"{phase}_sessions"] = cycle["phase_counts"].get(phase,0)
        row[f"{phase}_samples"] = sum(op["samples"] for op in cycle["operations"] if op["phase"]==phase)
    charges = [op for op in cycle["operations"] if op["phase"]=="charge"]
    discharges = [op for op in cycle["operations"] if op["phase"]=="discharge"]
    row["charge_window_sessions"] = sum(op["charge_window_observed"] for op in charges)
    row["charge_max_voltage_v"] = max((op["max_voltage_v"] for op in charges if op["max_voltage_v"] is not None),default=None)
    row["discharge_cutoff_v"] = discharges[-1]["last_voltage_v"] if len(discharges)==1 else None
    row["raw_status_sample_counts"] = cycle["status_sample_counts"]
    row["diagnostic_counts"] = dict(Counter(issue["reason"] for issue in cycle["issues"]))
    return {key:compact(value) if isinstance(value,(dict,list)) else value for key,value in row.items()}


class CanonicalWriter:
    def __init__(self,path):
        self.path = path
        self.writer = None
        self.buffer = []
        self.pending_rows = 0

    def append(self, table):
        self.buffer.append(table)
        self.pending_rows += table.num_rows
        if self.pending_rows >= 65536:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        table = pa.concat_tables(self.buffer)
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.path,table.schema,compression="zstd",use_dictionary=[
                "cell_id","raw_status","operation_id","operation_type","phase","charge_stage",
                "protocol_id","source_archive_sha256","quality_status",
            ])
        self.writer.write_table(table)
        self.buffer.clear()
        self.pending_rows = 0

    def close(self):
        self.flush()
        if self.writer is not None:
            self.writer.close()


def checked_inputs(staging, member):
    paths = [staging/member[key]["path"] for key in ("trace","summary")]
    for path,key in zip(paths,("trace","summary")):
        if sha256(path) != member[key]["sha256"]:
            raise ValueError(f"Staging SHA256 differs: {path.name}")
    return paths


def process_cell(staging, member, reference, source_sha, batch_size, canonical):
    trace, summary = checked_inputs(staging,member)
    data = load_json(summary)
    cell_id = member["cell_id"]
    if data["cell_id"] != cell_id or data["source_member"] != member["source_member"]:
        raise ValueError(f"Staging JSON identity differs: {cell_id}")
    dq, duplicates = index_dq(data)
    rows = iter_cycles(trace,batch_size=batch_size)
    first = list(islice(rows,PROFILE_CYCLES))
    protocol = audit_protocol(cell_id,first,reference)
    records, seen = [], set()
    for table in chain(first,rows):
        cycle_id = table["cycle_id"][0].as_py()
        cycle, phases = audit_cycle(table,dq.get(cycle_id))
        if cycle["cell_id"] != cell_id or cycle_id in seen:
            raise ValueError(f"Repeated or wrong staged cell/cycle key: {cell_id}/{cycle_id}")
        seen.add(cycle_id)
        records.append(cycle)
        if canonical is not None:
            canonical.append(canonical_table(table,cycle,phases,source_sha,protocol["protocol_id"]))
    if len(records)!=member["cycle_count"] or sum(row["sample_rows"] for row in records)!=member["sample_rows"]:
        raise ValueError(f"Staging manifest count differs: {cell_id}")
    annotate_pairs(records)
    summary_result = summarize_cell(records,protocol,dq,duplicates)
    protocol.update(cycles_covered=len(records) if protocol["protocol_id"] else 0,
                    sample_rows_covered=summary_result["staged_samples"] if protocol["protocol_id"] else 0)
    return records,summary_result,protocol,dq,duplicates


def write_issues(writer, records, summary):
    for row in records:
        identity = {key:row[key] for key in ISSUE_FIELDS[:3]}
        for issue in row["issues"]:
            writer.writerow({**identity,**issue})
        if row["pair_reason"]:
            writer.writerow({**identity,"reason":row["pair_reason"],"field":"pair","impact":"PAIR_EXCLUDED_FROM_P3_3_CANDIDATES"})
    for name,status in (("dq_extra_cycle_ids","DQ_EXTRA_ID"),("dq_duplicate_cycle_ids","DQ_DUPLICATE_ID"),
                        ("dq_missing_cycle_ids","DQ_ID_ABSENT"),("dq_null_cycle_ids","DQ_NULL")):
        for cycle_id in summary[name]:
            writer.writerow({"cell_id":summary["cell_id"],"cycle_id":cycle_id,"reason":status,"field":"dq_by_cycle_raw",
                             "impact":"DQ_IDENTITY_REVIEW; TRACE_RETAINED"})


def run_audit(staging,outdir,reference_path,expected_sha,batch_size,only_cell=None):
    import csv
    from contextlib import ExitStack

    source_file = staging/"conversion_manifest.json"
    if sha256(source_file) != expected_sha:
        raise ValueError("Conversion manifest SHA-256 differs from P3.1 clean readback")
    source = load_json(source_file)
    check_reference_cycle(staging)
    members = [item for item in source["data_members"] if only_cell is None or only_cell==item["cell_id"]]
    if not members or len({member["cell_id"] for member in members})!=len(members):
        raise ValueError("No matching staged cells or duplicate cell IDs")
    reference = load_json(reference_path)
    outdir.mkdir(parents=True,exist_ok=False)
    canonical = CanonicalWriter(outdir/"canonical_cycles.parquet") if only_cell is None else None
    cell_summaries = []
    with ExitStack() as stack:
        def open_csv(name, fields):
            target = stack.enter_context((outdir/name).open("w",encoding="utf-8",newline=""))
            writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            return writer

        inv = open_csv("cell_cycle_inventory.csv",INVENTORY_FIELDS)
        protocols = open_csv("protocol_inventory.csv",PROTOCOL_FIELDS)
        rejected = open_csv("rejected_records.csv",ISSUE_FIELDS)
        if canonical is not None:
            stack.callback(canonical.close)
        for member in members:
            records,cell_summary,protocol,dq,duplicates = process_cell(staging,member,reference,source["source_sha256"],batch_size,canonical)
            cell_summaries.append(cell_summary)
            inv.writerows(inventory_row(record,member["source_member"],protocol,dq,duplicates) for record in records)
            protocols.writerow({key:compact(value) if isinstance(value,list) else value for key,value in protocol.items()})
            write_issues(rejected,records,cell_summary)
            print(f"{member['cell_id']}: {cell_summary['cycles']} cycles, {cell_summary['ready_pairs']} candidate pairs",flush=True)

    totals = {"cells":len(cell_summaries),"cycles":sum(row["cycles"] for row in cell_summaries),
              "sample_rows":sum(row["staged_samples"] for row in cell_summaries),
              "cells_with_candidates":sum(row["ready_pairs"]>0 for row in cell_summaries),
              "ready_pairs":sum(row["ready_pairs"] for row in cell_summaries)}
    if only_cell is None:
        if (totals["cells"],totals["cycles"],totals["sample_rows"])!=(77,source["cycles"],source["sample_rows"]):
            raise ValueError(f"Full audit totals do not reconcile: {totals}")
        with pq.ParquetFile(outdir/"canonical_cycles.parquet") as parquet:
            if parquet.metadata.num_rows != totals["sample_rows"]:
                raise ValueError("Canonical Parquet row-count differs from staging")
    if only_cell == "1-1" and totals["cycles"]!=1504:
        raise ValueError(f"Reference cell inventory does not reconcile with 1504 cycles: {totals}")
    payload = {"source_sha256":source["source_sha256"],"source_manifest_sha256":expected_sha,
               "protocol_reference_sha256":sha256(reference_path),"totals":totals,"cells":cell_summaries,
               "thresholds":{"dq_counter_tolerance_mah":DQ_MATCH_MAH,"diagnostic_voltage_jump_v":VOLTAGE_JUMP_V,
                             "diagnostic_gap":"max(30 s, 5 * median positive phase interval)","candidate_charge_window_v":WINDOW_V,
                             "early_profile_tolerance_c":PROFILE_TOLERANCE_C,"early_profile_probe_cycles":PROFILE_CYCLES}}
    (outdir/"p3_2_audit_summary.json").write_text(compact(payload)+"\n",encoding="utf-8")
    print(compact(totals),flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--protocol-reference",type=Path,required=True)
    parser.add_argument("--staging-manifest-sha",required=True)
    parser.add_argument("--batch-size",type=int,default=32768)
    parser.add_argument("--cell")
    args = parser.parse_args()
    if args.batch_size<1:
        parser.error("--batch-size must be positive")
    run_audit(args.staging,args.output,args.protocol_reference,args.staging_manifest_sha,args.batch_size,args.cell)


if __name__ == "__main__":
    main()
