"""Reproduce the conditional P2.5 development grid and paired stress replays."""
import argparse
import csv
import gzip
import hashlib
import itertools
import json
import math
import os
import platform
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np

from src.cc import coulomb_count, score_populations
from src.development_data import P22_SHA256, RUN_IDS, load_development_runs
from src.ekf import EKF, FixedRC, load_frozen_calibration, load_research_ecm

ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / "configs/p25_development_search.json"


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def candidate_grid(plan):
    combinations = itertools.product(plan["initial_z_sd_fraction"], plan["process_variance_per_second_pairs"],
                                     plan["measurement_voltage_sd_v"])
    for index, (z_sd, q_density, v_sd) in enumerate(combinations):
        yield dict(id=f"grid-{index+1:02d}", p0_diag=[z_sd**2, plan["initial_vrc_sd_v"]**2],
                   q_per_s_diag=q_density, r_v2=v_sd**2)


def inputs_for_scenario(run, scenario, *, seed):
    prior = run.prior_soc + scenario.get("prior_offset_pp", 0)/100
    if not 0 <= prior <= 1:
        return None
    current = np.asarray(run.current_a, dtype=float) + scenario.get("current_bias_a", 0.)
    voltage = np.array(run.voltage_v, dtype=float, copy=True)
    if "current_noise_sd_a" in scenario or "voltage_noise_sd_v" in scenario:
        rng = np.random.Generator(np.random.PCG64(seed))
        repeated = np.isin(run.clock_event, ["DUPLICATE_OBSERVATION", "ZERO_DT_STEP_TRANSITION_SAME_SIGNAL"])
        group = np.cumsum(~repeated)-1
        current += rng.normal(0., scenario.get("current_noise_sd_a", 0.), group[-1]+1)[group]
        voltage += rng.normal(0., scenario.get("voltage_noise_sd_v", 0.), group[-1]+1)[group]
    return prior, current, voltage


def convergence_seconds(time, error_pp, max_gap_s, abs_error_pp=5., continuous_s=60.):
    """Return elapsed time at the start of the first subsequently confirmed span."""
    start = previous = None
    for t, error in zip(time, error_pp):
        if previous is not None and t-previous > max_gap_s:
            start = None
        if not math.isfinite(error) or abs(error) > abs_error_pp:
            start = None
        else:
            if start is None:
                start = t
            if t-start >= continuous_s:
                return float(start-time[0])
        previous = t
    return None


def replay(run, prior, current, voltage, candidate, model, ocv, max_gap_s, approval_record_id,
           current_range_a, *, vrc0=0., first_voltage_used_for_prior=False):
    if model.capacity_ah != run.capacity_ah:
        raise ValueError("CC and EKF capacity must match the frozen reference policy")
    if any(len(a) != len(run.row) for a in (current, voltage, run.clock_event, run.time_s)):
        raise ValueError("Expected one measurement and clock event per frozen source row")
    ekf = EKF(model, ocv, p0_diag=candidate["p0_diag"], q_per_s_diag=candidate["q_per_s_diag"],
              r_v2=candidate["r_v2"], max_gap_active_s=max_gap_s, current_range_a=current_range_a,
              model_version="fixed_1RC_v1_NEEDS_REVIEW_NOT_RELEASED", approval_record_id=approval_record_id)
    ekf.reset(prior, vrc0, run_id=run.run_id, first_voltage_used_for_prior=first_voltage_used_for_prior)
    rows = [ekf.update(float(t),float(i),float(v),clock_event=event)
            for t,i,v,event in zip(run.time_s,current,voltage,run.clock_event)]
    estimates = np.array([r["soc_pct"]/100 if r["soc_pct"] is not None else np.nan for r in rows])
    cc = coulomb_count(run.time_s,current,model.capacity_ah,prior)
    return estimates, cc, rows


def selection_key(validation_metrics, index):
    full = [row["FULL_DYNAMIC"] for row in validation_metrics]
    missing = max(1-r["numerator"]/r["denominator"] for r in full)
    worst = max(r["MAX_abs_pp"] if r["MAX_abs_pp"] is not None else math.inf for r in full)
    rmse = np.mean([r["RMSE_pp"] if r["RMSE_pp"] is not None else math.inf for r in full])
    return missing, worst, float(rmse), index


def diagnostics(run, reference, estimated, cc, rows, voltage, max_gap, elapsed):
    errors_pp = 100*(estimated-reference)
    flags = np.isfinite(voltage) & (voltage < 3.2976)
    effective = ~np.isin(run.clock_event, ["DUPLICATE_OBSERVATION","ZERO_DT_STEP_TRANSITION_SAME_SIGNAL"])
    residuals = np.array([r["innovation_v"] for r in rows if r["innovation_v"] is not None])
    valid = np.isfinite(estimated)
    worst_index = int(np.nanargmax(np.abs(errors_pp))) if valid.any() else None
    return dict(EKF=score_populations(estimated,reference,voltage), CC=score_populations(cc,reference,voltage),
                effective_event_count=int(effective.sum()), covered_effective_events=int((effective & valid).sum()),
                merged_repeated_events=int((~effective).sum()), voltage_corrections=sum(r["corrected"] for r in rows),
                status_counts=dict(Counter(r["status"] for r in rows)), projection_count=rows[-1]["boundary_count"],
                invalid_count=sum(r["status"] != "VALID" for r in rows),
                EKF_convergence_s=convergence_seconds(run.time_s,errors_pp,max_gap),
                CC_convergence_s=convergence_seconds(run.time_s,100*(cc-reference),max_gap),
                first_warning_timestamp_s=float(run.time_s[np.flatnonzero(flags)[0]]) if flags.any() else None,
                voltage_innovation_count=len(residuals),
                voltage_innovation_mean_v=float(residuals.mean()) if len(residuals) else None,
                voltage_innovation_rmse_v=float(np.sqrt(np.mean(residuals**2))) if len(residuals) else None,
                voltage_innovation_max_abs_v=float(np.max(np.abs(residuals))) if len(residuals) else None,
                worst_ekf_source_row=int(run.row[worst_index]) if worst_index is not None else None,
                worst_ekf_timestamp_s=float(run.time_s[worst_index]) if worst_index is not None else None,
                worst_ekf_warning=bool(flags[worst_index]) if worst_index is not None else None,
                raw_rows=len(rows), reset_after_initialization_count=0, paired_replay_wall_seconds=elapsed)


def export_trajectory(path, run, reference, current, measured, estimates, cc, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        # Immutable original signals allow inspection of noise/bias versus nominal.
        writer.writerow(["source_row_0based","clock_event","raw_current_a","raw_voltage_v","runtime_current_a",
                         "runtime_voltage_v","soc_ref_fraction_evaluation_only","soc_cc_fraction","soc_ekf_fraction",
                         "error_cc_pp","error_ekf_pp",*rows[0].keys()])
        for j, detail in enumerate(rows):
            z = float(estimates[j]) if np.isfinite(estimates[j]) else None
            writer.writerow([run.row[j],run.clock_event[j],run.current_a[j],run.voltage_v[j],current[j],
                             measured[j],reference[j],cc[j],z,100*(cc[j]-reference[j]),
                             100*(z-reference[j]) if z is not None else None,*detail.values()])


def decode_candidate(doc, capacity):
    p, units = doc["parameters"], doc["units"]
    if (doc.get("schema_version") != "p2.3.1" or doc.get("model") != "fixed_1RC"
            or any(units.get(k) != u for k,u in (("R0_ohm","ohm"),("R1_ohm","ohm"),("C1_farad","F"),
                                                ("tau_s","s"),("capacity_model_ah","Ah"),("soc","fraction"),
                                                ("voltage","V")))):
        raise ValueError("Unsupported ECM schema/model/units")
    model = FixedRC(p["R0_ohm"],p["R1_ohm"],p["C1_farad"],capacity)
    if (p.get("capacity_model_ah", doc.get("capacity_model_ah")) != capacity or
            not math.isclose(p["tau_s"],model.r1_ohm*model.c1_f,rel_tol=1e-9)):
        raise ValueError("ECM capacity or time constant differs from the frozen artifacts")
    return model


def run_development(p22_zip):
    from src.governance import require_conditional_approval

    require_conditional_approval(ROOT,"P2.5")
    p24 = read_json(ROOT/"results/p24/metrics.json")
    if (p24.get("gate") != "PASS" or p24.get("p22_delivery_sha256") != P22_SHA256
            or tuple(p24.get("runs", {})) != RUN_IDS or p24.get("test_exposed") is not False):
        raise PermissionError("Verified complete P2.4 gate is required before model replay")
    approval = read_json(ROOT/"approvals/conditional_approval_record.json")
    policy = read_json(ROOT/"configs/g10_conditional_run_policy.yaml")
    dest = ROOT/"results/p25"
    dest.mkdir(parents=True,exist_ok=True)
    for profile in ("DST","FUDS"):
        doc = load_research_ecm(ROOT/"artifacts/ecm_params.json", approval=approval, policy=policy, profile=profile,
                                audit_log=dest/"research_loader.jsonl", research_opt_in=True)
    ocv, capacity = load_frozen_calibration(ROOT/"artifacts/ocv_model.json", ROOT/"artifacts/capacity_metadata.json")
    model = decode_candidate(doc,capacity)
    plan = read_json(PLAN_PATH)
    candidates = list(candidate_grid(plan))
    registration_path = dest/"development_registration.json"
    registration = dict(plan_sha256=sha(PLAN_PATH), plan=plan, development_run_ids=list(RUN_IDS),
                        candidate_grid=candidates, candidate_ecm_sha256=approval["ecm_sha256"],
                        driver_sha256=sha(__file__),runtime_sha256=sha(ROOT/"src/ekf.py"),
                        p24_metrics_sha256=sha(ROOT/"results/p24/metrics.json"),
                        model_current_domain="Union of the four already documented development observed ranges",
                        test_trajectory_access=False)
    if registration_path.exists():
        previous = read_json(registration_path)
        previous.pop("registered_utc")
        if previous != registration:
            raise ValueError("Development registration has changed; preserve this experiment before starting another")
    else:
        write_json(registration_path,{**registration,"registered_utc":datetime.now(timezone.utc).isoformat()})
    accesses = []
    runs = list(load_development_runs(p22_zip,audit=accesses.append))
    if tuple(run.run_id for run,_ in runs) != RUN_IDS:
        raise ValueError("Development run IDs differ from the frozen split")
    intervals = np.concatenate([np.diff(run.time_s) for run,_ in runs if run.role=="identification"])
    intervals = intervals[intervals>0]
    max_gap = float(3*np.percentile(intervals,99.5))
    current_bounds = current_domain(doc)
    priors = doc["initialization"]
    for run,_ in runs:
        prior = priors[run.run_id]
        if (prior["v_rc0_v"] != 0. or prior["status"] != "CONDITIONALLY_RELAXED"
                or not math.isclose(prior["prior_soc_fraction"],run.prior_soc,abs_tol=1e-10,rel_tol=0)):
            raise ValueError("ECM preconditioning prior and development provenance disagree")
    selection = []
    keys = []
    with tempfile.TemporaryDirectory(dir=dest.parent) as temporary:
        stage = Path(temporary)
        for index,candidate in enumerate(candidates):
            metrics = {}
            for run,ref in runs:
                z,_,_ = replay(run,run.prior_soc,run.current_a,run.voltage_v,candidate,model,ocv,max_gap,
                               approval["approval_record_id"],current_bounds)
                metrics[run.run_id] = score_populations(z,ref,run.voltage_v)
            key = selection_key([metrics[run.run_id] for run,_ in runs if run.role=="validation"], index)
            keys.append(key)
            selection.append(dict(candidate=candidate, selection_tuple=[v if math.isfinite(v) else None for v in key],
                                  nominal_development_metrics=metrics))
        winner = min(range(len(candidates)),key=keys.__getitem__)
        if not math.isfinite(keys[winner][1]):
            raise ValueError("No candidate supplied a scorable validation trajectory")
        selected = candidates[winner]
        config = dict(selected=selected, max_gap_active_s=max_gap, gap_source="positive DST dynamic intervals only",
                      dst_positive_dt_s={str(k):float(np.percentile(intervals,k)) for k in (0,50,95,99,99.5,100)},
                      current_range_a=current_bounds, candidate_ecm_sha256=approval["ecm_sha256"],
                      approval_record_id=approval["approval_record_id"], context="P2.5 development selection",
                      scientific_release=False, ER4="NOT_EVALUATED", plan_sha256=sha(PLAN_PATH),
                      runtime_sha256=sha(ROOT/"src/ekf.py"), driver_sha256=sha(__file__),
                      warning_threshold_v=3.2976, seed=plan["seed"], estimated_state=["z_fraction","v_rc_v"])
        write_json(stage/"ekf_config.json",config)
        write_json(stage/"candidate_selection.json",selection)
        reports = {}
        for j,(run,ref) in enumerate(runs):
            per_run = {}
            for name,scenario in plan["scenarios"].items():
                seed = plan["seed"]+j
                inputs = inputs_for_scenario(run,scenario,seed=seed)
                if inputs is None:
                    per_run[name] = dict(status="INAPPLICABLE", reason="Requested prior would be outside [0,1]")
                    continue
                prior,current,voltage = inputs
                tic = perf_counter()
                z,cc,rows = replay(run,prior,current,voltage,selected,model,ocv,max_gap,
                                   approval["approval_record_id"],current_bounds)
                report = diagnostics(run,ref,z,cc,rows,voltage,max_gap,perf_counter()-tic)
                path = stage/"trajectories"/name/(run.run_id+".csv.gz")
                export_trajectory(path,run,ref,current,voltage,z,cc,rows)
                if name == "nominal" and report["CC"]["FULL_DYNAMIC"] != p24["runs"][run.run_id]["FULL_DYNAMIC"]:
                    raise ValueError("Nominal paired CC differs from P2.4")
                per_run[name] = dict(status="EXECUTED", role=run.role, actual_prior_soc_fraction=prior, seed=seed,
                                     trajectory=str(path.relative_to(stage)).replace(os.sep,"/"), trajectory_sha256=sha(path),
                                     **report)
            reports[run.run_id] = per_run
        report = dict(milestone="P2.5", gate="PASS", scientific_release=False, ER4="NOT_EVALUATED",
                      test_exposed=False, selected=selected, plan_sha256=sha(PLAN_PATH),
                      p24_metrics_sha256=sha(ROOT/"results/p24/metrics.json"), python=platform.python_version(),
                      numpy=np.__version__, runs=reports)
        write_json(stage/"metrics.json",report)
        write_json(stage/"source_access.json",dict(p22_delivery_sha256=P22_SHA256,members_read=accesses,
                                                  heldout_trajectory_reads=0))
        (stage/"report.md").write_text(summary_text(report),encoding="utf-8")
        for source in sorted(stage.rglob("*")):
            if source.is_file() and source.name != "metrics.json":
                output = dest/source.relative_to(stage)
                output.parent.mkdir(parents=True,exist_ok=True)
                os.replace(source,output)
        os.replace(stage/"metrics.json",dest/"metrics.json")
    return report


def current_domain(doc):
    domain = doc["observed_domain"]
    if domain["nominal_archive_temperature_c"] != 25:
        raise ValueError("Expected nominal 25 C experiment")
    if set(domain["per_run"]) != set(RUN_IDS):
        raise ValueError("Expected four documented development current ranges")
    pairs = [entry["current_a"] for entry in domain["per_run"].values()]
    if any(len(p) != 2 or not all(math.isfinite(x) for x in p) or p[0] >= p[1] for p in pairs):
        raise ValueError("Invalid observed current domain")
    return min(p[0] for p in pairs), max(p[1] for p in pairs)


def summary_text(report):
    lines = ["# P2.5 · EKF trên các run phát triển", "",
             "SoC được đối chiếu với reference tái dựng từ bộ đếm Arbin. Các phép đo đến cutoff nằm trong mẫu số toàn cửa sổ.",
             "G10 vẫn NEEDS_REVIEW. ECM chưa được phát hành khoa học. ER4 chưa đánh giá.", "",
             "| Run | Phạm vi | Có SoC / tổng | MAE (pp) | RMSE (pp) | P95 (pp) | MAX (pp) |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for run, scenarios in report["runs"].items():
        for pop in ("FULL_DYNAMIC","NON_FLAGGED","FLAGGED"):
            m = scenarios["nominal"]["EKF"][pop]
            fields = ["N/A" if m[k] is None else f"{m[k]:.4f}" for k in ("MAE_pp","RMSE_pp","P95_abs_pp","MAX_abs_pp")]
            lines.append("| "+" | ".join([run,pop,f"{m['numerator']}/{m['denominator']}",*fields])+" |")
    lines.extend(["","metrics.json lưu số liệu EKF/CC theo kịch bản, độ phủ, innovation, hội tụ, cờ điện áp và lần chạm biên.",
                  "candidate_selection.json lưu đủ ứng viên và tiêu chí chọn trên FUDS. Các tệp trajectory giữ từng dòng nguồn."])
    return "\n".join(lines)+"\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p22-zip",required=True,type=Path)
    args = parser.parse_args()
    result = run_development(args.p22_zip)
    print(result["milestone"],result["gate"],result["selected"]["id"])
