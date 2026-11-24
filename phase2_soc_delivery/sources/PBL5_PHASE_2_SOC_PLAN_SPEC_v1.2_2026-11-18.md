# PBL5 · Phase 2: SoC Estimation
## Kế hoạch triển khai và đặc tả kỹ thuật v1.2 (Progress & Conditional G10 Continuation)

**Ngày soạn:** 11/11/2026; **v1.1:** 12/11/2026; **cập nhật v1.2:** **18/11/2026**  
**Trạng thái:** P2.0 `PASS_OFFLINE`; P2.1 `PASS`; P2.2/B1 `PASS`; P2.3 đã có fixed 1-RC ECM v1 nhưng G10 vẫn `NEEDS_REVIEW`, ECM scientific release vẫn `BLOCKED`. Theo cập nhật của người phụ trách ngày 18/11/2026, đã có **phê duyệt trong chat `APPROVED_CONDITIONAL`** để dùng candidate v1 trong phạm vi nghiên cứu P2.4–P2.5, **không phải phát hành mô hình**. Quyết định này **chưa được ghi vào artifact/config của lượt chạy tiếp theo** và cần lưu dấu vết phê duyệt trước khi triển khai. P2.4–P2.7 chưa thực thi; `ER4=NOT_EVALUATED`.  
**Phạm vi:** F2, nghiên cứu SoC ngoại tuyến cấp **một cell** trên CALCE INR18650-20R; 1-RC ECM + Coulomb Counting baseline + EKF; không chứng minh hiệu năng pack Lishen 2S1P.  
**Môi trường:** Google Colab + Google Drive; module Python chạy độc lập; Git được định hướng cho versioning, không mặc định đã có commit.  
**Nguyên tắc ưu tiên:** Các phần v1.1 không được sửa dưới đây tiếp tục áp dụng. Bản v1.2 cập nhật **trạng thái thực hiện, quyền tiếp tục có điều kiện, cảnh báo điện áp, protocol chấm ER4 và bước tiếp theo**. Tài liệu này không tự sửa Logbook, không tạo kết quả thực nghiệm mới và không sửa artifact đã khóa.

---

## 1. Cơ sở và ranh giới

### 1.1. Những nội dung đã thống nhất

Theo bản chuyển giao `PBL5_TOM_TAT_CHUYEN_GIAO_CHAT_MOI(1).md`, cập nhật 11/11/2026:

- Concept B: Hybrid Model-Based & AI.
- Phase 2: CALCE → kiểm tra và tiền xử lý → OCV–SoC → nhận dạng 1-RC ECM → Coulomb Counting → EKF → đánh giá trên profile độc lập.
- Đầu ra: SoC (%) và trạng thái hợp lệ; estimator Python, artifacts và báo cáo.
- Coulomb Counting là baseline; nguồn tham chiếu phải được xác định từ dữ liệu và protocol thực tế.
- Người dùng báo Phase 1 đã hoàn thành; chưa có kiểm chứng độc lập code/test trong bản chuyển giao.
- SoH/Random Forest/NASA thuộc Phase 3; tích hợp ứng dụng thuộc Phase 4; kiểm chứng pack Lishen thật thuộc Phase 5.
- Mục tiêu ER4 là sai số SoC ≤10 điểm phần trăm. Cập nhật ngày 18/11/2026 sử dụng **MAX sai số tuyệt đối trên từng held-out run** làm tiêu chí theo điều kiện đã phê duyệt trong chat; chưa có kết quả chấm ER4.

**Nhận dạng ECM và hiệu chỉnh EKF không phải huấn luyện supervised ML.**

### 1.2. Quyết định kỹ thuật v1.1 được giữ nguyên

- Khóa **cửa sổ chấm điểm tải động (dynamic window)** bằng step/event metadata trước khi chạy estimator; pha pre-conditioning dùng để xác định mốc xuất phát và kiểm tra protocol, không tự động chấm điểm.
- Khai báo rõ nguồn cell: file OCV được người dùng mô tả thuộc `SP20-3`, còn DST thuộc `SP20-2`. Sử dụng OCV khác cell là **cross-cell transfer** có sai khác miền, không được mặc nhiên coi là đường OCV đúng của SP20-2.
- Chia dữ liệu theo **file/run/profile có thật**; phương án A đã được kiểm kê và khóa trong P2.1. Không chia ngẫu nhiên các dòng mẫu.
- Khi đủ bằng chứng về nghĩa cột, ưu tiên thử xây dựng SoC tham chiếu từ các **counter Ah của Arbin**; bắt buộc kiểm tra reset, cộng dồn, dấu, dung lượng và mốc SoC, không xem đó là ground truth trực tiếp.
- Ưu tiên **PCHIP** cho đường OCV–SoC và đạo hàm bậc nhất liên tục khi dữ liệu OCV phù hợp; đây là lựa chọn giảm rủi ro ở Jacobian, không bảo đảm EKF không có gai.
- Ưu tiên **nhận dạng trên đoạn xung / hồi phục** thay vì tối ưu không ràng buộc trên toàn DST. Tham số từ xung của SP20-3 chỉ là ứng viên **transfer/khởi tạo** cho SP20-2; tham số theo SoC là bước nâng cao có điều kiện.
- Sau mỗi EKF correction, ghi giá trị `z_unconstrained`, sau đó **project trạng thái SoC nội bộ** về [0,1] trước vòng lặp tiếp theo; kiểm tra tính nhất quán covariance và giới hạn OCV riêng.
- Xử lý timestamp trùng có nhận biết step transition; khi chắc chắn là rest, chấp nhận `dt` lớn bằng propagation phù hợp, không reset máy móc theo một `max_gap_s`.
- Thêm bản đề xuất đồng bộ **Bảng 2.8 + Hình 2.9 + mục 2.3.2** trong Logbook. Chưa chỉnh sửa trực tiếp tài liệu nhóm.

**Diễn giải theo phiên bản:** Dòng trên mô tả *thiết kế và phương pháp* từ v1.1. Các nhận định lịch sử tại thời điểm 12/11 như “chưa đọc XLS” đã được thay thế bằng trạng thái audit P2.1/P2.2 trong v1.2. Không hồi tố sửa raw, split/window hay protocol để làm đẹp residual.

### 1.3. Điểm đã kiểm chứng và các giới hạn còn tồn tại (18/11/2026)

**Đã có bằng chứng/hồ sơ bàn giao:**

- P2.1 `PASS`: kiểm kê sáu archive CALCE trong phương án A, parser, dấu dòng, run identity, split và các dynamic window. Không sửa các manifest đã đóng băng.
- P2.2/B1 `PASS`: `capacity_ref_ah = 2.028344937765965 Ah` cho **SP20-2** theo initial-capacity protocol; SoC reference dựng từ counter Arbin với chính sách reset/anchor; OCV của **SP20-3** dùng có gắn provenance khi chuyển sang SP20-2.
- P2.3 fixed 1-RC candidate có source, replay và forensic/identifiability evidence; các kiểm định lập trình không đồng nghĩa mô hình được nghiệm thu khoa học.
- Acquisition 16/11: `INCONCLUSIVE`, đã khảo sát 41.105 dòng DST bổ sung ở 0°C/45°C; dữ liệu này chưa bảo vệ được calibration cho case 25°C, chưa dùng để fit lại ECM.

**Vẫn cần xác minh/khóa trước các mốc tiếp theo:**

- **G10 khoa học:** chưa giải quyết sai lệch điện áp gần cutoff; `ecm_params.json` vẫn mang `NEEDS_REVIEW_NOT_RELEASED`.
- **Phê duyệt có điều kiện:** người phụ trách thông báo đã duyệt trong chat; chưa có record/config, chữ ký điện tử hoặc tham chiếu tin nhắn được đóng vào evidence triển khai. Phải ghi nhận rõ trước khi chạy P2.4–P2.5.
- **P2.5:** chưa chọn `P0`, `Q(dt)`, `R` cuối; chưa chạy EKF và chưa biết SoC accuracy.
- **P2.6:** chưa mở/đọc nội dung test US06/BJDST để chấm SoC; `ER4=NOT_EVALUATED`.
- **Phase 1:** interface và adapter mapping chưa audit độc lập; phải kiểm trước P2.7.
- **Nguồn calibration:** chưa có OCV/relaxation bổ sung **đúng cell SP20-2** tại 25°C được xác minh, cùng metadata noise/timing/T/aging đủ để giải thích G10.

**Ranh giới bằng chứng:** quyết định trong chat và báo cáo bàn giao là nguồn của các cập nhật này; bản v1.2 không tuyên bố đã chạy lại raw/notebooks hoặc tạo ra metrics mới. Các phát biểu “đã chốt” không được diễn giải thành “đã đạt hiệu năng”.

### 1.4. Không làm trong Phase 2

Không huấn luyện SoH, không thay EKF bằng LSTM/Transformer, không thiết kế lại backend/database/dashboard, không triển khai inference trên ESP32, không điều khiển sạc/xả và không thử nghiệm pin thật.

Module v1 xử lý **một cell, một luồng thời gian liên tục**. Việc tổng hợp SoC pack 2S, xử lý mất cân bằng hoặc chuyển tham số sang Lishen không thuộc nghiệm thu Phase 2. Không lấy điện áp pack chia hai để coi là phép đo từng cell.

**Lưu ý phạm vi bài báo:** Introduction v3 đề cập thêm *ML Residual Correction* để đánh giá SOC. Thuật toán ML cụ thể, mã nguồn và protocol của nhánh đó **chưa được chốt trong Spec Phase 2 này**. Không tự bổ sung ML residual vào P2.4/P2.5 hoặc dùng nó để che lỗi ECM khi chưa có quyết định phạm vi riêng.

---

## 2. Kết quả cần đạt

Phase 2 phải bàn giao được một quy trình tái lập:

    Dữ liệu thô
      → kiểm tra nguồn và chất lượng
      → dữ liệu chuẩn + split manifest
      → dung lượng/OCV và tham số ECM
      → baseline Coulomb Counting + EKF
      → kiểm thử holdout
      → module Python + artifacts + báo cáo

Khi hoàn tất, một người khác phải có thể chạy lại từ cùng dữ liệu, cấu hình và phiên bản code, thu được cùng kết quả trong dung sai số học đã công bố.

Phân biệt hai kết luận:

1. **Hoàn thành triển khai:** code, tests, artifacts và báo cáo đầy đủ.
2. **Đạt mục tiêu hiệu năng:** số đo thực tế đáp ứng giao thức nghiệm thu đã đóng băng.

Có thể hoàn thành triển khai nhưng chưa đạt mục tiêu. Không được thay thế kết luận thứ hai bằng việc notebook chạy không lỗi.

**Bổ sung v1.2:** `APPROVED_CONDITIONAL` chỉ cho phép tiếp tục **thử nghiệm nghiên cứu có cảnh báo**. Không đồng nghĩa G10 `PASS`, ECM `RELEASED`, ER4 `PASS` hay cho phép tích hợp vào đường điều khiển/bảo vệ pin thật.

---

## 3. Milestone và cổng kiểm tra

### 3.1. Trạng thái cập nhật ngày 18/11/2026

| Mốc | Kết quả/trạng thái | Gate và công việc tiếp theo |
|---|---|---|
| **P2.0** | `PASS_OFFLINE` | Interface Phase 1 còn `PENDING`; kiểm adapter thực trước P2.7. |
| **P2.1** | **`PASS`**; 6 archive CALCE, split theo file/run/profile và dynamic windows đã khóa | Giữ raw/provenance/split/window manifests bất biến. |
| **P2.2 / B1** | **`PASS`**; `capacity_ref_ah = 2.028344937765965 Ah` theo SP20-2 initial capacity, Arbin SoC reference, OCV SP20-3 → SP20-2 | Sử dụng artifact đã xác minh; không biến SoC reference thành runtime input. |
| **P2.3 / G10** | Đã có 1-RC ECM fixed v1, forensic và identifiability review; `G10=NEEDS_REVIEW`, `ECM_RELEASE=BLOCKED`; người phụ trách báo **`APPROVED_CONDITIONAL` trong chat** cho nghiên cứu P2.4–P2.5 | Ghi approval record và warning policy **trước khi chạy**; **không sửa** `ecm_params.json`/`lock_status`. |
| **Acquisition** | Đã khảo sát thêm 41.105 dòng ở 0°C/45°C; quyết định **`INCONCLUSIVE`**; chưa gửi CALCE contact | Không sử dụng dữ liệu ngoài 25°C để tự sửa model 25°C. Nhánh follow-up/calibration phải có quyết định riêng. |
| **P2.4** | **`NOT_EXECUTED`**; được phép bắt đầu **có điều kiện** | Chạy CC baseline theo frozen SoC/capacity/sign/clock/prior protocol; unit tests và trajectory; không cần phát hành ECM khoa học để kiểm logic CC. |
| **P2.5** | **`NOT_EXECUTED`**; được phép triển khai **có điều kiện** trên ECM v1 unreleased | EKF tiêu chuẩn + telemetry `LOW_SOC_MODEL_UNCERTAIN`; chọn `P0`, `Q`, `R` chỉ bằng DST/FUDS; log mismatch. |
| **P2.6** | **Chưa thực thi**; `ER4=NOT_EVALUATED` | Sau khi khóa mọi cấu hình, đánh giá US06/BJDST **một lần** theo protocol mục 10. Nếu không đạt, ghi nhận fail và quay về P2.3 theo change control. |
| **P2.7** | **Chưa thực thi** | Đóng gói code/artifact/evidence, kết quả (kể cả kết quả fail), cùng adapter Phase 1 và hạn chế model. |

### 3.2. Quyết định `APPROVED_CONDITIONAL` và giới hạn quyền

1. **Phạm vi phê duyệt được người dùng cung cấp:** chỉ dùng **fixed 1-RC ECM v1 đã khóa** làm nền thử nghiệm P2.4–P2.5, kèm cảnh báo điện áp và phép đánh giá được mô tả; không thay tham số, OCV/capacity, raw hay split.
2. **Phải ghi nhận trước khi chạy:** nguồn approval (link/trích dẫn/timestamp nếu có), người duyệt, phạm vi, SHA-256 của ECM candidate, warning threshold, phiên bản config và người thực hiện. Không tự tạo `approved_by` hoặc đường dẫn tin nhắn không có thật.
3. **Phân biệt hai cổng:** `conditional_execution_allowed=true` cho thực nghiệm trong phạm vi; `scientific_release=false` và `lock_status=NEEDS_REVIEW_NOT_RELEASED` vẫn giữ nguyên. Loader mặc định tiếp tục reject unreleased artifact. Nếu cần nhánh offline research đặc biệt, dùng **opt-in guard riêng có audit**, tuyệt đối không đổi bit release trong artifact gốc để vượt khóa.
4. **Không chuyển mốc bằng suy đoán:** P2.4/P2.5 chỉ đạt PASS khi có code, tests, artifacts và evidence theo từng milestone; P2.6 không bắt đầu trước khi khóa cấu hình và protocol; P2.7 chỉ sau các bước được yêu cầu.
5. **Held-out integrity:** FUDS là validation, không đưa vào ECM fitting loss; US06/BJDST đóng đến final evaluation. Mọi lần phơi bày dữ liệu test phải ghi trong evidence.

**Quyết định cũ `P2_4_authorized=false` trong ICF R2 là trạng thái trước thông tin phê duyệt mới.** Không chỉnh sửa hồi tố evidence cũ; lưu bản ghi phê duyệt mới có thời điểm và phạm vi riêng để giải thích thay đổi về quyền thực nghiệm.

## 4. P2.0–P2.1: Dữ liệu và thiết kế thí nghiệm

### 4.1. Phạm vi v1

**Phạm vi active đã khóa:** **25°C danh định** cho CALCE INR18650-20R SP20-2 dynamic; OCV cross-cell SP20-3. Không coi 25°C archive là chứng cứ nhiệt độ cell đã đo ở từng timestamp.

Nguồn DST 0°C/45°C đã được khảo sát trong acquisition (41.105 dòng), **không** được gộp vào calibration/validation/test 25°C đã khóa. Nguồn đó thiếu bằng chứng phù hợp về cell history, relaxation, temperature và độ bất định. Các mở rộng nhiệt độ cần protocol/change request riêng.

Trang CALCE chính thức liệt kê OCV, initial capacity và DST/FUDS/US06/BJDST cho INR18650-20R [S2]. P2.1 đã thực hiện audit trên sáu archive theo phương án A; không đánh đồng metadata/URL với bằng chứng một phép đo chưa có.

### 4.2. Dataset và split phương án A đã khóa (P2.1 PASS)

| Archive CALCE 25°C | Source cell | Vai trò đã chốt | Trạng thái tính đến 18/11 |
|---|---|---|---|
| `SP3_25C_IC_OCV_12_2_2015.zip` | **SP20-3** | Xây OCV–SoC; **cross-cell transfer** sang target SP20-2 | P2.1/P2.2 `PASS`; không chứng minh OCV same-cell. |
| `SP2_Initial_capacity_10_16_2015.zip` | **SP20-2** | Operational capacity theo initial-capacity protocol | P2.2/B1 `PASS`, `2.028344937765965 Ah`. |
| `SP2_25C_DST.zip` | **SP20-2** | **Identification/calibration**: DST50/80 | P2.1 `PASS`; dùng fitting ECM và phân tích; không lẫn với test. |
| `SP2_25C_FUDS.zip` | **SP20-2** | **Validation**: FUDS50/80 | P2.1 `PASS`; dùng validation/chọn `P0`, `Q`, `R`, **không dùng ECM calibration loss**. |
| `SP2_25C_US06.zip` | **SP20-2** | **Final held-out** | Chỉ inventory/hash; nội dung I/V/SoC không được mở để chọn model trước P2.6. |
| `SP2_25C_BJDST.zip` | **SP20-2** | **Final held-out** | Chỉ inventory/hash; nội dung I/V/SoC không được mở để chọn model trước P2.6. |

P2.1 đã khóa **8 dynamic windows** (DST 2, FUDS 2, US06/BJDST 4) theo step/event, không random theo dòng. File/run/profile được phân vai cố định. Pre-conditioning có thể dùng làm anchor/prior với căn cứ, nhưng không trộn vào population dynamic để chấm điểm. Đối với US06/BJDST, inventory và hash của archive không tương đương đã đọc nội dung held-out.

**Phương án B (chỉ hai DST runs) trong v1.1 là fallback lịch sử, không còn là protocol active.** Không thay đổi phương án A chỉ vì candidate đang có sai số lớn. URL nguồn công khai: https://calce.umd.edu/battery-data.

Đọc dữ liệu FUDS để validation vốn đã được cho phép. Không chọn correction ECM bằng cách fit residual FUDS hoặc thay đổi window/loại cutoff. Việc chốt lại EKF `P0/Q/R` dựa trên DST/FUDS theo điều kiện 18/11 phải giữ đúng split hiện hành.

### 4.3. Kiểm kê nguồn và provenance

`dataset_manifest.csv` tối thiểu ghi: source URL, archive name, internal XLS name/sheet, SHA-256, ngày tải, cell/sample, run, 25°C điều kiện danh định, thông tin nhiệt độ đo nếu có, khoảng thời gian, số mẫu, current sign ban đầu, bước kiểm tra và split.

Thêm `cell_transfer_id` / `source_cell_id` cho model OCV, `target_cell_id` cho dynamic run. Ghi riêng `calibration_source` cho OCV/ECM/capacity. Không trộn những nguồn calibration khác cell mà không có nhãn.

`window_manifest.csv` cho từng run phải ghi `preconditioning_rows`, `dynamic_start_row`, `dynamic_end_row`, `step_ids`, căn cứ xác định bằng I/V/t và các event, checksum và phiên bản quy tắc segment. Khi chưa chứng minh được ranh giới, để `window_status=NEEDS_REVIEW` và không chấm điểm.

Giữ nguyên raw archive; xuất processed có version; không đưa raw/ vào Git mặc định.

### 4.4. Data contract nội bộ

Schema nội bộ là **đích** của parser, không phải tên cột được khẳng định có trong mọi XLS:

| Trường | Quy ước | Kiểm tra |
|---|---|---|
| `run_id`, `cell_id`, `source_file` | ID có provenance | Không bịa sample hoặc gộp nhiều run |
| `time_s` | Test time chuẩn hóa, s | Giữ thứ tự file; phát hiện reset/time trùng; không sort âm thầm |
| `step_index`, `cycle_index`, `step_time_s` | Metadata Arbin, có thể null nếu thiếu | Không áp step ID cố định cho mọi file |
| `phase` | `PRECONDITION`, `DYNAMIC`, `OTHER` | Chứng minh bằng step + dạng I/V + lịch test |
| `voltage_v`, `current_a` | V, A; nội bộ **dương khi xả** | Arbin thường dùng **dương khi sạc**, phải kiểm tra trên data thực |
| `charge_capacity_ah`, `discharge_capacity_ah` | Counter bản gốc | Kiểm tra reset, đơn điệu trong đoạn, ý nghĩa step/cycle |
| `temperature_c` | °C hoặc null | Tách môi trường đặt 25°C với cảm biến đo |
| `soc_ref_fraction`, `reference_kind` | 0–1, chỉ dành evaluation | Không đưa vào EKF runtime |

### 4.5. Segment pre-conditioning và dynamic window

1. Đọc `Step_Index`, `Step_Time`, `Test_Time`, I, V, capacity counter cùng các event/mô tả protocol. Với từng file `DST_50SOC` / `DST_80SOC`, **kiểm tra liệu** các step đầu có gồm CC–CV, rest, discharge-to-target và rest hay không; không giả định 'Step_Index 1–4' là chuẩn cố định.
2. Tìm sample đầu tiên của waveform tải động và khoanh window; xuất đồ thị current/voltage + bảng thống kê step làm bằng chứng; review thủ công lần đầu rồi cố định rule có test.
3. Pre-conditioning được **lưu lại và phân tích riêng** để xây mốc dung lượng/SoC đầu run; không bị xóa hoặc nhập nhằng với dynamic.
4. Chấm điểm EKF chỉ trên **dynamic window khóa trước**. Đầu ra có thể được khởi tạo bằng thông tin pre-conditioning nếu thông tin đó hợp lệ với kịch bản đã tuyên bố và được cấp tương đương cho CC. Phải phân biệt 'prior theo lịch sử vận hành' và 'prior oracle biết nhãn test'; prior oracle không đại diện bài toán online triển khai.

### 4.6. Timestamp trùng và khoảng lấy mẫu

- Đọc `Test_Time(s)` theo run; dùng `Step_Time`/`Step_Index` để nhận diện thay step. `dt=0` ở ranh giới step có thể mang **thông tin V/I mới**; không được loại toàn bộ hay lấy trung bình một cách mù quáng.
- Trong preprocessing: tách `event` và `measurement`; gộp chỉ những quan sát trùng cùng thời điểm/thông tin. Nếu có nhiều phép đo cùng thời điểm nhưng khác step, phải chọn chính sách causal rõ (ví dụ giữ mẫu đo cuối của transition) và ghi log số dòng ảnh hưởng. Không dùng các phép đo lặp cùng nguồn như phép đo độc lập để EKF correction hai lần.
- Runtime `dt=0`: **không prediction, không tích phân điện lượng**. Nếu mẫu mới chỉ lặp phép đo cũ thì bỏ; nếu là thông tin đo mới ở transition có thể correction một lần theo policy, không giả định bỏ mọi mẫu và vẫn đạt coverage.
- Rest có log thưa 10–60 s hoặc lớn hơn là tình huống cần kiểm tra, không tự coi là hỏng. Ghi phân phối `dt` tách theo `phase` và rest/active để thiết lập ngưỡng.

## 5. P2.2: Dung lượng, OCV và SoC tham chiếu

### 5.1. Ba đại lượng phải tách biệt

- **Dung lượng dùng bởi model:** `capacity_model_ah`, xác định từ nguồn calibration có truy vết.
- **SoC tham chiếu của thí nghiệm:** dựng từ protocol và phép đo được xác nhận; chỉ dùng làm đáp án đánh giá.
- **Baseline Coulomb Counting:** thuật toán so sánh chạy cùng điều kiện thông tin đầu vào với EKF.

Không điều chỉnh dung lượng model bằng toàn bộ chu kỳ test để giảm sai số rồi báo là kiểm thử độc lập.

### 5.2. Xây dựng OCV–SoC, ưu tiên PCHIP

1. Từ Incremental OCV SP20-3, xác định mốc charge/discharge/rest và dung lượng theo protocol; chọn **điện áp cuối nghỉ** khi phù hợp. Chưa mặc định mọi rest đều dài 2 giờ.
2. Giữ nhánh sạc/xả riêng trong phân tích để quan sát hysteresis. Nếu gộp thành một đường OCV, công bố rõ quy tắc trung bình và giả định mô hình 1-curve.
3. Tạo bảng `z` tăng nghiêm ngặt với `OCV(z)` kèm độ tin cậy. Chỉ loại/hiệu chỉnh điểm bất thường bằng quy tắc đã công bố; không ép đơn điệu tùy ý để làm đẹp.
4. **Mặc định ưu tiên:** `scipy.interpolate.PchipInterpolator(z, ocv, extrapolate=False)` và `ocv_model.derivative()`; có unit tests tại knot và gần biên. PCHIP bảo toàn dạng, không vọt lố khi dữ liệu đơn điệu và có đạo hàm bậc nhất liên tục C¹ [S4].
5. Nội suy tuyến tính từng đoạn **không sai toán học**, nhưng đạo hàm có thể đổi bậc tại knot; không thể kết luận lúc nào cũng gây spike. Giữ như benchmark đơn giản nếu cần. PCHIP chỉ giải quyết độ liên tục đạo hàm, không giải quyết hysteresis/OCV lệch cell hoặc vùng plateau khó quan sát SoC.
6. Chỉ gọi `ocv(z)` trong **miền được hiệu chuẩn**; PCHIP mặc định có thể ngoại suy nên phải đặt `extrapolate=False`. Nếu đường OCV không phủ [0,1], xử lý trạng thái **ngoài miền OCV** riêng, không coi việc clip [0,1] là đủ để gọi hàm an toàn.
7. OCV SP20-3 dùng trên SP20-2 phải gắn provenance `source_cell_id=SP20-3`, `target_cell_id=SP20-2`, `transfer_assumption=true`; đánh giá nhạy cảm với offset/khác cell nếu có dữ liệu.

Không lấy điện áp đang tải làm OCV hoặc dùng kết quả từ test để sửa đường OCV trước khi chấm điểm.

### 5.3. Dựng SoC tham chiếu bằng capacity counter Arbin khi phù hợp

Ưu tiên **kiểm tra khả năng** sử dụng `Charge_Capacity(Ah)` và `Discharge_Capacity(Ah)` từ Arbin thay vì mặc định tích phân sampled `Current(A)` để tạo reference. Nhà sản xuất ghi các đại lượng capacity trong dữ liệu xuất; counter có thể được **reset theo schedule**, nên không có bảo đảm mỗi cột là tổng tích lũy xuyên file [S5]. Không khẳng định có 'tích phân phần cứng tần số cao' trong từng XLS khi chưa biết cấu hình thiết bị.

**Quy trình chuẩn:**

1. Kiểm tra cột thực có hay không, counter tăng theo thời gian thế nào, có reset tại `Step_Index` / `Cycle_Index` hay tại lệnh ResetCap không; dựng danh sách điểm reset.
2. Tách từng đoạn counter liên tục và lấy **gia số Ah** theo đoạn. Ở ranh giới reset, chỉ ghép các lượng có bằng chứng, không cộng nhầm bước nhảy reset âm thành điện lượng xả.
3. Xác định SoC anchor từ trạng thái đầy theo protocol (CC–CV + cutoff + rest, hoặc mốc có căn cứ) và/hoặc discharge-to-target. Câu 'đầy 100%' theo protocol **không phải SoC vật lý chính xác tuyệt đối**; báo sai số mốc.
4. Ưu tiên dung lượng `capacity_ref_ah` của đúng sample SP20-2 từ initial capacity nếu kiểm chứng được; **không lấy mặc định 2 Ah danh định** làm dung lượng thực nghiệm. `capacity_model_ah` cho estimator phải lấy từ calibration, không suy ra từ test tương lai.
5. Với quy ước `q_chg`, `q_dis` là các **gia số điện lượng dương** sau xử lý reset, quy ước `z_ref[k] = z_anchor + (sum(q_chg) - sum(q_dis)) / capacity_ref_ah` (giả định efficiency 1; ghi giả định khi sạc).
6. Đối chiếu với tích phân sampled `Current(A)` như **cross-check**, phân tích chênh tại sườn xung/time gap; không tuyên bố counter chính xác tuyệt đối hoặc độc lập hoàn toàn khỏi phép đo dòng.
7. Ghi `reference_kind=arbin_capacity_derived`, anchor, reference capacity, reset policy, uncertainty/limitations; không đưa `soc_ref_fraction`/các counter reference tương lai vào EKF.

**Phân biệt calibration/evaluation:** nếu `z0` lấy từ pre-conditioning của cùng run, phải chỉ rõ thông tin prior đó có sẵn ở runtime hay là test-oracle; dùng prior tương đương cho CC và EKF. Nếu chỉ có reference tái dựng, đánh giá là *so với reference từ Arbin*, không phải đo trực tiếp SoC bên trong pin.

Nếu không có counter đủ tin cậy, fallback tích phân sampled current kèm sai số và hạn chế. Nếu chưa có reference đủ chắc, vẫn được kiểm thử thuật toán/điện áp nhưng **không nghiệm thu độ chính xác SoC tuyệt đối**.

### 5.4. P2.2/B1: Kết quả nghiệm thu và artifact nguồn (18/11/2026)

- **`PASS`** theo hồ sơ bàn giao P2.2; người phụ trách xác nhận đã đối chiếu workbook Initial Capacity trên Colab.
- `capacity_ref_ah = 2.028344937765965 Ah` cho **SP20-2**. Đây là **operational capacity theo protocol**, không khẳng định dung lượng vật lý tuyệt đối hay độ chắc chắn vô hạn.
- Pipeline sử dụng **`artifacts/capacity_metadata.json`** của P2.2 verified delivery. Chính sách SoC reference, anchor và counter reset được khóa trong **`reference_protocol_P2_2.md`** và **`configs/p2_2_reference_policy.yaml`**.
- `capacity_model_ah` có thể lấy cùng giá trị đã công bố theo cấu hình calibration, nhưng `capacity_model_ah` và `capacity_ref_ah` không phải hai phép đo độc lập. Reference chỉ dành **evaluation**, không đưa vào estimator runtime.
- Nguồn OCV SP20-3 → dynamic SP20-2 là **cross-cell transfer**; không được tự đổi cell provenance hay chỉnh PCHIP để làm đẹp cutoff.

**Không được suy ra:** P2.2 `PASS` không có nghĩa P2.3 ECM `PASS`, EKF đã chạy hoặc SoC đạt ER4.

## 6. P2.3: Nhận dạng mô hình 1-RC ECM

### 6.1. Mô hình cơ sở

Trạng thái `x = [z, v_rc]^T`; `z` là SoC dạng 0–1, `v_rc` là điện áp phân cực.

Với dòng dương khi xả, dòng giữ hằng trong một khoảng lấy mẫu, hiệu suất Coulomb giả định bằng 1 và tham số cố định [S3]:

    dt = t[k] - t[k-1]
    a = exp(-dt / (R1 * C1))

    z_pred = z_prev - I_prev * dt / (3600 * capacity_model_ah)
    vrc_pred = a * vrc_prev + R1 * (1 - a) * I_prev

    voltage_pred = OCV(z_pred) - vrc_pred - R0 * I_now

Dòng cho tích phân khoảng trước và dòng cho sụt áp tại thời điểm hiện tại phải phù hợp quy ước timestamp của dữ liệu. Không trộn lẫn hai vai trò hoặc làm lệch một mẫu.

Nếu protocol thực tế buộc dùng quy ước tích phân khác, adapter phải chỉ rõ, có test và sử dụng nhất quán.

### 6.2. Quy trình nhận dạng trong v1.1 (lưu làm chuẩn thiết kế và phương án revision)

**Không fit 3 tham số tự do bằng least-squares không ràng buộc trên toàn DST ngay từ đầu**: sai lệch OCV tĩnh do hysteresis, dung lượng/OCV lệch cell, drift nhiệt hoặc dynamic chưa đủ mô tả có thể bị nhánh RC hấp thụ, làm hằng số thời gian phi thực tế. Tuy nhiên least-squares toàn profile không mặc nhiên sai nếu mô hình/regularization/data đủ tốt; có thể dùng làm bước refinement có kiểm soát.

**Luồng đề xuất:**

1. Tìm xung dòng và các đoạn nghỉ trong **Incremental OCV SP20-3**. Trước khi nhận dạng R0/R1/C1, kiểm tra độ phân giải V/I/t ở bước dòng, độ dài nghỉ, nhiệt độ, hysteresis và dạng hồi phục. Nếu chỉ có logging thưa, **không thể đo chính xác bước nhảy tức thời** ΔV₀, nên R0 chỉ là estimate có sai số/giới hạn.
2. Từ các đoạn đủ sạch, ước lượng `R0 ≈ -ΔV/ΔI` **sau khi tách mức OCV và vrc phù hợp quy ước dấu**; hồi phục nghỉ có thể fit dạng `V(t) ≈ V_∞ -/+ A exp(-t/tau)` theo cực tính xung. Dạng một mũ chỉ là **xấp xỉ**, vì hồi phục thực còn hysteresis/diffusion. Suy ra `R1` từ amplitude có căn cứ và `C1=tau/R1`; kiểm tra identifiability của `R1` và `C1` thay vì chỉ báo fit-loss.
3. Xuất `ecm_sp3_pulse_initialization.json` với provenance. **Đây là tham số SP3, không phải tham số đo trên SP2.** Trong nhánh cross-cell transfer, dùng trực tiếp và ghi rõ hạn chế; trong nhánh phù hợp SP2, chỉ sử dụng làm **prior/initial guesses** cho dữ liệu calibration SP2 (ví dụ DST_80SOC theo split đã khóa).
4. Trên **SP2 identification run**, chọn các xung/chuyển dòng/đoạn nghỉ đủ thông tin để xác định hoặc hiệu chỉnh `R0/R1/tau` SP2; có thể tối ưu điện áp bằng weighted/constrained LS **trên window nhận dạng**, ràng buộc dương và khoảng tau phù hợp quan sát; không để offset OCV tự do biến thành tau rất lớn. Báo độ nhạy và residual ở trạng thái tải/nghỉ.
5. **MVP bắt buộc:** bộ `(R0,R1,C1)` cố định, đã hiệu chỉnh từ calibration và kiểm tra trên validation. **Mở rộng có điều kiện:** `R0(z),R1(z),C1(z)` theo các vùng SoC *chỉ khi* có đủ xung/cell/calibration phủ dải và thấy improvement ngoài tập fitting. Không khẳng định trước '<20% tăng vọt' đã quan sát được trong hai run DST. SoC-dependent 1-RC giữ một nhánh RC nhưng phải cập nhật phương trình/Jacobian (mục 8.1).
6. Chốt cấu hình trước test; test cuối chỉ replay và đánh giá. Không chuyển các profile held-out vào LS/tuning dù là 'tinh chỉnh nhẹ'.

**Kết luận đánh giá:** dùng SP3 OCV + SP2 RC được nhận dạng từ SP2 là *cross-cell OCV transfer with target-cell calibration*. Dùng cả OCV + RC từ SP3 không hiệu chỉnh trên SP2 là *zero-shot cross-cell transfer*; hai kịch bản không được gọi chung là 'chứng minh cross-cell robustness'.

**Chú thích v1.2:** mô tả trên là quy trình thiết kế/future revision; đã có **fixed candidate v1 trên DST** và có replay FUDS, nhưng candidate **chưa đủ chứng cứ khoa học để release**. Không tái fit trong lượt P2.4–P2.5 được phê duyệt có điều kiện.

### 6.3. Artifacts

`ecm_params.json` chứa: tham số và đơn vị, capacity model, điều kiện nhiệt độ, miền SoC có dữ liệu, nguồn calibration, phương pháp fitting, cấu hình, mã/snapshot nguồn và kết quả validation. Nếu Git commit chưa có phải ghi `null`/unknown thay vì tạo commit giả.

**Artifact hiện hành vẫn có `lock_status=NEEDS_REVIEW_NOT_RELEASED`.** Không trực tiếp sửa file để đổi release status. Quyết định chạy nghiên cứu có điều kiện phải nằm trong **approval record riêng**, gắn checksum của candidate và opt-in loader guard theo mục 3.2; bản phát hành khoa học vẫn bị chặn.

Miền dòng/điện áp đã quan sát phải được ghi lại như miền kiểm chứng, không được diễn giải thành giới hạn an toàn phần cứng.

---

### 6.4. P2.3-G10: Kết quả đã biết và giới hạn khoa học

**Candidate fixed 1-RC ECM v1** theo evidence bàn giao: `R0 ≈ 0.077371 Ω`, `R1 ≈ 0.027650 Ω`, `C1 ≈ 813.50 F`, `τ ≈ 22.49 s`; `capacity_model_ah ≈ 2.0283449378 Ah`. Đây là tham số **ứng viên chưa release**, không phải bộ calibration được xác nhận đủ chính xác cho toàn miền vận hành.

| Dynamic run | MAE điện áp (mV) | RMSE điện áp (mV) | MAX abs điện áp (mV) |
|---|---:|---:|---:|
| DST 50SOC | 11.172 | 27.690 | 575.049 |
| DST 80SOC | 11.877 | 25.461 | 673.813 |
| FUDS 80SOC | 10.845 | 19.916 | **474.003** |
| FUDS 50SOC | 10.389 | 20.388 | **467.598** |

Số liệu là **sai số điện áp replay** từ hồ sơ P2.3, **không phải sai số SoC**. Trên FUDS có sai lệch cực đại xấp xỉ **0.47 V** gần cutoff ~2.50 V, kéo dài nhiều mẫu, không được tự cắt khỏi dynamic metrics.

G10 forensic và ICF R2 đã hoàn tất: fixed candidate có local Jacobian rank 3 trong kiểm định được định nghĩa, nhưng chưa có calibration support để bảo vệ low-state correction. Kết luận ICF **`NEW_CALIBRATION_DATA_REQUIRED`**; G10 và scientific release tiếp tục blocked. Same-cell acquisition sau đó **`INCONCLUSIVE`**: dữ liệu DST ở 0°C/45°C chưa cung cấp OCV/relaxation 25°C cùng cell đủ căn cứ; chưa gửi CALCE contact.

**Quyết định vận hành sau cập nhật 18/11:** cho phép **tiếp tục thử nghiệm offline có điều kiện** với candidate v1 để kiểm CC/EKF và đo giới hạn, **không tuyên bố giải quyết G10**. Phải công bố warning policy, toàn bộ residual, failure cases và độ phủ. Nếu ER4 không đạt, quay lại P2.3 để xét thay đổi model theo change control; không tự fit ngay trong lượt này.

## 7. P2.4: Coulomb Counting

Với giả định ở mục 6:

    z[k] = z[k-1] - I[k-1] * dt / (3600 * capacity_model_ah)

Bản đầu dùng cùng dấu dòng, clock, dung lượng và prior khởi tạo như EKF trong từng kịch bản đối chiếu.

Unit test tối thiểu:

- Xả 0,5 A trong 600 giây với dung lượng 1 Ah: giảm 0,083333... SoC, tức 8,3333 điểm phần trăm.
- Dòng bằng 0: SoC không đổi.
- Dòng sạc âm: SoC tăng theo mô hình.
- Chia cùng một khoảng dòng hằng thành nhiều bước cho cùng điện lượng.
- Timestamp trùng không làm tích phân hai lần.

Test lý tưởng chỉ chứng minh logic, không chứng minh hiệu năng trên pin thật.

---

**Trạng thái triển khai v1.2:** P2.4 **chưa chạy**, được phép bắt đầu khi **đã ghi approval record/config** và kiểm nguyên vẹn capacity/reference policy P2.2. CC nhận cùng current/timestamp/capacity/prior như EKF; CC là baseline, không dùng future reference làm input.

## 8. P2.5: EKF

### 8.1. Chu trình tính toán

Mỗi mẫu hợp lệ gồm: validation → prediction → dự báo điện áp → innovation → Kalman gain → correction → diagnostics.

Với tham số cố định và OCV PCHIP ở vị trí SoC dự báo:

    F = [[1, 0], [0, a]]
    H = [[dOCV/dz, -1]]

    P_pred = F @ P @ F.T + Q(dt)
    innovation = V_measured - V_predicted
    S = H @ P_pred @ H.T + R
    K = P_pred @ H.T / S

    x_new = x_pred + K * innovation

Cập nhật covariance bằng dạng Joseph:

    J = identity(2) - K @ H
    P_new = J @ P_pred @ J.T + K * R @ K.T

`R` là variance điện áp, đơn vị V². `Q` là process covariance, không phải dung lượng Ah.

Phải có chính sách `Q(dt)` rõ ràng. Đề xuất bản đầu scale covariance tham chiếu theo `dt / dt_ref`, ghi là xấp xỉ thiết kế và kiểm tra với các khoảng lấy mẫu được hỗ trợ.

Nếu dùng `R0(z),R1(z),C1(z)`, **không còn đúng toàn bộ** Jacobian cố định ở trên: measurement Jacobian có phần `dOCV/dz - I_now * dR0/dz`, còn dynamic Jacobian có các đạo hàm của `a(z)`, `R1(z)` theo SoC (ngoại trừ khi dùng frozen-parameter approximation có lý do và validation). Ưu tiên numerical/analytic differentiation có tests; không âm thầm sử dụng H/F sai. PCHIP làm `dOCV/dz` liên tục nhưng không bảo đảm observability tốt ở plateau.

### 8.2. Khởi tạo

- `z0`: prior có nguồn, không mặc định 100% cho mọi run.
- OCV-based initialization chỉ dùng khi có căn cứ cell đã nghỉ theo protocol.
- `vrc0 = 0` là giả định của bản đầu khi phù hợp; ghi rõ nếu run bắt đầu dưới tải.
- `P0`, `Q`, `R`: hiệu chỉnh trên validation; giá trị cuối được lưu.
- Lần nhận mẫu đầu sau reset không được tích phân một `dt` chưa tồn tại.
- Lưu trạng thái riêng cho từng run; không mang SoC/covariance sang cell hoặc run khác.

### 8.3. Boundary projection: state nội bộ và output

- Validation: mọi tham số, đầu vào, innovation và covariance hữu hạn; `S > 0`; `P` đối xứng và bán xác định dương trong dung sai.
- EKF correction tính `x_unconstrained = x_pred + K*innovation`. **Ghi** `z_unconstrained`, `boundary_overshoot`, số lần vi phạm và innovation ở diagnostics **trước khi clip**.
- Sau correction, **project `x_new[0] = clip(z_unconstrained, 0.0, 1.0)` ngay trong state được lưu cho bước kế tiếp**; output `soc_pct=100*x_new[0]`. Không chỉ clip output rồi để state nội bộ tràn biên.
- Projection là constrained-estimation heuristic, có thể làm covariance kém nhất quán; lưu `boundary_projected` và đánh giá tác động/điều chỉnh covariance hợp lý nếu cần. Không nói `clip()` làm SoC đúng.
- **Miền OCV là ràng buộc khác**: nếu OCV được hiệu chuẩn chỉ trên `[z_min,z_max]⊂[0,1]`, clip về [0,1] không đảm bảo gọi OCV an toàn. Trước mỗi lookup, kiểm tra `z ∈ [z_min,z_max]`. Khi ngoài miền, chỉ áp policy đã khai báo (prediction-only/OUT_OF_DOMAIN hoặc bounded lookup có flag), không ngoại suy rồi báo `VALID`.
- Trạng thái/covariance NaN/Inf hoặc correction thất bại: `NUMERICAL_ERROR`, không xuất `VALID`. Chạm biên lặp lại hoặc ngoài miền phải xuất trong báo cáo.
- `P` không được diễn giải là xác suất SoC đúng nếu chưa hiệu chuẩn uncertainty.

### 8.4. Đầu vào lỗi và temporal policy v1.1

| Tình huống | Hành vi quy định |
|---|---|
| Chưa khởi tạo/chưa load artifact | `NOT_READY`; không trả SoC như kết quả hợp lệ |
| `dt < 0` hoặc test time reset chưa được tách run | Reject/đánh dấu run boundary; không tính điện lượng ngược thời gian |
| `dt = 0` | Không prediction; loại phép đo lặp, hoặc một lần measurement correction nếu thực sự có observation mới ở step transition, theo policy đã test |
| Missing/NaN V/I | Không update bằng NaN. Không tích phân qua gap khi không có căn cứ về dòng; trả trạng thái phù hợp và reinitialize khi cần |
| `dt` lớn trong rest có chứng cứ | **Không reset tự động.** Nếu chứng minh `I≈0` liên tục trong interval (step metadata/schedule hoặc log đủ), propagate `z` giữ nguyên, `v_rc` suy giảm mũ với `a=exp(-dt/tau)`, propagation covariance phù hợp, có thể correction V tại cuối |
| `dt` lớn và chỉ biết hai đầu gần 0A | **Chưa đủ** kết luận toàn khoảng nghỉ: giữa gap có thể xảy ra xung không quan sát. Trả `GAP_UNOBSERVED`/degraded hoặc reset theo policy nếu không xác minh được |
| `dt` lớn dưới tải | Chỉ propagate nếu có chứng cứ I giữ ổn định hoặc thông tin charge counter *được cho phép dùng cho runtime*. Nếu không, không giả định I_prev suốt khoảng trống; đánh dấu gap và khởi tạo lại hợp lệ |
| Ngoài miền nhiệt độ/SoC/độ lớn dòng đã xác thực | `OUT_OF_DOMAIN` (hoặc prediction-only có flag); không khẳng định độ chính xác |
| Artifacts sai unit/schema/provenance | Reject với lỗi rõ |

Thay `max_gap_s` độc nhất bằng **policy theo chế độ**: ví dụ `max_gap_active_s`, `rest_gap_handling=propagate_if_verified`, `zero_dt_policy`. Không đặt threshold 5 s trước khi xem phân bố data. `|I_prev|≈0 && |I_now|≈0` **không phải bằng chứng đủ** cho rest liên tục. Phương trình mũ là nghiệm đúng của mô hình RC **nếu I=0 suốt interval và tham số không đổi**, không được gọi là 'đúng tuyệt đối' với pin thực tế.

Cần unit tests cho: timestamp trùng ở transition, duplicate measurement, rest 60 s có xác minh, gap 60 s chứa xung ẩn, NaN và active gap. Báo coverage tách lỗi thật và mẫu event bị hợp nhất có chủ đích.

### 8.5. Telemetry `LOW_SOC_MODEL_UNCERTAIN` (phê duyệt có điều kiện 18/11)

**Nguồn quy tắc:** quyết định được người phụ trách thông báo đã phê duyệt trong chat, **chưa được ghi vào cấu hình chạy**. Trước khi triển khai phải ghi threshold và evidence approval vào record riêng. Đây là **cờ độ tin cậy mô hình**, không phải bằng chứng SoC thực sự thấp, không phải cutoff an toàn phần cứng và không phải xác nhận miền OCV/ECM hợp lệ.

**Điều kiện phát cờ tại mỗi observation:**

```text
if voltage_v is finite and voltage_v < 3.2976:
    LOW_SOC_MODEL_UNCERTAIN = true
elif voltage_v is finite:
    LOW_SOC_MODEL_UNCERTAIN = false
else:
    LOW_SOC_MODEL_UNCERTAIN = null  # invalid/missing voltage; follow input status policy
```

- Ngưỡng **so sánh nghiêm ngặt `< 3.2976 V`** dùng **`V_measured` tại timestamp hiện tại**, không dùng `OCV`, `voltage_hat` hay SoC estimate để quyết định cờ. Vùng ~2.50 V sát cutoff chắc chắn thuộc vùng cờ khi điện áp đo hữu hạn.
- Nếu cờ bật, **EKF tiếp tục prediction/correction** theo chính sách mẫu `dt`, input validity, OCV-domain và covariance trong v1.1. Không tự bỏ sample, không dừng EKF, không reset, không clip thêm, không tự tăng `R`, không cắt cutoff khỏi metrics. Các lỗi `OUT_OF_DOMAIN`/`NUMERICAL_ERROR` thực sự vẫn do policy hiện hành xử lý.
- Telemetry phải ghi tối thiểu: `voltage_v`, `warning_flag`, threshold, `run_id`, timestamp, estimator status, innovation/voltage residual, `soc_pct` nếu hợp lệ. Cờ có thể cùng xuất hiện với status `VALID`; **không** có nghĩa độ chính xác được bảo đảm.
- Báo số lượng/tỷ lệ observations bật cờ, thời điểm đầu tiên, và so sánh metrics **toàn dynamic** với metrics **vùng không bật cờ**. Vùng cờ **không bị loại khỏi ER4**.
- Nếu điện áp thiếu/NaN: giữ handling `INVALID_INPUT`/reason theo policy hiện tại; không gán `false` để ngầm khẳng định vùng an toàn.

**Kiểm thử tối thiểu:** 3.29759 V → `true`; 3.29760 V → `false`; 3.29761 V → `false`; 2.50000 V → `true`; NaN → `null`/invalid; cờ **không** làm thay đổi recurrence EKF ở mẫu hợp lệ; toàn bộ window và số event giữ nguyên.

## 9. Contract module và tương thích Phase 1

### 9.1. API ngữ nghĩa đề xuất

    load_artifacts(path)
    reset(initial_soc_fraction, ...)
    update(sample) -> result

Đây không phải xác nhận chữ ký hiện có. Khi xem repository Phase 1, adapter phải giữ interface đã thống nhất, không tự đổi schema REST/database hoặc enum bên ngoài.

Core estimator không import FastAPI, Streamlit, Colab hoặc kết nối database. Notebook gọi core, không chứa một bản EKF khác biệt chạy song song.

### 9.2. Kết quả đề xuất

- `soc_pct`: số 0–100, hoặc null khi không thể cung cấp estimate theo contract.
- `status`: trạng thái tính hợp lệ của kết quả.
- `reason`: lý do chưa sẵn sàng, lỗi hoặc ngoài miền.
- `model_version`, timestamp/run scope.
- Diagnostics riêng cho nghiên cứu: điện áp dự báo, innovation, covariance, số lần chạm biên, trạng thái reset.
- **Telemetry v1.2 (research):** `LOW_SOC_MODEL_UNCERTAIN` (boolean/null), `low_soc_voltage_threshold_v = 3.2976`, `warning_policy_version`, `approval_record_id`/provenance; tách khỏi `status` kiểm tra đầu vào và không quảng bá là cảnh báo an toàn pin.

`NOT_READY` đã xuất hiện trong bản chuyển giao. Các nhãn `VALID`, `INVALID_INPUT`, `OUT_OF_DOMAIN`, `NUMERICAL_ERROR` là đề xuất nội bộ, phải map sang contract Phase 1 sau khi kiểm tra code.

`VALID` có nghĩa đủ điều kiện tính toán theo contract, không có nghĩa biết chắc SoC đúng với thực tế. Khi cờ `LOW_SOC_MODEL_UNCERTAIN=true`, kết quả nếu vẫn `VALID` về mặt tính toán **phải mang cảnh báo chất lượng mô hình**, không được âm thầm trình bày như độ chính xác đã xác nhận.

### 9.3. Mức tích hợp trong Phase 2

Chỉ yêu cầu import được module và chạy một adapter smoke test bằng replay nhỏ. Tích hợp đầy đủ luồng API, database, dashboard và cảnh báo hệ thống thuộc Phase 4.

---

## 10. P2.6: Protocol đánh giá

### 10.1. Khóa protocol và window trước test

`evaluation_protocol.yaml` + `window_manifest.csv` phải ghi: file/run SHA-256, OCV source cell / target dynamic cell, train/validation/test role, seed, capacity/reference anchor, configuration, **dynamic window start/end theo step/event được kiểm tra**, nguyên tắc deduplicate và timestamp; metric; danh sách loại trừ **vì lỗi dữ liệu** được định nghĩa trước khi nhìn sai số. **v1.2 bổ sung:** warning threshold `3.2976 V`, cách phân nhóm flagged/non-flagged, approval record, model candidate hash, điều kiện lock config và quy tắc **chỉ mở held-out một lần** sau lock.

- **Pre-conditioning không là vùng chấm điểm** nếu bài toán định nghĩa là 'SoC under dynamic load', vì đây là cách chọn population theo protocol trước khi quan sát kết quả, không phải tự cắt đầu run để cải thiện metric.
- Khởi tạo estimator tại mốc đầu dynamic: chỉ sử dụng thông tin lịch sử pre-conditioning sẵn có cho runtime hoặc ghi rõ scenario oracle; CC/EKF nhận prior như nhau.
- Không tự loại *đoạn đầu của dynamic* vì EKF hội tụ chậm. Báo toàn bộ window và hội tụ riêng. Không đổi step boundary/split theo lỗi của EKF.
- Phát cờ `LOW_SOC_MODEL_UNCERTAIN` theo **điện áp đo**, không dùng nó để lọc bỏ các điểm cuối xả khỏi **population đánh giá ER4**.
- Trước P2.6, khóa cấu hình ECM candidate, `P0/Q/R`, warning policy, seeds, code/environment hashes, metrics và reference. Sau đó chạy US06/BJDST **một lần**. Không dùng kết quả test để sửa cấu hình rồi tiếp tục gọi test cũ là holdout chưa thấy.
- Nếu quay lại tuning sau khi xem test, đánh dấu **`test_exposed=true`**; giữ kết quả fail đầu tiên, và cần held-out độc lập mới (hoặc thiết kế lại tuyên bố nghiên cứu) để nghiệm thu không thiên lệch.

### 10.2. Kịch bản

| Kịch bản | Cách chạy | Mục đích |
|---|---|---|
| Danh định | Nguồn initialization rõ; input không thêm perturbation | Đánh giá cơ sở |
| Lệch SoC đầu | ±10 và ±20 điểm phần trăm khi vẫn trong 0–100% | Khả năng phục hồi sai số prior |
| Nhiễu đo | Thêm nhiễu V/I có biên độ khai báo | Độ nhạy; không gọi đó là nhiễu đo được của sensor thật |
| Bias dòng | Cộng offset dòng có kiểm soát | Khả năng chống trôi và giới hạn EKF |
| Timestamp/gap/NaN | Chèn lỗi có vị trí biết trước | Xác minh hành vi an toàn dữ liệu, không bắt buộc duy trì estimate |
| Khác nhiệt độ | Phần mở rộng sau v1 | Kiểm tra domain shift; không tự gộp vào kết quả 25°C |

Mức noise/bias chốt trước test, không lấy bất kỳ con số tùy tiện nào làm đặc tính cảm biến thật.

Baseline và EKF phải nhận cùng dòng/điện áp khả dụng, capacity model và prior của từng kịch bản. Không sửa reference bằng đầu vào đã thêm nhiễu.

### 10.3. Metrics

Đặt `e_k = 100 * (z_est_k - z_ref_k)`, đơn vị **điểm phần trăm**:

    MAE = mean(abs(e))
    RMSE = sqrt(mean(e**2))
    P95 = percentile(abs(e), 95)
    MAX = max(abs(e))

Báo từng profile/run, sau đó mới báo tổng hợp. Không để run dài che kết quả kém ở run ngắn.

**Tách hai population của v1.2, bằng voltage đo hữu hạn tại mỗi observation:**

- `FULL_DYNAMIC`: **toàn bộ** dynamic window đã khóa, bao gồm observations flagged. Đây là tập duy nhất dùng để đối chiếu mục tiêu ER4.
- `NON_FLAGGED`: chỉ những observations trong cùng window có `V_measured >= 3.2976 V`, cờ false và có reference/estimate hợp lệ theo policy. Đây là diagnostic bổ sung; không dùng subset để kết luận ER4.
- Với `FLAGGED` (`V_measured < 3.2976 V`), vẫn báo số lượng/tỷ lệ và có thể báo metrics riêng như phân tích failure nếu reference/estimate hợp lệ. Tuyệt đối không xóa khỏi `FULL_DYNAMIC`.
- Cả `FULL_DYNAMIC` và `NON_FLAGGED` phải báo **MAE, RMSE, P95 và MAX(|e|)** cùng **numerator/denominator coverage**. Nếu subset rỗng, ghi `N/A (n=0)`; không trả số 0 như đã đạt. Mẫu không có estimate/reference phải được tính vào báo cáo coverage và trạng thái, không im lặng biến mất khỏi population.

**Cảnh báo diễn giải:** metric trên subset có thể đẹp hơn metric toàn window đơn giản vì đã loại vùng điện áp khó. Nó **không** thay thế nghiệm thu toàn window.

Báo thêm:

- Coverage: tỷ lệ **observation/event hợp lệ trong dynamic window đã khóa** có estimate và số bị bỏ; report riêng raw-row count, số duplicate/event hợp nhất và số measurement dùng thực tế.
- Sai số cả **dynamic window** từ điểm khởi tạo tại dynamic start; không chỉ đoạn sau khi EKF hội tụ. Sai số pre-conditioning có thể báo riêng nhưng không trộn vào ER4 dynamic.
- Sai số điện áp và innovation.
- Thời gian hội tụ cho kịch bản prior sai.
- Số lần reset, chạm biên, ngoài miền và lỗi số học.
- Thời gian xử lý trên môi trường đo được; chưa cam kết thời gian thực trên ESP32.

Đề xuất định nghĩa convergence: lần đầu |e| ≤5 điểm phần trăm liên tục trong 60 giây, đánh giá trên các mẫu hợp lệ đủ coverage. Đây là metric nghiên cứu đề xuất, không phải tiêu chí có sẵn trong logbook. Không hội tụ thì ghi rõ, không bỏ run.

### 10.4. ER4: Quy tắc chấp nhận có điều kiện đã cập nhật (18/11/2026)

Theo nội dung phê duyệt trong chat do người phụ trách thông báo, **tiêu chí mục tiêu** trên **mỗi run held-out US06/BJDST** trong **toàn bộ dynamic window danh định đã khóa** là:

```text
e_k_pp = 100 * (z_est[k] - z_ref[k])
ER4_run_target: MAX_k (abs(e_k_pp)) <= 10 percentage points
```

1. Chỉ thực hiện **sau P2.4/P2.5**, khi `P0`, `Q`, `R` đã được chọn trên **DST/FUDS** và toàn bộ mã/cấu hình đã khóa; US06/BJDST không tham gia fitting, lựa chọn warning threshold hoặc tune EKF.
2. Áp trên **từng run**, không thay bằng MAE/RMSE/P95 hoặc trung bình các run. Không loại samples cuối xả có `LOW_SOC_MODEL_UNCERTAIN=true`, không loại phần đầu dynamic vì sai số lớn; pre-conditioning nằm ngoài metric **theo protocol window đã khóa từ trước**.
3. Chỉ có thể tuyên bố **ER4 PASS** khi reference đáng tin trong giới hạn đã công bố, coverage/invalid events đáp ứng tiêu chí đã đăng ký và **mỗi run** đều thỏa MAX ≤10 điểm phần trăm. Nếu coverage chưa có chuẩn nghiệm thu được phê duyệt, phải báo rõ `ER4_ACCEPTANCE_INCOMPLETE` thay vì suy đoán PASS chỉ dựa trên các mẫu có estimate.
4. Nếu một run vượt ngưỡng hoặc protocol/coverage không hợp lệ, ghi rõ `ER4_FAIL` hoặc `ER4_NOT_ASSESSABLE` tương ứng; **quay lại P2.3 đề xuất ECM revision**. Bất kỳ đánh giá lại sau khi đã nhìn thấy test phải công bố `test_exposed` và không được coi cùng tập test là held-out pristine.
5. **Hiện trạng ngày 18/11:** chưa chạy CC/EKF, chưa có SoC metrics, **`ER4=NOT_EVALUATED`**. Số liệu voltage replay P2.3 không được dùng thay thế cho sai số SoC.

**Phạm vi:** tiêu chí trên chỉ đánh giá offline trên CALCE held-out trong điều kiện dữ liệu của nghiên cứu. Không chứng nhận an toàn hardware, không thay thế kiểm chứng trên Lishen và không tự động chuyển ECM scientific release thành `PASS`.

## 11. P2.7: Kiểm thử và bàn giao

### 11.1. Tests bắt buộc

| Nhóm | Bài kiểm tra |
|---|---|
| Parser / segmentation | `Step_Index` và dynamic start không hardcode; nhận đúng pre-conditioning; chart/manifest đối chiếu dòng và step |
| Arbin counters | Counter tăng, reset ở step/cycle, carry-over, đối chiếu với tích phân sampled current; không trừ trực tiếp qua reset |
| Clock/event | `dt=0` không đếm Ah hai lần; event step transition có thể có V/I mới; không double-correct V giống nhau |
| Reference | Anchor, `capacity_ref_ah`, sign, charge/discharge convention; test không có ground truth độc lập |
| OCV | PCHIP `extrapolate=False`, monotone-domain checks, đạo hàm liên tục ở knot, biên và plateau; nhánh charge/discharge |
| ECM | Hồi phục `v_rc` mũ ở I=0 theo mô hình; `tau>0`; nhận dạng từ xung; provenance SP3/SP2 |
| EKF | Khởi tạo không oracle trừ khi khai báo; covariance hợp lệ; `z_unconstrained` được log rồi state trong [0,1]; domain OCV riêng |
| Gap/rest | Rest xác minh 10–60 s không bị reset; gap có xung ẩn không bị đoán là rest; active gap có status phù hợp |
| Jacobian | Đúng cho fixed 1-RC và (nếu dùng) SoC-dependent RC, kiểm tra đạo hàm bằng finite differences |
| Causality/split | Không dùng SoC reference hay mẫu tương lai trong estimator; không rò rỉ run/profile/test vào fitting |
| Package | Notebook và module khớp nhau; import độc lập Colab, giữ contract Phase 1 |
| Conditional gate | Approval record v1.2 được lưu riêng; opt-in research guard nhận đúng SHA-256 candidate; loader mặc định vẫn từ chối unreleased artifact |
| Low-voltage warning | Test quanh 3.2976 V, NaN, 2.50 V, cờ telemetry không làm đổi EKF recurrence hay số observations chấm |
| ER4 populations | Test chấm `FULL_DYNAMIC` bao gồm flagged, `NON_FLAGGED` chỉ diagnostic; MAE/RMSE/P95/MAX theo run, coverage đầy đủ |
| Held-out governance | Tự động khóa model/config trước test, kiểm tra không đọc US06/BJDST trước P2.6, đánh dấu `test_exposed` nếu test đã được xem |

Synthetic tests chứng minh logic, không chứng minh accuracy CALCE.

### 11.2. Cấu trúc gợi ý

    phase2_soc/
      README.md
      pyproject.toml
      requirements-lock.txt
      notebooks/
        01_data_exploration.ipynb
        02_ocv_soc.ipynb
        03_ecm_identification.ipynb
        04_coulomb_counting.ipynb
        05_ekf_estimation.ipynb
        06_evaluation.ipynb
      src/soc/
        data.py
        ocv.py
        ecm.py
        coulomb_counting.py
        ekf.py
        evaluation.py
      tests/
      configs/
      manifests/
      artifacts/
      results/

Nếu repository Phase 1 đã có cấu trúc phù hợp, đặt module vào đó thay vì tạo kiến trúc thứ hai. Tên trên chỉ là gợi ý phân trách nhiệm.

Trên Drive giữ `raw/`, `processed/`, artifacts và kết quả lớn. Code, config, manifest và báo cáo nhẹ giữ trong Git. Đường dẫn là cấu hình, không hardcode một tài khoản Drive.

### 11.3. Bộ artifacts

- `dataset_manifest.csv`, `split_manifest.json`, `data_quality_report.md`.
- `reference_protocol.md`, `capacity_metadata.json`.
- `ocv_table.csv`, **`ecm_params.json` vẫn unreleased**, `ekf_config.json` (tạo ở P2.5).
- **Bắt buộc bổ sung cho v1.2 trước P2.4/P2.5:** `conditional_approval_record.json` hoặc `.md` (có nguồn phê duyệt thực), `configs/g10_conditional_run_policy.yaml` (ngưỡng 3.2976 V và giới hạn quyền), audit log của loader; tên có thể đổi nhưng phải giữ nội dung tương đương và provenance.
- `artifact_manifest.json`: schema version, model version, đơn vị, domain, hashes, commit nếu có và nguồn.
- `metrics.csv`, trajectory outputs, hình và `evaluation_report.md`.
- Module Python, tests và hướng dẫn chạy.

**Trạng thái artifact:** `artifacts/capacity_metadata.json` và các tài liệu P2.2 được nêu trong phần 5.4 là **bằng chứng đã có từ gói P2.2**. Phần lớn file thuộc P2.4–P2.7 ở danh sách trên vẫn là **đầu ra dự kiến**, chưa được tạo; `conditional_approval_record` và warning config **chưa được ghi** ở thời điểm cập nhật này. Không được tự ghi `PASS` dựa vào tên file tồn tại.

Ưu tiên JSON/CSV/NPZ minh bạch; không yêu cầu tải pickle từ nguồn không kiểm soát.

### 11.4. Definition of Done

Phase 2 chỉ được ghi hoàn tất khi có:

1. Dataset/units/sign/reference/split được kiểm tra và truy vết.
2. OCV/capacity/ECM được nhận dạng từ nguồn được phép.
3. CC và EKF chạy bằng code tái sử dụng, có tests.
4. Cấu hình cuối không được chọn bằng test.
5. Kết quả từng run, coverage, các thất bại và giới hạn đều được báo.
6. Package/artifacts tái lập trong runtime mới theo hướng dẫn.
7. Mapping sang interface Phase 1 và smoke test import/replay.
8. Kết luận riêng “hoàn thành triển khai” và “đạt/chưa đạt tiêu chí hiệu năng”.
9. Có approval record `APPROVED_CONDITIONAL` đầy đủ provenance, warning telemetry, full-window metrics/coverage và báo cáo rõ rằng ECM vẫn unreleased; không che failure cases.
10. ER4 có kết luận riêng dựa trên **mỗi held-out run** và `test_exposed` nếu có. Việc đạt ER4 (nếu xảy ra) không tự động xóa G10 hoặc cho phép phát hành mô hình không hạn chế.

---

## 12. Việc làm ngay sau cập nhật 18/11/2026: khởi động P2.4 có điều kiện

**Điểm xuất phát xác nhận:** P2.0 `PASS_OFFLINE`, P2.1/P2.2 `PASS`; P2.3 candidate đã có nhưng unreleased, G10 `NEEDS_REVIEW`; acquisition `INCONCLUSIVE`. P2.4–P2.7 **chưa chạy**, hiện chỉ mới đến chuẩn bị môi trường Python.

1. **Ghi phê duyệt (bắt buộc trước code chạy):** lập `conditional_approval_record` với quyết định `APPROVED_CONDITIONAL`, người duyệt và nguồn chat thực tế, phạm vi P2.4/P2.5, giữ `scientific_release=false`, baseline/source SHA-256, ngày và người thực hiện. Không bịa URL/message ID nếu chưa có.
2. **Ghi warning policy trong config riêng:** `LOW_SOC_MODEL_UNCERTAIN` khi `V_measured < 3.2976 V`; xác định telemetry schema, unit tests và quyền research opt-in. **Không** sửa `ecm_params.json`, OCV, capacity, frozen split/window hoặc giả tạo release bit.
3. **Kiểm tra đầu vào P2.4:** đọc verified `artifacts/capacity_metadata.json` và `reference_protocol_P2_2.md`/`configs/p2_2_reference_policy.yaml`; xác minh current sign >0 khi xả, `I_prev`, dt, initialization và boundary đã khóa; kiểm SHA/provenance input.
4. **Triển khai P2.4 – CC baseline:** viết/kiểm tra module và notebook 04, integration/unit tests cho dấu dòng, dt=0, current bias, charge/discharge, prior equivalence và absence of reference leakage; tạo trajectory DST/FUDS hợp lệ. Báo kết quả P2.4, **không tự đánh giá ER4**.
5. **Sau khi P2.4 qua gate, triển khai P2.5 – EKF:** dùng fixed ECM candidate dưới guard có điều kiện, OCV/capacity đã khóa; kiểm covariance/Jacobian, timestamp/gap và warning policy; hiệu chỉnh `P0`, `Q`, `R` **chỉ trên DST/FUDS**. Mọi lỗi model/cutoff vẫn giữ trong diagnostics và reports.
6. **Khóa final evaluation protocol:** xác nhận frozen models, config, warning threshold, seed, software environment, coverage requirement, full-window/`NON_FLAGGED` metrics, P2.6 approval/lock record; tuyệt đối không mở held-out trước lock.
7. **P2.6 khi đủ điều kiện:** chạy US06/BJDST **một lần**, báo toàn dynamic và ngoài-cờ, với MAX(|e|) ≤10 điểm phần trăm **cho từng run** làm tiêu chí ER4. Nếu fail, lưu kết quả và quay về P2.3 theo change request; không retune rồi tái dùng test cũ như pristine.
8. **P2.7 khi được phép:** bàn giao module, tests, artifacts, diagnostics, phase1 adapter, validation/failure reports; ghi rõ conditional-use chỉ phục vụ đánh giá nghiên cứu, chưa có ECM scientific release.

**Không thực hiện trong lượt này:** fitting lại ECM, thay OCV/capacity, dùng FUDS làm calibration loss, tự mở US06/BJDST trước bước 7, làm ML residual, phát hành model, thay đổi module bảo vệ phần cứng hoặc sửa Logbook khi nhóm chưa phê duyệt.

## 13. Nguồn, evidence và quy tắc truy vết

**[S1] Nguồn nội bộ ban đầu:** `PBL5_TOM_TAT_CHUYEN_GIAO_CHAT_MOI(1).md` (11/11/2026) và `PBL5_PHASE_2_SOC_PLAN_SPEC_v1.1(2).md` (12/11/2026). Bản v1.1 là **trạng thái thiết kế tại ngày 12/11**; các phát biểu “chưa audit raw” trong nó không phải trạng thái ngày 18/11.

**[S1a] Handoff Phase 2:** `PBL5_PHASE2_TONG_HOP_TOAN_BO_VA_HANDOFF_2026-11-15(1).md`: milestone P2.1/P2.2, tham số fixed ECM và sai số điện áp, G10 forensic/ICF, split, gating. Các ZIP/manifest P2.1/P2.2/P2.3 và G10 evidence là nguồn sơ cấp khi cần tái lập.

**[S1b] Identifiability evidence R2:** `G10_IDENTIFIABILITY_FEASIBILITY_REPORT(2).md` cùng `PBL5_P2_3_G10_IDENTIFIABILITY_SOURCE_ONLY_20261115(2).zip` và `PBL5_P2_3_G10_IDENTIFIABILITY_EVIDENCE_r2_20261115(1).zip`: local rank và data blocker, **không** cho phép release ECM.

**[S1c] Acquisition 16/11:** `G10_DATA_DECISION_REPORT.md` và `P2_3_G10_SAME_CELL_ACQUISITION_20261116_REPORTS (1).zip`: `INCONCLUSIVE`, 41.105 dòng DST 0°C/45°C, thiếu support same-cell 25°C, không có correction được validated.

**[S1d] Cập nhật người phụ trách 18/11/2026 (do người dùng cung cấp):** `P2.2/B1 PASS` và giá trị capacity chính xác; quyền **`APPROVED_CONDITIONAL` qua chat** để triển khai P2.4–P2.5 với warning 3.2976 V; quy tắc MAX(|e|) từng held-out run. **Chưa có approval record/config hay evidence chạy P2.4–P2.7** tại thời điểm chốt v1.2. Phải lưu nguồn phê duyệt khi triển khai; Spec không phải bản ký thay người phụ trách.

**Logbook dự án:** https://docs.google.com/document/d/1GSKzZFmZwOwOVgl5kWV8mKFYUPT4FCpcLIsPtVXF9ec/edit?tab=t.0. Kiến trúc Level-2 F2.1–F2.4 trong Bảng 2.8/Hình 2.9/mục 2.3.2 vẫn cần đồng bộ chính thức nếu nhóm duyệt offline-calibration. Cập nhật Spec v1.2 **không đồng nghĩa** đã cập nhật Google Doc.

**[S2] CALCE, University of Maryland:** https://calce.umd.edu/battery-data. Nguồn index công khai; trạng thái raw archive cần dựa vào audit/manifests từ P2.1 và acquisition, không suy từ URL.

**[S3] MathWorks, SOC Estimator (Kalman Filter):** https://www.mathworks.com/help/simscape-battery/ref/socestimatorkalmanfilter.html. Tham khảo phương trình ECM/EKF, không dùng block defaults như tham số nhận dạng dự án.

**Thứ tự ưu tiên nguồn:** dữ liệu/artifact + SHA + protocol đã khóa → evidence/report theo milestone → quyết định phê duyệt có nguồn truy vết → Spec v1.2 hợp nhất → định hướng Logbook. Không để một câu mô tả lịch sử ghi đè evidence mới hoặc biến phê duyệt có điều kiện thành scientific release.

## 14. Đề xuất sửa Logbook để tránh xung đột F2 (chưa áp dụng trực tiếp)

Đọc trực tiếp Logbook ngày 12/11/2026 xác nhận tại **mục 2.2.3, Bảng 2.8**:

- F2.1 hiện ghi **Online ECM Parameter Estimation**.
- F2.2 hiện ghi **OCV Estimation Using KF**.
- F2.3 hiện ghi **Adaptive SoC–OCV Curve Construction** dùng KF.
- F2.4 hiện ghi **SoC Estimation Using EKF**.

Đây là **khác biệt kiến trúc thực sự**, không chỉ khác tên gọi. Tuy nhiên kết luận 'ba KF chắc chắn không quan sát được (unobservable)' là **quá mạnh**: tính quan sát/phân biệt tham số phải được chứng minh theo mô hình, kích thích và các tín hiệu quan sát; nhiều cấu hình adaptive/multi-filter vẫn có thể hoạt động trong nghiên cứu [S6]. Lý do chuyển sang calibration offline là **giảm phạm vi, chi phí kiểm chứng, vòng phụ thuộc và rủi ro định danh**, chứ không phải định lý mọi cấu trúc cũ đều vô nghiệm.

**Bản thay thế đề xuất (giữ F2.1–F2.4):**

| Module | Input | Output | Chức năng |
|---|---|---|---|
| **F2.1 – Offline ECM Parameter Identification** | I/V/time + pulses/rest; cell/sample metadata; source OCV; temperature | R0,R1,C1 (constant hoặc mapping theo SoC có kiểm chứng), calibration metadata | Nhận dạng trên calibration data, kiểm tra transfer SP3→SP2 và xuất artifacts; **không tự update trong runtime v1** |
| **F2.2 – Offline OCV–SoC Characterization** | Incremental OCV, capacity reference, rest/charge/discharge steps | OCV(z), dOCV/dz, miền được hiệu chuẩn | Xây PCHIP offline, lưu provenance SP3 và điều kiện áp dụng SP2 |
| **F2.3 – Offline Model Validation & Artifact Packaging** | Calibration/validation profiles; ECM; OCV; reference protocol | Validated parameter package, model version, domain, reports | Kiểm tra ECM, khóa cấu hình, phát hiện model mismatch trước khi đưa vào EKF runtime |
| **F2.4 – Online SoC Estimation Using EKF** | Live V/I/time; calibrated ECM/OCV; initial state | Estimated SoC (%), validity status, diagnostics | EKF runtime, kiểm soát biên, gap, covariance; mục tiêu ER4 |

**Đoạn mô tả thay thế (để chèn vào mục 2.2.3):**

> Chức năng F2 – SoC Estimation sử dụng kiến trúc Hybrid Model-Based: các khối F2.1–F2.3 thực hiện đặc trưng hóa OCV–SoC, nhận dạng và kiểm chứng tham số ECM trong pha Offline Calibration; F2.4 sử dụng artifacts đã kiểm chứng để ước lượng SoC trực tuyến bằng Extended Kalman Filter. V1 không triển khai đồng thời các bộ Kalman Filter thích nghi độc lập để cập nhật tham số ECM, OCV và đường SoC–OCV. Phần thích nghi trực tuyến được coi là hướng nghiên cứu mở rộng, không phải thành phần bắt buộc của Phase 2.

**Các vị trí phải đồng bộ cùng lúc:** Bảng 2.8; Hình 2.9 (đường ranh giới Offline/Online và luồng artifacts); 2 đoạn giới thiệu F2 tại mục 2.2.3; câu 'Phương pháp thiết kế gồm bốn chức năng đã xác định ở Level 2' trong mục 2.3.2; spec/code và sơ đồ phần mềm liên quan. **Chưa tự sửa Google Doc** vì nhóm cần chốt thay đổi thiết kế có ảnh hưởng sơ đồ.

**Cập nhật 18/11:** chấp thuận triển khai candidate v1 có điều kiện **không** làm thay đổi kiến trúc F2.1–F2.4, không khôi phục online/adaptive filters, không thêm module residual ML vào Phase 2. Các đề xuất đồng bộ phải ghi rõ trạng thái G10 unreleased và cảnh báo dưới ngưỡng 3.2976 V khi mô tả bản thử nghiệm.

## 15. Nguồn bổ sung và changelog v1.2

- **[S4] SciPy PCHIP:** https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.PchipInterpolator.html — liên tục đạo hàm cấp 1, không nhất thiết cấp 2; mặc định có thể ngoại suy nếu không đặt `extrapolate=False`.
- **[S5] Arbin MITS export, counter reset:** https://www.arbin.com/what-can-be-included-in-the-export-file-eis-data-statistics-coulombic-efficiency.html và https://www.arbin.com/hybrid-pulse-power-characterization-hppc-testing-with-arbin-mits-pro.html — cột capacity trong export và khả năng reset counters theo schedule. Không suy ra tần số tích phân nội bộ từ cột XLS.
- **[S6] Nghiên cứu adaptive/online filters:** https://www.sciencedirect.com/science/article/pii/S2352152X22002067 — ví dụ về ước lượng tham số online + Kalman; không có cơ sở khẳng định mọi cấu trúc nhiều KF là unobservable.
- **v1.1 (12/11/2026):** đưa segmentation trước scoring; phân biệt archive đã công bố và file đã đọc; điều kiện SP3/SP2 transfer; counter reset/reference; PCHIP; pulse/rest fitting; clip state nội bộ; rest gap theo evidence; sửa ER4 scoring window; thêm đề xuất đồng bộ Logbook.
- **v1.2 (18/11/2026):** cập nhật `P2.0 PASS_OFFLINE`, `P2.1 PASS`, `P2.2/B1 PASS` và capacity chính xác `2.028344937765965 Ah`; P2.3 fixed ECM v1 và G10 mismatch ~0.47 V trên FUDS; acquisition `INCONCLUSIVE`/41.105 dòng 0°C/45°C; ghi nhận thông tin **chat approval `APPROVED_CONDITIONAL`** với caveat chưa tạo config/evidence; quy tắc `LOW_SOC_MODEL_UNCERTAIN` khi `V_measured < 3.2976 V`; metrics **FULL_DYNAMIC + NON_FLAGGED**; chốt mục tiêu `MAX(|e|) <= 10 pp` cho từng held-out run sau config lock; P2.4–P2.7 chưa thực thi, `ER4=NOT_EVALUATED`; cập nhật kế hoạch hành động. **Không thay đổi ECM candidate, scientific release, raw, OCV, split/window hoặc test results.**
