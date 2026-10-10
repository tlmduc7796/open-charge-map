# Smart EV Journey — Phase 06 — Backend Occupancy Inference & Wait Estimation

**Phase:** 06 / 11  
**Depends on:** Phase 05  
**Primary outcome:** Backend có thể forecast occupancy bằng model UrbanEV-trained và chuyển thành projected wait bằng runtime queue/service state.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.

> Trên nhánh `demo/backend-first`, model Phase 04 chưa tồn tại. Phase 06 dùng
> persistence fallback có nhãn rõ ràng để hoàn thiện và kiểm thử wait pipeline;
> release gate vẫn bị chặn cho đến khi artifact thật được tích hợp.


## 1. Goal

Tích hợp Occupancy Forecast Model vào backend và implement wait estimator tách biệt với ML model.

## 2. Tasks

### 2.1 Occupancy model service

- Load model/preprocessor/meta.
- Validate feature contract.
- Tạo inference interface:

```text
forecast_occupancy(station/context, horizon)
```

- Khi model unavailable, dùng persistence từ observation mới nhất và trả `forecast_source=persistence_fallback`.
- ETA vượt 15 phút dùng forecast +15 làm proxy và trả cờ `BEYOND_MODEL_HORIZON`.

### 2.2 Demo station → model input strategy

Vì UrbanEV station IDs không transfer trực tiếp sang station Việt Nam:

- không dùng raw station ID như learned categorical feature;
- chuẩn hóa occupancy history/state theo contract;
- ghi rõ transfer assumption.
- target và replay window dùng `occupancy_ratio` để chuẩn hóa khác biệt capacity.

Nếu demo không có historical window thật, chuẩn bị synthetic/replay occupancy window chỉ để feed inference theo đúng feature shape.

### 2.3 Wait estimator

Input tối thiểu:

- predicted occupied ports / ratio;
- total/operational ports;
- current `queue_length`;
- `avg_session_duration_min`;
- planned arrivals khi cần.
- arrival rate nền và scenario override từ `queue_assumptions.json`.

Output:

- `estimated_wait_min`;
- intermediate assumptions;
- confidence/limitation flag nếu cần.

Dùng Erlang C với arrival rate theo `queue_assumptions.json`, service rate từ `avg_session_duration_min` và số server bằng `operational_ports`. Tính queue hiện tại riêng, tránh cộng trùng với thành phần chờ kỳ vọng của Erlang C. Khi arrival rate >= tổng service rate, trả cờ `OVERLOADED` và áp dụng giới hạn wait hữu hạn cho scoring. Công thức phải deterministic và test được.

### 2.4 Unit tests

Test ít nhất:

- còn cổng trống → wait gần 0;
- full station + queue > 0 → wait > 0;
- port outage làm wait không giảm vô lý;
- queue tăng → estimated wait không giảm trong cùng điều kiện;
- invalid capacity bị reject.

## 3. Deliverables

- `OccupancyForecastService`
- `WaitEstimator`
- model loading config
- tests
- short technical note về assumptions

## 4. Exit Gate

- [ ] Backend load được occupancy artifact từ Phase 04 — blocked vì Phase 04 deferred.
- [x] Một inference request trả future occupancy hợp lệ bằng persistence fallback.
- [x] Wait estimator không dùng `observed_wait` làm input.
- [x] Queue/wait fields không được đưa ngược vào Occupancy Model.
- [x] Các monotonic sanity tests chính pass.
- [x] Planned arrivals có thể bật/tắt mà không phá estimator.
- [x] Config arrival rate được load/validate và scenario override áp dụng đúng trạm.
- [x] Failure/fallback behavior được xác định rõ.

**Exit Gate result:** `DEMO PASS / RELEASE BLOCKED` — 2026-09-25.

Chi tiết kiểm chứng: `data_platform/data/validation/phase6_forecast_wait_report.md`.

## 6. Implementation notes

### 6.1 Forecast contract

- Interface nhận history `occupancy_ratio` gồm 12 bước và horizon được căn về một trong
  +5/+10/+15/+20/+25/+30 phút.
- Khi không có model, prediction bằng observation mới nhất và trả
  `prediction_source=persistence` cùng flag `PERSISTENCE_FALLBACK`.
- Horizon không được artifact hỗ trợ dùng persistence ở chính mốc contract và trả
  `MODEL_HORIZON_UNSUPPORTED`; mốc trên 15 phút đồng thời trả `BEYOND_MODEL_HORIZON`.
- Nếu model adapter được cắm nhưng chưa có đủ history thật, service không gọi model;
  dùng persistence và trả `HISTORY_UNAVAILABLE`.
- Model output được clamp vào `[0, 1]`; lỗi inference tự hạ cấp sang persistence.
- Station không còn operational port trả ratio `null`, occupied ports bằng 0 và
  flag `STATION_OFFLINE`.

### 6.2 Wait formula and assumptions

```text
c = operational_ports
mu = 60 / avg_session_duration_min
lambda = baseline_arrival_rate + planned_arrival_rate
rho = lambda / (c * mu)

planned_arrival_rate =
    sum(arrival_probability trong cửa sổ) * 60 / window_min
```

Erlang C tính `P(wait)` và expected queue wait `Wq` khi `rho < 1`.
Runtime state được tính riêng:

```text
projected_available = c - predicted_occupied_ports
required_releases = max(0, queue_length + 1 - projected_available)
current_state_wait = required_releases * avg_session_duration_min / c
```

- Nếu còn ít nhất một cổng dự báo trống và queue hiện tại bằng 0, immediate wait bằng 0;
  `Wq` vẫn được trả riêng như steady-state assumption.
- Các trường hợp khác dùng `max(current_state_wait, Wq)`, không cộng hai thành phần để
  tránh double-count queue.
- Khi `lambda >= c * mu`, trả `OVERLOADED` và cap hữu hạn từ
  `WAIT_SCORING_CAP_MIN` để Phase 07 có thể score.
- Station offline cũng trả cap hữu hạn với `STATION_OFFLINE` và `CAPPED_WAIT`.
- Planned arrival chỉ tính record `planned`, chưa expire, đúng station và có `eta_at`
  trong `[evaluation_at, evaluation_at + window)`; có thể loại arrival của chính user.

### 6.3 Transfer limitation

Không dùng station ID Việt Nam làm learned feature. Persistence và model adapter chỉ nhận
occupancy ratio đã chuẩn hóa theo operational capacity. Artifact/preprocessor/metadata thật,
metric và feature-contract validation phải được bổ sung sau khi Phase 03–04 hoàn tất.
