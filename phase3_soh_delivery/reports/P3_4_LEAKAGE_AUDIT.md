# P3.4 — Kiểm tra rò rỉ và tái lập

**Kết quả kiểm tra** Đạt. P3.4 đã hoàn tất các điều kiện D05.

Bộ chọn ID chỉ nhận tệp eligibility gồm cell_id và ba mức dòng tham chiếu tĩnh. Container chọn ID chỉ được gắn bảng này, chính sách và thư mục đầu ra. Bước đối soát sau chia chỉ đọc cell_id và cycle_id của bảng nhãn và cell_id của canonical. Các trường SoH, Q_ref, dung lượng và tín hiệu đo nằm ngoài các cột được đọc.

| Tập | Cell | Khóa nhãn | Hàng canonical |
|---|---|---|---|
| Development | 57 | 106.733 | 67.248.432 |
| Held-out | 19 | 37.130 | 23.150.670 |
| Loại khỏi nhãn v1 | 1 | 0 | 1.337.557 |
| Tổng nguồn | 77 | 143.863 | 91.736.659 |

Development có 74.19% số nhãn và held-out có 25.81%. Cell 1-1 thuộc development và toàn bộ 1.499 khóa đi cùng nhau.
Hợp hai tập bằng 76 ID được duyệt và loại trừ 7-5. Giao ID, khóa nhãn và hàng canonical giữa hai tập đều bằng 0. Mỗi hàng canonical được gán từ duy nhất một cell vật lý.

## Năm fold development

Dùng GroupKFold 5 lượt với groups là cell_id của từng khóa nhãn development. Mỗi cell development xuất hiện đúng một lượt validation. Giao train và validation từng fold bằng 0, và 19 cell held-out vắng mặt trong cả năm lượt. [GroupKFold 1.7.2](https://scikit-learn.org/1.7/modules/generated/sklearn.model_selection.GroupKFold.html)

| Fold | Cell train | Cell validation | Nhãn train | Nhãn validation |
|---|---|---|---|---|
| 1 | 46 | 11 | 85.875 | 20.858 |
| 2 | 45 | 12 | 84.747 | 21.986 |
| 3 | 46 | 11 | 85.854 | 20.879 |
| 4 | 45 | 12 | 84.598 | 22.135 |
| 5 | 46 | 11 | 85.858 | 20.875 |

## Tái lập

Lượt chạy lại giữ nguyên đầu vào, thứ tự ID, phiên bản và seed 42. Cả hai manifest giống nhau từng byte.

- SHA-256 split `a364c48d2903bcdb42794502aff1facdd01de4d5b0322417fc3a721c8a66ef7a`.
- SHA-256 fold `45305db16fdf8efb29f52a1a0b3b4c7fb39d6416b356cab9a15b0e36998cd274`.

[Bằng chứng cấu trúc](../manifests/p3_4_audit_summary.json) · [Bằng chứng chạy lại](../manifests/p3_4_replay.json) · [Nhật ký kiểm thử](P3_4_TEST_LOG.txt)

