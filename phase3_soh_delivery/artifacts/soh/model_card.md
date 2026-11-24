# F3 SoH — RT-Batt v2, ứng viên p36-r1

Ước lượng SoH theo dung lượng vận hành tương đối của từng cell LFP ở cuối phiên sạc đủ điều kiện. Nhãn là dung lượng xả kế tiếp chia trung vị dung lượng xả năm cycle đầu của cùng cell theo D02/D03. Dữ liệu phát triển RT-Batt v2 thu ở buồng 30 °C. Nhiệt độ theo mẫu vắng mặt.

Đầu vào theo thứ tự D04 delta_q_350_358_ah, q_cc_ah, q_cv_ah, q_cv_over_q_cc.

Model F3 chính RF cell-balanced. 57 cell dev và 106.733 phiên, macro-MAE OOF 0.701471 pp. Độ phủ VALID sau guard trên OOF 93.2345%. Dữ liệu held-out ở trạng thái UNOPENED. F3 chỉ xuất sang F5 và phản hồi dung lượng tới F2 tắt trong v1.

Cần reviewer D06/D08/D12/D13/D15 và điều kiện D07 trước đánh giá held-out. ER5 và kiểm chứng trên pin mục tiêu chưa đánh giá. Dùng đúng schema/guard đã băm. Chỉ nạp model joblib có nguồn và SHA-256 khớp manifest.

[Ứng viên model freeze](../../manifests/p3_model_freeze.json) · [So sánh dev](../../reports/P3_6_WEIGHT_ABLATION.md) · [Hiệu chỉnh guard](../../reports/P3_6_OOD_CALIBRATION.md)
