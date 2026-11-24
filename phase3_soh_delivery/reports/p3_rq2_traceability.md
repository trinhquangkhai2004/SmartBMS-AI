# P3.0 — Truy vết RQ2

Với mỗi cell RT-Batt, tại cuối một phiên sạc đủ điều kiện, F3 dùng dữ liệu đã quan sát đến thời điểm đó để ước lượng SoH theo dung lượng. Khi pha xả hợp lệ kế tiếp kết thúc, dung lượng xả quan sát được dùng để dựng nhãn đối chiếu. Quy tắc ghép cùng cell và mốc thời gian chờ xác minh tại P3.2–P3.3.

| Câu hỏi | Thiết kế kiểm tra | Bằng chứng dự kiến |
|---|---|---|
| Nhóm đặc trưng sạc nào có ích cho dự đoán SoH? | So sánh các nhóm đặc trưng dung lượng nạp trong dải điện áp, pha CC/CV và tỷ số Q_CV/Q_CC trên cùng các fold theo cell. Chọn dải điện áp và hiệu chỉnh bằng tập phát triển. Khóa các ablation trước khi mở held-out. | Kiểm tra cửa sổ điện áp và thời điểm có đặc trưng ở P3.5, kết quả CV ở P3.6 và ablation đã khóa ở P3.7. |
| Random Forest so với XGBoost thế nào trên cell chưa từng dùng để huấn luyện? | Dùng cùng cell, đặc trưng và phép chia. Giữ Ridge làm baseline bắt buộc. So sánh theo MAE tính riêng mỗi cell rồi lấy trung bình, đồng thời công bố coverage và sai số theo cell. | Split/CV manifest P3.4, báo cáo CV và model freeze P3.6, báo cáo held-out P3.7. |

**Giới hạn diễn giải.** Các cell có thể chạy profile xả khác nhau. Dòng xả và ngưỡng điện áp cắt có thể ảnh hưởng dung lượng quan sát ngay cả sau khi chuẩn hóa theo Q_ref của từng cell. Báo cáo cân bằng profile khi chia và ghi rõ ngữ nghĩa dung lượng vận hành tương đối theo cell nếu thiếu phép xả tham chiếu chuẩn hóa. Kết luận chỉ áp dụng cho dữ liệu đã đánh giá.

**Ranh giới F2/F3.** Logbook §2.3.2 dùng ECM/EKF cho SoC, §2.3.3 dùng Random Forest cho SoH. Theo D09-v1, F2 giữ `Q_model` theo hiệu chuẩn Phase 2, F3 chuyển kết quả theo từng cell sang F5. Phản hồi dung lượng tắt toàn bộ v1. P3-IT-02 sẽ kiểm điều kiện này tại P3.8. [Chi tiết D09](../decisions/P3_APPROVAL_REGISTER.md#d09--ranh-giới-f2f3-của-v1).
