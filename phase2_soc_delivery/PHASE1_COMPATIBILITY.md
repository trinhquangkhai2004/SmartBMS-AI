# P2.7 · Đối chiếu giao diện SoC với Phase 1

Bộ chuyển đổi `src/phase1_adapter.py` triển khai chữ ký `SoCEstimator.estimate(measurement_window, config)` và trả về `app.schemas.EstimationResult` của Phase 1. Lời gọi hiện tại trong `app/state.py` truyền một mẫu mới nhất và `config=None`, nên kết quả vẫn là `NOT_READY` với `value_pct=null`. Bộ chuyển đổi nằm trong gói nghiên cứu ngoại tuyến. Phần mềm Phase 1, API, cơ sở dữ liệu và dashboard giữ nguyên phiên bản đang có.

## Dữ liệu đầu vào

Phép phát lại nhận các đối tượng `app.schemas.Telemetry` đã qua xác thực Pydantic. Mỗi cửa sổ thuộc cùng một thiết bị, phiên và cell 1S, với một cảm biến nhiệt độ. Điện áp lấy từ `cell_voltages_v[0]`, dòng lấy từ `pack_current_a` (A, dương khi xả), thời gian lấy từ `uptime_ms / 1000` (s). Mẫu ở nhiệt độ ngoài miền 25 °C được giữ với trạng thái ngoài miền của EKF. Trường `updated_at` để trống vì thời gian chạy của thiết bị không xác định được thời điểm UTC.

`ReplayConfig` chỉ định định danh thiết bị, phiên, số thứ tự mẫu đầu, SoC ban đầu theo tỷ phần, điện áp phân cực ban đầu và hàm tạo một EKF mới. Mỗi lần gọi phát lại từ mốc khởi tạo đó. Cửa sổ phải có số thứ tự liên tiếp, thời gian không giảm và cả ba nhóm cảm biến hợp lệ. Một bản ghi sai thứ tự, không hợp lệ, ngoài phạm vi 1S hoặc mang nguồn `HARDWARE` kết thúc cửa sổ với `INVALID_INPUT`. Khoảng thời gian giữa hai bản ghi được chuyển cho EKF với trạng thái chưa có bằng chứng về tải. Phép thử dùng tham số tổng hợp độc lập, không nạp hoặc cấp quyền dùng mẫu ECM đang giữ ở G10.

## Ánh xạ kết quả

| Kết quả EKF nghiên cứu | Trạng thái Phase 1 | Giá trị Phase 1 |
|---|---|---|
| `VALID`, cờ chất lượng bằng false | `VALID` | SoC theo %, phạm vi `CELL` |
| `VALID`, cờ chất lượng bằng true hoặc chưa biết | `NOT_READY` | null |
| `INVALID_INPUT`, `OUT_OF_DOMAIN` | `INVALID_INPUT` | null |
| `GAP_UNOBSERVED`, `NOT_READY` | `NOT_READY` | null |
| `NUMERICAL_ERROR` hoặc trạng thái lạ | `ERROR` | null |

Giao diện chẩn đoán `adapter.replay(window, config)` trả từng cặp `estimation` và `diagnostics`. Bản ghi nghiên cứu giữ nguyên giá trị SoC, trạng thái, nguyên nhân, phiên bản mô hình, thông tin phê duyệt và cờ `LOW_SOC_MODEL_UNCERTAIN` từ EKF. Phase 1 chỉ cho phép năm mã cảnh báo thiết bị đã định nghĩa. Ánh xạ trên tránh hiển thị giá trị có cờ như một kết quả bình thường, đồng thời giữ đủ mẫu nghiên cứu để chấm `FULL_DYNAMIC`. Các cờ trong `Telemetry.warnings` vẫn do thiết bị hoặc nguồn phát lại cung cấp.

## Kiểm tra lại trên Windows

Chạy từ thư mục `phase2_soc_delivery` với đường dẫn tới bản Phase 1 cần đối chiếu.

```powershell
$phase1Repo = 'D:\Study\PBL5\pbl5-bms-software'
$env:PYTHONPATH = $phase1Repo
$env:PYTHONDONTWRITEBYTECODE = '1'
& (Join-Path $phase1Repo '.venv-py314\Scripts\python.exe') -B -m pytest -W error -p no:cacheprovider -q tests/test_phase1_adapter.py
```

Ba bản ghi gốc của `sample_data/telemetry_1s.jsonl` có nhiệt độ 28–28,2 °C và cho kết quả ngoài miền. Trường hợp tổng hợp riêng đặt nhiệt độ bằng 25 °C để kiểm tra đường tính hợp lệ, đổi mili giây sang giây và quy ước dấu dòng. Các ca khác kiểm tra lệnh gọi thực của Phase 1, ngưỡng cảnh báo 3,2976 V, mất mẫu, mất quan sát và cách ly thiết bị/phiên. Đây là kiểm tra tương thích giao diện, không đánh giá ER4 hay độ chính xác trên pin thật.
