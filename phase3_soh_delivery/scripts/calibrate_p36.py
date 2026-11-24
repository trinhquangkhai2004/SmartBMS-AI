"""Calibrate feature/sigma and jump guards on development OOF only."""
import itertools
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from scripts.p36_inputs import PRIMARY, ROOT, development, dump_json, require, sha
from scripts.train_p36 import ARTIFACTS, MANIFESTS, REPORTS, RF_CONFIG, cell_scores, macro, read_config
from src.soh.evaluation_guard import EvaluationGuard


OOD_REPORT = f"{REPORTS}/P3_6_OOD_CALIBRATION.md"
OOD_POLICY = f"{ARTIFACTS}/ood_policy.json"
CALIBRATION = f"{MANIFESTS}/p3_6_guard_calibration.json"


def coverage_metrics(accepted, y, predicted, cells):
    scores = cell_scores(y[accepted], predicted[accepted], cells[accepted])
    return dict(valid_rows=int(accepted.sum()), population=len(accepted), coverage=float(accepted.mean()),
                macro_mae_pp=macro(scores)["macro_mae_pp"] if scores else None,
                macro_rmse_pp=macro(scores)["macro_rmse_pp"] if scores else None,
                cells_with_valid=len(scores))


def replay(xs, row_prior, order, config, runtime_parity=False):
    guard = EvaluationGuard(config)
    valid = np.zeros(len(xs), dtype=bool)
    count = dict(OUT_OF_DOMAIN=0, MODEL_UNCERTAIN=0, SOH_JUMP_ANOMALY=0, VALID=0)
    resync = 0
    reference_jumps = 0
    last_refs = {}
    for i in order:
        cell, cycle, features, raw, sigma, y = xs[i]
        result = (guard.evaluate(cell, "p36-r1-oof", cycle, features, raw, sigma) if runtime_parity
                  else guard.advance(cell, "p36-r1-oof", cycle, raw, row_prior[i]))
        status = result["status"]
        count[status] += 1
        if status == "VALID":
            valid[i] = True
            if result["reason"] == "SOH_BASELINE_RESYNCED":
                resync += 1
                reference_jumps += abs(y - last_refs[cell]) > config["reference_diagnostic_pp"]
            last_refs[cell] = y
    return valid, count, resync, int(reference_jumps)


def md(text):
    return "\n".join(text) + "\n"


def write_report(cal):
    choice = cal["selected_policy"]
    metric = cal["all_eligible"]
    guarded = cal["guarded_metrics"]
    lines = [
        "# P3.6 — Hiệu chỉnh OOD và jump/resync",
        "",
        "Tập hiệu chỉnh gồm 106.733 dự đoán OOF từ 57 cell development. Mỗi cặp biên dùng các giá trị hữu hạn "
        "của cell train trong đúng fold. CDF sắp tăng ổn định, mỗi cell có tổng trọng số 1 cho từng HI. "
        "P01/P99 là giá trị đầu tiên mà CDF đạt ngưỡng. Tệp hiệu chỉnh chứa cả biên theo từng fold và biên "
        "tính lại ở lần refit toàn dev. Sigma độ lệch chuẩn quần thể giữa các cây là chỉ báo bất đồng.",
        "",
        "| Số HI vi phạm | Phân vị sigma | Ngưỡng sigma (pp) | OOD | Uncertain sau OOD | VALID trước jump | Macro-MAE VALID (pp) |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in cal["ood_candidates"]:
        lines.append(f"| {row['min_feature_violations']} | {row['sigma_quantile']:.2f} | "
                     f"{row['sigma_threshold_pp']:.6f} | {row['ood_rows']} | {row['uncertain_rows']} | "
                     f"{row['valid_rows']} | {row['macro_mae_pp']:.6f} |")
    lines += [
        "",
        f"Ứng viên D12 dùng **{choice['min_feature_violations']} HI vi phạm** và sigma P{100*choice['sigma_quantile']:.0f} "
        f"(**{choice['sigma_threshold_pp']:.6f} pp**). OUT_OF_DOMAIN có ưu tiên trước MODEL_UNCERTAIN. "
        "Loại phiên thiếu HI, thiếu history hoặc stale theo mã trạng thái tương ứng. Các phiên bị chặn xóa "
        "chuỗi xác nhận đang chờ và giữ mốc hợp lệ cuối.",
        "",
        f"Ứng viên D13 dùng ngưỡng jump **{choice['delta_max_pp']} pp**, cần **{choice['resync_confirm_k']} phiên** "
        f"lệch tối đa **{choice['resync_stability_pp']} pp** giữa các dự đoán xác nhận, với khoảng cách tối đa "
        f"**{choice['max_confirmation_gap_cycles']} cycle** giữa hai xác nhận. Mốc cập nhật theo phiên mới nhất. "
        "Dữ liệu staging đặt lại đồng hồ theo cycle nên khoảng cách xác nhận tính theo thứ tự cycle. "
        "Stale từ hệ thống thời gian thực là đầu vào của guard.",
        "",
        "| Tập tính điểm | Số hàng | Số cell có điểm | Macro-MAE (pp) | Macro-RMSE (pp) |",
        "|---|---:|---:|---:|---:|",
        f"| Toàn bộ đủ điều kiện | {metric['valid_rows']} | {metric['cells_with_valid']} | {metric['macro_mae_pp']:.6f} | {metric['macro_rmse_pp']:.6f} |",
        f"| VALID sau tất cả guard | {guarded['valid_rows']} | {guarded['cells_with_valid']} | {guarded['macro_mae_pp']:.6f} | {guarded['macro_rmse_pp']:.6f} |",
        "",
        f"Độ phủ VALID {guarded['coverage']:.4%}. Số hàng theo trạng thái {cal['guarded_counts']}. "
        f"Resync {cal['resync_events']} lần. Trong các lần đó, {cal['reference_change_over_diagnostic_pp']} lần "
        "nhãn tham chiếu đổi quá ngưỡng chẩn đoán so với phiên hợp lệ trước. Con số này dùng mô tả đối chiếu "
        "trên OOF, vì dung lượng tham chiếu chỉ có sau xả.",
        "",
        "So sánh độ phân tán cây giữa OOF và lần refit toàn dev (P50/P90/P95/P99, pp).",
        "",
        "| Nguồn | P50 | P90 | P95 | P99 |",
        "|---|---:|---:|---:|---:|",
        *[f"| {name} | " + " | ".join(f"{quantiles[k]:.6f}" for k in ("0.5", "0.9", "0.95", "0.99")) + " |"
          for name, quantiles in [("OOF", cal["sigma_oof_quantiles"]),
                                  ("Refit toàn dev", cal["sigma_full_dev_quantiles"])]],
        "",
        "Bảng so sánh jump/resync có đủ tổ hợp cấu hình. Quy tắc chọn thử dùng các giới hạn tỷ lệ từ lưới đã đăng ký; "
        "ưu tiên cấu hình gần (5 pp, K=2, 2 pp, 2 cycle) nhất và dùng thứ tự quyết định cố định khi bằng nhau.",
        "",
        "| Jump (pp) | K | Ổn định (pp) | Gap (cycle) | Jump bị chặn | Resync | VALID | Macro-MAE VALID (pp) | Đạt giới hạn thử |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in cal["jump_candidates"]:
        lines.append(f"| {row['delta_max_pp']} | {row['resync_confirm_k']} | {row['resync_stability_pp']} | "
                     f"{row['max_confirmation_gap_cycles']} | {row['jump_rejections']} | {row['resync_events']} | "
                     f"{row['valid_rows']} | {row['macro_mae_pp']:.6f} | {row['within_candidate_limits']} |")
    lines += ["", "Cấu hình chờ reviewer D12/D13. Held-out P3.7 vẫn UNOPENED.",
              "", "[Số liệu và biên đầy đủ](../manifests/p3_6_guard_calibration.json) · [Chính sách ứng viên](../artifacts/soh/ood_policy.json)"]
    (ROOT / OOD_REPORT).write_text(md(lines), encoding="utf-8")


def main():
    dev = development()
    training = json.loads((ROOT / MANIFESTS / "p3_6_training.json").read_bytes())
    oof = ROOT / REPORTS / "P3_6_OOF_DEVELOPMENT.parquet"
    require(training["status"] == "REFIT_VERIFIED" and sha(oof) == training["development_oof_sha256"], "Invalid OOF binding")
    table = pq.read_table(oof)
    for name, array in [("cell_id", dev.cells), ("cycle_id", dev.cycles), ("validation_fold", dev.folds),
                        ("soh_ref_percent", dev.y)]:
        require(np.array_equal(table[name].to_pylist(), array), f"OOF key/target mismatch: {name}")
    predicted = table["rf_weighted"].to_numpy()
    sigma = table["rf_sigma_trees_pp"].to_numpy()
    require(np.isfinite(predicted).all() and np.isfinite(sigma).all(), "Nonfinite OOF predictions or sigma")
    c = read_config(RF_CONFIG)["ood"]
    bounds_by_fold = training["weighted_bounds_by_fold"]
    violation_counts = np.zeros(len(dev.y), dtype=int)
    xs = [(str(cell), int(cycle), row, float(raw), float(s), float(y))
          for cell, cycle, row, raw, s, y in zip(dev.cells, dev.cycles, dev.x, predicted, sigma, dev.y)]
    for fold, bounds in bounds_by_fold.items():
        idx = dev.folds == int(fold)
        intervals = np.array([bounds[name]["weighted"] for name in PRIMARY])
        x = dev.x[idx]
        violation_counts[idx] = ((x < intervals[:, 0]) | (x > intervals[:, 1])).sum(axis=1)

    ood_candidates = []
    for min_violations, sigma_q in itertools.product(c["min_violations_candidates"], c["sigma_quantile_candidates"]):
        threshold = float(np.quantile(sigma, sigma_q))
        out = violation_counts >= min_violations
        uncertain = (~out) & (sigma > threshold)
        metrics = coverage_metrics(~(out | uncertain), dev.y, predicted, dev.cells)
        ood_candidates.append(dict(min_feature_violations=min_violations, sigma_quantile=sigma_q,
                                   sigma_threshold_pp=threshold, ood_rows=int(out.sum()),
                                   uncertain_rows=int(uncertain.sum()), **metrics))
    feasible = [row for row in ood_candidates if row["ood_rows"]/len(sigma) <= c["max_feature_flag_fraction"]
                and row["uncertain_rows"]/len(sigma) <= c["max_sigma_flag_fraction"]]
    require(feasible, "No OOD candidate within development calibration limits")
    ood = min(feasible, key=lambda row: (row["min_feature_violations"], abs(row["sigma_quantile"]-.95),
                                         row["sigma_quantile"]))
    base = {k: ood[k] for k in ("min_feature_violations", "sigma_quantile", "sigma_threshold_pp")}
    base.update(primary_features=list(PRIMARY), feature_bounds=training["weighted_bounds_full"],
                reference_diagnostic_pp=c["jump_reference_change_diagnostic_pp"])
    prior = [("OUT_OF_DOMAIN" if n >= ood["min_feature_violations"] else
              "MODEL_UNCERTAIN" if s > ood["sigma_threshold_pp"] else None)
             for n, s in zip(violation_counts, sigma)]
    order = np.lexsort((dev.cycles, dev.cells))
    candidates = []
    keys = ("delta_max_pp", "resync_confirm_k", "resync_stability_pp", "max_confirmation_gap_cycles")
    grid = itertools.product(c["jump_threshold_candidates_pp"], c["resync_confirmations_candidates"],
                             c["resync_stability_candidates_pp"], c["gap_candidates_cycles"])
    for values in grid:
        jump = dict(zip(keys, values))
        accepted, counts, resynced, ref_jumps = replay(xs, prior, order, dict(base, **jump))
        metrics = coverage_metrics(accepted, dev.y, predicted, dev.cells)
        jumps = counts["SOH_JUMP_ANOMALY"]
        unblocked = len(prior) - ood["ood_rows"] - ood["uncertain_rows"]
        allowed = jumps/len(prior) <= c["max_jump_rejection_fraction"] and (
            resynced*1000/unblocked <= c["max_resync_events_per_1000_eligible"])
        candidates.append(dict(**jump, jump_rejections=jumps, resync_events=resynced,
                               reference_change_over_diagnostic_pp=ref_jumps, within_candidate_limits=allowed,
                               **metrics))
    eligible = [row for row in candidates if row["within_candidate_limits"]]
    require(eligible, "No jump/resync candidate within development calibration limits")
    def distance(row):
        return (sum(abs(row[k]-start) for k, start in zip(keys, (5,2,2,2))),
                -row["coverage"], tuple(row[k] for k in keys))
    chosen = min(eligible, key=distance)
    chosen_params = {k: chosen[k] for k in keys}
    selected = dict(base, **chosen_params, revision="p36-r1",
                    release_status="CANDIDATE_PENDING_REVIEW",
                    feature_quantile_method="cell_equal_mass_left_inverse_empirical_cdf",
                    tree_sigma="population_sd_rf_tree_predictions_pp",
                    status_priority=["STALE_INPUT", "INSUFFICIENT_HISTORY", "MISSING_FEATURE",
                                     "OUT_OF_DOMAIN", "MODEL_UNCERTAIN", "SOH_JUMP_ANOMALY"],
                    pending_on_nonvalid="clear_keep_previous_baseline",
                    confirmation_gap_unit="source_cycle_id_difference",
                    model_version_change="discard_prior_model_state")
    # Verify vectorized fold diagnostics against the runtime's own per-row status logic.
    valid_replay = np.zeros(len(xs), dtype=bool)
    totals = dict(OUT_OF_DOMAIN=0, MODEL_UNCERTAIN=0, SOH_JUMP_ANOMALY=0, VALID=0)
    total_resync = 0
    for fold, bounds in bounds_by_fold.items():
        folded_order = order[dev.folds[order] == int(fold)]
        policy = dict(selected, feature_bounds=bounds)
        valid, counts, resynced, _ = replay(xs, prior, folded_order, policy, runtime_parity=True)
        valid_replay |= valid
        total_resync += resynced
        for status, count in counts.items():
            totals[status] += count
    selected_mask, expected_counts, expected_resync, ref_jumps = replay(xs, prior, order, selected)
    require(np.array_equal(valid_replay, selected_mask) and totals == expected_counts
            and total_resync == expected_resync, "Runtime guard and OOF calibration disagree")
    fits = dict(selected_policy=selected, ood_candidates=ood_candidates, jump_candidates=candidates,
                all_eligible=coverage_metrics(np.ones(len(xs), dtype=bool), dev.y, predicted, dev.cells),
                guarded_metrics=coverage_metrics(valid_replay, dev.y, predicted, dev.cells),
                guarded_counts=totals, resync_events=total_resync, reference_change_over_diagnostic_pp=ref_jumps,
                calibration_license="development_oof_only", oof_sha256=sha(oof),
                fold_weighted_and_unweighted_bounds=bounds_by_fold,
                full_development_weighted_and_unweighted_bounds=training["weighted_bounds_full"],
                sigma_oof_quantiles=training["sigma_oof_quantiles"],
                sigma_full_dev_quantiles=training["sigma_full_dev_quantiles"],
                verification=dict(rows=len(xs), runtime_parity=True, heldout_value_files_read=0))
    dump_json(ROOT / OOD_POLICY, selected)
    dump_json(ROOT / CALIBRATION, fits)
    write_report(fits)
    print(f"Guard parity on {len(xs)} OOF rows, VALID {fits['guarded_metrics']['coverage']:.4%}, resync {total_resync}")


if __name__ == "__main__":
    main()
