# Smart EV data platform

ERD và thống kê database hiện tại: [docs/DATABASE_ERD.md](../docs/DATABASE_ERD.md).

Thư mục này tập trung toàn bộ dữ liệu của repository. Bootstrap PostgreSQL/PostGIS dùng
snapshot SQL và hai file xe JSON; backend demo cùng các script thu thập/kiểm tra vẫn đọc
các JSON/KML khác trong `data/`.

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
3. chạy Alembic migrations đến revision `0006_trip_tokens`;
4. nạp `data/bootstrap/current_database.sql` trong một transaction;
5. đối chiếu `data/static/vehicles.json` với `data/demo/vehicles.json` và nạp xe;
6. nạp planned arrivals, arrival rate nền và cửa sổ tính từ fixture runtime/demo;
7. tạo trạng thái cổng, lịch sử ban đầu và metric synthetic cho 86 trạm mới từ
   `data/runtime/station_status.json` của 16 trạm gốc;
8. kiểm tra số row sau khi nạp.

Với database đã bootstrap từ revision cũ, nâng schema và đồng bộ runtime seed mà không
khôi phục lại snapshot tĩnh:

```powershell
Set-Location data_platform
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe scripts\seed_runtime_data.py
..\.venv\Scripts\python.exe scripts\seed_synthetic_port_statuses.py
Set-Location ..
```

Hai seed trên tạo dữ liệu demo 3B cho trường còn thiếu trên toàn bộ catalog active:
arrival rate, port status, queue/session duration, access và opening hours. Giá trị được tạo
deterministically, có `data_origin/provenance=synthetic` và không ghi đè dữ liệu observed.

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

Snapshot trạm được chụp ngày 04/10/2026; hồ sơ xe được nạp thêm từ hai file JSON khi bootstrap.

| Bảng | Số row | Nội dung |
| --- | ---: | --- |
| `stations` | 102 | 16 trạm master và 86 trạm demo bổ sung |
| `station_external_refs` | 14 | Mã trạm từ nguồn bên ngoài |
| `connector_types` | 4 | CCS2, Type2 và hai chuẩn GB/T dành cho fixture demo |
| `ports` | 826 | Cổng sạc của toàn bộ trạm |
| `port_status` | 826 | 211 trạng thái gốc và 615 trạng thái synthetic cho trạm mới |
| `station_live_metrics` | 102 | 16 metric gốc và 86 metric synthetic cho trạm mới |
| `port_status_history` | 826 | 211 mốc gốc và 615 mốc khởi tạo synthetic |
| `station_occupancy_5m` | 4.624 | Occupancy theo bucket 5 phút |
| `predictions` | 96 | Prediction theo trạm và horizon |
| `station_amenities` | 714 | Bảy amenity cho mỗi trạm |
| `vehicle_models` | 21 | 20 hồ sơ nguồn hãng và một xe synthetic chỉ dành cho demo |
| `vehicle_connectors` | 41 | Quan hệ cổng sạc của 21 xe |
| `planned_arrivals` | 4 | Hai planned, một cancelled và một expired fixture synthetic |
| `station_arrival_rates` | 102 | Arrival rate nền synthetic, 16 fixture và 86 giá trị deterministic bổ sung |
| `trips` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `trip_positions` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `trip_events` | 0 | Chưa có dữ liệu trong snapshot hiện tại |
| `app_config` | 1 | Cửa sổ tính planned-arrival rate, hiện là 15 phút |

Trong 102 trạm có 52 trạm mang `review_status=synthetic` và `is_active=true`. Toàn bộ 714 amenity
là dữ liệu synthetic. Trong 86 trạm mới, 34 trạm có `review_status=verified` đối với thông tin
trạm, nhưng toàn bộ 615 cổng của 86 trạm đều có `data_origin=synthetic`. Trạng thái cổng và
queue được mô phỏng từ 16 bản ghi JSON gốc, gắn `data_origin=synthetic`; nhãn review của trạm
không bị thay đổi. Seeder chỉ bổ sung bản ghi thiếu và có thể chạy lại an toàn.

Để bổ sung trạng thái cho database đã bootstrap trước thay đổi này:

```powershell
Set-Location data_platform
.\.venv\Scripts\python.exe scripts\seed_synthetic_port_statuses.py
```

## Bố cục dữ liệu

```text
data_platform/
├── compose.yaml
├── alembic.ini
├── pyproject.toml
├── data/
│   ├── bootstrap/current_database.sql  # snapshot dùng để khởi tạo DB
│   ├── static/                         # trạm nguồn và 20 hồ sơ xe cho DB
│   ├── demo/                           # fixture backend, gồm 3 xe schema cũ
│   ├── collection/                     # candidate chờ review
│   ├── runtime/                        # trạng thái demo
│   ├── routes/                         # route cache
│   ├── ml/urbanev/                     # nguồn và EDA ML
│   └── validation/                     # báo cáo kiểm tra
├── migrations/
├── scripts/bootstrap_database.py
└── src/data_platform/
```

`current_database.sql`, hai file xe, `runtime/planned_arrivals.json` và
`demo/queue_assumptions.json` được bootstrap tự nạp. Hai xe demo VinFast trùng cấu hình được
gộp với hồ sơ nguồn hãng; xe GB/T synthetic được lưu với `market=DEMO`, `is_active=false`.
Dung lượng pin công bố của BYD đã được nạp; dung lượng khả dụng và công suất AC tối đa chưa được
hãng xác nhận nên không suy đoán. Mức tiêu thụ BYD được suy ra từ dung lượng công bố và tầm chạy
NEDC, có provenance `inferred`. Các mức SOC dự phòng/đích và hiệu suất sạc dùng giả định lập kế
hoạch `synthetic` cho 20 hồ sơ xe. Schema được tạo từ migrations; snapshot không chứa bảng hệ
thống PostGIS.

Để nạp lại xe vào database đã khởi tạo mà không lặp bản ghi:

```powershell
Set-Location data_platform
python scripts\seed_vehicles.py
```

Importer chỉ điền trường số còn `null` và giữ giá trị đang có trong DB. Nếu một cấu hình khớp
nhiều row hiện hữu, importer dừng để kiểm tra thủ công thay vì tự xóa dữ liệu có thể đang được
`trips` tham chiếu.

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
