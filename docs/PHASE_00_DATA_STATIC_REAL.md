# Smart EV Journey — Phase 00 — Static & Real-Source Data Completion

**Phase:** 00 / 11  
**Depends on:** Data Contract MVP  
**Primary outcome:** Hoàn thành master data thực/synthetic-enriched cho trạm sạc và xe, đúng schema và provenance.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Hoàn thành các dataset tĩnh theo `SMART_EV_JOURNEY_DATA_CONTRACT_MVP.md`, ưu tiên dữ liệu thực từ bản đồ/API cho thông tin có thể lấy được và synthetic-enrich có kiểm soát cho phần còn thiếu.

## 2. In Scope

- `stations.geojson`
- `vehicles.json`
- Quy ước ID canonical
- Chuẩn tọa độ WGS84 / EPSG:4326
- Provenance cho từng field synthetic
- Validation schema và invariants cơ bản

## 3. Tasks

### 3.1 `stations.geojson`

- Chọn vùng demo đủ nhỏ để route/map dễ quan sát nhưng có nhiều candidate station.
- Chạy station collector để tạo `data_platform/data/collection/station_candidates.json`; review candidate trước khi đưa vào master data.
- Thu thập tọa độ, tên, địa chỉ và provider ID từ nguồn bản đồ/API khi có.
- Chuẩn hóa:
  - `station_id`
  - `provider_station_id`
  - `name`
  - `address`
  - `geometry.coordinates`
  - `source_provider`
  - `source_updated_at`
- Ghi `access` và `notes`; trạm không public vẫn có thể hiển thị trên bản đồ nhưng phải đủ metadata để backend loại khỏi candidate mặc định.
- Synthetic-enrich chỉ các field API không cung cấp:
  - `operator`
  - `total_ports`
  - `connectors`
  - `amenities` nếu cần
- Điền chính xác `synthetic_fields`.
- Kiểm tra tổng `connectors[].count == total_ports`.

### 3.2 `data_platform/data/demo/vehicles.json`

Chuẩn bị một tập xe demo nhỏ nhưng đủ khác biệt về:

- battery capacity;
- AC/DC connector;
- max charging power;
- consumption;
- reserve SOC;
- target SOC.

Mỗi record phải có đầy đủ field bắt buộc trong data contract. Các giá trị project assumption trong profile xe thật phải được liệt kê trong `synthetic_fields`; `is_synthetic=true` chỉ dùng cho toàn bộ profile mô phỏng.

### 3.3 Validation

Viết validator để kiểm tra:

- ID không trùng;
- tọa độ hợp lệ;
- `total_ports > 0`;
- connector count hợp lệ;
- SOC trong `[0,1]`;
- power/capacity/consumption > 0;
- mọi synthetic field được khai báo trong provenance.

## 4. Deliverables

```text
data_platform/data/
├── collection/
│   └── station_candidates.json
├── static/
│   ├── stations.geojson
│   └── SOURCES.md
├── demo/
│   └── vehicles.json
└── validation/
    └── static_data_validation_report.md
```

## 5. Done Criteria

- Có đủ station thực trong vùng demo để tạo nhiều lựa chọn route.
- Tất cả station có canonical `station_id`.
- Không có station ngoài vùng demo do lỗi geocoding.
- Vehicle records đủ để test ít nhất:
  - compatible station;
  - incompatible connector;
  - low-SOC reachability case.
- Validator chạy không có schema error nghiêm trọng.

## 6. Exit Gate

**PASS chỉ khi tất cả điều kiện sau đạt:**

- [x] `stations.geojson` là `FeatureCollection` và parse được bằng GeoJSON parser.
- [x] 100% station có `station_id`, `name`, `address`, coordinate và `total_ports`.
- [x] `sum(connectors.count) == total_ports` cho mọi station.
- [x] Mọi field synthetic được liệt kê trong `synthetic_fields`.
- [x] `vehicles.json` có ít nhất 3 cấu hình xe đủ khác nhau để test compatibility/reachability.
- [x] Không có ID trùng.
- [x] Static data validation report không còn lỗi mức `ERROR`.

**Exit Gate result:** `PASS` — baseline v0.1, 2026-09-25. Trạm bổ sung phải chạy lại static validator và các generator runtime phụ thuộc.
