# P3.2 — Truy vết phiên sạc và lần xả kế tiếp của cell 1-1

**Trạng thái** `IN_PROGRESS`. Đã tái lập một cặp sạc–xả từ staging đã đọc lại độc lập. Quét ban đầu 13.163 hàng thuộc 16 chu kỳ của cell `1-1`. Ví dụ dưới đây dùng cycle `1` tại cả hai pha.

**Nguồn** `our_data/1-1.pkl` → `1-1.parquet` và `1-1.json`. Thứ tự `cycle_source_order` và `sample_index` lấy từ trật tự lưu của tệp nguồn. `time_s_raw` giữ giá trị `Time (s)`. [Manifest của cặp đã kiểm](../manifests/p3_2_first_cell_trace.json) · [Manifest staging](../data/staging/rt_batt_v2/conversion_manifest.json)

| Mốc | Cycle | Dòng mẫu | Thời gian nguồn (s) | Điện áp (V) | Dòng thô (mA) | Dung lượng thô (mAh) |
|---|---:|---:|---:|---:|---:|---:|
| Bắt đầu sạc | 1 | 0 | 0 | 2,7731 | 5.498,13 | 0 |
| Cuối sạc | 1 | 382 | 1.927 | 3,5999 | 54,811 | 1.175,6222 |
| Bắt đầu xả | 1 | 383 | 1.933 | 3,4021 | -5.498,13 | 1.175,6222 |
| Cuối xả | 1 | 835 | 4.179 | 1,9481 | -2.199,77 | 1,323 |

## Dấu dòng, thời điểm và dung lượng

- **Trạng thái và thứ tự.** Sạc có 383 hàng, gồm 114 hàng `Constant current charge` và 269 hàng `Constant current-constant voltage charge`. Sau khi sạc kết thúc ở 1.927 s, xả bắt đầu ở 1.933 s, cách 6 giây. Pha xả gồm 453 hàng với bốn nhãn `Constant current discharge_0` đến `Constant current discharge_3`. Hai pha quan sát được có thời gian tăng dần, không trùng, đảo hoặc thiếu. Nhãn gộp CC–CV cần kiểm chi tiết khi xác định ranh giới CC/CV ở P3.5.
- **Dấu dòng.** Cả 383 hàng sạc có dòng thô dương và cả 453 hàng xả có dòng thô âm. Với quy ước canonical P3.2 `I > 0` khi xả, phép quy đổi phù hợp cho trace này là `current_a = -current_ma_raw / 1000`. Staging giữ nguyên dấu và đơn vị thô.
- **Dung lượng xả.** Trường `capacity_mah_raw` giảm từ 1.175,6222 mAh xuống 1,323 mAh trong pha xả. Độ giảm **1.174,2992 mAh** khớp `dq[1] = 1.174,2992` trong JSON, tương đương **1,1742992 Ah** cho cặp này. Tích phân hình thang theo dòng và thời gian xấp xỉ **1.181,6323 mAh**, lệch **7,3331 mAh**. Cần kiểm công thức và tính nhất quán giữa hai cách tính khi audit toàn bộ nguồn.

**Hàm ý cho D03.** Trong ví dụ này, mốc quan sát đặc trưng là cuối sạc ở dòng mẫu 382. Dung lượng xả chỉ có đủ ở dòng mẫu 835. Ghép theo cùng cell và thứ tự pha quan sát được trong staging. `Time (s)` chỉ được dùng theo trục thời gian thô của trace, còn thứ tự giữa các cycle cần được xác minh trước khi áp dụng đại trà.

**Còn mở ở P3.2–P3.3.** Kiểm kê cell, cycle và protocol trên toàn nguồn, xác minh dấu/đơn vị dung lượng và quy tắc ghép khi thiếu mốc hoặc pha mơ hồ. D02 `Q_ref` và việc khóa D03 vẫn chờ audit đầy đủ.
