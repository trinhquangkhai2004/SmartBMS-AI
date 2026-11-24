# P3.5 — Kiểm tra đầu vào và thời điểm khả dụng

Bảng đầu ra có 106733 khóa cell–cycle duy nhất trên 57 cell thuộc development. Mỗi cell được kiểm tra theo danh sách cho phép đã khóa trước khi mở tệp vật lý. Chỉ tệp Parquet riêng theo ID development được đọc để tính đặc trưng. Các cột thời gian, V, I và nhãn trạng thái được chọn trên hàng sạc. Hàm dùng chung nhận tín hiệu sạc đến cuối phiên và từ chối trạng thái xả. ID, fold và chỉ số cuối phiên là metadata.

Nhãn dùng để so sánh cửa sổ được tính riêng từ JSON của từng cell development theo D02/D03. Khóa được đối chiếu đủ sau năm cycle khởi tạo và các loại trừ đã ghi ở P3.2. Q_ref, dung lượng xả, nhãn, số thứ tự cycle và thống kê tương lai đều nằm ngoài vector đặc trưng. Chuẩn hóa và fit Ridge chỉ dùng cell train trong mỗi fold. Chính sách phục vụ P3.6 phải giữ việc fit imputer, scaler và selector riêng theo train fold.

Đọc lại toàn bộ bảng đã kiểm tra schema, số hàng, khóa và fold. Ca runtime đối chiếu chính xác với bảng offline trên cell 1-1, cycle 6, cả giá trị và lý do thiếu. SHA-256 bảng đặc trưng: `1fd788eb75a1045f4d28ad6b87c87f3e93bf6ef2b3aa1884dd11cda338527188`. Đánh giá P3.7: UNOPENED.

## Đối soát bổ sung cho D04

UT-010 (UT-10) đối chiếu phiên ở hàng giữa của cell validation đầu tiên trong mỗi fold (5 phiên thực, 5 cell, 5 fold). Với từng phiên, đọc riêng các mẫu sạc từ đúng tệp cell dev, đổi mA thô sang A theo quy ước sạc âm và gọi hàm inference. Kiểm bằng phép so sánh chính xác cả 12 HI với bản offline, cùng mã lý do thiếu và chỉ số mẫu cuối. Xem log reports/P3_5_UT_010.log và tests/test_p35.py. Đây là kiểm tra tương đương hai đường gọi trên các phiên đã chọn.

Đối soát độ phủ độc lập giới hạn truy cập bằng SHA-256 của split/fold và danh sách development. Từng hàng trong 106.733 hàng khớp cell, fold và mốc kết thúc sạc trong trace. Bộ kiểm độ phủ chỉ đọc bảng feature development và các cột tín hiệu/khóa của 57 tệp staging development. Trạng thái P3.7 là UNOPENED. Điểm CV dùng chọn cửa sổ là điểm phát triển nội bộ.
