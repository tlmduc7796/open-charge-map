# Smart EV Journey

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

Compose tự dựng PostgreSQL/PostGIS, backend FastAPI, frontend nginx và feeder. PostgreSQL nạp lịch
sử 30 ngày từ `database/fixtures/simulator/station_occupancy_5m.csv` (có trong git, mount vào cả
postgres và feeder ở `/sim`); feeder phát lại chính file đó tới backend mỗi 5 phút nên dữ liệu và
luồng cập nhật luôn khớp nhau.

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

Mỗi lần feeder khởi động, nó **điền lấp các bucket 5 phút còn thiếu** trong `HISTORY_DAYS` ngày gần
nhất từ cùng CSV (cùng thứ, cùng giờ; `database/docker/sql/backfill_gap.sql`). Nhờ đó, dù máy ngủ
hoặc Docker bị tắt nhiều giờ, model dự báo vẫn có đủ 12 bucket liên tiếp ngay khi `docker compose up`
thay vì rơi về `persistence` khoảng 1 giờ. Phần điền lấp là dữ liệu synthetic; dòng đã có không bị
ghi đè. Đặt `BACKFILL_GAPS=0` để tắt.

Compose mặc định `RESET_ON_START=0`; dữ liệu PostgreSQL được giữ trong named volume. Để dựng lại
toàn bộ dữ liệu, chạy `docker compose down -v` rồi `docker compose up --build`. Để dừng nhưng giữ
dữ liệu, chạy `docker compose down`.

CSV occupancy trong git chỉ gồm tháng 9–10/2026 (~13,6 MB), cắt từ file đầy đủ của simulator bằng
`python scripts/trim_occupancy_csv.py` (đọc `simulator/data/`, ghi `database/fixtures/simulator/`).
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
POST /api/v1/trips                      # tạo từ searchId (giữ 10 phút trong bộ nhớ)
GET  /api/v1/trips/{id}
POST /api/v1/trips/{id}/position        # GPS, recordedAt có timezone
PATCH /api/v1/trips/{id}                # accept/decline/depart/correctBattery/cancel
POST /api/v1/internal/station-occupancy # số cổng đang dùng mỗi trạm (5 phút/lần), yêu cầu X-API-Key
POST /api/v1/internal/port-status       # trạng thái từng cổng (tuỳ chọn), yêu cầu X-API-Key
POST /api/v1/internal/port-status/mark-stale
```

Quy ước:

- `/api/v1` dùng `{lat,lng}`, pin phần trăm `[0,100]`, JSON `camelCase`, error envelope thống nhất
  và `X-Request-ID`. Domain và dữ liệu nội bộ dùng `{lat,lon}` và SOC `[0,1]`.
- Search chỉ đề xuất trạm có giờ mở cửa xác nhận (`24/7` hoặc `always_open=true`); trạm khác nằm
  trong `excludedCandidates` kèm mã lý do.
- Trip được lưu bền trong PostgreSQL. `POST /trips` trả `tripToken` đúng một lần; các request sau
  phải gửi `Authorization: Bearer <tripToken>` (database chỉ lưu SHA-256). GPS lặp/cũ không ghi
  đè trạng thái; re-plan dùng ngưỡng trong `app_config`, có cooldown và bỏ qua trạm đã từ chối.
- `searchId` và giới hạn tần suất nằm trong bộ nhớ từng process.
- Trạng thái trạm lấy từ bucket occupancy 5 phút mới nhất (`station_occupancy_5m`): số cổng trống
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
| `STATION_STATUS_STALE_AFTER_S` | Bucket occupancy mới nhất của trạm cũ hơn ngưỡng này thì trạm là `unknown` (mặc định 900 s; dữ liệu về mỗi 5 phút) |
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
