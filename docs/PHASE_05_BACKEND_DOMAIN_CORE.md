# Smart EV Journey — Phase 05 — Backend Domain Core

**Phase:** 05 / 11  
**Depends on:** Phase 04 trên luồng release; Phase 02 + dữ liệu Phase 00–01 trên nhánh demo backend-first
**Primary outcome:** Backend đọc đúng dữ liệu và thực hiện compatibility, reachability, charging estimate độc lập với UI.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.

> Nhánh `demo/backend-first` triển khai phase này theo ngoại lệ đã ghi trong
> `PHASE_INDEX.md`. Phase 03–04 vẫn deferred; Phase 05 không đọc model artifact.


## 1. Goal

Implement domain logic nền tảng trước khi ghép routing, prediction và recommendation.

## 2. Modules

- Station repository/service
- Vehicle repository/service
- Compatibility service
- Reachability service
- Charging estimate service
- Runtime station status repository
- Shared schemas/models

## 3. Tasks

### 3.1 Data access

- Load `stations.geojson`.
- Load `vehicles.json`.
- Load `station_status.json`.
- Validate schema khi startup.

### 3.2 Compatibility

Output tối thiểu:

- `compatible`
- `matched_connectors`
- `vehicle_max_power_kw`
- `station_max_power_kw`
- `effective_power_kw`
- `reason_codes`

### 3.3 Reachability

Tính:

- trip energy;
- arrival SOC;
- reserve SOC constraint;
- `reachable`.

Route distance có thể nhận như dependency/input; chưa cần API integration trong module này.

### 3.4 Charging estimate

Tính:

- energy cần nạp;
- target SOC;
- effective power;
- estimated charge duration.

Cost vẫn out of scope.

### 3.5 Tests

Unit tests cho:

- connector mismatch;
- effective power;
- insufficient SOC;
- reserve SOC;
- charging time edge cases.

## 4. Exit Gate

- [x] Backend load toàn bộ static/runtime dataset mà không schema error.
- [x] Compatibility unit tests pass.
- [x] Reachability unit tests pass.
- [x] Charging estimate unit tests pass.
- [x] Không có cost calculation trong MVP domain logic.
- [x] Domain services không phụ thuộc frontend.
- [x] Các công thức và unit được ghi rõ trong code/docs.

**Exit Gate result:** `PASS` — 2026-09-25 trên nhánh `demo/backend-first`.

Chi tiết kiểm chứng: `data/validation/phase5_domain_core_report.md`.

## 6. Implementation notes

- FastAPI fail sớm khi load nếu JSON sai schema, ID runtime thiếu/thừa hoặc
  `total_ports` không khớp static/runtime.
- Compatibility đối chiếu connector trong đúng nhóm AC/DC. Nếu nhiều connector khớp,
  kết quả công suất chọn đường sạc có `min(station_power, vehicle_limit)` lớn nhất.
- Reachability dùng mét cho route distance, Wh/km cho consumption, kWh cho battery và
  SOC dạng ratio `[0, 1]`. Arrival SOC không clamp để vẫn thể hiện phần năng lượng thiếu.
- Charging estimate dùng approximation công suất cố định của MVP. Khi SOC đã đạt target,
  energy và duration bằng 0; nếu còn phải sạc mà effective power bằng 0 thì input bị từ chối.
- Access policy như trạm private Audi không được trộn vào physical connector compatibility;
  việc lọc candidate theo access thuộc Phase 07.
