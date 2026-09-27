# Smart EV Journey — Phase 04 — Occupancy Forecast Model Training

**Phase:** 04 / 11  
**Depends on:** Phase 03  
**Primary outcome:** Có model occupancy đã train, benchmark, test và export cùng metadata.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Train mô hình dự đoán **future occupancy**, không train trực tiếp `wait_time`.

## 2. Modeling Scope

Input tối thiểu:

- historical occupancy sequence;
- capacity/occupancy ratio nếu sử dụng;
- deterministic temporal encoding có thể derive từ timestamp nếu cần.

Target chính: `occupancy_ratio`.

## 3. Tasks

### 3.1 Baseline

Implement ít nhất một baseline đơn giản:

- Last Observation / persistence.

Có thể thêm:

- moving average;
- linear/autoregressive baseline.

### 3.2 Model

Model candidate chính là XGBoost với lag/time features. Dùng 12 bước lookback ở resolution 5 phút và ba model trực tiếp cho horizon +5, +10, +15 phút. Không dùng station/entity ID, queue hoặc wait làm feature.

### 3.3 Experiment contract

Chốt:

- lookback window = 12 bước / 60 phút;
- forecast horizon = +5, +10, +15 phút;
- temporal resolution = 5 phút;
- feature list;
- target;
- random seeds.

### 3.4 Evaluation

Đánh giá trên test split bằng ít nhất:

- MAE;
- RMSE.

So với persistence baseline. Chỉ chọn XGBoost làm model phục vụ nếu test MAE tốt hơn persistence ít nhất 5%; nếu không, persistence là model phục vụ và XGBoost được giữ như experiment.

### 3.5 Export

Export:

- model artifact;
- scaler/preprocessor;
- `occupancy_model_meta.json`.

Metadata phải ghi:

- UrbanEV source;
- entity level;
- resolution;
- lookback;
- horizon;
- features;
- target;
- metrics;
- limitations.

## 4. Deliverables

```text
ml/artifacts/
├── occupancy_model.*
├── occupancy_preprocessor.*
├── occupancy_model_meta.json
└── evaluation_report.md
```

## 5. Exit Gate

- [ ] Baseline và candidate model đều chạy trên cùng test split.
- [ ] Không dùng queue/wait synthetic features để train.
- [ ] Test metrics được ghi lại reproducibly.
- [ ] Model artifact load lại được trong process mới.
- [ ] Inference một sample trả prediction đúng shape/horizon.
- [ ] Prediction được clamp/validate để không âm và không vượt capacity khi capacity áp dụng.
- [ ] `occupancy_model_meta.json` khớp artifact thật.
- [ ] Có quyết định rõ model nào được chọn cho MVP và lý do bằng metric/complexity.

**Exit Gate result:** `PASS / FAIL`
