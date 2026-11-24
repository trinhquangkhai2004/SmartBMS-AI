# Nhật ký tiếp xúc tập held-out

**Bản chia** p34-r1. Niêm phong logic danh sách 19 ID ứng viên bằng SHA-256. D05 đã được duyệt có điều kiện cho bản chia và năm fold này.

SHA-256 bản chia `a364c48d2903bcdb42794502aff1facdd01de4d5b0322417fc3a721c8a66ef7a`. SHA-256 bản fold `45305db16fdf8efb29f52a1a0b3b4c7fb39d6416b356cab9a15b0e36998cd274`.

| Mốc | Phạm vi dữ liệu ghi nhận | Mục đích và ảnh hưởng |
|---|---|---|
| P3.2 trước khi có danh tính test | Kiểm toàn bộ canonical của 77 cell | Đối soát chất lượng, phép ghép và ý nghĩa dq. |
| P3.3 trước khi có danh tính test | Tạo nhãn và báo phân bố toàn nguồn | Báo cáo tổng hợp đã được xem trước khi chọn 19 ID. Ghi nhận lịch sử đó cho diễn giải kết quả. |
| P3.4 chuẩn bị danh sách | Cột cell_id của nhãn v1 và metadata protocol tĩnh | Thu 76 ID đủ điều kiện, khóa policy quota và seed trước phép chia. |
| 2026-11-20T20:14:15.676233+07:00 | Tệp eligibility chỉ gồm ID và metadata tĩnh | Sinh duy nhất một bản ứng viên 57/19. Chạy lặp cùng policy để đối soát byte. |
| P3.4 sau khi sinh danh sách | Chỉ khóa cell/cycle, số hàng và SHA-256 | Xác minh giao rỗng, tái lập split/fold, kiểm phạm vi canonical. Đánh giá theo giá trị held-out chưa diễn ra. |

**Trạng thái đánh giá held-out tại P3.7** `UNOPENED`.

Khóa D05, ghi nhận 2026-11-20T20:44:08+07:00. Kiểm tra trên manifest và báo cáo; quyền sử dụng ở P3.5 chỉ bao gồm 57 cell development.

## Quy tắc từ lúc khóa D05

Dùng 57 cell development để chọn cửa sổ và đặc trưng sạc, fit mô hình và hiệu chỉnh ngưỡng. Đánh giá held-out ở P3.7 sau khi cấu hình đã đóng băng. Mỗi lượt tiếp xúc sau khóa ghi ngày giờ, người thực hiện, mục đích, các trường đọc, mã băm bản chia và quyết định liên quan.

[Manifest ID](../manifests/p3_split_manifest.json) · [Kiểm kê rò rỉ](P3_4_LEAKAGE_AUDIT.md)



## P3.6 p36-r1

Ghi nhận lúc 2026-11-22T11:37:33+07:00 bởi Codex theo phê duyệt D04 của người dùng. Đọc bảng HI đã khóa, danh sách
split a364c48d2903bcdb42794502aff1facdd01de4d5b0322417fc3a721c8a66ef7a
và 57 JSON staging ký SHA-256 của cell development. Trường đọc để dựng nhãn là cell_id, cycle_id
và dq theo cycle. Chạy fit, hiệu chỉnh và đo inference bằng development. Số tệp giá trị của 19 cell held-out
đã đọc trong P3.6 là 0. Đánh giá P3.7 vẫn **UNOPENED**.

[Đối soát đầu vào](../manifests/p3_6_input_readback.json) · [Ứng viên model freeze](../manifests/p3_model_freeze.json)


## P3.7 — Lần mở held-out duy nhất

Trạng thái P3.7 kể từ 2026-11-22T16:07:51+07:00 (UTC+07) **OPENED_ONCE**. Codex thực thi theo quyết định
D07 của Trịnh Quang Khải. Phạm vi 19 cell và 37.130 khóa đủ điều kiện được chỉ định từ p34-r1.
Đọc khóa, nhãn tham chiếu đã khóa và tín hiệu sạc staging của 19 cell. Áp dụng các mô hình,
schema, OOD policy và guard p36-r1 đã ký. [Biên nhận](../manifests/p3_7_open_receipt.json)

- Manifest ký duyệt SHA-256 `934ca32afcc4a13b83bba5e08d30edbf6912fad448fa92c23617199495c631c7`.
- D07 SHA-256 `838e663ef5e2c3bce9826c103b7e5693d4187fdabb5c4c5f70c250f34556a203`.
- Split SHA-256 `a364c48d2903bcdb42794502aff1facdd01de4d5b0322417fc3a721c8a66ef7a`.
- Frozen guard SHA-256 `7d5f5e1c6ca879448f3f8941c39fd33278b77985923f5231a8211db1c6bfe3b2`.
- Evaluator SHA-256 `f1ccf8befaf2cb64fec6abbba995938bdc681e14d2796239fb180ebb1a04aff3`.

Mục này ghi đè trạng thái lịch sử UNOPENED. Quyền chạy held-out đã được sử dụng.


### P3.7 — Lần chạy gặp lỗi

2026-11-22T16:07:51+07:00 · `ArrowInvalid`. Biên nhận vẫn đã sử dụng.


### P3.7 — Tiếp tục cùng biên nhận sau lỗi schema

2026-11-22T16:10:41+07:00 · Lượt đầu dừng khi Arrow kiểm tra danh sách cột. Parquet nhãn v1 có
release_status. label_status thuộc trace ghép cặp. Không có dòng nhãn được giải mã, không có
tệp tín hiệu held-out được mở, không có dự đoán được ghi trước lỗi. Tiếp tục theo cùng biên nhận
sau khi sửa bộ đọc schema, giữ nguyên SHA-256 của model, guard, data policy và D07.
[Biên bản lỗi và mã băm bộ đọc](../manifests/p3_7_same_session_recovery.json)


### P3.7 — Hoàn tất lần đánh giá duy nhất

2026-11-22T16:11:24+07:00 · 37.130 khóa trên 19 cell. [Dự đoán và trạng thái guard](../reports/P3_7_HELDOUT_PREDICTIONS.parquet)
có SHA-256 9788ecb4d652245ad1184fd283a5145bebc63ec489dc74c175310db17221105b. Kết quả D07 **ER5_PASS**.
[Biên bản kết quả](../manifests/p3_7_evaluation_result.json)
