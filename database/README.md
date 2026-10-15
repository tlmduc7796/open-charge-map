# Smart EV database

Nguồn sự thật của schema là các file SQL trong `schema/`; thứ tự áp dụng và số dòng kỳ vọng được khai báo trong `tables.toml`. ERD và thống kê chi tiết được lưu trong kho tài liệu bên ngoài repository.

Thư mục này chứa toàn bộ lớp dữ liệu của repository: schema PostgreSQL/PostGIS viết bằng SQL,
dữ liệu seed, fixture JSON cho backend và các công cụ dựng/kiểm tra database.

## Yêu cầu

- Python 3.12 trở lên (chỉ thư viện chuẩn, không cần cài gói nào);
- Docker Desktop đã chạy và có Docker Compose;
- PowerShell trên Windows.

## Bố cục

```text
database/
├── tables.toml          # DANH SÁCH DUY NHẤT: thứ tự áp dụng, nhóm vai trò, số dòng kỳ vọng
├── schema/              # DDL viết tay — NGUỒN SỰ THẬT của schema, mỗi bảng một file
│   ├── _base/           #   extensions, types (enum), functions
│   ├── catalog/  vehicles/  runtime/  history/  forecast/  trips/  config/
│   └── views/
├── data/<nhóm>/<bảng>.sql   # INSERT của bảng nhỏ, đọc được, sắp theo order_by
├── bulk/<bảng>.csv      # dữ liệu lớn nạp bằng COPY (hiện chưa có file nào)
├── fixtures/            # JSON/GeoJSON/KML cho backend và script (static, demo, runtime, routes…)
├── scripts/             # bootstrap_database, apply_sql, verify, export_data (stdlib + docker)
├── tests/               # test_sql_layout (chạy bằng pytest ở thư mục gốc, không cần Docker)
└── compose.yaml
```

### Nhóm bảng theo vai trò

| Nhóm | Bảng | Vai trò |
| --- | --- | --- |
| `catalog` | `connector_types`, `stations`, `ports` | Danh mục tĩnh: trạm, cổng, chuẩn cổng |
| `vehicles` | `vehicle_models`, `vehicle_connectors` | Hồ sơ xe và chuẩn cổng tương thích |
| `runtime` | `port_status` | Trạng thái từng cổng (tuỳ chọn, không quyết định số cổng trống); seed chỉ tạo sẵn dòng `unknown` |
| `history` | `port_status_history`, `station_occupancy_5m`, `station_occupancy_profile` | Chuỗi thời gian partition theo tháng; `station_occupancy_5m` là **nguồn sự thật của trạng thái trạm** (số cổng đang dùng mỗi 5 phút), nạp nguyên CSV tháng 9–10/2026 lúc khởi tạo Docker (có thể ghi thêm qua `POST /api/v1/internal/station-occupancy`); `station_occupancy_profile` là bảng trung bình dẫn xuất |
| `forecast` | `predictions` | Một dòng cho mỗi trạm × mốc 5–30 phút; seed chỉ có khóa, giá trị NULL cho backend ghi |
| `trips` | `trips` | Nhật ký bấm Chỉ đường (trạm đề xuất vs trạm thực sự chọn) do backend ghi |
| `config` | `app_config` | Cấu hình chỉnh được lúc chạy |

Ngoài ra `schema/views/` có `station_capacity` và `station_status_current` (backend đọc khi
khởi động). Các bảng `station_amenities`, `station_external_refs`, `station_live_metrics`,
`station_arrival_rates`, `planned_arrivals` đã bị loại khỏi bản demo;
arrival rate và planned arrival đọc từ fixture JSON trong bộ nhớ backend.

## Khởi động bằng Docker (một lệnh)

`compose.yaml` dựng lại **toàn bộ** database mỗi lần container khởi động. Chạy từ `database/`:

```powershell
docker compose up -d --force-recreate --wait
```

Lệnh này (mất vài giây):

1. xoá sạch dữ liệu cũ trong volume (`docker/reset-entrypoint.sh`);
2. tạo schema và nạp seed theo `tables.toml` (`docker/initdb/20-schema-and-data.sh`);
3. nạp **nguyên file** `fixtures/simulator/station_occupancy_5m.csv` (tháng 9 + tháng 10/2026,
   193 248 dòng, có trong git) vào `station_occupancy_5m`: không neo theo giờ máy, không dịch ngày,
   không cắt "tương lai" (`docker/initdb/30-simulator-history.sh`, `docker/sql/load_history.sql`);
   partition tháng được tạo trước khi chèn (`_2026_08` chứa 01/09 00:00–07:00 giờ VN vì biên UTC);
4. bảng trung bình `station_occupancy_profile` **không** tính ở đây: nó phụ thuộc thời điểm demo, nên
   backend gọi `refresh_station_occupancy_profile(p_days, p_timezone, p_now)` lúc khởi động và mỗi
   lần đổi giờ demo (chỉ tính bucket `<= p_now`);
5. trạng thái trạm tại một thời điểm T là bucket mới nhất `<= T`: hàm `station_status_at(T)`; view
   `station_status_current` chỉ là `station_status_at(now())`. Không cần ghi `port_status`.

Điều kiện: file CSV nằm trong git; tạo lại từ simulator bằng
`python scripts/trim_occupancy_csv.py --months 9 10 --year 2026`.

| Biến môi trường | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `RESET_ON_START` | `1` | `0` = giữ dữ liệu giữa các lần khởi động |
| `HISTORY_REQUIRED` | `1` | `0` = thiếu CSV chỉ cảnh báo và để lịch sử rỗng |

Không còn nguồn cập nhật định kỳ: dữ liệu chỉ đến từ CSV đã nạp và, tuỳ chọn, từ một nguồn ngoài gọi
`POST /api/v1/internal/station-occupancy` (backend upsert vào bucket 5 phút tương ứng của
`station_occupancy_5m`; báo sau trong cùng bucket ghi đè). Trạng thái trạm tại thời điểm demo T =
bucket mới nhất `<= T`: `available = operational − occupied`, `offline = total − operational`.
Backend coi trạm là `unknown` khi bucket đó cũ hơn `STATION_STATUS_STALE_AFTER_S` (mặc định 900
giây) so với T. Tính lại bảng trung bình theo một thời điểm:
`SELECT refresh_station_occupancy_profile(30, 'Asia/Ho_Chi_Minh', '2026-10-12 00:00+07');`.

> **Cảnh báo:** mỗi lần container khởi động là xoá toàn bộ dữ liệu trong volume, kể cả `trips`.
> Dùng `RESET_ON_START=0` nếu cần giữ dữ liệu.

## Khởi tạo database bằng script Python

Chạy từ thư mục gốc của repository (không cần venv riêng; Python hệ thống hoặc `.venv` của
backend đều được):

```powershell
Set-Location database
python scripts\bootstrap_database.py
```

`bootstrap_database.py` khởi động PostgreSQL/PostGIS bằng `compose.yaml`, tạo database nếu chưa
có, áp dụng `schema/` rồi nạp `data/` và `bulk/` theo thứ tự trong `tables.toml`, sau đó đối
chiếu số dòng với `tables.toml`. Nó từ chối database đã có bảng `stations`.

Các lệnh lẻ (đều chạy từ `database/`):

```powershell
python scripts\apply_sql.py --database-name smart_ev_data   # schema + dữ liệu
python scripts\apply_sql.py --schema-only                   # chỉ tạo bảng/view
python scripts\apply_sql.py --data-only                     # chỉ nạp dữ liệu vào bảng trống
```

Mỗi file chạy trong một transaction riêng nên lỗi chỉ rõ bảng nào hỏng. Cũng có thể dùng
`psql -f` theo đúng thứ tự trong `tables.toml`.

Database mặc định:

```text
host:     127.0.0.1
port:     5433
database: smart_ev_data
user:     smart_ev
password: smart_ev
```

## Kiểm tra và sửa

```powershell
python scripts\verify.py        # chạy trước khi commit thay đổi schema/dữ liệu
```

`verify.py` dựng một database tạm từ `schema/`+`data/`+`bulk/` rồi kiểm tra: file khớp
`tables.toml` (không thiếu, không thừa), áp dụng sạch vào database trống theo đúng thứ tự,
số dòng đúng, mọi bảng đều được khai báo, `station_status_current` trả đủ trạm. Test offline:
`pytest database/tests` từ thư mục gốc.

| Việc cần làm | Cách làm |
| --- | --- |
| Sửa cột/ràng buộc | Sửa `schema/<nhóm>/<bảng>.sql` (và `data/` nếu dữ liệu đổi), chạy `verify.py`, rồi tạo lại database local |
| Thêm bảng | Tạo `schema/<nhóm>/<bảng>.sql`, thêm khối `[[table]]` vào `tables.toml` sau các bảng nó tham chiếu; chạy `verify.py` |
| Sửa dữ liệu nhỏ | Sửa trực tiếp `data/<nhóm>/<bảng>.sql`; cập nhật `rows` trong `tables.toml` nếu đổi số dòng |
| Xuất lại dữ liệu từ một DB đang chạy | `python scripts\export_data.py --database-name <db>` |

`export_data.py` ghi file ổn định giữa các lần chạy (sắp theo `order_by`, bỏ cột kiểm toán có
mặc định `now()`, JSON được dàn dòng cho bảng nhỏ) nên diff chỉ thể hiện thay đổi thật.

## Dữ liệu sau khi khởi tạo

| Bảng | Số row | Nội dung |
| --- | ---: | --- |
| `stations` | 11 | 11 trạm VinFast (`operator_name = 'VinFast'`) |
| `connector_types` | 2 | Chỉ CCS2 và Type2 |
| `ports` | 200 | 178 CCS2 và 22 Type2 |
| `port_status` | 189 | Mỗi cổng một dòng; seed là `status='unknown'`, `reported_at` NULL; không ảnh hưởng số cổng trống của trạm |
| `predictions` | 66 | 11 trạm × 6 mốc; chỉ có `station_id` và `horizon_min`, mọi giá trị NULL |
| `vehicle_models` | 18 | 18 mẫu xe VinFast |
| `vehicle_connectors` | 35 | Quan hệ cổng sạc (CCS2/Type2) của 18 xe |
| `app_config` | 0 | Không seed; backend dùng giá trị mặc định cho tới khi có key |
| `port_status_history` | 0 | Không seed; backend ghi dần |
| `station_occupancy_5m` | 0 (bản seed) | Không có trong `data/`; nạp nguyên CSV tháng 9–10/2026 lúc khởi tạo Docker (có thể ghi thêm qua `/internal/station-occupancy`) |
| `station_occupancy_profile` | 0 (bản seed) | Dẫn xuất; tính bởi `refresh_station_occupancy_profile()` |
| `trips` | 0 | Do backend tạo |

Sau bootstrap bằng Python (không nạp lịch sử) mọi trạm chưa có bucket nào nên `operational_ports = 0`
và `unknown_ports = total_ports`: backend coi chúng là chưa có dữ liệu và chưa gợi ý được cho tới khi
nhận số cổng đang dùng qua `POST /api/v1/internal/station-occupancy`. Khởi động bằng Docker đã nạp
CSV tháng 9–10/2026 nên có trạng thái cho mọi thời điểm trong khoảng đó. `queue_length` lấy từ bucket (nullable), mặc định NULL.

Catalog chỉ gồm trạm và xe của VinFast, chỉ với cổng CCS2 và Type2: 5 trạm EV ONE, xe BYD, xe
demo GB/T và hai chuẩn GB/T đã bị bỏ khỏi `data/`. Các file trong `fixtures/` (dùng cho chế độ
memory và test) không đổi nên vẫn chứa 16 trạm.

Schema không lưu nguồn gốc dữ liệu (không có `provenance`, `data_origin`,
`simulation_run_id`). Các tham số xe không có trong catalog được backend **giả định** cho mọi xe:
SOC dự phòng 0,1; SOC đích 0,8; hiệu suất sạc 0,9; công suất AC/DC thiếu lấy 3,3 kW / 50 kW;
dung lượng pin khả dụng = dung lượng công bố. Hằng số nằm ở `ASSUMED_*` trong
`backend/app/catalog_repository.py`. Hai xe giữ mã `EV_VF5_PLUS` và `EV_VF7_ECO` làm
`vehicle_models.code` để khớp với `fixtures/demo/vehicles.json`.

Kịch bản demo (scenario, event giả lập, route cache, planned arrivals) đã được gỡ khỏi database
và `fixtures/`; sẽ thiết kế lại sau. `fixtures/` còn: `static/stations.geojson`,
`demo/vehicles.json`, `demo/queue_assumptions.json`, `runtime/station_status.json`, cùng các
thư mục tham khảo `collection/`, `ml/`, `validation/`.

## Nâng cấp database đã tồn tại

Không có migration: schema chỉ được áp dụng lên database trống. Database dựng từ phiên bản
cũ (102 trạm, có bảng/cột đã bỏ, có `alembic_version`) cần được tạo lại:

```powershell
docker compose down -v
python scripts\bootstrap_database.py
```

Lệnh trên xóa toàn bộ Docker volume của database local; chỉ chạy khi dữ liệu trong volume không
cần giữ lại. Để chỉ bỏ trạm demo bổ sung: `DELETE FROM stations WHERE code LIKE 'CAND_%';`
(các bảng con xóa theo cascade).

Backend kiểm tra lúc khởi động rằng các bảng/view cần dùng đã tồn tại (`/health` trả
`database: ready`); database cũ thiếu bảng sẽ báo "not initialized" thay vì chạy sai.

## Thư mục `trash`

Code phân tích, collector, seed rời, tests, artifacts và tài liệu cũ đã được chuyển vào `trash/`
để có thể phục hồi khi cần. `trash/` bị Git ignore và không tham gia quá trình bootstrap.
