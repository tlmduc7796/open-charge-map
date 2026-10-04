# Smart EV data platform

Thư mục này chứa bộ tối thiểu để tạo lại PostgreSQL/PostGIS database demo từ một snapshot SQL.
Không cần các JSON/KML thu thập, notebook, UrbanEV archive hoặc các script seed rời.

## Yêu cầu

- Python 3.12 trở lên;
- Docker Desktop đã chạy và có Docker Compose;
- PowerShell trên Windows.

## Khởi tạo database

Chạy từ thư mục gốc của repository:

```powershell
Set-Location data_platform
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python scripts\bootstrap_database.py
```

Lệnh cuối thực hiện toàn bộ quy trình:

1. khởi động PostgreSQL/PostGIS bằng `compose.yaml`;
2. chờ database sẵn sàng;
3. chạy Alembic migrations đến revision `0004_trips_config`;
4. nạp `data/bootstrap/current_database.sql` trong một transaction;
5. kiểm tra số row sau khi nạp.

Database mặc định:

```text
host:     127.0.0.1
port:     5433
database: smart_ev_data
user:     smart_ev
password: smart_ev
```

Bootstrap chỉ chạy trên database chưa có dữ liệu nghiệp vụ. Nếu phát hiện row đã tồn tại, script
dừng lại để tránh trộn hoặc ghi đè dữ liệu.

## Dữ liệu sau khi khởi tạo

Snapshot được chụp ngày 04/10/2026 và bao gồm cả dữ liệu master lẫn dữ liệu demo bổ sung.

| Bảng | Số row | Nội dung |
| --- | ---: | --- |
| `stations` | 102 | 16 trạm master và 86 trạm demo bổ sung |
| `station_external_refs` | 14 | Mã trạm từ nguồn bên ngoài |
| `connector_types` | 2 | CCS2 và Type2 |
| `ports` | 826 | Cổng sạc của toàn bộ trạm |
| `port_status` | 211 | Trạng thái hiện tại đã có trong snapshot |
| `station_live_metrics` | 16 | Queue/session metric hiện có |
| `port_status_history` | 211 | Lịch sử trạng thái cổng |
| `station_occupancy_5m` | 4.624 | Occupancy theo bucket 5 phút |
| `predictions` | 96 | Prediction theo trạm và horizon |
| `station_amenities` | 714 | Bảy amenity cho mỗi trạm |
| `vehicle_models` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `vehicle_connectors` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `trips` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `trip_positions` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `trip_events` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `app_config` | 0 | Chưa có dữ liệu trong snapshot hiện tại |

Trong 102 trạm có 52 trạm mang `review_status=synthetic` và `is_active=true`. Toàn bộ 714 amenity
là dữ liệu synthetic. Chỉ 211 cổng master có current status trong snapshot; không được suy diễn
status hoặc queue cho các cổng còn lại.

## Các file cần giữ

```text
data_platform/
├── compose.yaml
├── alembic.ini
├── pyproject.toml
├── data/bootstrap/current_database.sql
├── migrations/
├── scripts/bootstrap_database.py
└── src/data_platform/
```

`current_database.sql` là file dữ liệu duy nhất cần thiết. Schema được tạo từ migrations, vì vậy
snapshot không chứa các bảng hệ thống của PostGIS.

## Tạo lại database local từ đầu

Lệnh sau xóa toàn bộ Docker volume của database local:

```powershell
docker compose down -v
python scripts\bootstrap_database.py
```

Chỉ chạy khi chắc chắn dữ liệu trong volume không cần giữ lại. Các thay đổi phát sinh sau lần
bootstrap gần nhất sẽ mất nếu chưa được export.

## Thư mục `trash`

Code phân tích, collector, seed rời, tests, artifacts và tài liệu cũ đã được chuyển vào `trash/`
để có thể phục hồi khi cần. `trash/` bị Git ignore và không tham gia quá trình bootstrap.
