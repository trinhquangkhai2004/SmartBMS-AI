# P3.7 — Đo tài nguyên

Windows-10-10.0.26300-SP0, CPU , 16 CPU logic, Python 3.11.9. RF có cấu hình 8 luồng đã khóa.

RF **28,577,815 byte**. Kiểm SHA-256 và nạp tám mô hình mất 1687.7 ms.
Peak working set trước nạp 137,150,464 byte, sau nạp 502,845,440 byte, cuối lượt 970,596,352 byte. Tổng thời gian từ lúc mở nhãn đến hết đo inference 42.9 s.

Peak toàn lượt gồm Arrow, tám mô hình, tín hiệu tạm và ghi bằng chứng.
RF predict + sigma + guard trên 100 phiên đã tính HI có p95 **67.616 ms**, p99 **70.519 ms** và throughput **18.44 phiên/s**.
Đo trên Windows development. F5 thực tế và embedded còn chưa đo.
