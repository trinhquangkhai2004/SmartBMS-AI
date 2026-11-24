# P3.7 — Kết quả held-out RT-Batt v2

**ER5_PASS** theo D07. FULL_ELIGIBLE có **37,130 khóa trên 19 cell**. SoH tham chiếu là dung lượng vận hành tương đối của cell LFP.

| Chỉ số RF (pp nếu là sai số) | Raw | VALID |
|---|---:|---:|
| Số dự đoán | 37,130 | 35,586 |
| Độ phủ | 100.00% | 95.84% |
| Macro MAE | 0.8973 | 0.9032 |
| Macro RMSE | 1.0179 | 1.0183 |
| Micro MAE | 0.9908 | 1.0046 |
| Micro RMSE | 1.3988 | 1.4101 |
| Micro P95 | 3.1942 | 3.1981 |
| Micro MAX | 4.6181 | 4.6181 |

Guard ghi 632 OOD, 912 uncertain, 0 jump, 0 thiếu HI và 0 resync. Có 95 cycle ngoài eligibility đã khóa ở P3.3. Mọi khóa đủ điều kiện vẫn nằm trong mẫu số.

| Mô hình trên FULL_ELIGIBLE | Số dự đoán | Macro-MAE raw (pp) |
|---|---:|---:|
| train_median | 37,130 | 6.0503 |
| ridge | 37,130 | 1.1030 |
| rf | 37,130 | 0.8973 |
| rf_unweighted | 37,130 | 0.8891 |
| xgb | 37,130 | 0.9044 |
| voltage_window_only | 37,130 | 6.1584 |
| cc_cv_only | 37,130 | 1.0053 |
| phase_and_ratio | 37,130 | 1.0125 |

| Dải SoH tham chiếu | Phiên | Cell | Raw MAX (pp) | VALID |
|---|---:|---:|---:|---:|
| SOH_GE_80 | 32,256 | 19 | 4.6181 | 95.95% |
| SOH_LT_80 | 4,874 | 19 | 3.7969 | 95.10% |

Có 3 cell dưới 90% VALID. Hai dải SoH dùng để chẩn đoán.

[Chỉ số theo cell](P3_7_TEST_METRICS_PER_CELL.csv) · [Độ phủ OOD](P3_7_OOD_COVERAGE_BY_CELL.csv) · [Hai dải SoH](P3_7_SOH_BAND_DIAGNOSTICS.csv) · [Profile và cycle](P3_7_PROTOCOL_PERIOD_DIAGNOSTICS.csv) · [Ablation](P3_7_ABLATION.csv) · [Phân tích lỗi](P3_7_FAILURE_ANALYSIS.md)
