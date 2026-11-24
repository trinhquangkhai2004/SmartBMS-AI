# P3.1 — Kiểm tra nguồn RT-Batt v2

**Kết quả kiểm tra nguồn:** `SOURCE_VERIFIED`. P3-DT-01 đạt. Tệp gốc được lưu ở chế độ chỉ đọc tại `data/raw/rt_batt/v2/our_data.zip`.

| Mục | Bằng chứng |
|---|---|
| Nguồn | RT-Batt v2, DOI `10.17632/nsc7hnsg4s.2`, CC BY 4.0, công bố 24/05/2022 |
| Thời điểm hoàn tất tải | 20/11/2026, 12:56:29 (UTC+07:00). Giá trị UTC đầy đủ trong biên nhận. |
| Dung lượng ZIP | 1.188.136.932 byte, khớp metadata Mendeley |
| SHA-256 | `071d24617153693b0d29059568525e620f6af6512acc9d00c98c7adcf15125db`, khớp metadata Mendeley |
| Kiểm cấu trúc ZIP | 78 mục gồm 1 thư mục và 77 tệp; CRC tất cả mục đạt. Kiểm đường dẫn thoát thư mục, trùng tên và xung đột theo Windows, symlink/reparse, định dạng nén và mã hóa đều đạt. |
| Kiểm quota | 4.245.730.747 byte tổng sau giải nén, tệp lớn nhất 88.277.079 byte, tỷ lệ nén lớn nhất 4,088×. Giới hạn audit của archive này là 200 mục, 5 GiB tổng, 128 MiB/tệp và 20×/tệp. |
| Tệp theo phần mở rộng | `.pkl` — 77. Chưa kiểm tính đủ điều kiện theo cell hoặc chu kỳ. |
| Kiểm thử tự động | 11/11 đạt với Python 3.11. Bao gồm đường dẫn, trùng tên, symlink, vượt tỷ lệ nén, CRC sai, opcode bị cắt, global chưa rõ và byte thừa. |
| Milestone P3.1 | `P3_1_PASS`. Đã chuyển đủ 77 tệp và đọc lại độc lập cả schema, mã băm, 91.736.659 hàng tín hiệu và 146.122 chu kỳ trong staging. |

Nguồn chính thức và bằng chứng: [Mendeley v2](https://data.mendeley.com/datasets/nsc7hnsg4s/2), [metadata tệp từ Mendeley](https://data.mendeley.com/public-api/datasets/nsc7hnsg4s/files?folder_id=root&version=2), [biên nhận](../manifests/rt_batt_download_receipt.json), [manifest đầy đủ](../manifests/rt_batt_source_manifest.json), [SHA-256](../checksums.sha256), [kiểm tĩnh và điều kiện D11](P3_1_PICKLE_SECURITY.md).

## 20 tệp đầu theo thứ tự trong ZIP

| Đường dẫn | Sau giải nén (byte) | Trong ZIP (byte) |
|---|---:|---:|
| `our_data/1-1.pkl` | 53.553.885 | 17.309.189 |
| `our_data/1-2.pkl` | 88.277.079 | 26.465.614 |
| `our_data/1-3.pkl` | 57.386.031 | 16.584.872 |
| `our_data/1-4.pkl` | 45.359.349 | 12.851.046 |
| `our_data/1-5.pkl` | 58.293.447 | 15.708.660 |
| `our_data/1-6.pkl` | 37.837.770 | 11.531.117 |
| `our_data/1-7.pkl` | 48.766.119 | 12.643.743 |
| `our_data/1-8.pkl` | 64.277.382 | 16.534.420 |
| `our_data/2-2.pkl` | 72.468.021 | 17.725.536 |
| `our_data/2-3.pkl` | 54.662.280 | 15.800.798 |
| `our_data/2-4.pkl` | 41.683.974 | 10.719.526 |
| `our_data/2-5.pkl` | 36.734.361 | 9.460.792 |
| `our_data/2-6.pkl` | 40.868.952 | 10.228.166 |
| `our_data/2-7.pkl` | 55.935.489 | 14.492.515 |
| `our_data/2-8.pkl` | 44.391.066 | 11.821.956 |
| `our_data/3-1.pkl` | 52.017.495 | 13.086.974 |
| `our_data/3-2.pkl` | 57.696.618 | 14.740.068 |
| `our_data/3-3.pkl` | 40.708.923 | 10.182.588 |
| `our_data/3-4.pkl` | 41.969.958 | 10.792.425 |
| `our_data/3-5.pkl` | 81.214.392 | 22.848.248 |

## Tái lập

Từ thư mục Phase 3, trên máy có Python 3.11 và tệp gốc đã đối chiếu:

```powershell
py -3.11 -B -m unittest discover -s tests -v
py -3.11 scripts/audit_rt_batt_source.py --static-pickle
```

Lệnh audit tính lại SHA-256, kiểm CRC và tạo inventory. Đọc ZIP và rà opcode trong luồng dữ liệu chỉ đọc. Mục P3.2 chỉ bắt đầu khi staging đã được tạo và xác nhận theo P3.1.

Bằng chứng đóng P3.1 gồm [lần chạy Docker](../manifests/p3_conversion_execution.json), [kiểm đọc lại](../manifests/p3_staging_readback.json) và [manifest staging](../data/staging/rt_batt_v2/conversion_manifest.json).
