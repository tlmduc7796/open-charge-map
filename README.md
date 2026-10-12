# Smart EV Journey

## Station planning feature

The station recommendation feature is developed on top of this shared application so it can reuse the existing React frontend, FastAPI backend, PostgreSQL/PostGIS database, station catalog, and map infrastructure. Wait-time/occupancy forecasting remains a separate existing capability.

- [Station recommendation implementation plan](docs/station-planning/IMPLEMENTATION_PLAN_VI.md)
- [Shared API/domain contract and module briefs](docs/station-planning/modules/README.md)
- [Station planning overview](docs/station-planning/README.md)
- [Station recommendation ML demand pipeline](docs/station-planning/ML_DEMAND_PIPELINE_VI.md)

MVP đề xuất trạm sạc cho hành trình xe điện: xếp hạng trạm theo tổng thời gian (di chuyển + chờ +
sạc) dựa trên khả năng tương thích đầu sạc, tầm với của pin và dự báo occupancy tại thời điểm tới.
Phạm vi: TP.HCM.

Trạng thái hiện tại:

- **Database** là SQL viết tay (`database/schema/*.sql`), không dùng migration; xem
  [database/README.md](database/README.md).
- **ML** chưa tích hợp: mọi lời gọi backend → ML trả giá trị mặc định cố định
  (`backend/app/domain/ml_gateway.py`, `prediction_source=default`).
- **Kịch bản demo đã được gỡ** (scenario, event giả lập, route cache, `/planned-arrivals`); phần
  này sẽ thiết kế lại sau. Frontend dùng `/api/v1/search/route`.
- Phase 03–04 (UrbanEV preprocessing, model occupancy) chưa hoàn thành nên chưa có `RELEASE PASS`.

## Yêu cầu

- Python 3.12
- Node.js 20.19+ hoặc 22.12+, pnpm 11.19+
- Docker Desktop (PostgreSQL/PostGIS)

## Chạy nhanh (Windows)

```powershell
setup.bat      # một lần: venv backend, pnpm install, Postgres, nạp database
start.bat      # Postgres + backend (:8000) + frontend (:5173)
```

Điền `GOONG_API_KEY` vào `.env` (routing, Places) và `VITE_GOONG_MAPTILES_KEY` vào
`frontend/.env.local` (bản đồ). Hai key khác nhau; không dùng key này cho biến kia.

## Chạy bằng Docker

Cần Docker Desktop hoặc Docker Engine có Compose plugin. Từ thư mục gốc repo, chạy:

```sh
docker compose up --build
```

Compose tự dựng PostgreSQL/PostGIS, backend FastAPI và frontend nginx. PostgreSQL nạp **nguyên file**
`database/fixtures/simulator/station_occupancy_5m.csv` (tháng 9–10/2026, có trong git, mount ở `/sim`)
một lần lúc khởi tạo; không còn feeder hay nhịp cập nhật 5 phút. "Bây giờ" là **đồng hồ demo** của
backend (xem mục dưới), nên mọi trạng thái, dự báo và tìm kiếm đều tính tại thời điểm đó.

- Ứng dụng: http://127.0.0.1:5173
- Backend Swagger: http://127.0.0.1:8000/docs
- Backend health: http://127.0.0.1:8000/health
- Trạng thái container: `docker compose ps`

Không cần tạo `.env`. Có thể tạo `.env` từ `.env.example` để đặt `GOONG_API_KEY` (REST, backend),
`VITE_GOONG_MAPTILES_KEY` (Maptiles, frontend), hoặc đổi cổng và `POSTGRES_PASSWORD`. Không có key
Goong, backend dùng OSRM và frontend dùng Leaflet + OpenStreetMap. `VITE_API_BASE_URL` mặc định
`http://127.0.0.1:8000` và phải là URL mà trình duyệt trên máy người dùng truy cập được. Nếu thay
cổng, cập nhật các biến `BACKEND_HOST_PORT`, `FRONTEND_HOST_PORT`, `VITE_API_BASE_URL` và
`CORS_ORIGINS` tương ứng rồi build lại frontend.

### Đồng hồ demo

Dữ liệu chỉ phủ 2026-09-01 → 2026-10-31 (giờ VN), nên "bây giờ" của hệ thống là một đồng hồ có thể
chỉnh, không phải giờ máy:

- Trên bản đồ, khung giờ góc dưới trái có nút **Đổi giờ**: chọn ngày, giờ, phút, giây (giờ VN) rồi
  **Áp dụng**. Đồng hồ chạy tiếp từ thời điểm đó (không đóng băng); **Về giờ thật** trả lại giờ máy.
- Backend đọc trạng thái trạm là bucket mới nhất **không muộn hơn** giờ demo, dự báo chỉ dùng 12
  bucket đến thời điểm đó và bảng trung bình theo giờ chỉ gồm dữ liệu trước đó, nên không rò rỉ tương
  lai. Tìm kiếm, chuyến đi và `generatedAt` dùng cùng đồng hồ. Khi giờ demo đi qua mốc 5 phút kế
  tiếp, bucket mới tự xuất hiện mà không cần nguồn phát dữ liệu.
- `DEMO_NOW` (trong `.env` hoặc môi trường) đặt giờ ban đầu, ví dụ `DEMO_NOW=2026-10-11 08:00` (giờ
  VN; để trống = giờ thật). `DEMO_CLOCK_WRITABLE=false` khoá việc đổi giờ từ giao diện.
- API: `GET/PUT /api/v1/demo-clock` (body `{"demoNow": "2026-09-15T08:00:00+07:00"}` hoặc
  `{"reset": true}`) và `serverTime` trong `GET /health`. Đồng hồ nằm trong bộ nhớ một process:
  khởi động lại backend quay về `DEMO_NOW`.
- Ngoài khoảng dữ liệu (trước 01/09 hoặc sau 31/10/2026) mọi trạm là `unknown`; giao diện cảnh báo.

Compose mặc định `RESET_ON_START=0`; dữ liệu PostgreSQL được giữ trong named volume. Để dựng lại
toàn bộ dữ liệu, chạy `docker compose down -v` rồi `docker compose up --build`. Để dừng nhưng giữ
dữ liệu, chạy `docker compose down`.

CSV occupancy trong git chỉ gồm tháng 9–10/2026 (~13,6 MB), cắt từ file đầy đủ của simulator bằng
`python scripts/trim_occupancy_csv.py` (đọc `simulator/data/`, ghi `database/fixtures/simulator/`).
Dữ liệu đã nạp từ trước (cửa sổ 30 ngày cũ) không tự đổi: chạy `docker compose down -v` rồi
`docker compose up --build` để nạp lại nguyên CSV.
Các booster `ml/model/model_h{5..30}.json` bị loại khỏi Git. Không có sáu booster, backend vẫn chạy
nhưng dùng giá trị dự báo mặc định; `/model/status` tiếp tục báo mô hình chưa sẵn sàng.
Các kết quả simulator là dữ liệu synthetic, không phải dữ liệu trạm đo thực tế.

## Cài đặt thủ công

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements-dev.txt
Copy-Item .env.example .env
Copy-Item frontend\.env.example frontend\.env.local

# database (chỉ cần Python + Docker, không cần venv riêng)
python database\scripts\bootstrap_database.py

# backend
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

# frontend
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev --host 127.0.0.1
```

- Frontend: `http://127.0.0.1:5173`; health: `http://127.0.0.1:8000/health`; schema:
  `http://127.0.0.1:8000/docs`.
- Dùng cùng hostname `127.0.0.1`; nếu mở bằng `localhost` thì đặt `CORS_ORIGINS` tương ứng.
- Vite không đọc `.env` ở thư mục gốc; key frontend nằm trong `frontend/.env.local`.

## API

Catalog và tiện ích (chế độ cũ, không gắn kịch bản):

```text
GET  /stations   /stations/{id}   /stations/{id}/status   /vehicles   /model/status
GET  /geocoding/autocomplete?query=   /geocoding/details/{place_id}   # cần GOONG_API_KEY
POST /route
```

Hợp đồng `/api/v1`:

```text
GET  /api/v1/config
GET  /api/v1/stations?bbox=minLng,minLat,maxLng,maxLat
GET  /api/v1/stations/availability?offset=0|5|10|15|20|25|30
GET  /api/v1/stations/{id}   /api/v1/stations/{id}/ports
POST /api/v1/search/stations
POST /api/v1/search/route
POST /api/v1/direction-clicks           # ghi lần bấm "Chỉ đường": trạm hạng 1 vs trạm thực sự chọn
POST /api/v1/internal/station-occupancy # ghi số cổng đang dùng mỗi trạm (nguồn ngoài, tuỳ chọn), yêu cầu X-API-Key
GET  /api/v1/demo-clock                 # giờ demo + khoảng dữ liệu đã nạp
PUT  /api/v1/demo-clock                 # đổi giờ demo: {"demoNow": ISO có offset} hoặc {"reset": true}
POST /api/v1/internal/port-status       # trạng thái từng cổng (tuỳ chọn), yêu cầu X-API-Key
POST /api/v1/internal/port-status/mark-stale
```

Quy ước:

- `/api/v1` dùng `{lat,lng}`, pin phần trăm `[0,100]`, JSON `camelCase`, error envelope thống nhất
  và `X-Request-ID`. Domain và dữ liệu nội bộ dùng `{lat,lon}` và SOC `[0,1]`.
- Search chỉ đề xuất trạm có giờ mở cửa xác nhận (`24/7` hoặc `always_open=true`); trạm khác nằm
  trong `excludedCandidates` kèm mã lý do.
- Mỗi lần bấm "Chỉ đường" (mở Google Maps) frontend gọi `POST /direction-clicks`; backend ghi một dòng
  vào bảng `trips`: điểm bắt đầu, điểm kết thúc (NULL khi tìm trạm), pin còn, id trạm hệ thống đề xuất
  hạng 1 (`recommended_station_id`) và id trạm thực sự chọn (`actual_station_id`).
- `searchId` và giới hạn tần suất nằm trong bộ nhớ từng process.
- Trạng thái trạm lấy từ bucket occupancy 5 phút mới nhất không muộn hơn giờ demo (`station_occupancy_5m`): số cổng trống
  = `operational − occupied`; không cần biết cổng nào đang dùng, nên `/stations/{id}/ports` và
  `byConnector` được suy ra từ số đếm (`dataSource = inferred`). Trạm chưa có bucket, hoặc bucket
  cũ hơn `STATION_STATUS_STALE_AFTER_S`, là `unknown` và chưa được gợi ý cho tới khi nhận số liệu
  qua `POST /api/v1/internal/station-occupancy`; `queue_length` chưa có nguồn nên ước lượng chờ báo
  `WAIT_INPUT_UNAVAILABLE`. Kết quả tính toán có `generatedAt`; `updatedAt` là thời điểm dữ liệu
  nguồn đổi.

## Cấu hình (`.env`)

| Biến | Ý nghĩa |
| --- | --- |
| `DATABASE_URL` | PostgreSQL của backend (mặc định cổng `5433`, database `smart_ev_data`) |
| `CATALOG_STORAGE` | `database` (mặc định) hoặc `memory` (đọc `DATA_DIR`, dùng cho test/chẩn đoán) |
| `DATA_DIR` | Thư mục fixture JSON, mặc định `database/fixtures` |
| `GOONG_API_KEY` | REST key của backend (Directions, Places); không đặt vào biến `VITE_*` |
| `ROUTING_TIMEOUT_S` | Timeout routing Goong/OSRM |
| `WAIT_SCORING_CAP_MIN` | Trần thời gian chờ khi chấm điểm |
| `RECOMMEND_MAX_*`, `RECOMMEND_SOC_RISK_BUFFER` | Ngưỡng chuẩn hóa cố định |
| `RECOMMEND_CANDIDATE_CORRIDOR_M` | Bán kính hành lang PostGIS quanh đường thẳng đi–đến (mặc định 5000 m) |
| `STATION_STATUS_STALE_AFTER_S` | Bucket occupancy mới nhất của trạm cũ hơn ngưỡng này thì trạm là `unknown` (mặc định 900 s, tính theo giờ demo) |
| `DEMO_NOW` | Giờ demo ban đầu (giờ VN nếu không có offset; trống = giờ thật). Đổi lúc chạy bằng `PUT /api/v1/demo-clock` |
| `DEMO_CLOCK_WRITABLE` | `false` thì `PUT /api/v1/demo-clock` trả 403 (mặc định `true`) |
| `AVAILABILITY_GREEN_MIN` | Số cổng trống tối thiểu để trạm là `green` (mặc định 2) |
| `SEARCH_RATE_LIMIT_PER_MIN` | Giới hạn tìm kiếm mỗi IP mỗi process (mặc định 30) |
| `INTERNAL_API_KEY` | Bắt buộc cho `/api/v1/internal/*`; để trống thì endpoint trả 503 |
| `MODEL_ARTIFACT_PATH`, `MODEL_PREPROCESSOR_PATH`, `MODEL_META_PATH` | Artifact occupancy (chưa có) |
| `VITE_API_BASE_URL`, `VITE_GOONG_MAPTILES_KEY` | Frontend (`frontend/.env.local`) |

## Kiểm tra

```powershell
pytest                                   # backend, database layout, tests/
ruff check backend database
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
python database\scripts\verify.py        # SQL layer trên database tạm (cần Docker)
```

Test tích hợp PostgreSQL chỉ chạy khi đặt `BACKEND_TEST_DATABASE_URL` trỏ tới một database
**riêng** đã bootstrap (test ghi trạng thái cổng; không dùng database vận hành):

```powershell
python database\scripts\bootstrap_database.py --database-name smart_ev_test
$env:BACKEND_TEST_DATABASE_URL="postgresql+psycopg://smart_ev:smart_ev@127.0.0.1:5433/smart_ev_test"
pytest backend\tests
```

Backend test dùng một routing provider giả (đường thẳng × 1,35) nên không cần mạng hay key.

## Thêm trạm

1. Thêm trạm vào `database/fixtures/static/stations.geojson` (chế độ memory) và
   `database/data/catalog/{stations,ports}.sql` cùng `port_status.sql` (database); cập nhật `rows`
   trong `database/tables.toml`.
2. Cập nhật `fixtures/demo/queue_assumptions.json` và `fixtures/runtime/station_status.json` nếu
   dùng chế độ memory.
3. Chạy `python database\scripts\verify.py`, rồi tạo lại database local.
