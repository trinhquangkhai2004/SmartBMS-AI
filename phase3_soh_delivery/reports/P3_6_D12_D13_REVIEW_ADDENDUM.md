# P3.6 — Độ phủ OOD theo cell và quy ước stale khi phát lại offline

Phụ lục cho reviewer D12/D13, ứng viên `p36-r1`. Phạm vi là 106.733 dự đoán ngoài fold (OOF) của 57 cell development. Phiên bản manifest dùng để đối chiếu có SHA-256 `76654f841054f51796b86ec22e53fda5baf4826c69bbc97c0d5baadd1f9dbc9b`. P3.7 vẫn UNOPENED.

## D12 — Cách đọc hai bảng

- [Thống kê 57 cell, xếp từ độ phủ thấp nhất](P3_6_D12_CELL_OOF.csv). Mỗi dòng có fold, mẫu số, bốn trạng thái loại trừ lẫn nhau, % VALID và các tổ hợp HI vượt biên trong nhóm OOD. Với mỗi nhóm, bảng ghi số phiên, MAE, P95 và MAX của |RF thô − SoH tham chiếu| theo pp. P95 dùng nội suy tuyến tính. Ô trống biểu thị nhóm có 0 phiên. OOD_OR_UNCERTAIN gộp hai nhóm tương ứng. JUMP được thống kê riêng. Cột abs_gt_10pp_n dùng để đối chiếu mô tả trên dev.
- [Chi tiết bốn HI theo cell và nhóm](P3_6_D12_FEATURE_BREACHES.csv). Mỗi dòng ghi P01/P99 của tập train thuộc đúng fold, số mẫu dưới P01 và trên P99. Các nhóm ALL và OOD_OR_UNCERTAIN là tổng hợp. Một phiên có thể vi phạm nhiều HI, do đó cộng số vi phạm theo HI có thể lớn hơn số phiên OOD.
- [Mã tái lập](../scripts/review_p36_cell_ood.py). Ghép dự đoán/nhãn OOF với HI đã khóa theo cell, cycle và fold. Phát lại guard đã băm theo thứ tự cycle riêng trong từng cell. OUT_OF_DOMAIN khi từ hai HI trở lên vượt biên nghiêm ngặt. MODEL_UNCERTAIN khi chưa bị OOD và sigma giữa các cây vượt 1,545342 pp. Tổng sau phát lại khớp hồ sơ hiệu chỉnh: 99.512 VALID, 3.498 OOD, 3.721 UNCERTAIN, 2 JUMP.

### Toàn bộ cell có độ phủ VALID dưới 90%

Sai số trong bảng là MAE của RF thô (pp). Các phân vị, cực đại và vi phạm từng HI của cả 57 cell nằm trong hai bảng CSV ở trên.

| Cell | Tổng | VALID | OOD | UNCERTAIN | JUMP | VALID (%) | MAE VALID | MAE OOD | MAE UNCERTAIN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 7-2 | 2.025 | 71 | 1.484 | 470 | 0 | 3,51 | 0,545 | 0,882 | 0,333 |
| 4-7 | 2.211 | 1.108 | 1.092 | 10 | 1 | 50,11 | 1,201 | 2,453 | 3,712 |
| 4-1 | 2.212 | 1.583 | 81 | 548 | 0 | 71,56 | 0,838 | 0,727 | 0,791 |
| 5-4 | 1.957 | 1.456 | 350 | 151 | 0 | 74,40 | 1,504 | 2,848 | 2,341 |
| 3-8 | 2.337 | 1.766 | 159 | 412 | 0 | 75,57 | 0,404 | 0,261 | 0,303 |
| 5-6 | 2.455 | 1.991 | 205 | 259 | 0 | 81,10 | 0,591 | 0,811 | 0,489 |
| 7-3 | 1.290 | 1.089 | 58 | 143 | 0 | 84,42 | 0,918 | 0,782 | 2,488 |
| 6-6 | 2.463 | 2.089 | 0 | 374 | 0 | 84,82 | 0,427 | — | 2,298 |
| 1-1 | 1.499 | 1.297 | 0 | 201 | 1 | 86,52 | 0,627 | — | 1,459 |
| 2-7 | 2.197 | 1.933 | 0 | 264 | 0 | 87,98 | 0,368 | — | 0,529 |
| 8-5 | 1.343 | 1.189 | 60 | 94 | 0 | 88,53 | 0,941 | 0,856 | 2,263 |
| 1-7 | 1.673 | 1.494 | 0 | 179 | 0 | 89,30 | 0,700 | — | 0,595 |

### Hai trường hợp cần quyết định

**7-2, fold 1.** Trong 1.484 phiên OOD, 1.476 có delta_q_350_358_ah dưới P01 (0,018535 Ah), 1.446 có q_cv_over_q_cc dưới P01 (0,019337), 901 có q_cv_ah dưới P01 (0,017936 Ah) và 46 có q_cc_ah trên P99 (1,161539 Ah). Có 901 phiên đồng thời thấp ở điện lượng cửa sổ, điện lượng CV và tỷ số. Tỷ số dùng chung q_cv_ah ở tử số, nên hai phiếu vi phạm liên quan tới CV có thể cùng phản ánh một thay đổi. Phần lớn phiên OOD cũng vi phạm điện lượng cửa sổ.

| Cell và nhóm | Phiên | MAE (pp) | P95 tuyệt đối (pp) | MAX tuyệt đối (pp) |
|---|---:|---:|---:|---:|
| 7-2 VALID | 71 | 0,545 | 1,052 | 1,104 |
| 7-2 OUT_OF_DOMAIN | 1.484 | 0,882 | 1,723 | 2,508 |
| 7-2 MODEL_UNCERTAIN | 470 | 0,333 | 0,788 | 1,629 |
| 7-2 OOD hoặc UNCERTAIN | 1.954 | 0,750 | 1,688 | 2,508 |
| 4-7 VALID | 1.108 | 1,201 | 3,577 | 3,737 |
| 4-7 OUT_OF_DOMAIN | 1.092 | 2,453 | 3,895 | 4,461 |
| 4-7 MODEL_UNCERTAIN | 10 | 3,712 | 3,805 | 3,807 |
| 4-7 OOD hoặc UNCERTAIN | 1.102 | 2,465 | 3,894 | 4,461 |

**4-7, fold 5.** Cả 1.092 phiên OOD đều có delta_q_350_358_ah trên P99 (0,045442 Ah). Cùng nhóm đó, 829 phiên có q_cv_ah trên P99, 736 có q_cv_over_q_cc trên P99 và 104 có q_cc_ah dưới P01. Ngoài hai nhóm bị chặn trong bảng, một phiên JUMP có sai số tuyệt đối 3,354 pp.

**Diễn giải cho D12.** Cell 7-2 có lệch phân bố HI so với train-fold theo đúng định nghĩa đã khóa. Đồng thời, RF vẫn dự đoán sát nhãn ở nhiều phiên bị chặn, rõ nhất là nhóm MODEL_UNCERTAIN. Cả 1.954 phiên bị chặn của cell này đều có sai số dưới 2,51 pp. Dữ liệu không cung cấp nhãn độc lập xác nhận miền vật lý của từng phiên. Vì vậy chưa thể tính tỷ lệ báo động giả về miền vật lý. Cell 4-7 cho thấy guard có thể tập trung các phiên sai số cao hơn ở cell khác. Nếu mục tiêu là phát hiện sai số lớn đồng thời giữ độ phủ, hãy đối chiếu quy tắc hiện hành và các ứng viên dev trên cả 57 cell theo cùng tiêu chí sai số/độ phủ từng cell, trước khi quyết định đổi rule hoặc phiên bản. Mốc 90% dùng để liệt kê theo yêu cầu rà soát; D07 còn chờ duyệt.

## D13 — NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY

**Quy ước đề xuất để reviewer duyệt trước P3.7.** Với phát lại offline theo cycle từ staging RT-Batt, bên gọi truyền `stale=False` cho kiểm tra tuổi theo đồng hồ thực. Ghi vào cấu hình đánh giá P3.7 chế độ `NOT_APPLICABLE_OFFLINE_CYCLE_REPLAY`. Đồng hồ cục bộ khởi động lại mỗi cycle nên không suy ra được tuổi theo lịch; thời điểm chạy notebook cũng không biểu thị thời điểm thu tín hiệu. Các số đo coverage offline có phạm vi này.

Phát lại theo cell, phiên bản model/schema và cycle nguồn. Guard giữ kiểm tra cycle trùng hoặc lùi (`STALE_INPUT / NONINCREASING_CYCLE`), đủ lịch sử, đủ HI, OOD, sigma, jump và gap xác nhận tối đa 2 cycle. Cờ thời gian offline không xác nhận tính hợp lệ cho những kiểm tra này.

**P3.8 online.** Bên gọi F3/F5 tính tuổi từ timestamp quan sát thực cùng cơ sở thời gian và ngưỡng freshness đã được duyệt, rồi truyền cờ stale vào chính guard đã khóa. F5 hiển thị trạng thái held/stale và tuổi của giá trị hợp lệ cuối. Cần xử lý riêng timestamp thiếu hoặc không đáng tin. Việc áp dụng ở runtime thuộc P3.8. Spec v1.2 (§ P3.8, dòng 457) yêu cầu reviewer duyệt stale age trước P3.7. Nếu không có căn cứ đặt ngưỡng wall-clock bằng giây trên RT-Batt, ghi nhận rõ ngoại lệ phạm vi offline và phần ngưỡng online chờ bằng chứng trong quyết định D13 trước khi mở held-out. Phụ lục này là bằng chứng cho quyết định đó.
