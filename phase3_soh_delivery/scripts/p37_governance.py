"""Record Phase 3 approvals and implement the one-use held-out access receipt."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.p36_inputs import LEDGER, ROOT, dump_json, require, sha


STATUS = "manifests/p3_milestone_status.json"
FREEZE = "manifests/p3_model_freeze.json"
CANDIDATE = "manifests/p36_r1_candidate_snapshot.json"
D07 = "configs/p3_er5_evaluation.json"
RECEIPT = "manifests/p3_7_open_receipt.json"
PRECHECK = "manifests/p3_7_preflight.json"
REGISTER = "decisions/P3_APPROVAL_REGISTER.md"
ADDENDUM = "reports/P3_6_D12_D13_REVIEW_ADDENDUM.md"
LABELS = "data/processed/soh_labels.parquet"
SPLIT = "manifests/p3_split_manifest.json"
CONVERSION = "data/staging/rt_batt_v2/conversion_manifest.json"
CHAT = "codex://threads/01a1f73a-0102-73f2-8e1a-fabc053f76bb"
APPROVAL = dict(reviewer="Trịnh Quang Khải", reviewer_role="Phụ trách Phase 3 / Reviewer",
                approval_evidence=CHAT, approved_at="2026-11-22T15:57:44+07:00",
                turn_id="01a20279-c6db-7411-884d-feadcadde7c8",
                message_id="01a20279-c761-72d2-b204-996b3fca0fd6")
CANDIDATE_SHA = "76654f841054f51796b86ec22e53fda5baf4826c69bbc97c0d5baadd1f9dbc9b"
D05_LEDGER_SHA = "2e548b41de3cc1fd85d929562050e851826fdae82fa30788293d539aa740bff4"
STALE_REASON = "NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY"
STATUSES = dict(D06="APPROVED", D08="APPROVED", D12="APPROVED",
                D13="APPROVED_WITH_CONDITIONS", D15="APPROVED")
EVALUATION_SOURCES = {
    LABELS: "de1df883846f5ee475d02f363a7c808ef84ac164ce896423dcfdee72250329f2",
    "manifests/cycle_label_pairing.parquet": "90bfc1606761b8bd39750414ea168cc772ce8a5ff233ed5cc39b70e289e7d227",
}
D07_RULES = dict(population="FULL_ELIGIBLE", expected_cells=19, expected_rows=37130,
                 max_abs_error_pp=10.0, raw_coverage_global_min=.99, raw_coverage_per_cell_min=.95,
                 valid_coverage_global_min=.85, valid_coverage_per_cell_min=None, low_valid_diagnostic_below=.90,
                 band_cutoff_percent=80.0, band_source="soh_ref_percent",
                 zero_numeric_predictions_for_required_cell_max="ER5_NOT_ASSESSABLE",
                 decision_order=["ER5_NOT_MET", "ER5_NOT_ASSESSABLE", "ER5_PASS"],
                 chronological_early_late="first_vs_second_half_of_frozen_eligible_cycles_per_cell",
                 diagnostic_small_band="fewer_than_two_physical_cells; report observations only",
                 offline_stale=dict(value=False, reason=STALE_REASON),
                 online_stale_seconds="PENDING_EVIDENCE_P3_8_BEFORE_INFERENCE_VERIFIED")
EVIDENCE = dict(D06="reports/P3_6_MODEL_RESOURCE_BUDGET.md", D07=D07,
                D08="reports/P3_6_WEIGHT_ABLATION.md", D12=ADDENDUM, D13=ADDENDUM,
                D15="reports/P3_6_XGB_REFIT_AUDIT.md")
DECISIONS = {
    "D06": "RF cân bằng theo cell là mô hình chính. Macro-MAE dev 0,7015 pp. Tệp 28,58 MB. p95 24,0 ms trên Windows development. Giữ ablation không trọng số.",
    "D07": "ER5 dùng FULL_ELIGIBLE. MAX tuyệt đối ≤ 10,0 pp theo từng cell cho cả raw và VALID. Raw coverage ≥ 99,0% toàn tập và ≥ 95,0% mỗi cell. VALID ≥ 85,0% toàn tập. Chẩn đoán riêng cell dưới 90% VALID và hai dải SoH tham chiếu.",
    "D08": "Ridge bắt buộc, train-median làm sanity và XGBoost là đối chứng trên cùng schema/fold.",
    "D12": "Duyệt nguyên bản p36-r1. Guard thống kê bảo thủ, biên cell-weighted P01/P99 và sigma_trees. Ghi nhận độ phủ dev 93,23% và hành vi ở cell 7-2, 4-7.",
    "D13": "Jump 5 pp, K=2, ổn định 2 pp, gap tối đa 2 cycle. Hai resync OOF. Offline stale=False với NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY. Ngưỡng wall-clock chờ bằng chứng P3.8 trước INFERENCE_VERIFIED.",
    "D15": "FIXED_CV_N_ESTIMATORS. Refit XGBoost 200 cây trên toàn dev, tắt early stopping và eval_set.",
}


def now():
    return datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds")


def read(path):
    return json.loads((ROOT / path).read_bytes())


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic_bytes(path, raw):
    dest = ROOT / path
    temp = dest.with_suffix(dest.suffix + ".pending")
    temp.write_bytes(raw)
    temp.replace(dest)


def binding(path):
    return dict(path=str(path).replace("\\", "/"), sha256=sha(ROOT / path))


def verify_candidate(candidate, ledger_bytes=None, ledger_prefix=None):
    require(candidate["revision"] == "p36-r1" and len(candidate["artifact_hashes"]) == 36, "Wrong freeze candidate")
    for path, expected in candidate["artifact_hashes"].items():
        if path == LEDGER.as_posix() and ledger_prefix is not None:
            require(digest(ledger_bytes[:ledger_prefix]) == expected, "Original ledger changed")
        else:
            require(sha(ROOT / path) == expected, f"Candidate binding mismatch: {path}")
    for path, expected in candidate["input_hashes"].items():
        require(sha(ROOT / path) == expected, f"Frozen input mismatch: {path}")


def update_register():
    path = ROOT / REGISTER
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    marker = "## Phê duyệt p36-r1 và khóa D07"
    require(marker not in text, "Review register already amended")
    for decision, details in DECISIONS.items():
        line, = [item for item in text.splitlines() if item.startswith(f"| {decision} |")]
        col = line.split("|")
        col[2] = f" {details} "
        col[4] = f" {APPROVAL['reviewer']} ({APPROVAL['reviewer_role']}), {APPROVAL['approved_at']} "
        col[5] = f" `{STATUSES.get(decision, 'APPROVED')}` "
        col[6] = f" [Bằng chứng](../{EVIDENCE[decision]}) · [Phê duyệt trong chat]({CHAT}). "
        text = text.replace(line, "|".join(col), 1)
    text = text.replace("Người dùng duyệt trực tiếp với vai trò người yêu cầu/duyệt D04,",
                        "Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer),", 1)
    text = text.replace("Người dùng duyệt trực tiếp trong vai trò người yêu cầu và duyệt D04. Chat không cung cấp họ tên hoặc chức danh nhóm để điền vào biên bản.",
                        "Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer) duyệt trực tiếp trong chat. Họ tên và vai trò được bổ sung theo xác nhận khi duyệt p36-r1.", 1)
    text += newline.join(["", marker, "",
        f"Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer) duyệt ngày {APPROVAL['approved_at']}. "
        f"Đối chiếu 36/36 SHA-256 của [bản ứng viên gốc](../{CANDIDATE}). "
        f"[Tin xác nhận]({CHAT}), lượt `{APPROVAL['turn_id']}`, tin `{APPROVAL['message_id']}`.", "",
        "D13 đã đáp ứng điều kiện cho phát lại offline. P3.8 phải xác lập và kiểm thử stale wall-clock trước INFERENCE_VERIFIED.",
        "D07 được khóa trước tiếp xúc held-out. Mẫu số giữ toàn bộ khóa đã duyệt, bao gồm phiên thiếu hoặc bị guard chặn.",
        "Một cell thiếu dự đoán số cho MAX bắt buộc thì tiêu chí MAX của cell đó chưa đánh giá được. Vi phạm đã quan sát vẫn dẫn tới ER5_NOT_MET.", ""])
    atomic_bytes(REGISTER, text.encode("utf-8"))


def approve():
    require(not (ROOT / RECEIPT).exists(), "Held-out access already claimed")
    signed_path = ROOT / FREEZE
    raw = signed_path.read_bytes()
    if read(FREEZE)["status"] == "MODEL_FROZEN":
        signed = read(FREEZE)
        verify_candidate(read(CANDIDATE), (ROOT / LEDGER).read_bytes(), signed["ledger_snapshot_prefix_bytes"])
        require(sha(ROOT / D07) == signed["er5_evaluation_configuration"]["sha256"], "D07 binding mismatch")
        return
    require(digest(raw) == CANDIDATE_SHA, "Candidate SHA-256 differs from approved revision")
    candidate = json.loads(raw)
    require(candidate["heldout_evaluation"] == "UNOPENED", "Candidate exposure state changed")
    verify_candidate(candidate)
    original_ledger = (ROOT / LEDGER).read_bytes()
    require(b"## P3.7" not in original_ledger, "Unexpected P3.7 ledger entry")
    state = read(STATUS)
    marks = {m["milestone_id"]: m for m in state["milestones"]}
    require("P3.7" not in marks and marks["P3.6"]["status"] == "IN_PROGRESS", "Unexpected milestone state")
    atomic_bytes(CANDIDATE, raw)
    config = dict(revision="d07-r1", status="APPROVED", **APPROVAL, signed_at=now(),
                  labels_sha256=EVALUATION_SOURCES[LABELS], **D07_RULES)
    dump_json(ROOT / D07, config)
    update_register()
    p35 = marks["P3.5"]
    d04, = [d for d in p35["decisions"] if d["id"] == "D04"]
    d04.update(reviewer_name=APPROVAL["reviewer"], reviewer_role=APPROVAL["reviewer_role"],
               identity_confirmed_at=APPROVAL["approved_at"], identity_evidence=CHAT)
    p36 = marks["P3.6"]
    signed = dict(candidate, status="MODEL_FROZEN", governance_approval=APPROVAL,
                  candidate_snapshot=binding(CANDIDATE), ledger_snapshot_prefix_bytes=len(original_ledger),
                  reviewer_decisions=STATUSES, heldout_open_allowed=True, frozen_at=now(),
                  er5_evaluation_configuration={**binding(D07), "status":"APPROVED", "er5_evaluated":False},
                  heldout_evaluation="UNOPENED", review_addendum=binding(ADDENDUM),
                  d13_followup="P3.8 wall-clock stale threshold pending evidence")
    dump_json(signed_path, signed)
    register = binding(REGISTER)
    for out in marks["P3.0"]["outputs"]:
        if out["path"] == REGISTER:
            out.update(register)
    p36.update(status="PASS", release_status="MODEL_FROZEN", blocker=None,
               signed_at=APPROVAL["approved_at"], review_register=register,
               decisions=[dict(id=k, status=v, evidence=EVIDENCE[k], **APPROVAL) for k,v in STATUSES.items()],
               next_gate="D07 approved. One-time P3.7 evaluation with frozen p36-r1.")
    for out in p36["outputs"]:
        if out["path"] == FREEZE:
            out.update(binding(FREEZE))
    p36["outputs"].extend([binding(CANDIDATE), binding(D07), binding(ADDENDUM)])
    state["milestones"].append(dict(milestone_id="P3.7", status="IN_PROGRESS",
        release_status="D07_LOCKED_HELDOUT_UNOPENED", heldout_evaluation="UNOPENED",
        inputs=[binding(FREEZE), binding(D07), binding(SPLIT)]
               + [dict(path=p,sha256=h) for p,h in EVALUATION_SOURCES.items()],
        decisions=[dict(id="D07", status="APPROVED", evidence=D07, **APPROVAL)],
        outputs=[], tests_executed=[], next_gate="Preflight and acquire single exposure receipt."))
    dump_json(ROOT / STATUS, state)
    print("P3.6 PASS / MODEL_FROZEN, D07 APPROVED, 36/36 candidate bindings, held-out UNOPENED")


def append_ledger(text):
    path = ROOT / LEDGER
    atomic_bytes(LEDGER, path.read_bytes() + ("\n\n" + text.rstrip() + "\n").encode("utf-8"))


def refresh_ledger_bindings(state):
    ledger = binding(LEDGER)
    for m in state["milestones"]:
        if m["milestone_id"] in ("P3.4", "P3.6"):
            for out in m["outputs"]:
                if out["path"] == LEDGER.as_posix():
                    out["signed_snapshot_sha256"] = out.get("signed_snapshot_sha256", out["sha256"])
                    out.update(ledger)


def claim(details):
    """Create before any held-out data access. A failed run cannot claim again."""
    receipt = dict(opened_at=now(), exposure_count=1, status="OPENED", evaluator="Codex",
                   approval=APPROVAL, **details)
    path = ROOT / RECEIPT
    with path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    append_ledger(f"""## P3.7 — Lần mở held-out duy nhất

Trạng thái P3.7 kể từ {receipt['opened_at']} (UTC+07) **OPENED_ONCE**. Codex thực thi theo quyết định
D07 của Trịnh Quang Khải. Phạm vi 19 cell và 37.130 khóa đủ điều kiện được chỉ định từ p34-r1.
Đọc khóa, nhãn tham chiếu đã khóa và tín hiệu sạc staging của 19 cell. Áp dụng các mô hình,
schema, OOD policy và guard p36-r1 đã ký. [Biên nhận](../{RECEIPT})

- Manifest ký duyệt SHA-256 `{receipt['signed_freeze']['sha256']}`.
- D07 SHA-256 `{receipt['d07']['sha256']}`.
- Split SHA-256 `{receipt['split']['sha256']}`.
- Frozen guard SHA-256 `{receipt['guard_sha256']}`.
- Evaluator SHA-256 `{receipt['evaluator_sha256']}`.

Mục này ghi đè trạng thái lịch sử UNOPENED. Quyền chạy held-out đã được sử dụng.
""")
    state = read(STATUS)
    p37, = [m for m in state["milestones"] if m["milestone_id"] == "P3.7"]
    p37.update(heldout_evaluation="OPENED_ONCE", release_status="EVALUATION_OPENED",
               exposure_receipt=binding(RECEIPT), next_gate="Preserve row predictions and report from this run.")
    refresh_ledger_bindings(state)
    dump_json(ROOT / STATUS, state)
    return receipt


if __name__ == "__main__":
    approve()
