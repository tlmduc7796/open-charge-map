# Database ERD và thống kê dữ liệu

**Database:** `smart_ev_data` — PostgreSQL 16 + PostGIS 3.4
**Phạm vi:** 13 bảng nghiệp vụ của Smart EV; không tính các bảng hệ thống PostGIS/Tiger
và các bảng partition vật lý.
**Nguồn sự thật:** `database/schema/*.sql` (viết tay, không dùng migration), kiểm tra bằng
`database/scripts/verify.py`. Xem [database/README.md](../database/README.md).

Bản demo đơn giản hóa: không còn `station_amenities`, `station_external_refs`,
`station_live_metrics`, `station_arrival_rates`, `planned_arrivals` (arrival rate và planned
arrival đọc từ fixture JSON trong bộ nhớ backend).

## ERD

```mermaid
erDiagram
    STATIONS {
        uuid id PK
        text code UK
        text name
        geography location
        jsonb opening_hours
        access_level access_level
        boolean is_active
    }

    CONNECTOR_TYPES {
        text code PK
        current_type current_type
        text display_name
    }

    PORTS {
        uuid id PK
        uuid station_id FK
        text connector_code FK
        text label
        numeric max_power_kw
        boolean is_active
    }

    PORT_STATUS {
        uuid port_id PK, FK
        port_status_value status
        timestamptz reported_at "NULL = chưa báo"
        timestamptz estimated_finish_at
    }

    PORT_STATUS_HISTORY {
        uuid id PK
        timestamptz changed_at PK
        uuid port_id FK
        port_status_value status
    }

    STATION_OCCUPANCY_5M {
        uuid id PK
        timestamptz bucket_at PK
        uuid station_id FK
        smallint total_ports
        smallint operational_ports
        smallint occupied_ports
        integer queue_length
    }

    PREDICTIONS {
        uuid station_id PK, FK
        smallint horizon_min PK
        timestamptz run_at "NULL = chưa dự báo"
        numeric predicted_occupancy_ratio
        numeric mean_wait_minutes
        prediction_source prediction_source
        text model_version
    }

    VEHICLE_MODELS {
        uuid id PK
        text code UK
        text brand
        text model
        numeric battery_kwh
        numeric consumption_kwh_per_100km
        numeric max_ac_kw
        numeric max_dc_kw
        boolean is_active
    }

    VEHICLE_CONNECTORS {
        uuid vehicle_model_id PK, FK
        text connector_code PK, FK
    }

    TRIPS {
        uuid id PK
        uuid vehicle_model_id FK
        uuid recommended_station_id FK
        uuid actual_station_id FK
        text mode
        geography origin
        geography destination
        numeric start_battery_pct
        timestamptz created_at
    }

    APP_CONFIG {
        text key PK
        jsonb value
        timestamptz updated_at
    }

    STATIONS ||--|{ PORTS : "owns"
    CONNECTOR_TYPES ||--o{ PORTS : "classifies"
    PORTS ||--o| PORT_STATUS : "has current status"
    PORTS ||--o{ PORT_STATUS_HISTORY : "records history"
    STATIONS ||--o{ STATION_OCCUPANCY_5M : "has 5-minute history"
    STATIONS ||--o{ PREDICTIONS : "has forecast slots"
    VEHICLE_MODELS ||--o{ VEHICLE_CONNECTORS : "supports"
    CONNECTOR_TYPES ||--o{ VEHICLE_CONNECTORS : "maps compatibility"
    VEHICLE_MODELS ||--o{ TRIPS : "is used by"
    STATIONS o|--o{ TRIPS : "recommended (rank 1)"
    STATIONS o|--o{ TRIPS : "actually chosen"
```

`port_status_history` và `station_occupancy_5m` được partition theo tháng. Partition tháng được tạo
bằng `ensure_month_partition()` lúc nạp lịch sử và mỗi lần backend ghi occupancy; mỗi bảng có thêm
partition `DEFAULT` làm lưới an toàn.
`station_occupancy_profile` (trạm × thứ × bước 5 phút) là bảng dẫn xuất từ `station_occupancy_5m`.
`app_config` là bảng cấu hình độc lập nên không có khóa ngoại. Hai view:
`station_capacity` và `station_status_current` (backend đọc khi khởi động). `station_status_current`
lấy bucket **mới nhất** của `station_occupancy_5m` cho mỗi trạm (số cổng đang dùng, không cần biết
cổng cụ thể); `port_status` không tham gia.

## Số lượng bản ghi sau bootstrap

| Nhóm | Bảng | Số dòng | Ghi chú |
|---|---|---:|---|
| `catalog` | `stations` | 11 | 11 trạm VinFast |
| `catalog` | `connector_types` | 2 | CCS2, TYPE2 |
| `catalog` | `ports` | 200 | 178 CCS2 (20–250 kW), 22 TYPE2 (3,5–11 kW) |
| `vehicles` | `vehicle_models` | 18 | 18 mẫu xe VinFast |
| `vehicles` | `vehicle_connectors` | 35 | |
| `runtime` | `port_status` | 200 | tuỳ chọn; mỗi cổng một dòng, `status='unknown'`, `reported_at` NULL |
| `history` | `port_status_history` | 0 | backend ghi dần (chỉ khi có báo từng cổng) |
| `history` | `station_occupancy_5m` | 0 | không seed; nạp nguyên CSV tháng 9–10/2026 lúc khởi tạo Docker (có thể ghi thêm qua `POST /api/v1/internal/station-occupancy`) |
| `history` | `station_occupancy_profile` | 0 | dẫn xuất từ `station_occupancy_5m` bằng `refresh_station_occupancy_profile()` |
| `forecast` | `predictions` | 66 | 11 trạm × 6 mốc; chỉ có khóa, mọi giá trị NULL |
| `trips` | `trips` | 0 | do backend ghi (nhật ký bấm Chỉ đường) |
| `config` | `app_config` | 1 | `planned_arrival_window_min = 15` |

## Phân bố chính

| Access | Số trạm |
|---|---:|
| Public | 11 |

Phạm vi địa lý của 11 trạm: longitude `106.65922–106.72233`, latitude `10.70113–10.81201`.

## Điểm cần lưu ý

1. **Trạng thái trạm = bucket occupancy mới nhất.** `station_status_current` tính
   `available = operational − occupied`, `offline = total − operational`. Trạm chưa có bucket nào
   báo `operational_ports = 0`, `unknown_ports = total_ports` cho tới khi nhận số cổng đang dùng qua
   `POST /api/v1/internal/station-occupancy` (khởi động Docker đã nạp sẵn CSV tháng 9–10/2026).
2. **Hàng đợi chỉ có nếu bucket có.** `queue_length` lấy từ `station_occupancy_5m.queue_length`
   (nullable, hiện NULL), nên ước lượng chờ trả `WAIT_INPUT_UNAVAILABLE` cho tới khi có nguồn
   queue/session.
3. **`predictions` là bảng slot.** Backend UPDATE tại chỗ; không lưu lịch sử các lượt chạy.
   Enum `prediction_source` chỉ gồm `persistence` và `model` (API trả thêm `default`).
4. **`trips` là nhật ký bấm Chỉ đường, không phải hành trình.** Mỗi lần người dùng bấm "Chỉ đường"
   (chuyển sang Google Maps) backend ghi một dòng: điểm bắt đầu, điểm kết thúc (NULL khi tìm trạm),
   pin còn, trạm hệ thống đề xuất hạng 1 và trạm thực sự chọn. Arrival/planned arrival nằm trong bộ nhớ.
