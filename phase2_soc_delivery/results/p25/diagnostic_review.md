# Đối chiếu EKF với Coulomb Counting trên DST/FUDS

Trong 35.440 quan sát danh định, cả hai phương pháp đều trả SoC trên toàn cửa sổ. CC có sai số cực đại thấp hơn EKF ở cả bốn run khi dùng cùng prior lịch sử. Reference từ bộ đếm Arbin và CC cùng dựa vào dòng của cùng thiết bị. Phép đối chiếu này chưa định lượng được sai số tuyệt đối so với SoC vật lý độc lập.

| Run | MAX SoC EKF (pp) | MAX SoC CC (pp) | MAX innovation (V) | Số quan sát dưới 3,2976 V |
|---|---:|---:|---:|---:|
| DST 50SOC | 1,761 | 0,233 | 0,466 | 283 |
| DST 80SOC | 1,888 | 0,149 | 0,537 | 276 |
| FUDS 80SOC | 1,829 | 0,226 | 0,403 | 270 |
| FUDS 50SOC | 1,870 | 0,164 | 0,439 | 324 |

Trên hai run FUDS, sai lệch điện áp đo so với điện áp dự báo trước correction đạt 0,403–0,439 V. Những mẫu điện áp thấp vẫn đóng góp vào sai số và độ phủ toàn cửa sổ. Giới hạn mô hình G10 vẫn còn sau khi hiệu chỉnh cấu hình EKF.

## Ảnh hưởng của prior và nhiễu

- Khi giảm prior 20 điểm phần trăm, sai số cực đại ban đầu và các mẫu tiếp theo trên FUDS đạt 14,872 pp cho 80SOC và 19,090 pp cho 50SOC. Khoảng đầu tiên có sai số không quá 5 pp liên tục trong 60 giây bắt đầu lần lượt sau 11,14 và 66,66 giây. Thời gian hội tụ được báo riêng, và tất cả mẫu đầu run vẫn được chấm.
- Với bias dòng giả lập +0,05 A, MAX của CC trên hai run FUDS đạt 7,551 và 4,860 pp. EKF đạt 1,802 và 2,383 pp trên các mẫu còn hợp lệ, với độ phủ 10.966/11.098 và 6.913/6.999. Dòng đã thêm bias vượt miền dòng quan sát ở 132 và 86 mẫu. Mọi mẫu này vẫn có dòng riêng trong trajectory và trong mẫu số.
- Nhiễu Gaussian giả lập có độ lệch chuẩn 0,010 V và 0,020 A. FUDS 80SOC có 54 mẫu ngoài miền và FUDS 50SOC có 43 mẫu ngoài miền. Các tham số perturbation là điều kiện thí nghiệm được ghi trước khi chạy.
- Prior ban đầu thực tế của hai run 80SOC lớn hơn 80%. Cộng 20 pp sẽ vượt 100%, nên hai trường hợp đó có trạng thái INAPPLICABLE. Tổng cộng có 30 lượt replay hợp lệ trên 32 tổ hợp run và kịch bản.

Kết quả lựa chọn cấu hình dùng hai run FUDS. Bảng đầy đủ từng ứng viên nằm trong `candidate_selection.json`; `metrics.json` và 30 tệp trong `trajectories/` lưu các phân nhóm, độ phủ, trạng thái và sai số từng quan sát. Báo cáo này chỉ bao gồm P2.5.
