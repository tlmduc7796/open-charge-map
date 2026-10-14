# ml — dự báo occupancy 5 phút bằng 6 mô hình XGBoost

Pipeline gọn, tự chứa: đọc `station_occupancy_5m` (do `simulator/` sinh), dựng bộ dữ liệu
(X, y1…y6) rồi huấn luyện/đánh giá **6 XGBoost độc lập** dự đoán `occupancy_ratio` tại
**+5, +10, +15, +20, +25, +30 phút**.

> **Dữ liệu là synthetic** (`is_synthetic = true`, từ simulator). Kết quả chỉ dùng để so sánh
> đặc trưng/mô hình, **không** phải bằng chứng chất lượng khi vận hành. Không có artifact nào ở
> đây được đánh dấu `serving_ready`.

## Chạy

Python 3.12, chạy mọi lệnh từ **gốc repo**:

```powershell
python -m pip install -r ml/requirements.txt     # numpy, pandas, pyarrow, xgboost
python -m ml.build_dataset                        # đọc simulator/data/station_occupancy_5m.csv
python -m ml.train_eval                           # huấn luyện + đánh giá 6 mô hình
pytest ml/tests                                   # test, không cần dữ liệu thật
ruff check ml
```

Chạy thử nhanh: `python -m ml.train_eval --max-train-rows 50000 --n-estimators 50`.

## Cấu trúc

| File | Vai trò |
|---|---|
| `features.py` | hợp đồng cột + hàm đặc trưng thuần (cửa sổ, động lực, thời gian) |
| `geo_features.py` | bảng đặc trưng địa lý tĩnh theo trạm (POI 300m, dân số, trạm lân cận) |
| `build_dataset.py` | CSV → `dataset.parquet` + `dataset.meta.json` |
| `train_eval.py` | huấn luyện 6 model, so với persistence, ghi metric |
| `tests/` | pytest cho đặc trưng, dựng dataset, train smoke |

Đầu ra mặc định (cả `ml/data/` đã được gitignore):

| File | Nội dung |
|---|---|
| `ml/data/dataset.parquet` | mỗi dòng = (trạm, `t_last`): meta + X + y1…y6 |
| `ml/data/dataset.meta.json` | thứ tự cột, quy tắc split, sha256 nguồn, số dòng theo split/trạm |
| `ml/model/model_h5.json` … `model_h30.json` | 6 mô hình XGBoost (`save_model`) |
| `ml/data/occupancy_xgb/metrics.json` | MAE/RMSE của model và persistence theo horizon × split × nhóm trạm |
| `ml/data/occupancy_xgb/feature_importance.csv` | gain của từng đặc trưng theo horizon |

Ba thư mục độc lập, đổi bằng tham số: dữ liệu (`build_dataset --out-dir`,
`train_eval --data-dir`), model (`train_eval --model-dir`) và kết quả (`train_eval --out-dir`).
`ml/model/` và `ml/data/` đều nằm trong `.gitignore`, nên model và dữ liệu không bị commit.

## Định nghĩa dữ liệu

- **Nguồn:** cột `station_id, bucket_at, total_ports, operational_ports, occupied_ports`
  (lưới 5 phút). `occupancy_ratio = occupied_ports / operational_ports`.
- **Tháng 10 bị loại** (`--exclude-months 2026-10`, tính theo giờ `Asia/Ho_Chi_Minh`: 1/10
  00:00+07 = 30/9 17:00Z). Cả `t_last` lẫn `t_last + 30'` đều không rơi vào tháng bị loại.
- **`t_last`** là bucket của quan sát mới nhất đã biết (= `lag_1`); `y_k` là ratio tại
  `t_last + 5k` phút.
- **Cửa sổ hợp lệ:** 18 bucket liên tục đúng 5 phút (12 lag + 6 nhãn), không NaN. Mặc định bỏ
  24 giờ đầu của mỗi trạm vì simulator bắt đầu từ trạng thái rỗng (`--warmup-hours`).
- **Split theo ngày địa phương của `t_last`:** train < 2026-07-01, val 07-01…08-31,
  test 09-01…09-30 (`--val-start`, `--test-start`). Dòng có `t_last` và `t_last + 30'` thuộc hai
  split khác nhau bị loại để không rò nhãn qua ranh giới.

## Đặc trưng X (40 cột mỗi mô hình)

| Nhóm | Cột | Định nghĩa |
|---|---|---|
| Lịch sử (12) | `lag_1` … `lag_12` | ratio tại `t_last − 5(j−1)` phút; `lag_1` mới nhất |
| Xu hướng (5) | `diff_1` | `lag_1 − lag_2` |
| | `roll_mean_3`, `roll_mean_12` | trung bình 3 / 12 lag gần nhất |
| | `n_changes_12` | số cặp liền kề đổi giá trị, trong 11 cặp của 12 lag |
| | `steps_since_change` | số cặp liền kề không đổi liên tiếp từ mới nhất (0…11) |
| Sức chứa (1) | `total_ports` | số cổng của trạm tại bucket `t_last` |
| Địa lý tĩnh (13) | `poi_weighted_*_r300` (8) | tổng trọng số POI (chung + 7 `category_group`) trong 300m — xem `ml/geo_features.py` |
| | `ward_population` | dân số phường chứa trạm |
| | `n_stations_within_300m`, `competing_ports_within_300m` | số trạm khác + tổng cổng của chúng trong 300m |
| | `nearest_other_station_m`, `nearest_station_total_ports` | khoảng cách + số cổng của trạm gần nhất |
| Spatial lag (1) | `nearest_station_occupancy_lag1` | occupancy của trạm gần nhất tại cùng `t_last` |
| Thời gian `t_last` (4) | `last_tod_sin/cos`, `last_dow_sin/cos` | giờ trong ngày và thứ của `t_last` |
| Thời gian mốc dự đoán (4) | `pred_hk_tod_sin/cos`, `pred_hk_dow_sin/cos` | như trên, tại `t_last + 5k` phút |

- **Mô hình k** (k = 1…6, +5k phút) dùng 36 cột chung + 4 cột `pred_hk_*` của chính nó. Dataset
  lưu cả 6 bộ `pred_h1…pred_h6`.
- **Đặc trưng địa lý** đọc từ `data_platform/station_planning/demo_hcmc_v3/` (POI, dân số,
  danh sách trạm) — độc lập với `station_occupancy_5m`; `build_dataset.py --geo-table` cho
  phép nạp một bảng khác (vd. cho dữ liệu tổng hợp/kiểm thử).
- **Mã hoá chu kỳ:** `sin/cos(2π · phút_trong_ngày / 1440)` và `sin/cos(2π · thứ / 7)`, thứ
  Hai = 0. Giờ/thứ tính theo `Asia/Ho_Chi_Minh`; mốc đích đi qua nửa đêm thì thứ đổi theo.
- **Nhãn:** `y1…y6`. Cột meta (không vào X): `station_id`, `t_last`, `split`.

## Huấn luyện và đánh giá

- `XGBRegressor(objective="reg:squarederror", tree_method="hist")`, `max_depth=6`,
  `learning_rate=0.05`, `subsample=0.8`, `colsample_bytree=0.8`, tối đa 1000 cây, early stopping
  50 vòng trên tập **val**; dự đoán được `clip` về [0, 1]. Tham số chỉnh qua CLI.
- **Baseline persistence:** dự đoán `y_k = lag_1`.
- **Metric:** MAE và RMSE trên val và test, cho `all`, `small` (`total_ports ≤ 4`, mặc định) và
  `large`, kèm % giảm lỗi so với persistence (dương = model tốt hơn).
- Test chỉ được đọc để báo cáo sau khi huấn luyện; không tune trên test.

## Lưu ý khi đọc kết quả

- **Synthetic:** simulator dùng giả định (hệ số giờ/thứ, kiên nhẫn, công suất cố định), nên mô
  hình có thể chỉ học lại cấu trúc của bộ sinh dữ liệu.
- **Persistence rất mạnh** ở horizon ngắn trên chuỗi 5 phút; XGBoost trước đây (dữ liệu gold)
  từng thua persistence về MAE dù RMSE tốt hơn. Hãy đọc cả MAE lẫn RMSE.
- **`total_ports` chỉ có vài giá trị** (4/19/20/29/30/67; sáu trạm cùng 4 cổng) nên mô hình có
  thể dùng nó như định danh nhóm trạm, không có nghĩa là đã khái quát hoá sang trạm mới.
- **Trạm 1–4 cổng** có ratio rời rạc (0, 0.25, …, 1), trong khi trạm lớn gần liên tục; hai nhóm
  được báo cáo riêng.
