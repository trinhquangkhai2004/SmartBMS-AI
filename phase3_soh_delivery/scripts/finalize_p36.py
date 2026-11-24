"""Write technical freeze evidence for review. Reviewer sign-off is a separate gate."""
import csv
import json
from datetime import datetime

from scripts.calibrate_p36 import CALIBRATION, OOD_POLICY, OOD_REPORT
from scripts.p36_inputs import LEDGER, PRIMARY, ROOT, SPLIT_HASH, dump_json, require, sha
from scripts.train_p36 import ARTIFACTS, MANIFESTS, REPORTS, REQUIREMENTS, RF_CONFIG, XGB_CONFIG


CV_REPORT = f"{REPORTS}/P3_6_CV_VALIDATION.csv"
W_REPORT = f"{REPORTS}/P3_6_WEIGHT_ABLATION.md"
R_REPORT = f"{REPORTS}/P3_6_MODEL_RESOURCE_BUDGET.md"
X_REPORT = f"{REPORTS}/P3_6_XGB_REFIT_AUDIT.md"
MODEL_CARD = f"{ARTIFACTS}/model_card.md"
FREEZE = f"{MANIFESTS}/p3_model_freeze.json"
TEST_LOG = f"{REPORTS}/P3_6_TEST_LOG.txt"
RESOURCE = f"{MANIFESTS}/p3_6_resource_measurement.json"
INPUTS = f"{MANIFESTS}/p3_6_input_readback.json"
TRAINING = f"{MANIFESTS}/p3_6_training.json"
OOF = f"{REPORTS}/P3_6_OOF_DEVELOPMENT.parquet"
PREREG = f"{MANIFESTS}/p3_6_preregistration.json"


def read(path):
    return json.loads((ROOT / path).read_bytes())


def report(path, lines):
    (ROOT / path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_weight_report(train):
    with (ROOT / CV_REPORT).open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    c = train["candidates"]
    weighted = train["rf_selected"]
    def per_cell(key):
        return {r["cell"]: r for r in rows if r["configuration"] == key and r["level"] == "cell"}
    w = per_cell(weighted)
    u = per_cell("rf_unweighted")
    require(w.keys() == u.keys() and len(w) == 57, "RF ablation groups differ")
    lines = ["# P3.6 — So sánh mô hình và ảnh hưởng của trọng số", "",
             "Cùng 57 cell, 106.733 khóa và năm fold. Mỗi chỉ số macro là trung bình sai số từng cell "
             "gộp từ dự đoán ngoài fold. Trọng số fit mỗi hàng là N/(C × n_c). Ridge dùng scaler có trọng số "
             "fit riêng trong từng fold. Cả bốn HI đều hữu hạn cho mọi khóa nên lần chạy này bỏ qua imputer.",
             "",
             "| Cấu hình đã chọn | Macro-MAE (pp) | Macro-RMSE (pp) | Cell có MAE cao nhất | MAE (pp) |",
             "|---|---:|---:|---|---:|"]
    for name in ("train_median", train["ridge_selected"], weighted, "rf_unweighted", train["xgb_selected"],
                 "voltage_window_only", "cc_cv_only", "phase_and_ratio"):
        m = c[name]
        lines.append(f"| {name} | {m['macro_mae_pp']:.6f} | {m['macro_rmse_pp']:.6f} | "
                     f"{m['worst_cell']} | {m['worst_cell_mae_pp']:.6f} |")
    delta = c[weighted]["macro_mae_pp"] - c["rf_unweighted"]["macro_mae_pp"]
    lines += ["", f"Chênh macro-MAE có trọng số trừ không trọng số **{delta:+.6f} pp**. "
              "Hai RF dùng cùng seed, lưới đã chọn, bốn HI và fold; chênh lệch dương nghĩa là RF "
              "có trọng số có sai số lớn hơn.",
              "",
              "Ablation HI dùng cùng hyperparameter RF chính và toàn bộ khóa. Các mode lần lượt chỉ dùng "
              "dung lượng trong cửa sổ, dùng hai pha CC/CV, hoặc dùng hai pha cộng tỷ số. D04 áp dụng "
              "chế độ không đưa commissioning vào đầu vào mô hình. IC và nhiệt độ nằm ngoài v1.",
              "",
              "| Cell | Fold | Số phiên | MAE weighted (pp) | MAE unweighted (pp) | Weighted trừ unweighted (pp) |",
              "|---|---:|---:|---:|---:|---:|"]
    for cell in sorted(w, key=lambda key: tuple(map(int, key.split("-")))):
        a, b = w[cell], u[cell]
        require(a["rows"] == b["rows"] and a["fold"] == b["fold"], f"Weight comparison mismatch {cell}")
        ma, mb = float(a["mae_pp"]), float(b["mae_pp"])
        lines.append(f"| {cell} | {a['fold']} | {a['rows']} | {ma:.6f} | {mb:.6f} | {ma-mb:+.6f} |")
    report(W_REPORT, [*lines, "", "[Điểm từng fold và cell](P3_6_CV_VALIDATION.csv)"])


def write_resource_report(train, measure):
    rf = train["artifacts"]["rf"]
    require(measure["rf_sha256"] == rf["sha256"] and measure["rf_size_bytes"] == rf["bytes"]
            and rf["bytes"] <= train["rf_budget_bytes"], "RF budget evidence mismatch")
    top = train["candidates"][train["rf_top_cv_candidate"]]["macro_mae_pp"]
    chosen = train["candidates"][train["rf_selected"]]["macro_mae_pp"]
    report(R_REPORT, [
        "# P3.6 — Ngân sách và đo tài nguyên RF",
        "",
        f"RF đã đóng gói **{rf['bytes']:,} byte** ({rf['bytes']/1e6:.3f} MB với 1 MB = 1.000.000 byte), "
        f"trong giới hạn {train['rf_budget_bytes']:,} byte. {train['fit_count']['rf_weighted']} lần fit CV "
        "cho tám cấu hình RF weighted, sau đó refit theo thứ tự macro-MAE để kiểm ngân sách.",
        "",
        f"Ứng viên đứng đầu CV {train['rf_top_cv_candidate']}. Bản được chọn {train['rf_selected']}. "
        f"Chênh lệch so với đứng đầu CV {chosen-top:+.6f} pp. Các lần thử đóng gói {train['rf_size_attempts']}.",
        "",
        f"Số đo trên {measure['platform']}, CPU {measure['cpu']}, {measure['logical_processors']} luồng logic, "
        f"RAM {measure['physical_ram_bytes']:,} byte, Python {measure['python']}. RF inference một luồng "
        "trên 200 phiên dev với HI đã tính và sau 5 phiên làm nóng. Cần đo lại trong môi trường F5 thực tế.",
        "",
        "| Phép đo | Kết quả |",
        "|---|---:|",
        f"| Thời gian kiểm SHA-256 và nạp model | {measure['elapsed_load_ms']:.3f} ms |",
        f"| Peak working set trước khi load | {measure['baseline_peak_bytes']:,} byte |",
        f"| Peak working set sau khi load | {measure['post_load_peak_bytes']:,} byte |",
        f"| Peak working set đến hết inference, gồm chuẩn bị mẫu | {measure['post_infer_peak_bytes']:,} byte |",
        f"| RF predict p95 / p99 | {measure['predict']['p95_ms']:.3f} / {measure['predict']['p99_ms']:.3f} ms |",
        f"| RF predict + sigma p95 / p99 | {measure['predict_plus_sigma']['p95_ms']:.3f} / {measure['predict_plus_sigma']['p99_ms']:.3f} ms |",
        "",
        f"So sánh trước và sau reload trên cả 106.733 hàng. Chênh lớn nhất của RF là "
        f"{rf['maximum_reload_absolute_difference_pp']:.3g} pp. Dung sai 1e-10 pp.",
        "",
        "[Số đo chi tiết](../manifests/p3_6_resource_measurement.json)",
    ])


def write_xgb_report(train):
    with (ROOT / CV_REPORT).open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    xgb = train["artifacts"]["xgb"]
    lines = ["# P3.6 — Kiểm tra XGBoost fixed-grid và refit",
             "",
             "Chiến lược `FIXED_CV_N_ESTIMATORS`. Lưới n_estimators 100, 200, 400, 600 đã đăng ký "
             "trước CV. Mỗi fold dùng đúng bốn HI và trọng số theo cell train. Early stopping tắt, "
             "không truyền eval_set trong cả CV lẫn full refit. Chọn theo macro-MAE trên 57 cell OOF.",
             "",
             "| Ứng viên | Số cây | Fold 1 | Fold 2 | Fold 3 | Fold 4 | Fold 5 | Gộp 57 cell (pp) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key, candidate in train["candidates"].items():
        if candidate["family"] != "xgboost":
            continue
        folds = [f"{float(r['mae_pp']):.6f}" for r in rows
                 if r["configuration"] == key and r["level"] == "fold_macro"]
        require(len(folds) == 5, f"Missing XGBoost fold evidence for {key}")
        lines.append(f"| {key} | {candidate['params']['n_estimators']} | {' | '.join(folds)} | "
                     f"{candidate['macro_mae_pp']:.6f} |")
    lines += ["",
              f"Full refit **{train['xgb_n_estimators_final']} cây** trên **{xgb['refit_cells']} cell** "
              f"và **{xgb['refit_rows']:,} hàng**. Chênh lớn nhất sau reload "
              f"{xgb['maximum_reload_absolute_difference_pp']:.3g} pp. "
              f"XGBoost {train['runtime']['libraries']['xgboost']}.",
              "", "[Cấu hình XGBoost](../configs/p3_xgb_training.yaml) · [Kết quả đầy đủ](P3_6_CV_VALIDATION.csv)"]
    report(X_REPORT, lines)


def write_model_card(t, calibration):
    rf = t["candidates"][t["rf_selected"]]
    report(MODEL_CARD, [
        "# F3 SoH — RT-Batt v2, ứng viên p36-r1",
        "",
        "Ước lượng SoH theo dung lượng vận hành tương đối của từng cell LFP ở cuối phiên sạc đủ điều kiện. "
        "Nhãn là dung lượng xả kế tiếp chia trung vị dung lượng xả năm cycle đầu của cùng cell theo D02/D03. "
        "Dữ liệu phát triển RT-Batt v2 thu ở buồng 30 °C. Nhiệt độ theo mẫu vắng mặt.",
        "",
        f"Đầu vào theo thứ tự D04 {', '.join(PRIMARY)}.",
        "",
        f"Model F3 chính RF cell-balanced. 57 cell dev và 106.733 phiên, macro-MAE OOF {rf['macro_mae_pp']:.6f} pp. "
        f"Độ phủ VALID sau guard trên OOF {calibration['guarded_metrics']['coverage']:.4%}. "
        "Dữ liệu held-out ở trạng thái UNOPENED. F3 chỉ xuất sang F5 và phản hồi dung lượng tới F2 tắt trong v1.",
        "",
        "Cần reviewer D06/D08/D12/D13/D15 và điều kiện D07 trước đánh giá held-out. ER5 và kiểm chứng trên pin mục tiêu "
        "chưa đánh giá. Dùng đúng schema/guard đã băm. Chỉ nạp model joblib có nguồn và SHA-256 khớp manifest.",
        "",
        "[Ứng viên model freeze](../../manifests/p3_model_freeze.json) · "
        "[So sánh dev](../../reports/P3_6_WEIGHT_ABLATION.md) · [Hiệu chỉnh guard](../../reports/P3_6_OOD_CALIBRATION.md)",
    ])


def append_ledger(recorded, p34):
    path = ROOT / LEDGER
    current = path.read_bytes()
    require(b"UNOPENED" in current, "Held-out ledger gate changed")
    original_hash = "2e548b41de3cc1fd85d929562050e851826fdae82fa30788293d539aa740bff4"
    if b"## P3.6 p36-r1" not in current:
        require(sha(path) == original_hash, "Ledger changed unexpectedly before P3.6")
        addition = f"""

## P3.6 p36-r1

Ghi nhận lúc {recorded} bởi Codex theo phê duyệt D04 của người dùng. Đọc bảng HI đã khóa, danh sách
split {SPLIT_HASH}
và 57 JSON staging ký SHA-256 của cell development. Trường đọc để dựng nhãn là cell_id, cycle_id
và dq theo cycle. Chạy fit, hiệu chỉnh và đo inference bằng development. Số tệp giá trị của 19 cell held-out
đã đọc trong P3.6 là 0. Đánh giá P3.7 vẫn **UNOPENED**.

[Đối soát đầu vào](../manifests/p3_6_input_readback.json) · [Ứng viên model freeze](../manifests/p3_model_freeze.json)
"""
        path.write_bytes(current + addition.encode("utf-8"))
    for entry in p34["outputs"]:
        if entry["path"] == LEDGER.as_posix():
            entry["sha256"] = sha(path)
            entry["d05_approved_snapshot_sha256"] = original_hash


def link_review_evidence(p30, p36):
    path = "decisions/P3_APPROVAL_REGISTER.md"
    full_path = ROOT / path
    original = full_path.read_bytes()
    entries = {
        "D06": (R_REPORT, "Ngân sách RF và thiết kế CV"),
        "D08": (W_REPORT, "Benchmark và ablation"),
        "D12": (OOD_REPORT, "Hiệu chỉnh ngưỡng OOD"),
        "D13": (OOD_REPORT, "Hiệu chỉnh jump/resync"),
        "D15": (X_REPORT, "XGBoost fixed-grid và refit"),
    }
    text = original.decode("utf-8")
    for decision in entries:
        position = [line for line in text.splitlines() if line.startswith(f"| {decision} |")]
        require(len(position) == 1, f"Cannot identify decision {decision}")
        line = position[0]
        if "EVIDENCE_READY_PENDING_REVIEWER_APPROVAL" in line:
            continue
        col = line.split("|")
        require(col[5].strip() in ("`SPEC_SELECTED`", "`PENDING_DEV_CALIBRATION`"),
                f"Retain prior approval for {decision}")
        evidence, title = entries[decision]
        col[5] = " `EVIDENCE_READY_PENDING_REVIEWER_APPROVAL` "
        col[6] = f" [{title}](../{evidence}) · [Bản ứng viên đã băm](../{FREEZE}). "
        text = text.replace(line, "|".join(col), 1)
    temp = full_path.with_suffix(".p36.tmp")
    temp.write_bytes(text.encode("utf-8"))
    temp.replace(full_path)
    record = dict(path=path, sha256=sha(full_path))
    for entry in p30["outputs"]:
        if entry["path"] == path:
            entry.update(record)
    p36["review_register"] = record


def main():
    training = read(TRAINING)
    calibration = read(CALIBRATION)
    resources = read(RESOURCE)
    input_gate = read(INPUTS)
    require(training["status"] == "REFIT_VERIFIED" and input_gate["status"] == "PASS"
            and calibration["verification"]["runtime_parity"]
            and calibration["verification"]["heldout_value_files_read"] == 0, "P3.6 evidence incomplete")
    require(sha(ROOT / CV_REPORT) == training["model_selection_oof_SHA256"]
            and sha(ROOT / OOF) == training["development_oof_sha256"] == calibration["oof_sha256"],
            "CV or OOF reports changed")
    for model in training["artifacts"].values():
        require(model["refit_rows"] == 106733 and model["refit_cells"] == 57
                and sha(ROOT / model["path"]) == model["sha256"], "Model binding/refit evidence invalid")
    test_text = (ROOT / TEST_LOG).read_text(encoding="utf-8")
    require("\nOK" in test_text and "PASS: five primary OOF" in test_text and "FAILED" not in test_text, "P3.6 verification log did not pass")
    write_weight_report(training)
    write_resource_report(training, resources)
    write_xgb_report(training)
    write_model_card(training, calibration)
    status_file = ROOT / MANIFESTS / "p3_milestone_status.json"
    status = read(status_file.relative_to(ROOT))
    by_id = {m["milestone_id"]: m for m in status["milestones"]}
    recorded = datetime.now().astimezone().isoformat(timespec="seconds")
    append_ledger(recorded, by_id["P3.4"])
    p36 = by_id["P3.6"]
    recorded = read(FREEZE)["generated_at"] if (ROOT / FREEZE).exists() else recorded
    files = [INPUTS, TRAINING, RESOURCE, CALIBRATION, PREREG,
             "artifacts/soh/feature_schema.json", OOD_POLICY, MODEL_CARD, CV_REPORT, OOF, W_REPORT,
             R_REPORT, X_REPORT, OOD_REPORT, TEST_LOG, RF_CONFIG, XGB_CONFIG, REQUIREMENTS,
             "src/soh/evaluation_guard.py", "tests/test_evaluation_guard.py", "tests/test_p36.py",
             "scripts/p36_inputs.py", "scripts/train_p36.py", "scripts/calibrate_p36.py",
             "scripts/measure_p36.py", "scripts/finalize_p36.py", "scripts/verify_p36.py", LEDGER.as_posix()]
    files.extend(model["path"] for model in training["artifacts"].values())
    bindings = {path: sha(ROOT / path) for path in files}
    decisions = {decision: "PENDING_REVIEWER_APPROVAL" for decision in ("D06", "D08", "D12", "D13", "D15")}
    freeze = dict(revision="p36-r1", spec_version=status["spec_version"], generated_at=recorded,
                  status="FROZEN_CANDIDATE_PENDING_REVIEWER_APPROVAL", candidate_artifacts_locked=True,
                  heldout_evaluation="UNOPENED", heldout_open_allowed=False,
                  development_rows=106733, development_cells=57,
                  primary_features=list(PRIMARY), input_hashes={i["path"]: i["sha256"] for i in p36["inputs"]},
                  artifact_hashes=bindings, models=training["artifacts"],
                  rf_selected=training["rf_selected"], rf_budget_bytes=training["rf_budget_bytes"],
                  rf_sample_weight_formula="N/(C*n_c) on each fit only",
                  model_runtime=training["runtime"], policy=calibration["selected_policy"],
                  xgb=dict(refit_strategy=training["xgb_refit_strategy"],
                           n_estimators_final=training["xgb_n_estimators_final"], early_stopping=False, eval_set=None),
                  guard_sha256=bindings["src/soh/evaluation_guard.py"], reviewer_decisions=decisions,
                  er5_evaluation_configuration=dict(status="PENDING_D07", er5_evaluated=False),
                  feature_schema_sha256=bindings["artifacts/soh/feature_schema.json"],
                  ood_policy_sha256=bindings[OOD_POLICY])
    dump_json(ROOT / FREEZE, freeze)
    p36.update(status="IN_PROGRESS", release_status=freeze["status"], revision="p36-r1",
               heldout_evaluation="UNOPENED",
               outputs=[dict(path=p, sha256=h) for p,h in {**bindings, FREEZE: sha(ROOT / FREEZE)}.items()],
               tests_executed=[dict(id="P3.6 dev join and one-fold smoke", status="PASS", evidence=INPUTS),
                               dict(id="P3.6 guard full OOF replay parity", status="PASS", evidence=CALIBRATION),
                               dict(id="UT-011 / UT-11 reload parity and RF resource measurement",
                                    status="PASS", evidence=R_REPORT),
                               dict(id="P3.6 unit tests", status="PASS", evidence=TEST_LOG)],
               decisions=[dict(id=k, status=v, evidence=e) for (k,v), e in zip(decisions.items(),
                          [R_REPORT, W_REPORT, OOD_REPORT, OOD_REPORT, X_REPORT])],
               blocker="Reviewer sign-off D06/D08/D12/D13/D15 still required to declare MODEL_FROZEN.",
               next_gate="Review the pinned candidate; D07 independently required before P3.7.")
    link_review_evidence(by_id["P3.0"], p36)
    dump_json(status_file, status)
    print(f"Candidate pinned, {len(bindings)} SHA-256 bindings, reviewer approval pending, held-out UNOPENED")


if __name__ == "__main__":
    main()
