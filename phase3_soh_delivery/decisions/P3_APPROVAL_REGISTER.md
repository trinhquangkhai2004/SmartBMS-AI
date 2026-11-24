# Phase 3 — Sổ quyết định và phê duyệt

Cập nhật 20/11/2026 (Asia/Saigon), theo spec v1.2 §9. Người phụ trách Phase 3 là owner cấp nghiệp vụ, tên và bằng chứng ký duyệt chờ ghi nhận. Người dùng đã xác nhận ranh giới F2/F3 của v1 và báo rằng nhóm đã duyệt D01. P3.0 chờ bổ sung metadata quyết định D01 để đóng hồ sơ.

| ID | Quyết định hoặc chính sách | Owner | Reviewer / ngày duyệt | Trạng thái | Bằng chứng để khóa |
|---|---|---|---|---|---|
| D01 | RT-Batt v2 là nguồn chính. Người dùng báo nhóm đã duyệt. | Phụ trách Phase 3 | Chờ tên và ngày giờ duyệt thực tế | `GROUP_APPROVAL_REPORTED` | [Bản ghi D01](P3_DATASET_CHANGE_RECORD.md), phản hồi “D01 đã được nhóm duyệt”. Chờ revision và biên bản gốc. |
| D02 | Trung vị dung lượng xả cycle 1–5 cho 76 cell đủ điều kiện. Loại 7-5 khỏi tập nhãn v1, giữ đủ khóa truy vết. | Phụ trách dữ liệu | Người dùng duyệt trực tiếp trong chat ngày 20/11/2026 (UTC+07) | `APPROVED` | [Chính sách nhãn v1](../configs/p3_soh_reference_policy.yaml), xác nhận bên dưới. |
| D03 | Dự đoán cuối sạc, dùng lần xả kế tiếp duy nhất cùng cell–cycle làm nhãn sau cuối xả. Q_observed (Ah) = paired_dq_raw / 1000. Áp dụng cutoff và diễn giải dung lượng vận hành theo policy v1. | Phụ trách dữ liệu | Người dùng duyệt trực tiếp trong chat ngày 20/11/2026 (UTC+07) | `APPROVED` | [Chính sách nhãn v1](../configs/p3_soh_reference_policy.yaml), xác nhận bên dưới. |
| D04 | Duyệt p35-r1 cho cuối sạc: `delta_q_350_358_ah`, `q_cc_ah`, `q_cv_ah`, `q_cv_over_q_cc`. Cửa sổ 3,50–3,58 V trong đoạn sạc dòng thấp. IC và thermal ngoài bộ v1. | Phụ trách mô hình | Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer), 2026-11-22T11:11:00+07:00 | `APPROVED` | [Quyết định trong chat](codex://threads/01a1f732-e6c8-7212-8549-7f676a3526e3) · [Chi tiết D04](#d04-p35-r1) · [Danh sách SHA-256](../manifests/p3_5_SHA256SUMS.txt). |
| D05 | Khóa p34-r1, 57/19 cell và 5 fold. | Phụ trách mô hình | Người dùng duyệt trực tiếp qua chat, ghi nhận 2026-11-20T20:44:08+07:00 | `APPROVED_WITH_CONDITIONS` (đã hoàn tất) | [Phân bố fold](../reports/P3_4_PROTOCOL_BALANCE.md) · [Nhật ký P3.7](../reports/test_exposure_ledger.md). |
| D06 | RF cân bằng theo cell là mô hình chính. Macro-MAE dev 0,7015 pp. Tệp 28,58 MB. p95 24,0 ms trên Windows development. Giữ ablation không trọng số. | Phụ trách mô hình | Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer), 2026-11-22T15:57:44+07:00 | `APPROVED` | [Bằng chứng](../reports/P3_6_MODEL_RESOURCE_BUDGET.md) · [Phê duyệt trong chat](codex://threads/01a1f73a-0102-73f2-8e1a-fabc053f76bb). |
| D07 | ER5 dùng FULL_ELIGIBLE. MAX tuyệt đối ≤ 10,0 pp theo từng cell cho cả raw và VALID. Raw coverage ≥ 99,0% toàn tập và ≥ 95,0% mỗi cell. VALID ≥ 85,0% toàn tập. Chẩn đoán riêng cell dưới 90% VALID và hai dải SoH tham chiếu. | Phụ trách Phase 3 | Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer), 2026-11-22T15:57:44+07:00 | `APPROVED` | [Bằng chứng](../configs/p3_er5_evaluation.json) · [Phê duyệt trong chat](codex://threads/01a1f73a-0102-73f2-8e1a-fabc053f76bb). |
| D08 | Ridge bắt buộc, train-median làm sanity và XGBoost là đối chứng trên cùng schema/fold. | Phụ trách mô hình | Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer), 2026-11-22T15:57:44+07:00 | `APPROVED` | [Bằng chứng](../reports/P3_6_WEIGHT_ABLATION.md) · [Phê duyệt trong chat](codex://threads/01a1f73a-0102-73f2-8e1a-fabc053f76bb). |
| D09 | F2 giữ dung lượng hiệu chuẩn. F3 xuất sang F5. Phản hồi dung lượng F3 → F2 tắt trong v1. | Phụ trách tích hợp | Người dùng xác nhận phạm vi qua chat, 20/11/2026 (Asia/Saigon) · Kiểm chứng P3-IT-02 tại P3.8, 2026-11-23T21:30:50+07:00 | `APPROVED_AND_VERIFIED_IN_P3_8` | D09-v1 dưới đây. `P3-IT-02` đã PASS tại P3.8 ([Báo cáo P3.8](../reports/P3_8_INTEGRATION_TEST.md) · [Biên bản P3.8](../manifests/p3_8_verification.json)). |
| D10 | Miền nghiên cứu RT-Batt LFP tại 30°C. | Phụ trách Phase 3 | Chờ xác nhận | `SPEC_SELECTED` | Kiểm chứng bên ngoài trước khi mở rộng miền. |
| D11 | Chạy chuyển đổi bằng LOCAL_DOCKER_HARDENED với đúng image d11-r1 đã kiểm. | Phụ trách dữ liệu | Reviewer D11 theo xác nhận của người dùng; chờ tên, giờ duyệt và biên bản gốc. | `APPROVED_AS_REPORTED_BY_REQUESTER` | [Quyết định đường chuyển đổi](../manifests/p3_conversion_route.json). |
| D12 | Duyệt nguyên bản p36-r1. Guard thống kê bảo thủ, biên cell-weighted P01/P99 và sigma_trees. Ghi nhận độ phủ dev 93,23% và hành vi ở cell 7-2, 4-7. | Phụ trách mô hình | Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer), 2026-11-22T15:57:44+07:00 | `APPROVED` | [Bằng chứng](../reports/P3_6_D12_D13_REVIEW_ADDENDUM.md) · [Phê duyệt trong chat](codex://threads/01a1f73a-0102-73f2-8e1a-fabc053f76bb). |
| D13 | Jump 5 pp, K=2, ổn định 2 pp, gap tối đa 2 cycle. Hai resync OOF. Offline stale=False (`NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY`). Online wall-clock trên miền RT-Batt v2: ngưỡng tuổi quan sát tối đa 86.400 giây (24 giờ), dung sai đồng hồ tương lai 5 giây; timestamp thiếu/naive trả `STALE` và F5 tính lại tuổi khi đọc/hiển thị. | Phụ trách tích hợp | Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer), 2026-11-22T15:57:44+07:00 (offline) · 2026-11-23T21:30:50+07:00 (online) | `APPROVED` | [Phụ lục P3.6](../reports/P3_6_D12_D13_REVIEW_ADDENDUM.md) · [Báo cáo P3.8](../reports/P3_8_INTEGRATION_TEST.md) · [Biên bản P3.8](../manifests/p3_8_verification.json) · [Phê duyệt P3.8](#phê-duyệt-p38-inference_verified-và-d13-online). |
| D14 | Dòng dương khi xả, âm khi sạc. Integration test dùng tiền tố P3-IT. | Phụ trách dữ liệu | Chờ xác nhận | `SPEC_SELECTED` | So sánh hợp đồng Phase 2, bằng chứng UT/IT. |
| D15 | FIXED_CV_N_ESTIMATORS. Refit XGBoost 200 cây trên toàn dev, tắt early stopping và eval_set. | Phụ trách mô hình | Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer), 2026-11-22T15:57:44+07:00 | `APPROVED` | [Bằng chứng](../reports/P3_6_XGB_REFIT_AUDIT.md) · [Phê duyệt trong chat](codex://threads/01a1f73a-0102-73f2-8e1a-fabc053f76bb). |
| D16 | Chẩn đoán theo hai dải reference SoH ≥80% và <80%, không thay đổi tập nghiệm thu FULL_ELIGIBLE. | Phụ trách đánh giá | Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer), 2026-11-23T10:48:49+07:00 | `APPROVED` | [Hai dải SoH P3.7](../reports/P3_7_SOH_BAND_DIAGNOSTICS.csv) · [Biên bản P3.7](#phê-duyệt-p37-test_reported-và-er5_pass). |

Khi duyệt, ghi tên owner và reviewer thực tế, ngày giờ kèm múi giờ, trạng thái phê duyệt, revision và mã băm artifact căn cứ. Các vai trò trên cần nhóm xác nhận khi phân công.

## D09 — Ranh giới F2/F3 của v1

Người dùng xác nhận phạm vi kỹ thuật qua phản hồi trong chat ngày 20/11/2026 (Asia/Saigon). Bản ghi phạm vi trong hồ sơ lần này là **D09-v1**.

- **F2** ước lượng SoC bằng EKF với `Q_model` cố định theo bản hiệu chuẩn Phase 2. **F3** ước lượng SoH theo từng cell. F5 nhận kết quả để hiển thị và theo dõi, gồm `soh_percent`, `status`, `observed_at` và `model_version` theo hợp đồng P3.8.
- `f3_to_f2_capacity_feedback: false` áp dụng cho toàn bộ v1. Tiêu chí `P3-IT-02` tại P3.8 đã **PASS**: phát kết quả F3 không làm thay đổi `Q_model`, hồ sơ mô hình Phase 2 và hồ sơ ER4 đã khóa (SHA-256 `capacity_metadata.json`, `ekf_config.json` và `p26/metrics.json` bất biến theo [Báo cáo P3.8](../reports/P3_8_INTEGRATION_TEST.md) và [Biên bản P3.8](../manifests/p3_8_verification.json)). [Bàn giao Phase 2](../../phase2_soc_delivery/handoff/PHASE_2_SOC_V1_CLOSEOUT.md)
- **Phase 4** tích hợp F3 → F5 với phản hồi dung lượng vẫn tắt. Sau khi có dữ liệu kiểm chứng trên pin mục tiêu ở **Phase 5**, nhóm mới xem xét F3 → F2 qua thay đổi được phê duyệt riêng. Cần xác minh quy đổi SoH thành dung lượng hữu dụng cho đúng cell và so sánh sai số SoC giữa dung lượng cố định và dung lượng cập nhật trên dữ liệu độc lập. Nếu đạt tiêu chí đã thống nhất, F2 chỉ nhận SoH `VALID`, còn hiệu lực và đúng cell đang ước lượng. Khi thiếu bất kỳ điều kiện nào, F2 dùng dung lượng đã được chấp nhận gần nhất.

## Phê duyệt bộ nhãn P3.3 v1

“Oke tôi duyệt D02 cho 76 cell, giữ cell 7-5 ngoài tập nhãn v1 và duyệt D03 như đề xuất.”

Ghi nhận lúc 2026-11-20T20:05:38+07:00 từ chat hiện tại. Phạm vi gồm 143.863 nhãn trên 76 cell. Phê duyệt áp dụng cho đúng các tệp đã kiểm tại [biên bản đọc lại](../manifests/p3_3_readback.json). Trạng thái dự thảo nhúng trong tệp thể hiện thời điểm tạo dữ liệu. P3.4 dùng phiên bản được xác định bằng SHA-256 trong chính sách và manifest mốc.

## D05 p34-r1

Người dùng duyệt có điều kiện cho đúng bộ ID và năm fold đã tạo. Điều kiện hoàn tất gồm bảng tầng theo fold, trạng thái P3.7 UNOPENED và đối chiếu mã SHA-256.

- reports/P3_4_PROTOCOL_BALANCE.md — `f9a4d8610cd5a64648433dad52f5561bc67c057b7688260877bb55cbe5e8dc3b`
- reports/test_exposure_ledger.md — `2e548b41de3cc1fd85d929562050e851826fdae82fa30788293d539aa740bff4`
- reports/P3_4_LEAKAGE_AUDIT.md — `abb810826952b2bce0c828dab3d9b077cd7d6e24c773e80902410998de3fd368`
- manifests/p3_split_manifest.json — `a364c48d2903bcdb42794502aff1facdd01de4d5b0322417fc3a721c8a66ef7a`
- manifests/p3_cv_fold_manifest.json — `45305db16fdf8efb29f52a1a0b3b4c7fb39d6416b356cab9a15b0e36998cd274`

## D04 p35-r1

Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer) duyệt trực tiếp trong chat. Họ tên và vai trò được bổ sung theo xác nhận khi duyệt p36-r1. Quyết định lúc 2026-11-22T11:11:00+07:00, ghi sổ lúc 2026-11-22T11:26:09+07:00. [Xác nhận trong chat](codex://threads/01a1f732-e6c8-7212-8549-7f676a3526e3)

Tin xác nhận thuộc lượt `01a20173-4194-7f01-bd39-00617814135a`, tin nhắn `01a20173-4223-70f0-8d0d-ed3bc58febe3`. Người dùng cho phép cập nhật sổ, chốt P3.5 và triển khai P3.6 trên 57 cell development.

Đã so khớp 14/14 SHA-256. Bốn HI đủ trên toàn bộ 106.733 phiên và trên từng cell development. UT-010 (UT-10) đạt 11/11 theo nhật ký đã đối chiếu. [Đọc lại P3.5](../manifests/p3_5_readback.json) · [Độ phủ](../reports/P3_5_FEATURE_AVAILABILITY.md) · [Nhật ký UT-010](../reports/P3_5_UT_010.log)

## Phê duyệt p36-r1 và khóa D07

Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer) duyệt ngày 2026-11-22T15:57:44+07:00. Đối chiếu 36/36 SHA-256 của [bản ứng viên gốc](../manifests/p36_r1_candidate_snapshot.json). [Tin xác nhận](codex://threads/01a1f73a-0102-73f2-8e1a-fabc053f76bb), lượt `01a20279-c6db-7411-884d-feadcadde7c8`, tin `01a20279-c761-72d2-b204-996b3fca0fd6`.

D13 đã đáp ứng điều kiện cho phát lại offline. P3.8 phải xác lập và kiểm thử stale wall-clock trước INFERENCE_VERIFIED.
D07 được khóa trước tiếp xúc held-out. Mẫu số giữ toàn bộ khóa đã duyệt, bao gồm phiên thiếu hoặc bị guard chặn.
Một cell thiếu dự đoán số cho MAX bắt buộc thì tiêu chí MAX của cell đó chưa đánh giá được. Vi phạm đã quan sát vẫn dẫn tới ER5_NOT_MET.

## Phê duyệt P3.7 (TEST_REPORTED và ER5_PASS)

Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer) xác nhận ký `PASS` cho mốc **P3.7** lúc `2026-11-23T10:48:49+07:00` sau khi kiểm toán toàn vẹn 5/5 đầu vào P3.7, 18/18 đầu ra P3.7 và 36/36 artifact đóng băng của `p36-r1` trên đĩa (0 sai lệch SHA-256).

- Chấp thuận biên bản [p3_7_same_session_recovery.json](../manifests/p3_7_same_session_recovery.json) (lỗi đọc tên cột projection `ArrowInvalid` xảy ra trước khi giải mã bất kỳ dòng nhãn hay tệp tín hiệu held-out nào; giữ nguyên 100% model, guard, schema và D07).
- Xác nhận kết luận độc lập **`ER5_PASS`** theo `D07` trên miền **RT-Batt v2 LFP 30 °C** (`FULL_ELIGIBLE` 37.130 khóa / 19 cell; raw coverage 100,00%; VALID coverage 95,84%; MAX tuyệt đối lớn nhất 4,6181 pp ≤ 10,0 pp trên cả 19 cell; 2 dải chẩn đoán `SOH_GE_80` và `SOH_LT_80` đều `OBSERVED`).
- Tách bạch rõ phạm vi: `P3.7 = PASS` (`TEST_REPORTED`) và `ER5_PASS` **không** đồng nghĩa `INFERENCE_VERIFIED` (chờ kiểm chứng và duyệt P3.8, bao gồm ngưỡng wall-clock stale `D13`) và **`HARDWARE_VALIDATED = false`** đối với Lishen 2S1P.
- Không mở lại tập held-out cho bất kỳ điều chỉnh ngưỡng hay siêu tham số nào. [Tóm tắt P3.7](../reports/P3_7_TEST_SUMMARY.md) · [Biên bản kết quả](../manifests/p3_7_evaluation_result.json)

## Phê duyệt P3.8 (INFERENCE_VERIFIED và D13 online)

Trịnh Quang Khải (Phụ trách Phase 3 / Reviewer) xác nhận ký `PASS` cho mốc **P3.8 (`INFERENCE_VERIFIED`)** và phê duyệt chính sách **D13 online** lúc `2026-11-23T21:30:50+07:00`.

- **Biên bản căn cứ đã review:** [manifests/p3_8_verification.json](../manifests/p3_8_verification.json) — SHA-256 `32e76a97227978b1c8d1c8b5e2519f617522d4efa273d6192fa64a0a0dbcd471` (đối chiếu khớp 11/11 đầu ra P3.8 trên đĩa và trong sổ tiến độ).
- **Chính sách D13 online được duyệt cho v1:** ngưỡng tuổi quan sát tối đa **`86.400` giây** (24 giờ), dung sai đồng hồ tương lai **`5` giây**; timestamp `observed_at` hoặc `now_utc` bị thiếu/thiếu múi giờ trả `STALE` với mã lý do tường minh (`MISSING_OBSERVED_AT_TIMESTAMP` / `UNTRUSTED_OBSERVED_AT_TIMESTAMP` / `UNTRUSTED_REFERENCE_CLOCK`), và F5 tính lại tuổi tại thời điểm đọc/hiển thị để chuyển sang `HELD_STALE` (`current_soh_percent = null`, giữ `held_last_valid_soh_percent`) khi quá 24 giờ không có phiên sạc mới. Chế độ phát lại offline vẫn giữ `NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY`.
- **Phạm vi và ranh giới miền:** áp dụng trên miền **RT-Batt v2 LFP 30 °C** (`A123_APR18650M1A`), chặn fail-closed mọi thiết bị ngoài allowlist hoặc thiếu metadata thiết bị (`NOT_VALIDATED_FOR_DEVICE`, `soh_percent = null`), cưỡng chế `f3_to_f2_capacity_feedback = false` (`P3-IT-02` PASS theo D09), và **`hardware_validated = false`** (chưa xác minh trên pack Lishen 2S1P).
- **Bằng chứng kiểm thử và hợp đồng:** 73 test trong [P3_8_TEST_LOG.txt](../reports/P3_8_TEST_LOG.txt) (71 đạt, 2 ca cũ bỏ qua, 0 lỗi), parity 37.130 phiên P3.7 (0 lệch trạng thái, max |ΔSoH| = `5,68 × 10⁻¹⁴` pp), 25 chu kỳ staging cell `1-1` (`ΔHI = 0`), tương thích schema Phase 1 đạt 4/4, và xác minh độc lập JSON Schema Draft 2020-12 hợp lệ trên các phản hồi `VALID`, `NOT_VALIDATED_FOR_DEVICE`, `STALE`, `INVALID_INPUT`.
- **Cổng tiếp theo:** mở `P3.9 = IN_PROGRESS` để đóng gói hồ sơ tái lập và bàn giao Phase 3 (không mở lại tập held-out, không sửa các artifact đã đóng băng). [Báo cáo P3.8](../reports/P3_8_INTEGRATION_TEST.md) · [Biên bản P3.8](../manifests/p3_8_verification.json)


