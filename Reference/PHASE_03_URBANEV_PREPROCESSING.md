# Smart EV Journey — Phase 03 — UrbanEV Preprocessing & Temporal Split

**Phase:** 03 / 11  
**Depends on:** Phase 02  
**Primary outcome:** Tạo `urbanev_processed.csv`/equivalent reproducibly và chia train/validation/test theo thời gian.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Biến UrbanEV raw thành representation tối giản phù hợp Occupancy Forecast Model mà không đưa các feature out-of-scope vào MVP.

## 2. In Scope

Canonical fields:

- `timestamp`
- `entity_id`
- `entity_level`
- `interval_min`
- `total_ports` khi xác định được
- `occupied_ports`
- `occupancy_ratio`
- `split`
- `data_source`

Target đã chốt cho MVP là `occupancy_ratio`, resolution 5 phút. Entity không có capacity tin cậy không được đưa vào tập train chính.

Không đưa vào model MVP:

- price;
- service fee;
- weather;
- POI;
- volume/energy;
- queue/wait synthetic data.

## 3. Tasks

- Xác định source files UrbanEV dùng.
- Chọn `station` level nếu source station-level đủ sạch; nếu không, ghi rõ lý do dùng zone-level.
- Chuẩn hóa timestamp và interval.
- Join static capacity nếu cần.
- Tính `occupancy_ratio` khi có `total_ports`.
- Detect:
  - missing timestamp;
  - duplicate observation;
  - negative occupancy;
  - occupancy vượt capacity.
- Không random shuffle time series trước split.
- Chia theo time range:
  - train;
  - validation;
  - test.
- Lưu scaler/normalization parameters chỉ fit trên train.
- Viết preprocessing script chạy lại được từ raw.

## 4. Deliverables

```text
ml/
├── src/preprocess_urbanev.py
└── artifacts/
    ├── urbanev_processed.csv
    ├── split_manifest.json
    └── preprocessing_meta.json
```

## 5. Validation

Báo cáo tối thiểu:

- số entity;
- time range;
- temporal resolution;
- missing rate;
- train/validation/test ranges;
- target distribution;
- invalid row count.

## 6. Exit Gate

- [ ] Preprocessing chạy lại từ raw bằng một command.
- [ ] Không có temporal leakage giữa train/validation/test.
- [ ] `occupied_ports >= 0` cho mọi row.
- [ ] Nếu có capacity: `occupied_ports <= total_ports`.
- [ ] Scaler chỉ fit trên train.
- [ ] Processed dataset không chứa queue/wait synthetic fields.
- [ ] Processed dataset không chứa các feature đã xác định out of scope.
- [ ] Validation report được lưu cùng artifact.

**Exit Gate result:** `PASS / FAIL`
