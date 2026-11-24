# P3.5 — Cửa sổ điện áp và phân đoạn sạc

Miền kiểm tra gồm 57 cell development, 106.733 phiên đủ điều kiện nhãn. Mỗi cửa sổ áp dụng cho đoạn sạc dòng thấp có nhãn CC–CV. Tích phân hình thang chia đoạn tuyến tính tại hai biên V. Yêu cầu quan sát cả hai biên trên đoạn này.

| Cửa sổ (V) | Số phiên đủ | Macro-MAE theo cell (điểm %) | MAE trung bình theo cell ở fold 1–5 |
|---|---:|---:|---|
| 3.45–3.55 | 106733 | 0.7954 | 0.9901, 0.5409, 0.6971, 0.7091, 1.0709 |
| 3.50–3.58 | 106733 | 0.7885 | 1.0038, 0.4832, 0.7612, 0.6203, 1.1173 |
| 3.45–3.60 | 18393 | Thiếu độ phủ để so sánh cùng mẫu |  |

Cửa sổ chọn cho v1 là delta_q_350_358_ah. Đối chiếu dùng Ridge chẩn đoán cố định alpha=1 cùng ba HI CC/CV, chuẩn hóa trên fold train và tổng trọng số ngang nhau theo cell. MAE tính riêng từng cell ngoài fold rồi lấy trung bình. Đây là điểm chọn cửa sổ trên development; ước lượng độ chính xác cuối cùng thuộc P3.7.

Pha CC nhanh và top-up yêu cầu plateau dòng quanh 5,5 A và 1,1 A. CV yêu cầu điện áp quanh 3,6 V cùng dòng suy giảm tới tối đa nửa dòng đầu CV. Mỗi đoạn tích phân chỉ dùng các khoảng đo trong cùng pha. Khe thời gian giữa hai nhãn sạc và khoảng giáp ranh CC/CV chưa phân loại bị bỏ; q_cc và q_cv mô tả phần điện lượng quan sát được. Điện lượng cửa sổ phản ánh riêng phần sạc dòng thấp. Các ngưỡng phân pha là quy tắc thực nghiệm cho RT-Batt, chưa có chuẩn pha độc lập hay xác minh trên Lishen.
