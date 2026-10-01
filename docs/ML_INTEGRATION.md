# Smart EV Journey — Hướng dẫn bàn giao model ML cho backend

Tài liệu này dành cho người phụ trách **ML (Phase 03–04)**. Backend đã có sẵn "ổ cắm" cho
model occupancy; bạn chỉ cần xuất đúng 3 file và chạy một lệnh kiểm tra. **Không cần sửa code
backend.**

Ranh giới trách nhiệm:

| Phần | Người phụ trách | Nằm ở |
|---|---|---|
| Tiền xử lý UrbanEV, train, đánh giá, xuất artifact | ML | `ml/` |
| Nạp artifact, forecast, wait, recommendation, API, UI | Backend/Frontend | `backend/`, `frontend/` |
| Hợp đồng giữa hai bên | Chung | tài liệu này + `backend/app/domain/occupancy_model.py` |

## 1. Làm nhanh (3 lệnh)

```powershell
# 1) Xem artifact mẫu đúng định dạng (không phải model thật, ghi ra thư mục tạm)
python scripts\make_example_model_artifacts.py --out build\example_artifacts
python scripts\make_example_model_artifacts.py --out build\example_artifacts_time --time-features

# 2) Sau khi xuất artifact của bạn vào ml/artifacts/, kiểm tra bằng đúng loader của backend
python scripts\validate_model_artifacts.py            # đọc đường dẫn từ .env / mặc định
python scripts\validate_model_artifacts.py --dir ml\artifacts

# 3) Chạy backend rồi xem kết quả
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000/model/status   -> prediction_source: "model"
# http://127.0.0.1:8000/health/checks  -> occupancy_model: ok
```

`validate_model_artifacts.py` in `PASS` nghĩa là backend sẽ nạp được model. Nếu `FAIL`, dòng lỗi
nói rõ lý do (thiếu file, meta sai, thiếu thư viện khi unpickle, …).

## 2. Ba file cần bàn giao

Đặt trong `ml/artifacts/` (đường dẫn đổi được bằng `MODEL_ARTIFACT_PATH`,
`MODEL_PREPROCESSOR_PATH`, `MODEL_META_PATH` trong `.env`):

| File | Nội dung |
|---|---|
| `occupancy_model.joblib` | `dict` `{5: estimator, 10: estimator, 15: estimator}` — **ba model trực tiếp**, key là số phút. Mỗi estimator có `predict(rows)`: nhận list 2 chiều, trả về `occupancy_ratio` tương lai cho từng dòng. |
| `occupancy_preprocessor.joblib` | Object có `transform(rows)` (fit **chỉ trên train**), hoặc `None` nếu không scale. Được gọi trước `predict`. |
| `occupancy_model_meta.json` | Metadata, xem mục 4. |

Lưu ý: `.gitignore` đang bỏ qua `ml/artifacts/*.joblib`, nên file `.joblib` **không nằm trong git**.
Hãy chia sẻ chúng qua kênh khác (Drive/release) kèm số phiên bản, còn `occupancy_model_meta.json`
thì commit được.

## 3. Feature: backend tạo input như thế nào

Mỗi dòng input được ghép **theo tên, đúng thứ tự `features` bạn khai báo trong meta**.

| Tên feature | Ý nghĩa |
|---|---|
| `lag_12` … `lag_1` | `occupancy_ratio` của 12 bước × 5 phút gần nhất. `lag_12` cũ nhất, `lag_1` mới nhất. **Bắt buộc có đủ 12.** |
| `hour_sin`, `hour_cos` | `sin/cos(2π·h/24)`, với `h = giờ + phút/60` của **quan sát mới nhất**, theo giờ UTC+7. |
| `dow_sin`, `dow_cos` | `sin/cos(2π·d/7)`, với `d = weekday` (thứ Hai = 0), cùng múi giờ. |

- Thứ tự cột tùy bạn, miễn khớp với lúc train (ví dụ time feature đứng trước lag cũng được).
- Feature time là **tùy chọn**; không khai báo thì backend không cần timestamp.
- Mọi tên khác (đặc biệt `station_id`, `queue_length`, `wait_*`, price, weather, POI, volume) bị
  **từ chối** khi nạp. Đây là scope guard của MVP.
- Cần feature mới (ví dụ `is_weekend`)? Thêm vào `TIME_FEATURES` và `build_feature_row` trong
  `backend/app/domain/occupancy_model.py` cùng một test, rồi cập nhật bảng trên. Hãy báo người
  phụ trách backend thay vì tự đổi.

Để train/serve khớp tuyệt đối, có thể dùng chính hàm của backend khi tạo feature:

```python
from backend.app.domain.occupancy_model import build_feature_row
row = build_feature_row(features, history_12_oldest_first, observed_at_tz_aware)
```

Hoặc tự cài theo công thức ở bảng trên. Timestamp UrbanEV (giờ Thâm Quyến, UTC+8) khi train nên
dùng **giờ địa phương như ghi trong dữ liệu**, tương ứng giờ địa phương của trạm khi serving.
Đây là giả định transfer Shenzhen → TP.HCM và phải được nêu khi thuyết trình.

## 4. `occupancy_model_meta.json`

```json
{
  "model_name": "smart_ev_occupancy_xgb",
  "model_version": "1.0.0",
  "task": "occupancy_forecasting",
  "training_dataset": "UrbanEV",
  "training_level": "station",
  "temporal_resolution_min": 5,
  "lookback_steps": 12,
  "forecast_steps": 3,
  "features": ["lag_12", "lag_11", "...", "lag_1", "hour_sin", "hour_cos"],
  "target": "occupancy_ratio",
  "metrics": {"mae": 0.0, "rmse": 0.0, "persistence_mae": 0.0, "test_split": "2023-..."},
  "notes": ["Station identifiers are not transferable features.",
            "Queue and waiting-time labels are not provided by UrbanEV."]
}
```

Các giá trị cố định (khác đi là bị từ chối): `task`, `target = occupancy_ratio`,
`temporal_resolution_min = 5`, `lookback_steps = 12`, `forecast_steps = 3` (tương ứng +5/+10/+15).
`training_level` là `station` hoặc `zone`. `metrics` là object tự do — nên ghi cả MAE/RMSE của
persistence trên cùng test split để chứng minh quyết định chọn model (Phase 04: XGBoost chỉ được
chọn nếu MAE tốt hơn persistence ≥ 5%).

> Đồng bộ tài liệu: mẫu `occupancy_model_meta.json` trong
> `SMART_EV_JOURNEY_DATA_CONTRACT_MVP.md` §12 (target `occupied_ports`, `features` kiểu
> `occupied_ports/total_ports`) **chưa khớp** với hợp đồng này (Phase 03/04/06 đều chốt
> `occupancy_ratio`). Khi hai bên chốt xong, cần sửa §12 cho thống nhất.

## 5. Backend sẽ làm gì với model của bạn

- **Nạp lúc khởi động.** Thiếu file → bình thường (dùng persistence, không lỗi). Có file nhưng sai
  hợp đồng/hỏng → ghi log lỗi, **vẫn chạy bằng persistence**, và `/model/status` trả
  `load_error` nêu lý do. Không bao giờ làm sập demo.
- **Kiểm tra thử khi nạp:** chạy thử cả ba horizon trên vài chuỗi mẫu; kết quả không hữu hạn
  (NaN/inf) → từ chối. Kết quả ngoài `[0, 1]` → cảnh báo trong log (backend vẫn clamp về `[0, 1]`).
- **Horizon:** thời gian đi tới trạm được làm tròn lên 5/10/15 phút; ETA > 15 phút dùng model
  +15 làm proxy và gắn cờ `BEYOND_MODEL_HORIZON`.
- **History hiện tại là giả.** Demo chỉ có *một* snapshot trạng thái trạm, nên backend lặp giá trị
  đó 12 lần (cờ `SYNTHETIC_HISTORY`). Model của bạn sẽ thấy chuỗi lag **phẳng**; đây là hạn chế của
  dữ liệu demo, không phải lỗi model. Khi có replay/history thật, backend truyền vào qua tham số
  `occupancy_history` mà không cần đổi artifact. Hãy nêu điều này khi đánh giá "model có tốt hơn
  persistence trong demo không".
- **Chỉ occupancy.** Wait time do Erlang C (backend) tính từ occupancy dự báo + queue/service
  runtime. Model **không** dự đoán wait và không nhận queue/wait làm input.

## 6. Môi trường & phiên bản

- Model được unpickle trong backend, nên backend cần **cài cùng thư viện** bạn dùng khi lưu
  (ví dụ `xgboost`, `scikit-learn`) với **cùng phiên bản**, cùng Python 3.12. Hãy thêm đúng
  phiên bản vào `backend/requirements.txt` cùng lúc bàn giao. Nếu quên, validator sẽ báo
  `cannot unpickle artifacts: ModuleNotFoundError ...`.
- Không pickle class tự định nghĩa trong notebook/`__main__` (backend sẽ không import được). Đặt
  class trong module có thể import (ví dụ `ml/src/...`) hoặc dùng estimator chuẩn của thư viện.
- Estimator XGBoost/sklearn nhận list 2 chiều qua `predict` bình thường.

## 7. Checklist bàn giao

- [ ] Ba file đúng tên, đúng đường dẫn; `.joblib` chia sẻ ngoài git, meta đã commit.
- [ ] `python scripts\validate_model_artifacts.py` in `PASS`, không có `[warn]` chưa giải thích.
- [ ] `metrics` trong meta có MAE/RMSE của model **và** persistence trên cùng test split.
- [ ] `features` không chứa station ID, queue, wait, price, weather, POI, volume.
- [ ] Thư viện + phiên bản cần để unpickle đã thêm vào `backend/requirements.txt`.
- [ ] `/model/status` trả `prediction_source: "model"` và `release_ready: true` khi chạy backend.
- [ ] Ghi vào `evaluation_report.md`: giả định transfer Shenzhen → TP.HCM và hạn chế history giả.
