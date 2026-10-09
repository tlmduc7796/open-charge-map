# Smart EV Journey — MVP Data Contract

## 1. Scope

Tài liệu này chuẩn hóa các bộ dữ liệu dùng cho phiên bản MVP/hackathon của **Smart EV Journey**.

Phạm vi hiện tại chỉ giữ các dữ liệu cần cho:

- dữ liệu trạm sạc thực trên bản đồ;
- hồ sơ xe và kiểm tra tương thích;
- huấn luyện/dự đoán **future occupancy** theo schema tương thích UrbanEV;
- trạng thái runtime, queue và wait-time estimation;
- planned arrivals;
- cấu hình arrival rate synthetic cho wait estimator;
- route cache;
- demo events và demo scenarios;
- các dữ liệu dẫn xuất cho compatibility, reachability, charging-time estimate và station recommendation.

### Out of scope ở phiên bản này

Các thành phần sau **không nằm trong data contract MVP**:

- `electricity_price`;
- `service_fee`;
- historical charging `volume` / energy consumption từ UrbanEV;
- weather features;
- POI features;
- cost estimation;
- cost-based recommendation score;
- ML model train trực tiếp để dự đoán `wait_time` từ UrbanEV.

> UrbanEV là **dataset ML bên ngoài** dùng để train/validation/test mô hình occupancy forecasting. Các trạng thái `queue_length`, session duration và planned arrivals của trạm demo là dữ liệu synthetic/runtime riêng; chúng không được ghép vào UrbanEV để train occupancy model.

---

## 2. Quy ước chung

| Thành phần | Quy ước |
|---|---|
| ID | `string` |
| Timestamp | ISO-8601 có timezone, ví dụ `2026-09-24T18:30:00+07:00` |
| Demo timezone | `Asia/Ho_Chi_Minh` |
| Coordinate canonical | WGS84 / EPSG:4326 |
| Distance | meter |
| Route duration | second |
| Charging / waiting duration | minute |
| ML interval | minute, mặc định `5` |
| Power | kW |
| Energy | kWh |
| SOC | số thực trong `[0, 1]` |
| Ratio | số thực trong `[0, 1]` |

### Ranh giới API `/api/v1`

- Domain và file dữ liệu tiếp tục dùng SOC `[0,1]` và tọa độ `{lat,lon}`.
- API công khai nhận/trả pin theo phần trăm `[0,100]` và tọa độ `{lat,lng}`; adapter
  chuyển đổi tại ranh giới HTTP, không truyền đơn vị API vào domain.
- Field JSON của `/api/v1` dùng `camelCase`; timestamp luôn có timezone và response có
  `updatedAt` khi biểu diễn trạng thái có thể thay đổi.
- Forecast contract công khai hỗ trợ offset `0,5,10,15,20,25,30`. Mốc chưa có model
  tương ứng dùng persistence và phải trả nguồn/flag fallback, không nội suy như model thật.

### `data_source`

Các dataset có thể dùng field `data_source` với một trong các giá trị:

- `map_real`: lấy từ API/bản đồ hoặc nguồn thực;
- `urbanev_real`: dữ liệu UrbanEV;
- `synthetic`: dữ liệu mô phỏng;
- `runtime`: dữ liệu trạng thái đang chạy;
- `derived`: dữ liệu tính từ các dataset khác;
- `routing_api`: dữ liệu trả về từ Goong/OSRM.

### Container của file

- `stations.geojson` dùng GeoJSON `FeatureCollection`; mỗi phần tử trong `features` tuân theo schema Feature bên dưới.
- `data_platform/data/demo/vehicles.json`, `station_status.json`, `planned_arrivals.json`, `demo_events.json` và `demo_scenarios.json` dùng JSON array ở top-level. `data_platform/data/static/vehicles.json` là bộ hồ sơ cho database, dùng object `snapshot` + `vehicles` riêng.
- Mỗi file trong `routes/*.json`, `queue_assumptions.json` và `occupancy_model_meta.json` dùng một JSON object ở top-level.

---

# 3. `stations.geojson`

## Mục đích

Master data của các trạm sạc trong vùng demo. Tọa độ, tên, địa chỉ và các thông tin lấy được từ nguồn bản đồ nên dùng dữ liệu thật; các thuộc tính không có từ API có thể synthetic-enrich nhưng phải ghi provenance.

**Giai đoạn sử dụng:** chuẩn bị dữ liệu bản đồ, compatibility, reachability, charging estimate, recommendation và runtime UI.

## Schema

File có `type = "FeatureCollection"` và `features` là array các GeoJSON Feature.

### GeoJSON Feature

| Attribute | Type | Bắt buộc | Nguồn | Mô tả |
|---|---|---:|---|---|
| `type` | string | ✓ | Fixed | Luôn là `Feature` |
| `geometry.type` | string | ✓ | Fixed | Luôn là `Point` |
| `geometry.coordinates` | `[lon, lat]` | ✓ | Real | Tọa độ WGS84 |

### `properties`

| Attribute | Type | Bắt buộc | Nguồn | Mô tả |
|---|---|---:|---|---|
| `station_id` | string | ✓ | Project | ID canonical của trạm |
| `provider_station_id` | string/null |  | Real | ID từ nguồn bản đồ/API nếu có |
| `name` | string | ✓ | Real | Tên trạm |
| `address` | string | ✓ | Real | Địa chỉ hiển thị |
| `operator` | string/null |  | Real/Synthetic | Đơn vị vận hành |
| `zone_id` | string/null |  | Derived | Vùng không gian chứa trạm; không dùng làm feature bắt buộc ở MVP |
| `total_ports` | int | ✓ | Real/Synthetic | Tổng số cổng sạc vật lý |
| `connectors` | array | ✓ | Real/Synthetic | Danh sách connector/công suất |
| `amenities` | array[string] |  | Real/Synthetic | Tiện ích tại trạm |
| `opening_hours` | string/object/null |  | Real | Thời gian hoạt động nếu biết |
| `access` | enum | ✓ | `public`, `customers`, `private` hoặc `unknown` |
| `notes` | array[string] | ✓ | Ghi chú vận hành/giới hạn truy cập; có thể rỗng |
| `source_provider` | string | ✓ | Provenance | Ví dụ `goong`, `manual`, `synthetic_enrichment` |
| `source_updated_at` | datetime/null |  | Provenance | Lần cập nhật nguồn |
| `synthetic_fields` | array[string] | ✓ | Provenance | Field nào được synthetic-enrich |

### `connectors[]`

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `type` | string | ✓ | Ví dụ `CCS2`, `Type2`, `GB/T` |
| `current` | enum | ✓ | `AC` hoặc `DC` |
| `max_power_kw` | float | ✓ | Công suất tối đa của loại connector |
| `count` | int | ✓ | Số cổng thuộc loại này |
| `source` | string | ✓ | `real` hoặc `synthetic` |

## Mẫu

```json
{
  "type": "Feature",
  "geometry": {
    "type": "Point",
    "coordinates": [106.7008, 10.7769]
  },
  "properties": {
    "station_id": "ST001",
    "provider_station_id": "map_abc_001",
    "name": "Demo Charging Station 1",
    "address": "Quận 1, TP.HCM",
    "operator": "Demo Operator",
    "zone_id": "ZONE_01",
    "total_ports": 8,
    "connectors": [
      {
        "type": "CCS2",
        "current": "DC",
        "max_power_kw": 120,
        "count": 6,
        "source": "synthetic"
      },
      {
        "type": "Type2",
        "current": "AC",
        "max_power_kw": 22,
        "count": 2,
        "source": "synthetic"
      }
    ],
    "amenities": ["parking", "cafe"],
    "opening_hours": "24/7",
    "access": "public",
    "notes": [],
    "source_provider": "map_real",
    "source_updated_at": "2026-09-24T10:00:00+07:00",
    "synthetic_fields": ["operator", "total_ports", "connectors"]
  }
}
```

---

# 4. `data_platform/data/demo/vehicles.json`

## Mục đích

Hồ sơ xe EV chuẩn hóa để kiểm tra connector compatibility, reachability và ước lượng thời gian sạc.

**Giai đoạn sử dụng:** compatibility, reachability, charging estimate, demo scenarios.

## Schema

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `vehicle_id` | string | ✓ | ID canonical của mẫu xe |
| `make` | string | ✓ | Hãng xe |
| `model` | string | ✓ | Model |
| `variant` | string/null |  | Phiên bản |
| `battery_capacity_kwh` | float | ✓ | Dung lượng pin danh định |
| `usable_battery_kwh` | float/null |  | Dung lượng khả dụng nếu biết |
| `max_ac_power_kw` | float | ✓ | Công suất AC tối đa xe nhận được |
| `max_dc_power_kw` | float | ✓ | Công suất DC tối đa xe nhận được |
| `ac_connectors` | array[string] | ✓ | Connector AC hỗ trợ |
| `dc_connectors` | array[string] | ✓ | Connector DC hỗ trợ |
| `consumption_wh_km` | float | ✓ | Mức tiêu thụ điện trung bình |
| `reserve_soc` | float | ✓ | SOC tối thiểu cần giữ |
| `default_target_soc` | float | ✓ | SOC mặc định sau sạc |
| `charging_efficiency` | float | ✓ | Hiệu suất sạc, ví dụ `0.90` |
| `source` | string | ✓ | Nguồn dữ liệu |
| `is_synthetic` | bool | ✓ | `true` khi toàn bộ vehicle profile là synthetic |
| `synthetic_fields` | array[string] | ✓ | Các field được giả định/synthetic-enrich trong một profile thật; có thể rỗng |

## Mẫu

```json
{
  "vehicle_id": "EV_VF8_DEMO",
  "make": "VinFast",
  "model": "VF 8",
  "variant": null,
  "battery_capacity_kwh": 87.7,
  "usable_battery_kwh": null,
  "max_ac_power_kw": 11,
  "max_dc_power_kw": 150,
  "ac_connectors": ["Type2"],
  "dc_connectors": ["CCS2"],
  "consumption_wh_km": 205,
  "reserve_soc": 0.10,
  "default_target_soc": 0.80,
  "charging_efficiency": 0.90,
  "source": "manual",
  "is_synthetic": false,
  "synthetic_fields": ["reserve_soc", "default_target_soc", "charging_efficiency"]
}
```

---

# 5. UrbanEV / `urbanev_processed.csv`

## Mục đích

UrbanEV là nguồn dữ liệu lịch sử thực dùng cho **train, validation và test** mô hình dự đoán occupancy. Dataset gốc có thể được giữ nguyên ở thư mục raw; `urbanev_processed.csv` là representation tối giản sau preprocessing để model của project sử dụng.

**Giai đoạn sử dụng:** preprocessing ML, train, validation, test và đánh giá Occupancy Forecast Model.

> UrbanEV không phải chỉ là test set. Việc chia train/validation/test phải thực hiện theo **thời gian** để hạn chế temporal leakage. Queue và wait-time không phải ground truth của UrbanEV.

## Schema tối thiểu của `urbanev_processed.csv`

| Attribute | Type | Bắt buộc | Nguồn | Mô tả |
|---|---|---:|---|---|
| `timestamp` | datetime | ✓ | UrbanEV | Thời điểm của observation |
| `entity_id` | string | ✓ | UrbanEV | ID station hoặc zone sau preprocessing |
| `entity_level` | enum | ✓ | Project | `station` hoặc `zone`; MVP ưu tiên `station` nếu dùng station-level UrbanEV |
| `interval_min` | int | ✓ | UrbanEV/Project | Resolution của dữ liệu; giữ nhất quán khi train |
| `total_ports` | int/null |  | UrbanEV static data | Capacity của entity nếu xác định được; bắt buộc nếu target/model dùng count theo capacity |
| `occupied_ports` | float | ✓ | UrbanEV | Số charging ports/piles đang occupied |
| `occupancy_ratio` | float/null |  | Derived | `occupied_ports / total_ports` khi có capacity |
| `split` | enum | ✓ | Project | `train`, `validation` hoặc `test`, được gán theo time range |
| `data_source` | string | ✓ | Provenance | Luôn `urbanev_real` |

## Invariants

```text
occupied_ports >= 0
0 <= occupancy_ratio <= 1                  (nếu có)
occupied_ports <= total_ports              (nếu total_ports có giá trị)
split ∈ {train, validation, test}
```

## Mẫu CSV

```csv
timestamp,entity_id,entity_level,interval_min,total_ports,occupied_ports,occupancy_ratio,split,data_source
2022-09-01T00:00:00+08:00,UEV_ST_1001,station,5,20,7,0.35,train,urbanev_real
2022-09-01T00:05:00+08:00,UEV_ST_1001,station,5,20,8,0.40,train,urbanev_real
```

## Các field UrbanEV ngoài scope MVP

Các dữ liệu UrbanEV như price, weather, POI, charging volume và các auxiliary factors khác **không được đưa vào feature contract tối thiểu hiện tại**. Có thể giữ trong raw dataset để mở rộng sau nhưng model MVP không phụ thuộc vào chúng.

---

# 6. `station_history.csv` — Optional simulation/replay log

## Mục đích

`station_history.csv` **không còn là training dataset của ML model**. File này là tùy chọn và chỉ cần nếu demo muốn replay trạng thái theo thời gian, vẽ historical chart hoặc đánh giá wait estimator bằng synthetic ground truth.

Nếu demo chỉ cần current runtime state + events thì có thể **không tạo file này**.

**Giai đoạn sử dụng:** optional demo replay, simulation test và evaluation của wait estimator. Không dùng để train Occupancy Forecast Model.

## Schema

| Attribute | Type | Bắt buộc | Nguồn | Mô tả |
|---|---|---:|---|---|
| `timestamp` | datetime | ✓ | Synthetic | Thời điểm của snapshot mô phỏng |
| `station_id` | string | ✓ | Project | ID trạm demo |
| `total_ports` | int | ✓ | Static | Tổng số cổng |
| `operational_ports` | int | ✓ | Synthetic | Số cổng đang hoạt động |
| `occupied_ports` | int | ✓ | Synthetic | Số cổng đang bận |
| `available_ports` | int | ✓ | Derived | `operational_ports - occupied_ports` |
| `occupancy_ratio` | float/null | ✓ | Derived | `occupied_ports / operational_ports`; `null` khi `operational_ports = 0` |
| `queue_length` | int | ✓ | Synthetic | Số xe đang chờ ở snapshot đó |
| `avg_session_duration_min` | float | ✓ | Synthetic/Assumption | Service-time assumption tại trạm |
| `simulated_wait_ground_truth_min` | float/null |  | Synthetic | Chỉ dùng nếu cần đánh giá wait estimator |
| `event_id` | string/null |  | Synthetic | Event đã tác động lên snapshot nếu có |
| `data_source` | string | ✓ | Provenance | Luôn `synthetic` |

## Mẫu CSV

```csv
timestamp,station_id,total_ports,operational_ports,occupied_ports,available_ports,occupancy_ratio,queue_length,avg_session_duration_min,simulated_wait_ground_truth_min,event_id,data_source
2026-09-24T18:00:00+07:00,ST001,8,8,6,2,0.75,0,28.0,0.0,,synthetic
2026-09-24T18:05:00+07:00,ST001,8,8,8,0,1.00,2,28.0,7.5,EVT_001,synthetic
```

> `queue_length` và `simulated_wait_ground_truth_min` trong file này chỉ mô tả **simulation log**. Chúng không được ghép vào `urbanev_processed.csv` và không phải feature để train occupancy model.

---

# 7. `station_status.json`

## Mục đích

Snapshot trạng thái hiện tại của từng trạm trong demo. Đây là runtime input chính cho trạng thái capacity/occupancy/queue; không phải training dataset.

**Giai đoạn sử dụng:** runtime UI, wait estimation, recommendation, dynamic rerouting.

## Schema

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `station_id` | string | ✓ | ID trạm |
| `timestamp` | datetime | ✓ | Thời điểm snapshot |
| `total_ports` | int | ✓ | Tổng số cổng |
| `operational_ports` | int | ✓ | Số cổng hoạt động |
| `occupied_ports` | int | ✓ | Số cổng đang bận |
| `available_ports` | int | ✓ | Số cổng còn trống |
| `offline_ports` | int | ✓ | Số cổng offline |
| `occupancy_ratio` | float/null | ✓ | `occupied_ports / operational_ports`; `null` khi `operational_ports = 0` |
| `queue_length` | int | ✓ | Số xe đang chờ |
| `avg_session_duration_min` | float | ✓ | Thời lượng service/charging trung bình dùng cho wait estimator |
| `data_source` | string | ✓ | Thường là `runtime` hoặc `synthetic` |

## Mẫu

```json
{
  "station_id": "ST001",
  "timestamp": "2026-09-24T18:30:00+07:00",
  "total_ports": 8,
  "operational_ports": 8,
  "occupied_ports": 7,
  "available_ports": 1,
  "offline_ports": 0,
  "occupancy_ratio": 0.875,
  "queue_length": 1,
  "avg_session_duration_min": 28.0,
  "data_source": "synthetic"
}
```

Invariants:

```text
occupied_ports + available_ports = operational_ports
operational_ports + offline_ports = total_ports
0 <= occupied_ports <= operational_ports
occupancy_ratio = occupied_ports / operational_ports  (nếu operational_ports > 0)
occupancy_ratio = null                                 (nếu operational_ports = 0)
```

---

# 8. `demo_events.json`

## Mục đích

Mô tả các sự kiện synthetic làm thay đổi trạng thái trạm trong demo, ví dụ congestion hoặc charger outage.

**Giai đoạn sử dụng:** demo runtime và dynamic rerouting.

## Schema

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `event_id` | string | ✓ | ID event |
| `event_type` | enum | ✓ | `congestion`, `port_outage`, `queue_spike`, `station_recovery` |
| `station_id` | string | ✓ | Trạm bị tác động |
| `start_at` | datetime | ✓ | Thời gian bắt đầu |
| `end_at` | datetime/null |  | Thời gian kết thúc |
| `severity` | enum | ✓ | `low`, `medium`, `high` |
| `effects` | object | ✓ | Các thay đổi cần áp dụng |
| `description` | string |  | Mô tả cho demo/log |
| `is_synthetic` | bool | ✓ | Luôn `true` |

### `effects` cho phép

| Attribute | Type | Mô tả |
|---|---|---|
| `offline_ports_delta` | int | Tăng/giảm số cổng offline |
| `queue_length_delta` | int | Tăng/giảm queue |
| `occupied_ports_delta` | int | Tăng/giảm số cổng bận nếu scenario cần |

## Mẫu

```json
{
  "event_id": "EVT_001",
  "event_type": "port_outage",
  "station_id": "ST003",
  "start_at": "2026-09-24T19:00:00+07:00",
  "end_at": "2026-09-24T19:30:00+07:00",
  "severity": "high",
  "effects": {
    "offline_ports_delta": 3
  },
  "description": "Three charging ports become unavailable.",
  "is_synthetic": true
}
```

---

# 9. `demo_scenarios.json`

## Mục đích

Các kịch bản cố định phục vụ demo và integration test.

**Giai đoạn sử dụng:** demo end-to-end và test.

## Schema

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `scenario_id` | string | ✓ | ID scenario |
| `name` | string | ✓ | Tên scenario |
| `vehicle_id` | string | ✓ | Xe được sử dụng |
| `initial_soc` | float | ✓ | SOC đầu hành trình |
| `target_soc` | float | ✓ | SOC mong muốn sau sạc |
| `origin` | object | ✓ | Điểm bắt đầu |
| `destination` | object | ✓ | Điểm đích |
| `departure_at` | datetime | ✓ | Thời gian khởi hành |
| `preference` | object | ✓ | Trọng số recommendation |
| `event_ids` | array[string] | ✓ | Event cần kích hoạt |
| `route_ids` | array[string] | ✓ | Các route cache dùng để so sánh direct/via station trong scenario |

### `origin` / `destination`

```json
{
  "lat": 10.7769,
  "lon": 106.7008,
  "label": "Start"
}
```

### `preference`

| Attribute | Type | Mô tả |
|---|---|---|
| `wait_weight` | float | Trọng số thời gian chờ |
| `detour_weight` | float | Trọng số detour |
| `charging_time_weight` | float | Trọng số thời gian sạc |
| `soc_risk_weight` | float | Trọng số rủi ro SOC |

Tổng trọng số nên bằng `1.0`.

## Mẫu

```json
{
  "scenario_id": "SCN_001",
  "name": "Congestion reroute demo",
  "vehicle_id": "EV_VF8_DEMO",
  "initial_soc": 0.24,
  "target_soc": 0.80,
  "origin": {
    "lat": 10.7769,
    "lon": 106.7008,
    "label": "Origin"
  },
  "destination": {
    "lat": 10.8231,
    "lon": 106.6297,
    "label": "Destination"
  },
  "departure_at": "2026-09-24T18:45:00+07:00",
  "preference": {
    "wait_weight": 0.40,
    "detour_weight": 0.25,
    "charging_time_weight": 0.25,
    "soc_risk_weight": 0.10
  },
  "event_ids": ["EVT_001"],
  "route_ids": ["ROUTE_BASE_DIRECT", "ROUTE_VIA_ST001"]
}
```

---

# 10. `routes/*.json`

## Mục đích

Cache route lấy từ Goong/OSRM để tránh phụ thuộc hoàn toàn vào API trong demo.

**Giai đoạn sử dụng:** reachability, ETA, detour calculation, fallback khi routing API lỗi.

## Schema

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `route_id` | string | ✓ | ID cache route |
| `provider` | string | ✓ | `goong` hoặc `osrm` |
| `origin` | object | ✓ | Điểm đầu |
| `destination` | object | ✓ | Điểm cuối |
| `waypoints` | array[object] | ✓ | Điểm trung gian, có thể rỗng |
| `geometry` | object/string | ✓ | GeoJSON LineString hoặc encoded polyline |
| `distance_m` | float | ✓ | Tổng quãng đường |
| `duration_s` | float | ✓ | Thời gian route |
| `retrieved_at` | datetime | ✓ | Thời điểm gọi API |
| `request_hash` | string | ✓ | Cache key |
| `data_source` | string | ✓ | `routing_api` |

## Mẫu

```json
{
  "route_id": "ROUTE_001",
  "provider": "goong",
  "origin": {"lat": 10.7769, "lon": 106.7008},
  "destination": {"lat": 10.8231, "lon": 106.6297},
  "waypoints": [],
  "geometry": {
    "type": "LineString",
    "coordinates": []
  },
  "distance_m": 12840,
  "duration_s": 1680,
  "retrieved_at": "2026-09-24T18:00:00+07:00",
  "request_hash": "origin-destination-provider-hash",
  "data_source": "routing_api"
}
```

---

# 11. `planned_arrivals.json`

## Mục đích

Lưu các xe mà hệ thống hiện đang hướng tới một trạm trong tương lai gần. Đây là input runtime bổ sung cho projected station load/wait.

**Giai đoạn sử dụng:** runtime wait estimation và station recommendation.

## Schema

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `arrival_id` | string | ✓ | ID planned arrival |
| `station_id` | string | ✓ | Trạm dự kiến đến |
| `vehicle_id` | string/null |  | Xe nếu cần giữ reference |
| `created_at` | datetime | ✓ | Lúc planned arrival được tạo |
| `eta_at` | datetime | ✓ | ETA trung tâm |
| `eta_window_start` | datetime | ✓ | Bắt đầu ETA window |
| `eta_window_end` | datetime | ✓ | Kết thúc ETA window |
| `expected_energy_kwh` | float | ✓ | Năng lượng dự kiến cần nạp |
| `expected_charge_duration_min` | float | ✓ | Thời gian sạc dự kiến |
| `arrival_probability` | float | ✓ | Xác suất xe thực sự đến, `[0,1]` |
| `expires_at` | datetime | ✓ | Hết hiệu lực |
| `route_id` | string/null |  | Route liên quan |
| `status` | enum | ✓ | `planned`, `arrived`, `cancelled`, `expired` |
| `data_source` | string | ✓ | `runtime` hoặc `synthetic` |

## Mẫu

```json
{
  "arrival_id": "ARR_001",
  "station_id": "ST005",
  "vehicle_id": "EV_VF8_DEMO",
  "created_at": "2026-09-24T18:45:00+07:00",
  "eta_at": "2026-09-24T19:05:00+07:00",
  "eta_window_start": "2026-09-24T19:02:00+07:00",
  "eta_window_end": "2026-09-24T19:08:00+07:00",
  "expected_energy_kwh": 31.4,
  "expected_charge_duration_min": 28.0,
  "arrival_probability": 0.85,
  "expires_at": "2026-09-24T19:15:00+07:00",
  "route_id": "ROUTE_005",
  "status": "planned",
  "data_source": "synthetic"
}
```

---

# 11a. `queue_assumptions.json`

## Mục đích

Cấu hình arrival rate nền cho Erlang C tại các trạm demo. Đây là giả định synthetic được hiệu chỉnh theo scenario, không phải số xe đến quan sát được từ UrbanEV. Occupancy replay chỉ dùng để kiểm tra mức tải của giả định; thay đổi occupancy không xác định chính xác số xe đến.

**Giai đoạn sử dụng:** runtime wait estimation và deterministic demo scenarios.

## Schema

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `planned_arrival_window_min` | int | ✓ | Cửa sổ thời gian dương dùng để quy đổi planned arrivals thành xe/giờ |
| `station_rates` | array[object] | ✓ | Mỗi trạm demo có đúng một record gồm `station_id` và `baseline_arrival_rate_per_hour` không âm |
| `scenario_overrides` | array[object] | ✓ | Mỗi record gồm `scenario_id`, `station_id` và `baseline_arrival_rate_per_hour` không âm; có thể rỗng |
| `data_source` | string | ✓ | Luôn `synthetic` |

Một cặp `(scenario_id, station_id)` chỉ có tối đa một override. Khi chạy scenario, override thay thế rate nền của trạm tương ứng; các trạm khác giữ rate nền. Rate nền không bao gồm planned arrivals. `evaluation_at` là ETA của candidate station đang được đánh giá.

```text
planned_arrival_rate_per_hour =
    sum(arrival_probability của các arrival status=planned, expires_at > evaluation_at,
        có eta_at trong [evaluation_at, evaluation_at + planned_arrival_window_min))
    * 60 / planned_arrival_window_min

arrival_rate_per_hour = baseline_arrival_rate_per_hour + planned_arrival_rate_per_hour
```

Không tính arrival của chính user đang xem recommendation trước khi user chọn route; mỗi `arrival_id` chỉ được tính một lần. `avg_session_duration_min` từ `station_status.json` cung cấp service rate riêng cho Erlang C.

## Mẫu

```json
{
  "planned_arrival_window_min": 15,
  "station_rates": [
    {"station_id": "ST001", "baseline_arrival_rate_per_hour": 1.5}
  ],
  "scenario_overrides": [
    {"scenario_id": "SCN_001", "station_id": "ST001", "baseline_arrival_rate_per_hour": 2.5}
  ],
  "data_source": "synthetic"
}
```

Các con số trong mẫu chỉ minh họa schema; cần hiệu chỉnh khi đã có danh sách trạm, capacity và scenario cụ thể.

---

# 12. `occupancy_model_meta.json`

## Mục đích

Metadata đi kèm `occupancy_model.joblib`. File model binary không phải dataset; metadata này ghi rõ model được train trên dữ liệu nào và cần feature nào.

**Giai đoạn sử dụng:** training, model loading, validation, reproducibility.

## Schema

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|---:|---|
| `model_name` | string | ✓ | Tên model |
| `model_version` | string | ✓ | Version |
| `task` | string | ✓ | `occupancy_forecasting` |
| `training_dataset` | string | ✓ | Ví dụ `UrbanEV` |
| `training_level` | enum | ✓ | `station` hoặc `zone` |
| `temporal_resolution_min` | int | ✓ | Resolution train |
| `lookback_steps` | int | ✓ | Số bước lịch sử đầu vào |
| `forecast_steps` | int | ✓ | Số bước cần dự đoán |
| `features` | array[string] | ✓ | Feature model sử dụng |
| `target` | string | ✓ | `occupied_ports` hoặc `occupancy_ratio` |
| `metrics` | object | ✓ | MAE/RMSE/... |
| `notes` | array[string] |  | Limitation |

## Mẫu

```json
{
  "model_name": "smart_ev_occupancy_v1",
  "model_version": "1.0.0",
  "task": "occupancy_forecasting",
  "training_dataset": "UrbanEV",
  "training_level": "station",
  "temporal_resolution_min": 5,
  "lookback_steps": 12,
  "forecast_steps": 3,
  "features": [
    "occupied_ports",
    "occupancy_ratio",
    "total_ports"
  ],
  "target": "occupied_ports",
  "metrics": {
    "mae": null,
    "rmse": null
  },
  "notes": [
    "Station identifiers are not transferable features across Shenzhen and Vietnam.",
    "Queue and waiting-time labels are not provided by UrbanEV."
  ]
}
```

---

# 13. Derived compatibility data

## Mục đích

Kết quả kiểm tra một xe có thể sử dụng một trạm hay không. Có thể tính runtime và không bắt buộc persist lâu dài.

**Giai đoạn sử dụng:** lọc candidate stations.

## Schema

| Attribute | Type | Mô tả |
|---|---|---|
| `vehicle_id` | string | Xe |
| `station_id` | string | Trạm |
| `compatible` | bool | Có connector tương thích hay không |
| `matched_connectors` | array[string] | Connector chung |
| `station_max_power_kw` | float | Công suất trạm phù hợp |
| `vehicle_max_power_kw` | float | Công suất tối đa xe nhận |
| `effective_power_kw` | float | `min(station, vehicle)` |
| `reason_codes` | array[string] | Giải thích kết quả |
| `data_source` | string | `derived` |

## Mẫu

```json
{
  "vehicle_id": "EV_VF8_DEMO",
  "station_id": "ST001",
  "compatible": true,
  "matched_connectors": ["CCS2"],
  "station_max_power_kw": 120,
  "vehicle_max_power_kw": 150,
  "effective_power_kw": 120,
  "reason_codes": ["MATCHED_CCS2"],
  "data_source": "derived"
}
```

---

# 14. Derived reachability data

## Mục đích

Đánh giá xe có đủ năng lượng để đến trạm với reserve SOC hay không.

**Giai đoạn sử dụng:** lọc candidate stations.

## Schema

| Attribute | Type | Mô tả |
|---|---|---|
| `vehicle_id` | string | Xe |
| `station_id` | string | Trạm |
| `route_id` | string | Route đã dùng |
| `route_distance_m` | float | Quãng đường tới trạm |
| `route_duration_s` | float | ETA route |
| `initial_soc` | float | SOC hiện tại |
| `reserve_soc` | float | SOC dự phòng |
| `trip_energy_kwh` | float | Năng lượng cần cho route |
| `estimated_arrival_soc` | float | SOC dự kiến khi tới |
| `reachable` | bool | Có thể tới an toàn hay không |
| `data_source` | string | `derived` |

## Công thức cơ bản

```text
trip_energy_kwh = route_distance_km * consumption_wh_km / 1000
calculation_battery_kwh = usable_battery_kwh nếu có, nếu không dùng battery_capacity_kwh
estimated_arrival_soc = initial_soc - trip_energy_kwh / calculation_battery_kwh
reachable = estimated_arrival_soc >= reserve_soc
```

---

# 15. Derived charging estimate

## Mục đích

Ước lượng lượng điện và thời gian cần sạc tại một candidate station.

**Giai đoạn sử dụng:** recommendation.

## Schema

| Attribute | Type | Mô tả |
|---|---|---|
| `vehicle_id` | string | Xe |
| `station_id` | string | Trạm |
| `arrival_soc` | float | SOC khi tới |
| `target_soc` | float | SOC mục tiêu |
| `energy_to_add_kwh` | float | Điện năng cần nạp |
| `effective_power_kw` | float | Công suất sạc hiệu dụng |
| `charging_efficiency` | float | Hiệu suất sạc |
| `estimated_charge_min` | float | Thời gian sạc dự kiến |
| `data_source` | string | `derived` |

## Công thức cơ bản

```text
calculation_battery_kwh = usable_battery_kwh nếu có, nếu không dùng battery_capacity_kwh
energy_to_add_kwh = (target_soc - arrival_soc) * calculation_battery_kwh
estimated_charge_min = energy_to_add_kwh / (effective_power_kw * charging_efficiency) * 60
```

> MVP dùng approximation công suất cố định; charging curve chi tiết có thể bổ sung sau.

---

# 16. Derived station recommendation

## Mục đích

Lưu các thành phần đã normalize và score cuối cho từng candidate station. Không chứa cost component trong MVP.

**Giai đoạn sử dụng:** xếp hạng candidate stations và giải thích recommendation.

## Schema

| Attribute | Type | Mô tả |
|---|---|---|
| `station_id` | string | Trạm |
| `compatible` | bool | Compatibility |
| `reachable` | bool | Reachability |
| `detour_min` | float | Detour so với hành trình gốc |
| `predicted_occupied_ports` | float | Occupancy forecast |
| `predicted_occupancy_ratio` | float | Tỷ lệ bận forecast |
| `estimated_wait_min` | float | Wait estimate |
| `estimated_charge_min` | float | Charging-time estimate |
| `arrival_soc` | float | SOC khi tới |
| `wait_score` | float | Score chuẩn hóa cho wait |
| `detour_score` | float | Score chuẩn hóa cho detour |
| `charging_time_score` | float | Score chuẩn hóa cho charging time |
| `soc_risk_score` | float | Score chuẩn hóa cho SOC risk |
| `final_score` | float | Score tổng |
| `rank` | int | Thứ hạng |
| `data_source` | string | `derived` |

## Mẫu

```json
{
  "station_id": "ST001",
  "compatible": true,
  "reachable": true,
  "detour_min": 6.5,
  "predicted_occupied_ports": 6.8,
  "predicted_occupancy_ratio": 0.85,
  "estimated_wait_min": 5.2,
  "estimated_charge_min": 27.0,
  "arrival_soc": 0.15,
  "wait_score": 0.78,
  "detour_score": 0.72,
  "charging_time_score": 0.80,
  "soc_risk_score": 0.64,
  "final_score": 0.75,
  "rank": 1,
  "data_source": "derived"
}
```

---

# 17. Tóm tắt dataset sau khi cắt scope

| Dataset / artifact | Nội dung chính | Nguồn chính | Giai đoạn sử dụng |
|---|---|---|---|
| `stations.geojson` | Vị trí, capacity, connector, công suất, provenance | Map thật + synthetic enrichment | Data setup, map, compatibility, recommendation |
| `demo/vehicles.json` | Battery, connector, charging limits, consumption, SOC rules | Real/manual | Compatibility, reachability, charging estimate |
| UrbanEV / `urbanev_processed.csv` | Historical occupancy data dùng cho train/validation/test | UrbanEV real | Occupancy ML |
| `station_history.csv` *(optional)* | Synthetic replay/simulation log; không dùng train ML | Synthetic | Replay, chart, wait-estimator evaluation |
| `station_status.json` | Current capacity, occupancy, queue và service-time assumption | Synthetic runtime | Runtime wait/recommendation |
| `demo_events.json` | Congestion/outage/queue spike | Synthetic | Dynamic demo |
| `demo_scenarios.json` | Fixed end-to-end demo inputs | Synthetic | Demo/test |
| `routes/*.json` | Geometry, distance, duration | Goong/OSRM | Reachability, detour, fallback |
| `planned_arrivals.json` | Xe dự kiến tới trạm và ETA | Runtime/synthetic | Projected load/wait |
| `queue_assumptions.json` | Arrival rate nền và override synthetic theo scenario | Synthetic | Erlang C wait estimation |
| `occupancy_model.joblib` | Binary occupancy forecasting model | Train/validate/test từ UrbanEV | Inference |
| `occupancy_model_meta.json` | Model schema/version/features/metrics | Generated | Reproducibility |
| Derived compatibility | Vehicle-station compatibility | Derived | Candidate filtering |
| Derived reachability | Khả năng xe tới trạm | Derived | Candidate filtering |
| Derived charging estimate | Energy và charging time cần thiết | Derived | Recommendation |
| Derived station recommendation | Detour/wait/charge/SOC score | Derived | Final ranking |

---

# 18. Các field đã loại khỏi MVP

Các field sau không nên xuất hiện trong canonical MVP data trừ khi sau này scope được mở rộng:

```text
electricity_price
service_fee
total_price
weather / temperature / humidity / rain
historical_volume_kwh
historical_charging_energy
poi_features
estimated_cost
cost_score
```

Lý do chính: chúng không cần thiết để chứng minh occupancy forecasting + wait estimation trong phiên bản hiện tại, đồng thời một số feature UrbanEV có domain distribution khác đáng kể so với dữ liệu demo tại Việt Nam.

Ngoài ra, `queue_length` và wait-time synthetic **không thuộc UrbanEV feature contract**. Chúng chỉ tồn tại trong runtime state hoặc optional simulation log của demo.
