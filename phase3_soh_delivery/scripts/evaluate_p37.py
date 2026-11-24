"""Single-use evaluation of the approved p36-r1 artifacts on frozen held-out keys."""
import argparse
import importlib.metadata
import json
import os
import platform
from pathlib import Path
from time import perf_counter

import numpy as np
import psutil
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from scripts.p36_inputs import LEDGER, PRIMARY, ROOT, STAGING, dump_json, labels_from_summary, require, sha
from scripts.p37_governance import (
    CANDIDATE, CANDIDATE_SHA, CONVERSION, D07, D07_RULES, EVALUATION_SOURCES,
    FREEZE, LABELS, PRECHECK, RECEIPT, SPLIT, STALE_REASON, STATUS, append_ledger,
    binding, claim, now, read, refresh_ledger_bindings, verify_candidate,
)
from scripts.p37_metrics import band, describe
from scripts.train_p36 import dispersion, verify_load
from src.soh.evaluation_guard import EvaluationGuard
from src.soh.feature_extractor import FAST, TOP, extract_charge


OUTPUT = "reports/P3_7_HELDOUT_PREDICTIONS.parquet"
RUN = "manifests/p3_7_run_evidence.json"
RECOVERY = "manifests/p3_7_same_session_recovery.json"
TEST_LOG = "reports/P3_7_TEST_LOG.txt"
EXECUTABLES = ["scripts/p37_governance.py", "scripts/evaluate_p37.py", "scripts/p37_metrics.py",
               "scripts/report_p37.py", "tests/test_p37.py"]
PARTS = ROOT / "data/evaluation/p37-r1"
SIGNALS = ["cell_id", "cycle_id", "cycle_source_order", "sample_index", "raw_status",
           "time_s_raw", "voltage_v_raw", "current_ma_raw"]
LABEL_FIELDS = ["cell_id", "cycle_id", "cycle_source_order", "feature_available_at",
                "soh_ref_percent", "release_status", "target_semantics", "q_ref_ah"]

PREDICTIONS = pa.schema([
    ("cell_id", pa.string()), ("cycle_id", pa.int64()), ("cycle_source_order", pa.int32()),
    ("end_charge_sample_index", pa.int32()), ("soh_ref_percent", pa.float64()),
    ("soh_band", pa.string()), ("cycle_period", pa.string()), ("stage_1_c", pa.int32()),
    *((f, pa.float64()) for f in PRIMARY), ("feature_notes", pa.string()),
    ("status", pa.string()), ("reason", pa.string()), ("soh_percent", pa.float64()),
    ("sigma_trees_pp", pa.float64()), ("stale", pa.bool_()), ("stale_policy", pa.string()),
    ("last_valid_soh", pa.float64()), ("last_valid_cycle", pa.int64()),
    ("baseline_version", pa.int32()), ("previous_baseline_pp", pa.float64()),
    ("confirmation_count", pa.int32()),
    *((name + "_raw", pa.float64()) for name in (
        "rf", "rf_unweighted", "ridge", "train_median", "xgb",
        "voltage_window_only", "cc_cv_only", "phase_and_ratio")),
])


def process_memory():
    mem = psutil.Process().memory_info()
    return {"rss_bytes": mem.rss, "peak_working_set_bytes": getattr(mem, "peak_wset", mem.rss)}


def preflight(resume=False):
    require((ROOT / RECEIPT).exists() == resume, "Held-out receipt state does not match run mode")
    freeze = read(FREEZE)
    require(freeze["status"] == "MODEL_FROZEN" and freeze["heldout_open_allowed"], "Freeze not approved")
    require(sha(ROOT / CANDIDATE) == CANDIDATE_SHA, "Candidate snapshot hash differs")
    candidate = read(CANDIDATE)
    require(all(freeze[key] == candidate[key] for key in (
        "artifact_hashes", "input_hashes", "models", "policy", "primary_features", "guard_sha256")),
        "Signed freeze changed an approved artifact or policy")
    ledger = (ROOT / LEDGER).read_bytes()
    require((b"## P3.7" in ledger) == resume, "Ledger exposure does not match run mode")
    verify_candidate(candidate, ledger, freeze["ledger_snapshot_prefix_bytes"])
    require(sha(ROOT / D07) == freeze["er5_evaluation_configuration"]["sha256"], "D07 hash mismatch")
    config = read(D07)
    require(config["status"] == "APPROVED" and all(config[k] == v for k, v in D07_RULES.items()),
            "D07 rules do not match the signed criteria")
    require(tuple(freeze["primary_features"]) == PRIMARY, "Frozen feature order mismatch")
    state = {m["milestone_id"]: m for m in read(STATUS)["milestones"]}
    require(state["P3.6"]["status"] == "PASS"
            and state["P3.7"]["heldout_evaluation"] == ("OPENED_ONCE" if resume else "UNOPENED"),
            "P3.7 gate state differs from run mode")
    split = read(SPLIT)
    heldout = split["held_out_cell_ids"]
    dev = split["development_cell_ids"]
    require(len(heldout) == len(set(heldout)) == config["expected_cells"]
            and not set(heldout) & set(dev) and split["revision"] == "p34-r1", "Frozen split mismatch")
    profile = {row["cell_id"]: row["stage_1_c"] for row in split["cell_metadata"]}
    require(all(cell in profile for cell in heldout), "Held-out profile metadata missing")
    conversion = read(CONVERSION)
    staged = {m["cell_id"]: m for m in conversion["data_members"] if m["cell_id"] in heldout}
    require(set(staged) == set(heldout), "Staging inventory lacks held-out cells")
    for cell, meta in staged.items():
        require(meta["trace"]["path"] == f"{cell}.parquet" and (ROOT / STAGING / f"{cell}.parquet").is_file(),
                "A held-out staging path is missing")
    require((ROOT / LABELS).is_file() and not (ROOT / OUTPUT).exists(), "Missing labels or prior output exists")
    lock = {name: sha(ROOT / name) for name in EXECUTABLES}
    reported_versions = freeze["model_runtime"]["libraries"]
    packages = {k: importlib.metadata.version(k) for k in reported_versions}
    require(packages == reported_versions, "Runtime package versions differ from the model freeze")
    require(platform.python_version() == freeze["model_runtime"]["python"], "Python differs from freeze")
    policy = read("artifacts/soh/ood_policy.json")
    require(policy == freeze["policy"], "Policy does not equal signed p36-r1 policy")
    before = process_memory()
    start = perf_counter()
    models = {name: verify_load(ROOT / m["path"], m["sha256"]) for name, m in freeze["models"].items()}
    resources = dict(runtime=dict(platform=platform.platform(), cpu=platform.processor(),
                                  logical_processors=psutil.cpu_count(), ram_bytes=psutil.virtual_memory().total,
                                  python=platform.python_version(), packages=packages),
                     memory_before_load=before, memory_after_load=process_memory(),
                     all_models_verified_load_ms=1000 * (perf_counter()-start),
                     frozen_rf_threads=models["rf"].n_jobs, rf_bytes=freeze["models"]["rf"]["bytes"])
    return freeze, config, heldout, dev, profile, staged, models, resources, lock


def load_reference(cells, cutoff):
    path = ROOT / LABELS
    require(sha(path) == EVALUATION_SOURCES[LABELS], "Approved label parquet changed")
    return read_released_labels(path, cells, cutoff)


def read_released_labels(path, cells, cutoff):
    table = pq.read_table(path, columns=LABEL_FIELDS, filters=[("cell_id", "in", cells)])
    by_cell = {cell: {} for cell in cells}
    for record in table.to_pylist():
        cell, cycle = record["cell_id"], record["cycle_id"]
        ref = record["soh_ref_percent"]
        require(record["release_status"] == "DRAFT_PENDING_D02_D03_REVIEW"
                and record["target_semantics"] == "cell_relative_operational_capacity"
                and ref is not None and np.isfinite(ref) and record["q_ref_ah"] > 0
                and record["feature_available_at"] is not None, f"Invalid released reference: {cell}/{cycle}")
        require(cycle not in by_cell[cell], "Duplicate approved cell-cycle key")
        record["soh_band"] = band(ref, cutoff)
        by_cell[cell][cycle] = record
    require(set(table["cell_id"].unique().to_pylist()) == set(cells), "Label population missing a held-out cell")
    return by_cell


def features_for_cell(cell, path, references):
    t_start = perf_counter()
    table = pq.read_table(path, columns=SIGNALS, filters=[("raw_status", "in", [FAST, TOP])], use_threads=False)
    require(table["cell_id"].unique().to_pylist() == [cell], f"Mislabeled charge file: {cell}")
    cycles, orders, samples = [table[col].to_numpy() for col in SIGNALS[1:4]]
    fast = pc.equal(table["raw_status"], FAST).to_numpy(zero_copy_only=False)
    stages = np.array([TOP, FAST])[fast.astype(np.int8)]
    clock, voltage, raw = [table[col].to_numpy() for col in SIGNALS[-3:]]
    current = -raw/1000
    bounds = np.r_[0, np.flatnonzero(np.diff(orders)) + 1, len(orders)]
    computed = {}
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        cycle = int(cycles[lo])
        if cycle not in references:
            continue
        require(cycle not in computed and np.all(cycles[lo:hi] == cycle), f"Ambiguous charge key {cell}/{cycle}")
        expected = references[cycle]["feature_available_at"]["sample_index"]
        end = int(samples[hi-1])
        if end != expected or int(orders[lo]) != references[cycle]["cycle_source_order"]:
            computed[cycle] = (end, {}, {"charge": "FROZEN_END_CHARGE_MISMATCH"})
        elif not np.all(np.diff(samples[lo:hi]) == 1):
            computed[cycle] = (end, {}, {"charge": "NONCONTIGUOUS_CHARGE_SAMPLES"})
        else:
            cut = slice(lo, hi)
            values, notes = extract_charge(clock[cut], voltage[cut], current[cut], stages[cut])
            computed[cycle] = (end, values, notes)
    return computed, perf_counter()-t_start


def predict_matrix(matrix, models, metadata):
    result, masks = {}, {}
    for name, model in models.items():
        indices = [PRIMARY.index(f) for f in metadata[name].get("features", PRIMARY)]
        x = np.ascontiguousarray(matrix[:, indices], dtype=np.float32 if name.startswith("rf") else np.float64)
        eligible = np.isfinite(x).all(axis=1)
        if name == "train_median":
            # The constant baseline has no dependence on HI values.
            eligible[:] = True
            x = np.zeros_like(x)
        predictions = np.full(len(x), np.nan)
        sigma = None
        if np.any(eligible):
            subset = x[eligible]
            predictions[eligible] = model.predict(subset)
            if name == "rf":
                sigma = np.full(len(x), np.nan)
                sigma[eligible] = dispersion(model, subset)
        result[name] = predictions
        masks[name] = eligible
        if name == "rf":
            result["sigma"] = sigma if sigma is not None else np.full(len(x), np.nan)
    return result


def evaluate_cell(cell, computed, references, stage, freeze, models, config):
    ordered = sorted(references.values(), key=lambda row: row["cycle_source_order"])
    cycles = [rec["cycle_id"] for rec in ordered]
    require(all(b > a for a, b in zip(cycles, cycles[1:])), f"Non-increasing source cycles: {cell}")
    matrix = np.full((len(ordered), len(PRIMARY)), np.nan)
    missing = []
    ends = []
    for i, ref in enumerate(ordered):
        end, values, notes = computed.get(ref["cycle_id"], (None, {}, {"charge": "CHARGE_NOT_FOUND"}))
        ends.append(end)
        missing.append({k: v for k, v in notes.items() if k in PRIMARY or k == "charge"})
        matrix[i] = [values.get(f, np.nan) for f in PRIMARY]
    start = perf_counter()
    prediction = predict_matrix(matrix, models, freeze["models"])
    guard = EvaluationGuard(freeze["policy"])
    rows = []
    for i, ref in enumerate(ordered):
        raw = {name + "_raw": float(prediction[name][i]) if np.isfinite(prediction[name][i]) else None
               for name in models}
        sigma = float(prediction["sigma"][i]) if np.isfinite(prediction["sigma"][i]) else None
        guarded = guard.evaluate(cell, freeze["revision"], ref["cycle_id"], matrix[i], raw["rf_raw"],
                                 sigma, stale=config["offline_stale"]["value"])
        rows.append(dict(cell_id=cell, cycle_id=ref["cycle_id"], cycle_source_order=ref["cycle_source_order"],
                         end_charge_sample_index=ends[i], soh_ref_percent=ref["soh_ref_percent"],
                         soh_band=ref["soh_band"], cycle_period="EARLY" if i < len(ordered)//2 else "LATE",
                         stage_1_c=stage, feature_notes=json.dumps(missing[i], ensure_ascii=False, sort_keys=True),
                         stale=False, stale_policy=STALE_REASON, sigma_trees_pp=sigma, **guarded, **raw,
                         **{f: float(v) if np.isfinite(v) else None for f, v in zip(PRIMARY, matrix[i])}))
    return rows, matrix, perf_counter()-start


def rehearsal(freeze, cfg, dev, profiles, models):
    cell = "1-1"
    require(cell in dev, "Rehearsal fixture outside development")
    conversion = read(CONVERSION)
    meta, = [m for m in conversion["data_members"] if m["cell_id"] == cell]
    base = ROOT / STAGING
    for name in ("trace", "summary"):
        require(sha(base / meta[name]["path"]) == meta[name]["sha256"], "Development rehearsal fixture changed")
    refs = labels_from_summary(cell, json.loads((base / meta["summary"]["path"]).read_bytes()))
    dev_features = pq.read_table(ROOT / "data/features/soh_feature_table.parquet",
                                 columns=["cycle_id", "end_charge_sample_index", *PRIMARY],
                                 filters=[("cell_id", "=", cell)]).to_pylist()
    references = {row["cycle_id"]: dict(cycle_id=row["cycle_id"], cycle_source_order=row["cycle_id"]-1,
                  feature_available_at={"sample_index": row["end_charge_sample_index"]},
                  soh_ref_percent=refs[row["cycle_id"]], soh_band=band(refs[row["cycle_id"]], 80.0))
                  for row in dev_features}
    computed, _ = features_for_cell(cell, base / meta["trace"]["path"], references)
    rows, matrix, _ = evaluate_cell(cell, computed, references, profiles[cell], freeze, models, cfg)
    np.testing.assert_array_equal(matrix, [[row[f] for f in PRIMARY] for row in dev_features])
    require(len(rows) == len(refs) and set(references) == set(refs)
            and describe(rows)["raw_count"] == len(rows), "Development rehearsal mismatch")
    print(f"Development rehearsal PASS, {cell}, {len(rows)} rows, all four HI exact, all 8 models fit-free")


def benchmark(model, matrix, policy):
    good = matrix[np.isfinite(matrix).all(axis=1)]
    if not len(good):
        return None
    indices = np.linspace(0, len(good)-1, min(106, len(good)), dtype=int)
    guard = EvaluationGuard(policy)
    duration = []
    for i, index in enumerate(indices):
        row = np.ascontiguousarray(good[index].reshape(1, -1), dtype=np.float32)
        start = perf_counter()
        prediction = float(model.predict(row)[0])
        sigma = float(dispersion(model, row)[0])
        guard.evaluate("runtime-benchmark", "p36-r1", i+1, good[index], prediction, sigma, stale=False)
        if i >= 6:
            duration.append(1000*(perf_counter()-start))
    if not duration:
        return None
    return dict(samples=len(duration), p95_ms=float(np.percentile(duration, 95)),
                p99_ms=float(np.percentile(duration, 99)), throughput=1000/float(np.mean(duration)))


def execute(freeze, config, heldout, profiles, staged, models, resources, code_hashes, resume=False):
    checked = read(PRECHECK)
    require(checked["files"] == {f: sha(ROOT / f) for f in (FREEZE, D07, TEST_LOG)}, "Preflight inputs changed")
    if resume:
        receipt = resume_same_receipt(checked, code_hashes)
    else:
        require(checked["code_hashes"] == code_hashes and not PARTS.exists(), "Unexpected evaluator or run output")
        receipt = claim(dict(signed_freeze=binding(FREEZE), d07=binding(D07), split=binding(SPLIT),
                    preflight=binding(PRECHECK), label_source={"path":LABELS,"sha256":EVALUATION_SOURCES[LABELS]},
                    guard_sha256=freeze["guard_sha256"], evaluation_revision="p37-r1", code_hashes=code_hashes,
                    evaluator_sha256=code_hashes["scripts/evaluate_p37.py"]))
    start = perf_counter()
    try:
        PARTS.mkdir(parents=True, exist_ok=resume)
        references = load_reference(heldout, config["band_cutoff_percent"])
        require(sum(map(len, references.values())) == config["expected_rows"], "FULL_ELIGIBLE denominator changed")
        outcome, blocks = {}, []
        for cell in heldout:
            meta = staged[cell]["trace"]
            path = ROOT / STAGING / meta["path"]
            require(sha(path) == meta["sha256"], f"Held-out staging hash mismatch: {cell}")
            computed, elapsed = features_for_cell(cell, path, references[cell])
            rows, matrix, inference = evaluate_cell(cell, computed, references[cell], profiles[cell], freeze, models, config)
            checkpoint = PARTS / f"{cell}.parquet"
            pq.write_table(pa.Table.from_pylist(rows, schema=PREDICTIONS), checkpoint.with_suffix(".tmp"), compression="zstd")
            checkpoint.with_suffix(".tmp").replace(checkpoint)
            blocks.append(matrix)
            outcome[cell] = {**binding(checkpoint.relative_to(ROOT)), "staging": binding(path.relative_to(ROOT)),
                             "eligible": len(rows), "pre_eligibility_exclusions": staged[cell]["cycle_count"] - len(rows),
                             "feature_elapsed_s":elapsed, "all_model_guard_elapsed_s":inference}
            print(f"Preserved held-out predictions {len(outcome)}/{len(heldout)}", flush=True)
        dest = ROOT / OUTPUT
        with pq.ParquetWriter(dest.with_suffix(".tmp"), PREDICTIONS, compression="zstd") as writer:
            for cell in heldout:
                writer.write_table(pq.read_table(ROOT / outcome[cell]["path"]))
        dest.with_suffix(".tmp").replace(dest)
        resources["rf_predict_sigma_guard"] = benchmark(models["rf"], np.concatenate(blocks), freeze["policy"])
        resources["memory_after_evaluation"] = process_memory()
        resources["elapsed_s"] = perf_counter()-start
        for path,digest in code_hashes.items():
            require(sha(ROOT / path) == digest, f"Evaluator changed after opening: {path}")
        verify_candidate(read(CANDIDATE), (ROOT / LEDGER).read_bytes(), freeze["ledger_snapshot_prefix_bytes"])
        dump_json(ROOT / RUN, dict(status="PREDICTIONS_PRESERVED", completed_at=now(), receipt=binding(RECEIPT),
            prediction_output=binding(OUTPUT), per_cell=outcome, runtime=resources, exposure_count=1,
            eligible_rows=sum(m["eligible"] for m in outcome.values()), signed_guard_sha256=freeze["guard_sha256"],
            code_hashes=code_hashes, recovery=binding(RECOVERY) if resume else None))
        print(f"Single held-out evaluation preserved {config['expected_rows']} predictions", flush=True)
    except Exception as error:
        append_ledger(f"### P3.7 — Lần chạy gặp lỗi\n\n{now()} · `{type(error).__name__}`. Biên nhận vẫn đã sử dụng.")
        state = read(STATUS)
        milestone = next(m for m in state["milestones"] if m["milestone_id"] == "P3.7")
        milestone.update(status="BLOCKED", release_status="OPENED_RUN_INTERRUPTED")
        refresh_ledger_bindings(state)
        dump_json(ROOT / STATUS, state)
        raise


def resume_same_receipt(checked, code_hashes):
    receipt = read(RECEIPT)
    state = read(STATUS)
    p37 = next(m for m in state["milestones"] if m["milestone_id"] == "P3.7")
    ledger = (ROOT / LEDGER).read_text(encoding="utf-8")
    require(p37["release_status"] == "OPENED_RUN_INTERRUPTED" and receipt["exposure_count"] == 1
            and p37["exposure_receipt"] == binding(RECEIPT) and "ArrowInvalid" in ledger
            and PARTS.is_dir() and not any(PARTS.iterdir())
            and not any((ROOT / p).exists() for p in (OUTPUT, RUN, RECOVERY)), "Same-session recovery gate failed")
    require(receipt["code_hashes"] == checked["code_hashes"], "Original evaluator mismatch")
    for key in ("signed_freeze", "d07", "split", "preflight"):
        require(receipt[key] == binding(receipt[key]["path"]), f"Original receipt binding changed: {key}")
    originals = {}
    for path, expected in receipt["code_hashes"].items():
        if expected != code_hashes[path]:
            require(path in ("scripts/evaluate_p37.py", "scripts/report_p37.py"), "Unexpected changed executable")
            snapshot = binding(f"manifests/p37_initial_{Path(path).name}.txt")
            require(snapshot["sha256"] == expected, "Initial evaluator evidence changed")
            originals[path] = snapshot
    require(len(originals) == 2, "Missing original evaluator/reporter snapshot")
    recovery = dict(resumed_at=now(), receipt=binding(RECEIPT), exposure_count=1,
                    previous_error="ArrowInvalid: label_status belongs to pairing trace; released labels use release_status",
                    failure_point="Arrow scanner field projection validation before materializing any rows",
                    previous_heldout_label_rows_materialized=0, previous_heldout_signal_files_accessed=0,
                    previous_prediction_parts=0, archived_code=originals, code_hashes=code_hashes)
    with (ROOT / RECOVERY).open("x", encoding="utf-8") as stream:
        json.dump(recovery, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    append_ledger(f"""### P3.7 — Tiếp tục cùng biên nhận sau lỗi schema

{recovery['resumed_at']} · Lượt đầu dừng khi Arrow kiểm tra danh sách cột. Parquet nhãn v1 có
release_status. label_status thuộc trace ghép cặp. Không có dòng nhãn được giải mã, không có
tệp tín hiệu held-out được mở, không có dự đoán được ghi trước lỗi. Tiếp tục theo cùng biên nhận
sau khi sửa bộ đọc schema, giữ nguyên SHA-256 của model, guard, data policy và D07.
[Biên bản lỗi và mã băm bộ đọc](../{RECOVERY})
""")
    p37.update(status="IN_PROGRESS", release_status="EVALUATION_OPENED", same_receipt_recovery=binding(RECOVERY))
    refresh_ledger_bindings(state)
    dump_json(ROOT / STATUS, state)
    return receipt


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mode", choices=["rehearse", "one-time-heldout", "resume-schema-failure"])
    args = cli.parse_args()
    with threadpool_limits(limits=1, user_api="blas"):
        resume = args.mode == "resume-schema-failure"
        freeze, config, heldout, dev, profile, staged, models, resources, code_hashes = preflight(resume=resume)
        if args.mode == "rehearse":
            rehearsal(freeze, config, dev, profile, models)
        else:
            execute(freeze, config, heldout, profile, staged, models, resources, code_hashes, resume=resume)


if __name__ == "__main__":
    main()
