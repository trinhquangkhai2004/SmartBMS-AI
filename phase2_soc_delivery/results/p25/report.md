# P2.5 · EKF trên các run phát triển

SoC được đối chiếu với reference tái dựng từ bộ đếm Arbin. Các phép đo đến cutoff nằm trong mẫu số toàn cửa sổ.
G10 vẫn NEEDS_REVIEW. ECM chưa được phát hành khoa học. ER4 chưa đánh giá.

| Run | Phạm vi | Có SoC / tổng | MAE (pp) | RMSE (pp) | P95 (pp) | MAX (pp) |
|---|---|---:|---:|---:|---:|---:|
| 11_05_2015_SP20-2_DST_50SOC | FULL_DYNAMIC | 6698/6698 | 0.6195 | 0.7703 | 1.3276 | 1.7614 |
| 11_05_2015_SP20-2_DST_50SOC | NON_FLAGGED | 6415/6415 | 0.6326 | 0.7823 | 1.3329 | 1.7614 |
| 11_05_2015_SP20-2_DST_50SOC | FLAGGED | 283/283 | 0.3228 | 0.4095 | 0.8886 | 1.0101 |
| 11_05_2015_SP20-2_DST_80SOC | FULL_DYNAMIC | 10645/10645 | 0.8551 | 0.9666 | 1.7676 | 1.8884 |
| 11_05_2015_SP20-2_DST_80SOC | NON_FLAGGED | 10369/10369 | 0.8641 | 0.9747 | 1.7738 | 1.8884 |
| 11_05_2015_SP20-2_DST_80SOC | FLAGGED | 276/276 | 0.5159 | 0.5845 | 0.9601 | 1.0221 |
| 11_06_2015_SP20-2_FUDS_80SOC | FULL_DYNAMIC | 11098/11098 | 0.6149 | 0.7432 | 1.3440 | 1.8295 |
| 11_06_2015_SP20-2_FUDS_80SOC | NON_FLAGGED | 10828/10828 | 0.6115 | 0.7362 | 1.3372 | 1.8251 |
| 11_06_2015_SP20-2_FUDS_80SOC | FLAGGED | 270/270 | 0.7522 | 0.9830 | 1.7394 | 1.8295 |
| 11_09_2015_SP20-2_FUDS_50SOC | FULL_DYNAMIC | 6999/6999 | 0.5986 | 0.7485 | 1.5816 | 1.8701 |
| 11_09_2015_SP20-2_FUDS_50SOC | NON_FLAGGED | 6675/6675 | 0.5879 | 0.7319 | 1.5432 | 1.8681 |
| 11_09_2015_SP20-2_FUDS_50SOC | FLAGGED | 324/324 | 0.8202 | 1.0323 | 1.7758 | 1.8701 |

metrics.json lưu số liệu EKF/CC theo kịch bản, độ phủ, innovation, hội tụ, cờ điện áp và lần chạm biên.
candidate_selection.json lưu đủ ứng viên và tiêu chí chọn trên FUDS. Các tệp trajectory giữ từng dòng nguồn.
