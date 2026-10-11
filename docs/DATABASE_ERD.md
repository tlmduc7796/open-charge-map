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
        uuid station_id FK
        text mode
        text phase
        geography origin
        geography destination
        geography route
        integer route_version
        text auth_token_hash
        jsonb planned
        timestamptz created_at
        timestamptz ended_at
    }

    TRIP_POSITIONS {
        uuid trip_id PK, FK
        timestamptz recorded_at PK
        geography location
        numeric battery_pct
        numeric speed_kmh
        numeric distance_km
    }

    TRIP_EVENTS {
        uuid id PK
        uuid trip_id FK
        timestamptz created_at
        text type
        jsonb payload
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
    STATIONS o|--o{ TRIPS : "may be selected by"
    TRIPS ||--o{ TRIP_POSITIONS : "records GPS"
    TRIPS ||--o{ TRIP_EVENTS : "records lifecycle"
```

`port_status_history` và `station_occupancy_5m` được partition theo tháng (09, 10 và 11/2026).
`app_config` là bảng cấu hình độc lập nên không có khóa ngoại. Hai view:
`station_capacity` và `station_status_current` (backend đọc khi khởi động).

## Số lượng bản ghi sau bootstrap

| Nhóm | Bảng | Số dòng | Ghi chú |
|---|---|---:|---|
| `catalog` | `stations` | 11 | 11 trạm VinFast |
| `catalog` | `connector_types` | 2 | CCS2, TYPE2 |
| `catalog` | `ports` | 200 | 178 CCS2 (20–250 kW), 22 TYPE2 (3,5–11 kW) |
| `vehicles` | `vehicle_models` | 18 | 18 mẫu xe VinFast |
| `vehicles` | `vehicle_connectors` | 35 | |
| `runtime` | `port_status` | 200 | mỗi cổng một dòng, `status='unknown'`, `reported_at` NULL |
| `history` | `port_status_history` | 0 | backend ghi dần |
| `history` | `station_occupancy_5m` | 0 | không seed |
| `forecast` | `predictions` | 66 | 11 trạm × 6 mốc; chỉ có khóa, mọi giá trị NULL |
| `trips` | `trips`, `trip_positions`, `trip_events` | 0 | do backend tạo |
| `config` | `app_config` | 1 | `planned_arrival_window_min = 15` |

## Phân bố chính

| Access | Số trạm |
|---|---:|
| Public | 11 |

Phạm vi địa lý của 11 trạm: longitude `106.65922–106.72233`, latitude `10.70113–10.81201`.

## Điểm cần lưu ý

1. **Trạng thái chưa có.** Mọi cổng ở `unknown`, nên `station_status_current` báo
   `operational_ports = 0` và backend coi mọi trạm là offline cho tới khi nhận trạng thái qua
   `POST /api/v1/internal/port-status`.
2. **Không có nguồn hàng đợi.** `queue_length` của view luôn NULL và không còn bảng metrics, nên
   ước lượng chờ trả `WAIT_INPUT_UNAVAILABLE` cho tới khi backend có nguồn queue/session.
3. **`predictions` là bảng slot.** Backend UPDATE tại chỗ; không lưu lịch sử các lượt chạy.
   Enum `prediction_source` chỉ gồm `persistence` và `model` (API trả thêm `default`).
4. **Arrival/planned arrival nằm trong bộ nhớ.** Trip không còn ghi cam kết mềm vào database;
   việc lưu bền được hoãn lại.
