# P2.6 · Bàn giao chẩn đoán cuối xả

**19/11/2026 · SP20-2 · Spec v1.2 · Kịch bản nominal, cửa sổ `FULL_DYNAMIC`**

**Kết luận.** Cả 356 sự kiện `OUT_OF_DOMAIN` đều có SoC dự đoán `z_pred < 0` trước bước hiệu chỉnh điện áp. Không có dòng điện vượt miền đã khóa trong 35.737 sự kiện. Kiểm tra riêng SoC tham chiếu phát hiện 484 mẫu dưới 0, trong đó 346 mẫu trùng với `OUT_OF_DOMAIN`. Trạng thái nghiệm thu của cả bốn lượt là **`ER4_NOT_ASSESSABLE`**. [Biên bản P2.6](p26/metrics.json)

## 1. Kết quả bốn lượt

| Lượt | Tổng sự kiện | Ngoài miền dòng | Ngoài miền do `z_pred < 0` | SoC tham chiếu ngoài [0, 1] | Trùng cả hai | EKF có kết quả |
|---|---:|---:|---:|---:|---:|---:|
| US06 50% | 6.883 | 0 | 130 | 155 | 130 | 6.753 / 6.883 (98,11%) |
| US06 80% | 10.694 | 0 | 133 | 183 | 123 | 10.561 / 10.694 (98,76%) |
| BJDST 80% | 11.214 | 0 | 64 | 107 | 64 | 11.150 / 11.214 (99,43%) |
| BJDST 50% | 6.946 | 0 | 29 | 39 | 29 | 6.917 / 6.946 (99,58%) |
| **Tổng** | **35.737** | **0** | **356** | **484** | **346** | **35.381 / 35.737 (99,00%)** |

“Trùng cả hai” nghĩa là trên cùng `source_row_0based`, EKF có trạng thái `OUT_OF_DOMAIN` và SoC tham chiếu vượt biên. Có 138 mẫu tham chiếu âm vẫn có kết quả EKF. Cả 10 sự kiện EKF ngoài miền trong khi tham chiếu còn trong [0, 1] đều thuộc US06 80%. Cả bốn lượt có số dòng CSV bằng số sự kiện hiệu dụng. Tỷ lệ tổng chỉ dùng để mô tả, vì tiêu chí độ bao phủ 100% áp dụng cho từng lượt. [Giao thức P2.6](../configs/p26_final_protocol.json)

## 2. Nguyên nhân của 130 dòng US06 50%

- Miền `runtime_current_a` đã khóa là `[-2.1421873569488525, 4.001959800720215]` A. Dòng của cả lượt nằm trong `[-0.8593196868896484, 3.9965412616729736]` A. Riêng 130 dòng ngoài miền có dòng điện trong `[-0.5470462441444397, 3.1471359729766846]` A. [Cấu hình P2.5](p25/ekf_config.json)
- Đường OCV chỉ nhận SoC trong `[0, 1]` và tắt ngoại suy. Cả 130 dòng có `z_pred` trong `[-0.0003364821530154123, -1.4752718385352776e-06]`. Đường chạy nominal dùng nhiệt độ mặc định 25 °C của EKF. Điều kiện kích hoạt `OUT_OF_DOMAIN` trong 130 dòng là dự đoán SoC dưới cận dưới của OCV. [Mô hình OCV](../artifacts/ocv_model.json) · [Điều kiện miền trong EKF](../src/ekf.py#L289) · [Lời gọi EKF](../run_ekf.py#L81)
- Dòng nguồn `8175` có kết quả `VALID`, dòng xả `0.6659256219863892` A và trạng thái SoC sau chiếu biên bằng `0.0`. Ở dòng `8176`, EKF dùng dòng xả mẫu trước trong `1.0063838167152426` s nên `z_pred = -9.177936660260449e-05`. Kiểm tra miền diễn ra trước bước chiếu trạng thái về 0. EKF bỏ qua hiệu chỉnh điện áp và để trống `soc_ekf_fraction` ở dòng này. [Quỹ đạo US06 50%](p26/trajectories/11_11_2015_SP20-2_US06_50SOC.csv.gz)

Kiểm tra công thức dự đoán trên cả bốn lượt tái tạo được `z_pred` cho toàn bộ 356 sự kiện ngoài miền từ trạng thái, dòng mẫu trước và `dt_s` đã lưu. Trong đó 355 sự kiện bắt đầu từ trạng thái SoC bằng 0, một sự kiện bắt đầu từ SoC dương sát 0 (US06 80%, dòng `11703`). Cả 356 đều có cờ `LOW_SOC_MODEL_UNCERTAIN` (điện áp đo dưới 3,2976 V) và không hiệu chỉnh điện áp. Cờ điện áp thấp là thông tin chẩn đoán. Điều kiện quyết định ở đây là `z_pred < 0`. [Mã EKF](../src/ekf.py#L289)

## 3. Kiểm tra riêng SoC tham chiếu

Các giá trị dưới đây là tỷ phần SoC nguyên văn từ cột `soc_ref_fraction_evaluation_only`. Dải dòng tham chiếu âm tính cả hai đầu. Để tra từng dòng, dùng `source_row_0based` trong tệp tương ứng.

| Lượt | Dải dòng tham chiếu âm | Giá trị nhỏ nhất cả lượt | Giá trị lớn nhất trong nhóm âm | Giá trị lớn nhất cả lượt | Dòng đầu `OUT_OF_DOMAIN` |
|---|---|---|---|---|---:|
| US06 50% | `8166–8320` | `-0.014463190874533405` (8320) | `-0.00027912497383142387` (8166) | `0.5068770818131236` (1438) | 8176 |
| US06 80% | `11715–11897` | `-0.010032712819332046` (11897) | `-6.67885839102933e-05` (11715) | `0.8027647244644013` (1204) | 11703 |
| BJDST 80% | `12330–12436` | `-0.012543823943786947` (12436) | `-0.00012395599443548733` (12330) | `0.8027397077686863` (1223) | 12373 |
| BJDST 50% | `8346–8384` | `-0.006826201188903536` (8384) | `-4.807796092087813e-05` (8346) | `0.5068664995046224` (1439) | 8356 |

Ở US06 50%, tham chiếu âm lần đầu tại dòng `8166` khi EKF vẫn `VALID` và `z_pred = 0.00514692125032275`. Tất cả 130 dòng ngoài miền nằm trong 155 dòng tham chiếu âm. Ở US06 80%, EKF ra ngoài miền 12 dòng trước khi tham chiếu âm lần đầu. Tham chiếu từng mẫu được dùng để chấm điểm. EKF nhận giá trị khởi tạo từ lịch sử đến đầu cửa sổ, rồi dùng dòng và điện áp để cập nhật. [Lượt US06 50%](p26/runs/11_11_2015_SP20-2_US06_50SOC.json) · [Lượt US06 80%](p26/runs/11_11_2015_SP20-2_US06_80SOC.json)

Cả bốn lượt có tham chiếu hữu hạn và không có mẫu trên 1. Theo quy tắc P2.2 áp dụng trong P2.6, SoC tham chiếu bằng mốc đầy vận hành (gán bằng 1 sau CC–CV và nghỉ) cộng với điện lượng ròng theo bộ đếm Arbin (nạp trừ xả) chia cho dung lượng khóa `2.028344937765965` Ah. Giá trị cuối lượt tương ứng điện lượng xả ròng vượt dung lượng khóa khoảng **13,85–29,34 mAh** theo công thức này. Cả bốn lượt mang cờ `OUT_OF_RANGE_REFERENCE` và chất lượng `PROVISIONAL`. Hồ sơ bộ đếm không ghi nhận khoảng trống chưa giải quyết. Cần kiểm chứng mốc đầy, dung lượng hữu dụng tới ngưỡng cắt và độ chính xác bộ đếm để quy nguyên nhân vật lý. [Dung lượng khóa](../artifacts/capacity_metadata.json) · [Cách dựng tham chiếu](../src/final_evaluation.py#L109) · [Biên bản từng lượt](p26/runs/)

## 4. Bước tiếp theo theo Spec v1.2

1. **P2.3, hành vi EKF ở biên SoC thấp.** Dùng dữ liệu phát triển và phép thử tổng hợp để kiểm tra cách dự đoán, giới hạn miền OCV và trả trạng thái quanh 0% khi vẫn đang xả. Ưu tiên kiểm chứng trên dữ liệu cùng cell ở vùng cuối xả nếu thu được. Miền dòng hiện hành bao phủ toàn bộ mẫu trong bốn lượt đã kiểm tra.
2. **Kiểm chứng lại cách dựng SoC tham chiếu.** Rà mốc đầy, dung lượng và điện lượng đến điểm cắt bằng dữ liệu hiệu chuẩn độc lập. Giữ các giá trị tham chiếu âm trong hồ sơ gốc để định lượng độ lệch và truy vết tới số hàng nguồn.
3. **Đăng ký phiên bản mới trước lần nghiệm thu tiếp theo.** Giữ kết quả v1 `ER4_NOT_ASSESSABLE` và trạng thái `test_exposed=true`. US06/BJDST hiện tại dùng để chẩn đoán. Phiên bản mới cần một tập kiểm thử độc lập chưa xem, với mã, cấu hình, quy tắc tham chiếu và tiêu chí được khóa trước. Kiến trúc vẫn theo phương án đã duyệt gồm hiệu chuẩn offline và ước lượng SoC online bằng EKF. [Spec v1.2, mục 10.4](../sources/PBL5_PHASE_2_SOC_PLAN_SPEC_v1.2_2026-11-18.md#104-er4-quy-tắc-chấp-nhận-có-điều-kiện-đã-cập-nhật-18112026) · [Giao thức P2.6](../configs/p26_final_protocol.json)

## Đối chiếu bằng chứng

Đọc bốn quỹ đạo nominal đã lưu theo thứ tự nguồn, so sánh hai miền với ngưỡng đầy đủ và đối chiếu số đếm với biên bản từng lượt. Đã kiểm tra SHA-256 của bản khóa P2.6, 21 tệp trong danh sách khóa, gói P2.2, bốn biên bản và bốn quỹ đạo. Phân tích đọc dữ liệu đã lưu, không chạy lại EKF trên tập US06/BJDST. [Bản khóa](p26/locked_protocol.json) · [Bốn quỹ đạo](p26/trajectories/)
