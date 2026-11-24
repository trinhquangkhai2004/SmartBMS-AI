# D01 — Thay đổi nguồn dữ liệu Phase 3

Ngày ghi nhận: 20/11/2026 (Asia/Saigon). Căn cứ: Spec Phase 3 v1.2, mục 0, P3.0 và §9. Chủ quyết định là người phụ trách Phase 3 theo spec. Người dùng báo nhóm đã duyệt D01. Chi tiết người duyệt, giờ duyệt, revision và biên bản gốc đang chờ bổ sung.

| Trường | Giá trị |
|---|---|
| `DATASET_SOURCE_SELECTED` | `RT_BATT_V2` |
| `NASA_PREVIOUS_LOGBOOK_DECISION` | `SUPERSEDED_PENDING_GROUP_CHANGE_RECORD` |
| Quyết định trước đây | Logbook PBL5 v1.2 ngày 19/11/2026, §2.3.3, Bảng 2.20. NASA 0,38; CALCE 0,36; Experimental Data 0,26. |
| Quyết định của người phụ trách | RT-Batt v2 / HUST làm nguồn chính cho F3, DOI 10.17632/nsc7hnsg4s.2. |
| Phê duyệt sửa Logbook | `GROUP_APPROVAL_REPORTED` qua phản hồi của người dùng. Chờ bổ sung thông tin biên bản để chốt hồ sơ. |
| Miền nghiên cứu | 77 cell công bố, LFP/graphite, 1,1 Ah, 3,3 V, 30°C, cùng giao thức sạc và nhiều profile xả. Số cell và chu kỳ đủ điều kiện sẽ được xác định tại P3.2–P3.3. |

Nguồn: [Logbook hiện hành](../../Tai_lieu/Logbook_PBL5_F2_v1.2_2026-11-19.docx), [RT-Batt v2](https://data.mendeley.com/datasets/nsc7hnsg4s/2), [repo tác giả](https://github.com/HAIRLAB/Health_status_prediction).

## Phụ lục AHP đề xuất

Giữ bốn tiêu chí và tỷ lệ trọng số công bố trong Bảng 2.20. Các trọng số hiển thị cộng thành 1,01 do độ chính xác của bảng, nên chia mỗi trọng số cho 1,01 khi tính tổng. Giữ tỷ lệ ưu tiên lịch sử NASA/CALCE trên từng hàng, rồi thêm mức ưu tiên RT-Batt đề xuất từ chứng cứ dưới đây và chuẩn hóa mỗi hàng để tổng bằng 1. Đây là ma trận đề xuất từ trọng số đã làm tròn. Nhóm cần rà lại các so sánh cặp trước khi ký revision.

| Tiêu chí Bảng 2.20 | Trọng số gốc | NASA | CALCE | RT-Batt v2 |
|---|---:|---:|---:|---:|
| SoH Reference Availability | 0,41 | 0,3333 | 0,3333 | 0,3333 |
| V/I/T Feature Availability | 0,24 | 0,3830 | 0,3085 | 0,3085 |
| Dataset Documentation | 0,18 | 0,3333 | 0,3333 | 0,3333 |
| Relevance to 18650 Cell Experiments | 0,18 | 0,2857 | 0,2857 | 0,4286 |
| **Tổng có trọng số** | **1,00 sau chuẩn hóa** | **0,3366** | **0,3189** | **0,3444** |
| **Hạng đề xuất** | | **2** | **3** | **1** |

- **Tham chiếu SoH.** RT-Batt ngang NASA/CALCE ở vòng đánh giá tài liệu. Nguồn RT-Batt mô tả thí nghiệm lão hóa nhiều cell, nhưng nguồn dung lượng cấp chu kỳ, cut-off, khả năng ghép nhãn và Q_ref vẫn cần audit. NASA công bố trường dung lượng xả. CALCE mô tả các chương trình cycling có dữ liệu dung lượng. [RT-Batt v2](https://data.mendeley.com/datasets/nsc7hnsg4s/2), [NASA Aging Datasets](https://data.nasa.gov/dataset/li-ion-battery-aging-datasets), [CALCE Battery Research Data](https://calce.umd.edu/data).
- **V/I/T.** Giữ lợi thế NASA vì nguồn mô tả điện áp, dòng và nhiệt độ đo theo thời gian. Đặt RT-Batt ngang CALCE ở mức ưu tiên tạm thời của hàng này. Meta RT-Batt công bố nhiệt độ môi trường 30°C. Kênh nhiệt độ và tín hiệu sạc từng mẫu của RT-Batt cần xác minh ở P3.2. [NASA Aging Datasets](https://data.nasa.gov/dataset/li-ion-battery-aging-datasets), [CALCE Battery Research Data](https://calce.umd.edu/data), [RT-Batt v2](https://data.mendeley.com/datasets/nsc7hnsg4s/2).
- **Tài liệu.** Đặt ba nguồn ngang nhau vì đều có tài liệu công khai về thiết kế thí nghiệm. RT-Batt có DOI cố định cho phiên bản và repo của tác giả. [NASA Aging Datasets](https://data.nasa.gov/dataset/li-ion-battery-aging-datasets), [CALCE Battery Research Data](https://calce.umd.edu/data), [RT-Batt v2](https://data.mendeley.com/datasets/nsc7hnsg4s/2), [repo tác giả](https://github.com/HAIRLAB/Health_status_prediction).
- **Phù hợp với thí nghiệm 18650.** Đề xuất ưu tiên 1,5 lần so với mỗi nguồn cũ vì RT-Batt dùng A123 APR18650M1A LFP/graphite, cùng giao thức sạc để nghiên cứu đặc trưng sạc và nhiều profile xả trên 77 cell công bố. NASA cũng dùng cell 18650 nhưng mục dữ liệu gốc chỉ mô tả Li-ion. CALCE có nhiều dòng cell và mục A123 trên trang nguồn là cell đường kính 25,4 mm. [Bài báo RT-Batt](https://doi.org/10.1039/D2EE01676A), [RT-Batt v2](https://data.mendeley.com/datasets/nsc7hnsg4s/2), [NASA Aging Datasets](https://data.nasa.gov/dataset/li-ion-battery-aging-datasets), [CALCE Battery Research Data](https://calce.umd.edu/data).

Lợi thế đề xuất của RT-Batt so với NASA khoảng 0,008. Nếu nhóm đánh giá RT-Batt ngang NASA/CALCE ở tiêu chí 18650, NASA đứng đầu theo các giả định còn lại. Phụ lục lưu điểm đề xuất. Revision và phản hồi AHP cụ thể của nhóm đang chờ đối chiếu với biên bản. Bằng chứng ghép phiên sạc–xả và tính đủ điều kiện của dữ liệu sẽ được bổ sung sau P3.2–P3.3. Phạm vi kiểm chứng là cell RT-Batt tại 30°C, còn Lishen 2S1P cần thí nghiệm riêng.

## Duyệt revision

| Người phụ trách | Người duyệt nhóm | Ngày duyệt | Bằng chứng | Trạng thái |
|---|---|---|---|---|
| Người phụ trách Phase 3 theo spec v1.2 | Chờ tên người duyệt | Chờ ngày giờ thực tế | Spec §9 D01, phụ lục trên và phản hồi “D01 đã được nhóm duyệt” ngày 20/11/2026 (Asia/Saigon) | `GROUP_APPROVAL_REPORTED` |
