# P3.6 — Ngân sách và đo tài nguyên RF

RF đã đóng gói **28,577,815 byte** (28.578 MB với 1 MB = 1.000.000 byte), trong giới hạn 50,000,000 byte. 40 lần fit CV cho tám cấu hình RF weighted, sau đó refit theo thứ tự macro-MAE để kiểm ngân sách.

Ứng viên đứng đầu CV rf_weighted-5. Bản được chọn rf_weighted-5. Chênh lệch so với đứng đầu CV +0.000000 pp. Các lần thử đóng gói [{'model': 'rf', 'candidate': 'rf_weighted-5', 'bytes': 28577815}].

Số đo trên Windows-10-10.0.26300-SP0, CPU , 16 luồng logic, RAM 16,497,901,568 byte, Python 3.11.9. RF inference một luồng trên 200 phiên dev với HI đã tính và sau 5 phiên làm nóng. Cần đo lại trong môi trường F5 thực tế.

| Phép đo | Kết quả |
|---|---:|
| Thời gian kiểm SHA-256 và nạp model | 373.742 ms |
| Peak working set trước khi load | 135,057,408 byte |
| Peak working set sau khi load | 281,776,128 byte |
| Peak working set đến hết inference, gồm chuẩn bị mẫu | 281,776,128 byte |
| RF predict p95 / p99 | 14.773 / 16.164 ms |
| RF predict + sigma p95 / p99 | 23.997 / 26.331 ms |

So sánh trước và sau reload trên cả 106.733 hàng. Chênh lớn nhất của RF là 5.68e-14 pp. Dung sai 1e-10 pp.

[Số đo chi tiết](../manifests/p3_6_resource_measurement.json)
