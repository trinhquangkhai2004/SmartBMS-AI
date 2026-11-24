# P3.4 — Cân bằng protocol giữa các tập

Phương án p34-r1 gồm 57 cell development và 19 cell held-out. D05 được phê duyệt có điều kiện, các điều kiện đã hoàn tất.

Tầng chỉ dùng mức dòng xả tham chiếu thứ nhất. Ba mức đầu đã khớp với số đo P3.2. Mức thứ tư nằm ngoài phép chia vì BatteryML ghi 1 C và staging đo gần 2 C. Mức thứ hai và thứ ba được báo để thấy độ cân bằng còn lại. [Chính sách chia](../configs/p3_split_policy.yaml) · [Danh mục protocol](../manifests/protocol_inventory.csv)

## Mức dòng xả thứ 1

| C-rate | Tổng cell | Development | Held-out |
|---|---|---|---|
| 2 C | 5 | 4 | 1 |
| 3 C | 24 | 18 | 6 |
| 4 C | 23 | 17 | 6 |
| 5 C | 24 | 18 | 6 |

## Mức dòng xả thứ 2

| C-rate | Tổng cell | Development | Held-out |
|---|---|---|---|
| 1 C | 15 | 14 | 1 |
| 2 C | 15 | 9 | 6 |
| 3 C | 15 | 14 | 1 |
| 4 C | 16 | 9 | 7 |
| 5 C | 15 | 11 | 4 |

## Mức dòng xả thứ 3

| C-rate | Tổng cell | Development | Held-out |
|---|---|---|---|
| 1 C | 16 | 11 | 5 |
| 2 C | 15 | 13 | 2 |
| 3 C | 15 | 8 | 7 |
| 4 C | 15 | 13 | 2 |
| 5 C | 15 | 12 | 3 |

## Phân bố tầng dòng xả thứ nhất trong validation

| Fold | Cell | Nhãn | 2 C | 3 C | 4 C | 5 C |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 11 | 20858 | 1 | 5 | 4 | 1 |
| 2 | 12 | 21986 | 2 | 4 | 3 | 3 |
| 3 | 11 | 20879 | 0 | 3 | 4 | 4 |
| 4 | 12 | 22135 | 1 | 4 | 2 | 5 |
| 5 | 11 | 20875 | 0 | 2 | 4 | 5 |
| **Tổng** | **57** | **106733** | **4** | **18** | **17** | **18** |

Fold 3 và 5 thiếu cell 2 C trong validation. Bốn cell 2 C thuộc validation của các fold 1, 2 và 4.

## Giới hạn diễn giải

- Tầng 2 C có một cell held-out. Kết quả của cell này có bằng chứng hạn chế cho cả nhóm 2 C.
- Mức thứ nhất chỉ đại diện cho một chiều của profile xả.
- Có 0 tổ hợp ba mức đầu xuất hiện ở cả hai tập. Thiết kế đánh giá trên cell chưa từng dùng để fit trong phạm vi các profile RT-Batt. Đánh giá trên protocol hoàn toàn mới sẽ cần một revision được duyệt riêng.

[Danh sách ID theo tập](../manifests/p3_split_manifest.json)

