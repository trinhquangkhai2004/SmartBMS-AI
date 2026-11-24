# P3.6 — Hiệu chỉnh OOD và jump/resync

Tập hiệu chỉnh gồm 106.733 dự đoán OOF từ 57 cell development. Mỗi cặp biên dùng các giá trị hữu hạn của cell train trong đúng fold. CDF sắp tăng ổn định, mỗi cell có tổng trọng số 1 cho từng HI. P01/P99 là giá trị đầu tiên mà CDF đạt ngưỡng. Tệp hiệu chỉnh chứa cả biên theo từng fold và biên tính lại ở lần refit toàn dev. Sigma độ lệch chuẩn quần thể giữa các cây là chỉ báo bất đồng.

| Số HI vi phạm | Phân vị sigma | Ngưỡng sigma (pp) | OOD | Uncertain sau OOD | VALID trước jump | Macro-MAE VALID (pp) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.90 | 1.171414 | 7868 | 6907 | 91958 | 0.651365 |
| 1 | 0.95 | 1.545342 | 7868 | 2443 | 96422 | 0.659175 |
| 1 | 0.99 | 2.938600 | 7868 | 0 | 98865 | 0.670748 |
| 2 | 0.90 | 1.171414 | 3498 | 8686 | 94549 | 0.658232 |
| 2 | 0.95 | 1.545342 | 3498 | 3721 | 99514 | 0.669050 |
| 2 | 0.99 | 2.938600 | 3498 | 207 | 103028 | 0.680813 |
| 3 | 0.90 | 1.171414 | 1646 | 9784 | 95303 | 0.662501 |
| 3 | 0.95 | 1.545342 | 1646 | 4627 | 100460 | 0.672285 |
| 3 | 0.99 | 2.938600 | 1646 | 753 | 104334 | 0.684549 |

Ứng viên D12 dùng **2 HI vi phạm** và sigma P95 (**1.545342 pp**). OUT_OF_DOMAIN có ưu tiên trước MODEL_UNCERTAIN. Loại phiên thiếu HI, thiếu history hoặc stale theo mã trạng thái tương ứng. Các phiên bị chặn xóa chuỗi xác nhận đang chờ và giữ mốc hợp lệ cuối.

Ứng viên D13 dùng ngưỡng jump **5 pp**, cần **2 phiên** lệch tối đa **2 pp** giữa các dự đoán xác nhận, với khoảng cách tối đa **2 cycle** giữa hai xác nhận. Mốc cập nhật theo phiên mới nhất. Dữ liệu staging đặt lại đồng hồ theo cycle nên khoảng cách xác nhận tính theo thứ tự cycle. Stale từ hệ thống thời gian thực là đầu vào của guard.

| Tập tính điểm | Số hàng | Số cell có điểm | Macro-MAE (pp) | Macro-RMSE (pp) |
|---|---:|---:|---:|---:|
| Toàn bộ đủ điều kiện | 106733 | 57 | 0.701471 | 0.827479 |
| VALID sau tất cả guard | 99512 | 57 | 0.668971 | 0.788723 |

Độ phủ VALID 93.2345%. Số hàng theo trạng thái {'OUT_OF_DOMAIN': 3498, 'MODEL_UNCERTAIN': 3721, 'SOH_JUMP_ANOMALY': 2, 'VALID': 99512}. Resync 2 lần. Trong các lần đó, 1 lần nhãn tham chiếu đổi quá ngưỡng chẩn đoán so với phiên hợp lệ trước. Con số này dùng mô tả đối chiếu trên OOF, vì dung lượng tham chiếu chỉ có sau xả.

So sánh độ phân tán cây giữa OOF và lần refit toàn dev (P50/P90/P95/P99, pp).

| Nguồn | P50 | P90 | P95 | P99 |
|---|---:|---:|---:|---:|
| OOF | 0.492345 | 1.171414 | 1.545342 | 2.938600 |
| Refit toàn dev | 0.335318 | 0.504040 | 0.588152 | 0.856430 |

Bảng so sánh jump/resync có đủ tổ hợp cấu hình. Quy tắc chọn thử dùng các giới hạn tỷ lệ từ lưới đã đăng ký; ưu tiên cấu hình gần (5 pp, K=2, 2 pp, 2 cycle) nhất và dùng thứ tự quyết định cố định khi bằng nhau.

| Jump (pp) | K | Ổn định (pp) | Gap (cycle) | Jump bị chặn | Resync | VALID | Macro-MAE VALID (pp) | Đạt giới hạn thử |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 4 | 2 | 1 | 1 | 2 | 2 | 99512 | 0.668971 | True |
| 4 | 2 | 1 | 2 | 2 | 2 | 99512 | 0.668971 | True |
| 4 | 2 | 1 | 5 | 2 | 2 | 99512 | 0.668971 | True |
| 4 | 2 | 2 | 1 | 2 | 2 | 99512 | 0.668971 | True |
| 4 | 2 | 2 | 2 | 2 | 2 | 99512 | 0.668971 | True |
| 4 | 2 | 2 | 5 | 2 | 2 | 99512 | 0.668971 | True |
| 4 | 3 | 1 | 1 | 10 | 2 | 99504 | 0.668662 | True |
| 4 | 3 | 1 | 2 | 10 | 2 | 99504 | 0.668662 | True |
| 4 | 3 | 1 | 5 | 10 | 2 | 99504 | 0.668662 | True |
| 4 | 3 | 2 | 1 | 10 | 2 | 99504 | 0.668662 | True |
| 4 | 3 | 2 | 2 | 10 | 2 | 99504 | 0.668662 | True |
| 4 | 3 | 2 | 5 | 10 | 2 | 99504 | 0.668662 | True |
| 5 | 2 | 1 | 1 | 2 | 2 | 99512 | 0.668971 | True |
| 5 | 2 | 1 | 2 | 2 | 2 | 99512 | 0.668971 | True |
| 5 | 2 | 1 | 5 | 2 | 2 | 99512 | 0.668971 | True |
| 5 | 2 | 2 | 1 | 2 | 2 | 99512 | 0.668971 | True |
| 5 | 2 | 2 | 2 | 2 | 2 | 99512 | 0.668971 | True |
| 5 | 2 | 2 | 5 | 2 | 2 | 99512 | 0.668971 | True |
| 5 | 3 | 1 | 1 | 10 | 2 | 99504 | 0.668662 | True |
| 5 | 3 | 1 | 2 | 10 | 2 | 99504 | 0.668662 | True |
| 5 | 3 | 1 | 5 | 10 | 2 | 99504 | 0.668662 | True |
| 5 | 3 | 2 | 1 | 10 | 2 | 99504 | 0.668662 | True |
| 5 | 3 | 2 | 2 | 10 | 2 | 99504 | 0.668662 | True |
| 5 | 3 | 2 | 5 | 10 | 2 | 99504 | 0.668662 | True |
| 7 | 2 | 1 | 1 | 2 | 2 | 99512 | 0.668971 | True |
| 7 | 2 | 1 | 2 | 2 | 2 | 99512 | 0.668971 | True |
| 7 | 2 | 1 | 5 | 2 | 2 | 99512 | 0.668971 | True |
| 7 | 2 | 2 | 1 | 2 | 2 | 99512 | 0.668971 | True |
| 7 | 2 | 2 | 2 | 2 | 2 | 99512 | 0.668971 | True |
| 7 | 2 | 2 | 5 | 2 | 2 | 99512 | 0.668971 | True |
| 7 | 3 | 1 | 1 | 10 | 2 | 99504 | 0.668662 | True |
| 7 | 3 | 1 | 2 | 10 | 2 | 99504 | 0.668662 | True |
| 7 | 3 | 1 | 5 | 10 | 2 | 99504 | 0.668662 | True |
| 7 | 3 | 2 | 1 | 10 | 2 | 99504 | 0.668662 | True |
| 7 | 3 | 2 | 2 | 10 | 2 | 99504 | 0.668662 | True |
| 7 | 3 | 2 | 5 | 10 | 2 | 99504 | 0.668662 | True |

Cấu hình chờ reviewer D12/D13. Held-out P3.7 vẫn UNOPENED.

[Số liệu và biên đầy đủ](../manifests/p3_6_guard_calibration.json) · [Chính sách ứng viên](../artifacts/soh/ood_policy.json)
