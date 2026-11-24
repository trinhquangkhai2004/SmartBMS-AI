# P3.8 — Báo cáo kiểm thử đóng gói F3.1–F3.4, OOD/Jump/Stale và tích hợp F5

**Thời điểm xác minh:** 2026-11-23T21:13:42+07:00  
**Trạng thái kỹ thuật:** `PASS` (đã sửa đủ 4 điểm rà soát P3.8; chờ reviewer xác nhận lại và ký `INFERENCE_VERIFIED`)  
**Phiên bản mô hình / schema:** `p36-r1` / `p35-r1`  
**Phạm vi miền:** RT-Batt v2 LFP 30 °C (`hardware_validated = false`, `f3_to_f2_capacity_feedback = false`).

## 1. Đối chiếu tương đương (Parity) giữa gói P3.8 và bản đóng băng P3.6/P3.7

| Phép kiểm parity | Phạm vi | Sai lệch lớn nhất | Kết quả |
|---|---|---:|---|
| F3.3 + F3.4 packaged vs `P3_7_HELDOUT_PREDICTIONS.parquet` | 37,130 khóa / 19 cell | raw `5.68e-14` pp, sigma `0.00e+00` pp, valid `5.68e-14` pp; sai status `0` | **PASS** |
| End-to-end F3.1→F3.4→F5 từ staging Parquet cell `1-1` | 25 chu kỳ | max |ΔHI| = `0.00e+00` | **PASS** |

## 2. Kết quả kiểm thử đơn vị, bảo mật và tích hợp (`tests/test_p38.py` + toàn bộ suite)

| Test ID | Nội dung xác minh | Kết quả |
|---|---|---|
| `UT-011` (`UT-11`) | Nạp RF từ manifest ký SHA-256, thứ tự 4 HI, reload deterministic, ngân sách ≤ 50 MB | **PASS** |
| `UT-12` | Weighted P01/P99 OOD, `sigma_trees`, wall-clock `STALE` (D13: biên 86.400/86.401 s và +5/+6 s), thiếu/naive `observed_at` và naive `now_utc` → `UNTRUSTED_REFERENCE_CLOCK`, mẫu đơn lẻ → `INSUFFICIENT_HISTORY`, sai dấu dòng → `INVALID_INPUT` | **PASS** |
| `P3-MT-05` | Không deadlock: nhảy > 5 pp sau các phiên `INSUFFICIENT_HISTORY` → `SOH_JUMP_ANOMALY`, lưu/khôi phục snapshot qua restart, đạt `K=2` phiên ổn định (≤ 2 pp) → `VALID` + `SOH_BASELINE_RESYNCED` | **PASS** |
| `P3-IT-01` | Hợp đồng F3 → F5 ([soh_inference.schema.json](../contracts/soh_inference.schema.json)) kiểm toàn phần bằng JSON Schema (kể cả phản hồi lỗi `cell_id = null`), tách bạch `CURRENT_VALID` vs `HELD_STALE`, và tính lại tuổi khi đọc/hiển thị (25 giờ không có phiên sạc mới → `HELD_STALE`) | **PASS** |
| `P3-IT-02` | `f3_to_f2_capacity_feedback = False` bị cưỡng chế cứng; SHA-256 `capacity_metadata.json`, `ekf_config.json`, `p26/metrics.json` của Phase 2 bất biến | **PASS** |
| `P3-IT-03` | Allowlist chặt fail-closed theo manifest: chặn Lishen 18650 / 2S1P / chemistry khác, `cell_model = "UNKNOWN"`, và mọi phiên thiếu metadata thiết bị (bỏ trống `domain_id`/`chemistry`/`cell_model`/`nominal_capacity_ah`) trên dữ liệu thật cell `1-1` cycle `6` → `NOT_VALIDATED_FOR_DEVICE`, `soh_percent = null` | **PASS** |
| `P3-SEC-01` | Từ chối artifact sai SHA-256, đường dẫn URI từ xa, tệp `.pkl` thô và sai thứ tự feature schema | **PASS** |
| Tương thích schema Phase 1 (`app.schemas.EstimationResult`) | Kiểm chéo với repo `D:\Study\PBL5\pbl5-bms-software` (không sửa Phase 1; không cắt âm thầm SoH > 100%) | **PASS** |

Nhật ký chạy đầy đủ: [P3_8_TEST_LOG.txt](P3_8_TEST_LOG.txt).

## 3. Chính sách Wall-Clock Stale cho Runtime Online (D13 follow-up)

- **Offline cycle replay (RT-Batt):** giữ nguyên `stale = False`, `stale_mode = NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY` do đồng hồ cục bộ reset theo từng cycle.
- **Online F3/F5 runtime:** triển khai `WallClockStalePolicy` trong [ood.py](../src/soh/ood.py) với ứng viên mặc định `max_observation_age_seconds = 86400.0` (24 giờ cho sự kiện cập nhật theo phiên sạc, tách biệt với ngưỡng polling 5 giây của telemetry tức thời Phase 1) và `max_future_skew_seconds = 5.0`. Timestamp thiếu, thiếu múi giờ (naive) hoặc lệch tương lai vượt 5 giây đều trả `STALE` với mã lý do tường minh và `soh_percent = null`.

## 4. Đo tài nguyên và giới hạn triển khai

- Môi trường đo: `Windows-10-10.0.26300-SP0`, Python `3.11.9`, `16` CPU logic, RAM vật lý `16,497,901,568` byte.
- Kích thước `rf_model.joblib`: **28,577,815 byte** (28.58 MB ≤ ngân sách ứng viên 50,000,000 byte).
- Thời gian kiểm SHA-256 (manifest + code + schema + policy + model) và nạp mô hình: **4310.89 ms**.
- Peak working set trước nạp: `61,906,944` byte; sau nạp: `260,829,184` byte; sau toàn bộ kiểm tra: `586,764,288` byte.
- Độ trễ F3.3 + F3.4 cho 1 phiên đã trích HI (100 mẫu sau 5 warmup): **p95 = 130.727 ms**, **p99 = 156.164 ms**, throughput **9.38 phiên/s**.
- Độ trễ trọn vòng F3.1 → F3.4 → F5 từ chuỗi sạc staging (25 chu kỳ cell `1-1`): **p95 = 123.834 ms**, **p99 = 125.043 ms**.
- **Giới hạn:** Kết quả đo trên Windows Python runtime; chưa suy diễn sang ESP32/embedded và chưa xác minh trên pack Lishen 2S1P.

## 5. Ràng buộc bất biến Phase 2 (`P3-IT-02`)

| Tệp Phase 2 | SHA-256 trước và sau suy luận F3 |
|---|---|
| `phase2_soc_delivery/artifacts/capacity_metadata.json` | `bcd2f28b57d9b21ed43f99561d6b8dfc263aaf2ba38c2e60759584f27479e8e0` |
| `phase2_soc_delivery/results/p25/ekf_config.json` | `1508778b1d827c80e844641bde0bc4029494eaf5c1b662bd1a190f80647ce7c8` |
| `phase2_soc_delivery/results/p26/metrics.json` | `47cc07535ab1dc6f6e10cc9247a342dcb73d41a80b25cbcc838b23d61f2eaa4e` |
