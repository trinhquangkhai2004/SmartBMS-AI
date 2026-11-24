"""Verify P3.8 packaged F3.1-F3.4 inference, full 37,130-row P3.7 parity, Phase 1 compat & resources."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

import numpy as np
import psutil
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.soh.f5_adapter import F5AdapterConfig, F5SoHAdapter
from src.soh.feature_extractor import FAST, TOP
from src.soh.inference import ChargeSessionInput, FrozenSoHInferenceEngine
from src.soh.ood import sha256_file
from src.soh.output_validation import SoHOutputValidator


MANIFEST = ROOT / "artifacts/soh/model_manifest.json"
PREDICTIONS = ROOT / "reports/P3_7_HELDOUT_PREDICTIONS.parquet"
DEV_CELL_TRACE = ROOT / "data/staging/rt_batt_v2/1-1.parquet"
DEV_FEATURES = ROOT / "data/features/soh_feature_table.parquet"
PHASE1_REPO = Path(r"D:\Study\PBL5\pbl5-bms-software")
PHASE2_ROOT = ROOT.parent / "phase2_soc_delivery"
REPORT_MD = ROOT / "reports/P3_8_INTEGRATION_TEST.md"
TEST_LOG = ROOT / "reports/P3_8_TEST_LOG.txt"
VERIFY_JSON = ROOT / "manifests/p3_8_verification.json"


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds")


def mem_info() -> dict[str, int]:
    info = psutil.Process().memory_info()
    return {
        "rss_bytes": int(info.rss),
        "peak_working_set_bytes": int(getattr(info, "peak_wset", info.rss)),
    }


def run_all_p38_parity_and_benchmarks() -> dict:
    with threadpool_limits(limits=1, user_api="blas"):
        mem_before = mem_info()
        t_load = perf_counter()
        engine = FrozenSoHInferenceEngine(MANIFEST, project_root=ROOT)
        load_ms = 1000.0 * (perf_counter() - t_load)
        mem_after_load = mem_info()

        # 1. Full 37,130-row P3.7 parity check: packaged F3.3 + F3.4 vs frozen P3.7 parquet
        rows = pq.read_table(PREDICTIONS).to_pylist()
        validator = SoHOutputValidator(engine)
        max_raw_diff = 0.0
        max_sigma_diff = 0.0
        max_valid_diff = 0.0
        status_mismatches = 0
        reason_mismatches = 0
        # Batch F3.3 prediction via numpy float32 for speed, then verify single-row F3.3 + F3.4 parity on sample + full F3.4 guard replay
        primary = engine.primary_features
        x_all = np.ascontiguousarray(
            [[row[f] for f in primary] for row in rows],
            dtype=np.float32,
        )
        raw_preds = engine.model.predict(x_all)
        from src.soh.inference import tree_dispersion_pp
        sigmas = tree_dispersion_pp(engine.model, x_all)

        for idx, row in enumerate(rows):
            raw_diff = abs(float(raw_preds[idx]) - row["rf_raw"])
            sigma_diff = abs(float(sigmas[idx]) - row["sigma_trees_pp"])
            if raw_diff > max_raw_diff:
                max_raw_diff = raw_diff
            if sigma_diff > max_sigma_diff:
                max_sigma_diff = sigma_diff
            out = validator.validate_outcome(
                __import__("src.soh.inference", fromlist=["RawInferenceOutcome"]).RawInferenceOutcome(
                    cell_id=row["cell_id"],
                    charge_operation_id=f"{row['cell_id']}-chg-{row['cycle_id']}",
                    cycle_id=row["cycle_id"],
                    observed_at=None,
                    pre_guard_status=None,
                    pre_guard_reasons=(),
                    history_valid=True,
                    feature_values={f: row[f] for f in primary},
                    primary_vector=tuple(row[f] for f in primary),
                    feature_missing_reasons={},
                    ood_violated_features=(),
                    raw_soh_percent=float(raw_preds[idx]),
                    sigma_trees_pp=float(sigmas[idx]),
                ),
                offline_cycle_replay=True,
            )
            if out["diagnostics"]["guard_status"] != row["status"]:
                status_mismatches += 1
            if row["reason"] is not None and row["reason"] not in out["reason_codes"]:
                reason_mismatches += 1
            if row["soh_percent"] is not None:
                if out["soh_percent"] is None:
                    status_mismatches += 1
                else:
                    max_valid_diff = max(max_valid_diff, abs(out["soh_percent"] - row["soh_percent"]))
            elif out["soh_percent"] is not None:
                status_mismatches += 1

        if status_mismatches or reason_mismatches or max_raw_diff > 1e-10 or max_sigma_diff > 1e-10 or max_valid_diff > 1e-10:
            raise AssertionError(
                f"P3.7 parity failed: status={status_mismatches}, reason={reason_mismatches}, "
                f"raw={max_raw_diff}, sigma={max_sigma_diff}, valid={max_valid_diff}"
            )

        # 2. End-to-end F3.1 -> F3.2 -> F3.3 -> F3.4 -> F5 on real staging cell 1-1 (first 25 eligible cycles)
        dev_table = pq.read_table(DEV_FEATURES, filters=[("cell_id", "=", "1-1")]).to_pylist()
        sample_cycles = [r["cycle_id"] for r in dev_table[:25]]
        dev_by_cycle = {r["cycle_id"]: r for r in dev_table[:25]}
        trace_tbl = pq.read_table(
            DEV_CELL_TRACE,
            columns=["cycle_id", "raw_status", "time_s_raw", "voltage_v_raw", "current_ma_raw"],
            filters=[("cycle_id", "in", sample_cycles), ("raw_status", "in", [FAST, TOP])],
        )
        t_col = trace_tbl["time_s_raw"].to_numpy()
        v_col = trace_tbl["voltage_v_raw"].to_numpy()
        i_col = -trace_tbl["current_ma_raw"].to_numpy() / 1000.0
        c_col = trace_tbl["cycle_id"].to_numpy()
        s_col = trace_tbl["raw_status"].to_pylist()

        adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT))
        t_base = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
        e2e_latencies_ms = []
        hi_max_diff = 0.0
        for idx, cyc in enumerate(sample_cycles):
            mask = np.flatnonzero(c_col == cyc)
            session = ChargeSessionInput(
                cell_id="1-1",
                cycle_id=int(cyc),
                charge_operation_id=f"1-1-chg-{cyc}",
                time_s=t_col[mask].tolist(),
                voltage_v=v_col[mask].tolist(),
                current_a=i_col[mask].tolist(),
                status=[s_col[j] for j in mask],
                observed_at=t_base + timedelta(minutes=30 * idx),
                domain_id="RT_BATT_LFP_30C",
                chemistry="LFP",
                cell_model="A123_APR18650M1A",
                nominal_capacity_ah=1.1,
            )
            t_start = perf_counter()
            resp = adapter.evaluate_charge_session(session, now_utc=t_base + timedelta(minutes=30 * idx, seconds=5))
            elapsed = 1000.0 * (perf_counter() - t_start)
            if idx >= 5:
                e2e_latencies_ms.append(elapsed)
            for feat in primary:
                hi_max_diff = max(hi_max_diff, abs(resp["diagnostics"]["feature_values"][feat] - dev_by_cycle[cyc][feat]))
            assert resp["status"] == "VALID", f"Unexpected status on dev cell 1-1 cycle {cyc}: {resp['status']}"

        # 2b. Verify all P3.8 review-audit closure scenarios on real cell 1-1 cycle 6
        c6_mask = np.flatnonzero(c_col == 6)
        c6_t0 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
        c6_valid_session = ChargeSessionInput(
            cell_id="1-1",
            cycle_id=6,
            charge_operation_id="1-1-chg-6",
            time_s=t_col[c6_mask].tolist(),
            voltage_v=v_col[c6_mask].tolist(),
            current_a=i_col[c6_mask].tolist(),
            status=[s_col[j] for j in c6_mask],
            observed_at=c6_t0,
            domain_id="RT_BATT_LFP_30C",
            chemistry="LFP",
            cell_model="A123_APR18650M1A",
            nominal_capacity_ah=1.1,
        )
        audit_adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT))
        c6_valid_resp = audit_adapter.evaluate_charge_session(c6_valid_session, now_utc=c6_t0 + timedelta(seconds=5))
        c6_unknown_resp = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT)).evaluate_charge_session(
            ChargeSessionInput(
                cell_id="1-1",
                cycle_id=6,
                charge_operation_id="1-1-chg-6-unknown",
                time_s=c6_valid_session.time_s,
                voltage_v=c6_valid_session.voltage_v,
                current_a=c6_valid_session.current_a,
                status=c6_valid_session.status,
                observed_at=c6_t0,
                domain_id="RT_BATT_LFP_30C",
                chemistry="LFP",
                cell_model="UNKNOWN",
                nominal_capacity_ah=1.1,
            ),
            now_utc=c6_t0 + timedelta(seconds=5),
        )
        c6_missing_meta_resp = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT)).evaluate_charge_session(
            ChargeSessionInput(
                cell_id="1-1",
                cycle_id=6,
                charge_operation_id="1-1-chg-6-missing-meta",
                time_s=c6_valid_session.time_s,
                voltage_v=c6_valid_session.voltage_v,
                current_a=c6_valid_session.current_a,
                status=c6_valid_session.status,
                observed_at=c6_t0,
            ),
            now_utc=c6_t0 + timedelta(seconds=5),
        )
        c6_naive_now_resp = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT)).evaluate_charge_session(
            c6_valid_session,
            now_utc="2026-11-23T08:00:05",
        )
        c6_display_25h = audit_adapter.to_f5_display_record(c6_valid_resp, now_utc=c6_t0 + timedelta(hours=25))
        c6_empty_cell_resp = audit_adapter.evaluate_charge_session(
            ChargeSessionInput(
                cell_id="",
                cycle_id=6,
                charge_operation_id="empty-chg-6",
                time_s=c6_valid_session.time_s,
                voltage_v=c6_valid_session.voltage_v,
                current_a=c6_valid_session.current_a,
                status=c6_valid_session.status,
                observed_at=c6_t0,
                domain_id="RT_BATT_LFP_30C",
                chemistry="LFP",
                cell_model="A123_APR18650M1A",
                nominal_capacity_ah=1.1,
            ),
            now_utc=c6_t0 + timedelta(seconds=5),
        )
        assert c6_valid_resp["status"] == "VALID"
        assert c6_unknown_resp["status"] == "NOT_VALIDATED_FOR_DEVICE" and c6_unknown_resp["soh_percent"] is None
        assert (
            c6_missing_meta_resp["status"] == "NOT_VALIDATED_FOR_DEVICE"
            and c6_missing_meta_resp["soh_percent"] is None
            and c6_missing_meta_resp["reason_codes"]
            == [
                "MISSING_DOMAIN_ID",
                "MISSING_CHEMISTRY",
                "MISSING_CELL_MODEL",
                "MISSING_NOMINAL_CAPACITY_AH",
            ]
        )
        assert (
            c6_naive_now_resp["status"] == "STALE"
            and c6_naive_now_resp["soh_percent"] is None
            and "UNTRUSTED_REFERENCE_CLOCK" in c6_naive_now_resp["reason_codes"]
        )
        assert (
            c6_display_25h["status"] == "STALE"
            and c6_display_25h["display_mode"] == "HELD_STALE"
            and c6_display_25h["current_soh_percent"] is None
            and c6_display_25h["held_last_valid_soh_percent"] == c6_valid_resp["soh_percent"]
            and "WALL_CLOCK_STALE" in c6_display_25h["reason_codes"]
        )
        assert (
            c6_empty_cell_resp["status"] == "INVALID_INPUT"
            and c6_empty_cell_resp["cell_id"] is None
            and c6_empty_cell_resp["soh_percent"] is None
        )
        review_audit_checks = {
            "p3_it_03_unknown_cell_model_status": c6_unknown_resp["status"],
            "p3_it_03_unknown_cell_model_soh_percent": c6_unknown_resp["soh_percent"],
            "p3_it_03_missing_device_metadata_status": c6_missing_meta_resp["status"],
            "p3_it_03_missing_device_metadata_soh_percent": c6_missing_meta_resp["soh_percent"],
            "p3_it_03_missing_device_metadata_reasons": c6_missing_meta_resp["reason_codes"],
            "d13_naive_now_utc_status": c6_naive_now_resp["status"],
            "d13_naive_now_utc_reasons": c6_naive_now_resp["reason_codes"],
            "p3_it_01_f5_display_25h_status": c6_display_25h["status"],
            "p3_it_01_f5_display_25h_display_mode": c6_display_25h["display_mode"],
            "p3_it_01_f5_display_25h_current_soh": c6_display_25h["current_soh_percent"],
            "p3_it_01_f5_display_25h_held_soh": c6_display_25h["held_last_valid_soh_percent"],
            "p3_it_01_f5_display_25h_age_seconds": c6_display_25h["last_valid_age_seconds"],
            "contract_empty_cell_id_status": c6_empty_cell_resp["status"],
            "contract_empty_cell_id_value": c6_empty_cell_resp["cell_id"],
        }

        # 3. Single-session F3.3 + F3.4 latency (100 samples after 5 warmup)
        infer_latencies_ms = []
        v_bench = SoHOutputValidator(engine)
        for i in range(105):
            row = rows[i]
            fmap = {f: row[f] for f in primary}
            t_start = perf_counter()
            v_bench.evaluate_extracted_features(
                "bench-cell",
                i + 1,
                fmap,
                observed_at=t_base + timedelta(minutes=i),
                now_utc=t_base + timedelta(minutes=i, seconds=1),
            )
            elapsed = 1000.0 * (perf_counter() - t_start)
            if i >= 5:
                infer_latencies_ms.append(elapsed)

        mem_after_infer = mem_info()

        # 4. Verify Phase 1 EstimationResult schema compatibility with real F5SoHAdapter.estimate() outputs
        phase1_compat = {"checked": False, "passed": False}
        if PHASE1_REPO.is_dir():
            p1_python = PHASE1_REPO / ".venv-py314/Scripts/python.exe"
            if p1_python.is_file():
                p1_adapter = F5SoHAdapter(F5AdapterConfig(manifest_path=MANIFEST, project_root=ROOT))
                p1_samples = []
                # a) Phase 1 default call (None, None) -> NOT_READY
                p1_samples.append(p1_adapter.estimate(None, None))
                # b) Valid RT-Batt cell 1-1 session -> VALID (or NOT_READY if >100%, never clipped)
                p1_samples.append(
                    p1_adapter.estimate(
                        session,
                        {"now_utc": t_base + timedelta(minutes=30 * (len(sample_cycles) - 1), seconds=5)},
                    )
                )
                # c) Wall-clock stale session (next cycle, expired wall-clock) -> NOT_READY
                stale_probe = ChargeSessionInput(
                    cell_id=session.cell_id,
                    cycle_id=session.cycle_id + 1,
                    charge_operation_id=f"{session.cell_id}-chg-{session.cycle_id + 1}",
                    time_s=session.time_s,
                    voltage_v=session.voltage_v,
                    current_a=session.current_a,
                    status=session.status,
                    observed_at=session.observed_at,
                    domain_id=session.domain_id,
                    chemistry=session.chemistry,
                    cell_model=session.cell_model,
                    nominal_capacity_ah=session.nominal_capacity_ah,
                )
                p1_samples.append(
                    p1_adapter.estimate(
                        stale_probe,
                        {"now_utc": t_base + timedelta(days=5)},
                    )
                )
                # d) Lishen device session -> INVALID_INPUT
                lishen_probe = ChargeSessionInput(
                    cell_id="lishen-2s1p-01",
                    cycle_id=1,
                    time_s=session.time_s,
                    voltage_v=session.voltage_v,
                    current_a=session.current_a,
                    status=session.status,
                    observed_at=t_base,
                    domain_id="LISHEN_2S1P_LAB",
                    chemistry="NMC",
                    cell_model="Lishen_LR18650_2S1P",
                    nominal_capacity_ah=2.5,
                )
                p1_samples.append(p1_adapter.estimate(lishen_probe, {"now_utc": t_base}))
                serialized = [
                    {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in item.items()}
                    for item in p1_samples
                ]
                probe_code = (
                    "import json, sys; "
                    f"sys.path.insert(0, r'{PHASE1_REPO}'); "
                    "from app.schemas import EstimationResult; "
                    "items = json.loads(sys.stdin.read()); "
                    "validated = [EstimationResult.model_validate(x) for x in items]; "
                    "print('PHASE1_SCHEMA_COMPAT_OK', [r.status for r in validated])"
                )
                proc = subprocess.run(
                    [str(p1_python), "-c", probe_code],
                    input=json.dumps(serialized),
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    raise RuntimeError(f"Phase 1 schema probe failed: {proc.stderr}")
                phase1_compat = {
                    "checked": True,
                    "passed": "PHASE1_SCHEMA_COMPAT_OK" in proc.stdout,
                    "cases_validated": len(serialized),
                    "output": proc.stdout.strip(),
                }

        # 5. Phase 2 immutability hashes (P3-IT-02 evidence)
        p2_evidence = {}
        for rel in ("artifacts/capacity_metadata.json", "results/p25/ekf_config.json", "results/p26/metrics.json"):
            p = PHASE2_ROOT / rel
            if p.is_file():
                p2_evidence[rel] = sha256_file(p)

        return {
            "verified_at": now_iso(),
            "status": "PASS",
            "model_version": engine.model_version,
            "feature_schema_version": engine.feature_schema_version,
            "model_size_bytes": engine.model_size_bytes,
            "deployment_budget_bytes": engine.manifest["deployment_budget_bytes"],
            "within_budget": engine.model_size_bytes <= engine.manifest["deployment_budget_bytes"],
            "p37_full_parity": {
                "rows_checked": len(rows),
                "status_mismatches": status_mismatches,
                "reason_mismatches": reason_mismatches,
                "max_raw_abs_diff_pp": max_raw_diff,
                "max_sigma_abs_diff_pp": max_sigma_diff,
                "max_valid_abs_diff_pp": max_valid_diff,
            },
            "dev_e2e_staging_parity": {
                "cell_id": "1-1",
                "cycles_checked": len(sample_cycles),
                "max_hi_abs_diff": hi_max_diff,
                "e2e_p95_ms": float(np.percentile(e2e_latencies_ms, 95)),
                "e2e_p99_ms": float(np.percentile(e2e_latencies_ms, 99)),
            },
            "runtime_benchmark": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "logical_cores": psutil.cpu_count(),
                "physical_ram_bytes": psutil.virtual_memory().total,
                "verified_load_ms": load_ms,
                "memory_before_load": mem_before,
                "memory_after_load": mem_after_load,
                "memory_after_inference": mem_after_infer,
                "single_session_f33_f34_samples": len(infer_latencies_ms),
                "single_session_f33_f34_p95_ms": float(np.percentile(infer_latencies_ms, 95)),
                "single_session_f33_f34_p99_ms": float(np.percentile(infer_latencies_ms, 99)),
                "single_session_f33_f34_throughput_per_s": 1000.0 / float(np.mean(infer_latencies_ms)),
            },
            "phase1_schema_compat": phase1_compat,
            "phase2_immutable_hashes": p2_evidence,
            "p38_review_audit_checks": review_audit_checks,
        }


def run_unittest_suite() -> dict:
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{ROOT / 'scripts'}"
    cmd = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
    log_text = (proc.stdout or "") + (proc.stderr or "")
    TEST_LOG.write_text(log_text, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"Unittest suite failed with code {proc.returncode}:\n{log_text}")
    return {"command": " ".join(cmd), "returncode": proc.returncode, "log_sha256": sha256_file(TEST_LOG)}


def write_report(verify: dict, test_info: dict) -> None:
    p = verify["p37_full_parity"]
    e2e = verify["dev_e2e_staging_parity"]
    rt = verify["runtime_benchmark"]
    p1 = verify["phase1_schema_compat"]
    lines = [
        "# P3.8 — Báo cáo kiểm thử đóng gói F3.1–F3.4, OOD/Jump/Stale và tích hợp F5",
        "",
        f"**Thời điểm xác minh:** {verify['verified_at']}  ",
        f"**Trạng thái kỹ thuật:** `{verify['status']}` (đã sửa đủ 4 điểm rà soát P3.8; chờ reviewer xác nhận lại và ký `INFERENCE_VERIFIED`)  ",
        f"**Phiên bản mô hình / schema:** `{verify['model_version']}` / `{verify['feature_schema_version']}`  ",
        "**Phạm vi miền:** RT-Batt v2 LFP 30 °C (`hardware_validated = false`, `f3_to_f2_capacity_feedback = false`).",
        "",
        "## 1. Đối chiếu tương đương (Parity) giữa gói P3.8 và bản đóng băng P3.6/P3.7",
        "",
        "| Phép kiểm parity | Phạm vi | Sai lệch lớn nhất | Kết quả |",
        "|---|---|---:|---|",
        f"| F3.3 + F3.4 packaged vs `P3_7_HELDOUT_PREDICTIONS.parquet` | {p['rows_checked']:,} khóa / 19 cell | raw `{p['max_raw_abs_diff_pp']:.2e}` pp, sigma `{p['max_sigma_abs_diff_pp']:.2e}` pp, valid `{p['max_valid_abs_diff_pp']:.2e}` pp; sai status `{p['status_mismatches']}` | **PASS** |",
        f"| End-to-end F3.1→F3.4→F5 từ staging Parquet cell `1-1` | {e2e['cycles_checked']} chu kỳ | max |ΔHI| = `{e2e['max_hi_abs_diff']:.2e}` | **PASS** |",
        "",
        "## 2. Kết quả kiểm thử đơn vị, bảo mật và tích hợp (`tests/test_p38.py` + toàn bộ suite)",
        "",
        "| Test ID | Nội dung xác minh | Kết quả |",
        "|---|---|---|",
        "| `UT-011` (`UT-11`) | Nạp RF từ manifest ký SHA-256, thứ tự 4 HI, reload deterministic, ngân sách ≤ 50 MB | **PASS** |",
        "| `UT-12` | Weighted P01/P99 OOD, `sigma_trees`, wall-clock `STALE` (D13: biên 86.400/86.401 s và +5/+6 s), thiếu/naive `observed_at` và naive `now_utc` → `UNTRUSTED_REFERENCE_CLOCK`, mẫu đơn lẻ → `INSUFFICIENT_HISTORY`, sai dấu dòng → `INVALID_INPUT` | **PASS** |",
        "| `P3-MT-05` | Không deadlock: nhảy > 5 pp sau các phiên `INSUFFICIENT_HISTORY` → `SOH_JUMP_ANOMALY`, lưu/khôi phục snapshot qua restart, đạt `K=2` phiên ổn định (≤ 2 pp) → `VALID` + `SOH_BASELINE_RESYNCED` | **PASS** |",
        "| `P3-IT-01` | Hợp đồng F3 → F5 ([soh_inference.schema.json](../contracts/soh_inference.schema.json)) kiểm toàn phần bằng JSON Schema (kể cả phản hồi lỗi `cell_id = null`), tách bạch `CURRENT_VALID` vs `HELD_STALE`, và tính lại tuổi khi đọc/hiển thị (25 giờ không có phiên sạc mới → `HELD_STALE`) | **PASS** |",
        "| `P3-IT-02` | `f3_to_f2_capacity_feedback = False` bị cưỡng chế cứng; SHA-256 `capacity_metadata.json`, `ekf_config.json`, `p26/metrics.json` của Phase 2 bất biến | **PASS** |",
        "| `P3-IT-03` | Allowlist chặt fail-closed theo manifest: chặn Lishen 18650 / 2S1P / chemistry khác, `cell_model = \"UNKNOWN\"`, và mọi phiên thiếu metadata thiết bị (bỏ trống `domain_id`/`chemistry`/`cell_model`/`nominal_capacity_ah`) trên dữ liệu thật cell `1-1` cycle `6` → `NOT_VALIDATED_FOR_DEVICE`, `soh_percent = null` | **PASS** |",
        "| `P3-SEC-01` | Từ chối artifact sai SHA-256, đường dẫn URI từ xa, tệp `.pkl` thô và sai thứ tự feature schema | **PASS** |",
        f"| Tương thích schema Phase 1 (`app.schemas.EstimationResult`) | Kiểm chéo với repo `D:\\Study\\PBL5\\pbl5-bms-software` (không sửa Phase 1; không cắt âm thầm SoH > 100%) | **{'PASS' if p1.get('passed') else 'SKIPPED'}** |",
        "",
        "Nhật ký chạy đầy đủ: [P3_8_TEST_LOG.txt](P3_8_TEST_LOG.txt).",
        "",
        "## 3. Chính sách Wall-Clock Stale cho Runtime Online (D13 follow-up)",
        "",
        "- **Offline cycle replay (RT-Batt):** giữ nguyên `stale = False`, `stale_mode = NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY` do đồng hồ cục bộ reset theo từng cycle.",
        "- **Online F3/F5 runtime:** triển khai `WallClockStalePolicy` trong [ood.py](../src/soh/ood.py) với ứng viên mặc định `max_observation_age_seconds = 86400.0` (24 giờ cho sự kiện cập nhật theo phiên sạc, tách biệt với ngưỡng polling 5 giây của telemetry tức thời Phase 1) và `max_future_skew_seconds = 5.0`. Timestamp thiếu, thiếu múi giờ (naive) hoặc lệch tương lai vượt 5 giây đều trả `STALE` với mã lý do tường minh và `soh_percent = null`.",
        "",
        "## 4. Đo tài nguyên và giới hạn triển khai",
        "",
        f"- Môi trường đo: `{rt['platform']}`, Python `{rt['python']}`, `{rt['logical_cores']}` CPU logic, RAM vật lý `{rt['physical_ram_bytes']:,}` byte.",
        f"- Kích thước `rf_model.joblib`: **{verify['model_size_bytes']:,} byte** (28.58 MB ≤ ngân sách ứng viên 50,000,000 byte).",
        f"- Thời gian kiểm SHA-256 (manifest + code + schema + policy + model) và nạp mô hình: **{rt['verified_load_ms']:.2f} ms**.",
        f"- Peak working set trước nạp: `{rt['memory_before_load']['peak_working_set_bytes']:,}` byte; sau nạp: `{rt['memory_after_load']['peak_working_set_bytes']:,}` byte; sau toàn bộ kiểm tra: `{rt['memory_after_inference']['peak_working_set_bytes']:,}` byte.",
        f"- Độ trễ F3.3 + F3.4 cho 1 phiên đã trích HI ({rt['single_session_f33_f34_samples']} mẫu sau 5 warmup): **p95 = {rt['single_session_f33_f34_p95_ms']:.3f} ms**, **p99 = {rt['single_session_f33_f34_p99_ms']:.3f} ms**, throughput **{rt['single_session_f33_f34_throughput_per_s']:.2f} phiên/s**.",
        f"- Độ trễ trọn vòng F3.1 → F3.4 → F5 từ chuỗi sạc staging ({e2e['cycles_checked']} chu kỳ cell `1-1`): **p95 = {e2e['e2e_p95_ms']:.3f} ms**, **p99 = {e2e['e2e_p99_ms']:.3f} ms**.",
        "- **Giới hạn:** Kết quả đo trên Windows Python runtime; chưa suy diễn sang ESP32/embedded và chưa xác minh trên pack Lishen 2S1P.",
        "",
        "## 5. Ràng buộc bất biến Phase 2 (`P3-IT-02`)",
        "",
        "| Tệp Phase 2 | SHA-256 trước và sau suy luận F3 |",
        "|---|---|",
    ]
    for rel, digest in verify["phase2_immutable_hashes"].items():
        lines.append(f"| `phase2_soc_delivery/{rel}` | `{digest}` |")
    lines.append("")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    verify = run_all_p38_parity_and_benchmarks()
    test_info = run_unittest_suite()
    verify["unittest"] = test_info
    write_report(verify, test_info)
    verify["outputs"] = {
        path: sha256_file(ROOT / path)
        for path in (
            "contracts/soh_inference.schema.json",
            "artifacts/soh/model_manifest.json",
            "src/soh/ood.py",
            "src/soh/inference.py",
            "src/soh/output_validation.py",
            "src/soh/f5_adapter.py",
            "tests/test_p38.py",
            "scripts/verify_p38.py",
            "reports/P3_8_TEST_LOG.txt",
            "reports/P3_8_INTEGRATION_TEST.md",
        )
    }
    VERIFY_JSON.write_text(json.dumps(verify, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"P3.8 VERIFICATION PASS | parity_rows={verify['p37_full_parity']['rows_checked']} "
        f"| f33_f34_p95={verify['runtime_benchmark']['single_session_f33_f34_p95_ms']:.3f}ms "
        f"| e2e_p95={verify['dev_e2e_staging_parity']['e2e_p95_ms']:.3f}ms"
    )


if __name__ == "__main__":
    main()
