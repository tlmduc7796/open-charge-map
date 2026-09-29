# Smart EV Journey — Phase 01 — Runtime Synthetic Data & UrbanEV Source Preparation

**Phase:** 01 / 11  
**Depends on:** Phase 00  
**Primary outcome:** Hoàn thành toàn bộ phần data còn lại trong MVP contract trước khi code application.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Hoàn thành các dataset synthetic/runtime và chuẩn bị UrbanEV làm nguồn ML. Sau phase này, **data layer của MVP phải đầy đủ theo data contract**.

## 2. In Scope

- UrbanEV raw acquisition
- `station_status.json`
- `planned_arrivals.json`
- `queue_assumptions.json`
- `demo_events.json`
- `demo_scenarios.json`
- `routes/*.json`
- `station_history.csv` chỉ nếu cần replay/evaluation
- Data validation và cross-file referential integrity

## 3. Tasks

### 3.1 UrbanEV raw source

- Tải và lưu dataset UrbanEV cần thiết.
- Giữ raw data bất biến.
- Ghi:
  - source URL/version;
  - ngày tải;
  - checksum nếu có.
- Chưa train model ở phase này.

Suggested structure:

```text
data/ml/urbanev/
├── raw/
└── source_manifest.md
```

### 3.2 `station_status.json`

Sinh current snapshot cho mọi station demo:

- `total_ports`
- `operational_ports`
- `occupied_ports`
- `available_ports`
- `offline_ports`
- `occupancy_ratio`
- `queue_length`
- `avg_session_duration_min`

Bảo đảm invariants:

```text
occupied_ports + available_ports = operational_ports
operational_ports + offline_ports = total_ports
occupancy_ratio = occupied_ports / operational_ports khi operational_ports > 0
occupancy_ratio = null khi operational_ports = 0
```

### 3.3 `planned_arrivals.json`

Tạo các arrival records đủ để test:

- không có planned arrival;
- một planned arrival;
- nhiều xe cùng hướng về một station;
- arrival hết hạn/cancelled.

### 3.3a `queue_assumptions.json`

- Ghi arrival rate nền synthetic (xe/giờ) cho mỗi trạm demo.
- Chỉ thêm override cho cặp scenario–station cần thay đổi rate nền.
- Chốt cửa sổ thời gian quy đổi planned arrivals sang xe/giờ.
- Hiệu chỉnh rate theo capacity và scenario; occupancy replay chỉ dùng để kiểm tra mức tải, không suy ra arrival rate trực tiếp từ chênh lệch occupancy.

### 3.4 `demo_events.json`

Chuẩn bị ít nhất:

- `congestion`
- `port_outage`
- `queue_spike`
- `station_recovery`

Effects không được làm state âm hoặc vượt capacity.

### 3.5 `demo_scenarios.json`

Chuẩn bị các scenario cố định cho integration/demo, gồm:

- normal journey;
- low-SOC journey;
- congestion reroute;
- port outage/reroute.

### 3.6 `routes/*.json`

Lấy route thật từ routing provider cho các scenario chính và cache response theo data contract.

### 3.7 Optional `station_history.csv`

Chỉ tạo nếu cần:

- replay trạng thái;
- vẽ chart;
- test wait estimator bằng synthetic ground truth.

**Không dùng file này để train occupancy model.**

### 3.8 Cross-file validation

Kiểm tra:

- mọi `station_id` runtime tồn tại trong `stations.geojson`;
- mọi `vehicle_id` scenario tồn tại trong `vehicles.json`;
- mọi `event_id` scenario tồn tại;
- mọi `route_id` referenced tồn tại;
- planned arrival không tham chiếu station/vehicle không tồn tại.

## 4. Deliverables

```text
data/
├── ml/urbanev/raw/
├── runtime/
│   ├── station_status.json
│   └── planned_arrivals.json
├── demo/
│   ├── demo_events.json
│   ├── demo_scenarios.json
│   ├── queue_assumptions.json
│   └── station_history.csv        # optional
├── routes/
└── validation/
    └── full_data_validation_report.md
```

## 5. Exit Gate

- [x] Tất cả dataset bắt buộc trong MVP Data Contract đã tồn tại.
- [x] UrbanEV raw được lưu riêng, ZIP integrity `PASS` và có SHA-256 trong source manifest.
- [x] Runtime state thỏa capacity invariants.
- [x] Referential integrity giữa station/vehicle/event/route đạt 100%.
- [x] Mỗi station có đúng một arrival rate nền không âm; mọi scenario override tham chiếu ID hợp lệ và không trùng cặp.
- [x] Có 4 demo scenarios cố định.
- [x] Ba route quan trọng đã cache từ OSRM public.
- [x] `station_history.csv` chưa tạo vì là optional; quyết định replay từ UrbanEV processed được chuyển sang Phase 03 và không dùng để train.
- [x] Full data validation report không còn lỗi mức `ERROR`.

**Exit Gate result:** `PASS` — 2026-09-25. Validator: `0 ERROR`, `1 WARNING` (chỉ cảnh báo file optional `station_history.csv` chưa tạo).

## 6.1 Kết quả thực tế

- UrbanEV official archive: `647,305,188` bytes, `3,138` members, SHA-256 `9d3f0aec34434546d082509efcdeeaea116eaa841701cc5854a9b62a27881a79`.
- Archive chứa `1,429` CSV station-processed và `1,682` CSV station-level raw 5-minute; Phase 03 không cần resample dữ liệu zone-level 1 giờ.
- Route cache OSRM: direct `14,037 m`, via Lavida `15,655 m`, via Deutsches Haus `15,128 m`.
- Runtime/demo: 16 station states, 4 planned-arrival records, 4 event types, 4 fixed scenarios,
  arrival-rate assumptions cho đủ 16 station và route cache cho toàn bộ 15 station public.
