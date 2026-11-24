# P3.6 — Kiểm tra XGBoost fixed-grid và refit

Chiến lược `FIXED_CV_N_ESTIMATORS`. Lưới n_estimators 100, 200, 400, 600 đã đăng ký trước CV. Mỗi fold dùng đúng bốn HI và trọng số theo cell train. Early stopping tắt, không truyền eval_set trong cả CV lẫn full refit. Chọn theo macro-MAE trên 57 cell OOF.

| Ứng viên | Số cây | Fold 1 | Fold 2 | Fold 3 | Fold 4 | Fold 5 | Gộp 57 cell (pp) |
|---|---:|---:|---:|---:|---:|---:|---:|
| xgboost-1 | 100 | 0.772646 | 0.691410 | 0.563348 | 0.657158 | 0.834269 | 0.702732 |
| xgboost-2 | 200 | 0.731725 | 0.714805 | 0.484388 | 0.719880 | 0.852223 | 0.701191 |
| xgboost-3 | 400 | 0.713548 | 0.736275 | 0.483914 | 0.727047 | 0.894857 | 0.711848 |
| xgboost-4 | 600 | 0.705340 | 0.746689 | 0.493733 | 0.720255 | 0.913790 | 0.716576 |

Full refit **200 cây** trên **57 cell** và **106,733 hàng**. Chênh lớn nhất sau reload 0 pp. XGBoost 3.0.5.

[Cấu hình XGBoost](../configs/p3_xgb_training.yaml) · [Kết quả đầy đủ](P3_6_CV_VALIDATION.csv)
