# Smart EV Journey

MVP đề xuất trạm sạc phù hợp cho hành trình EV dựa trên compatibility, reachability, occupancy forecast, estimated wait và detour.

Phase 00–02 cung cấp dữ liệu và skeleton chạy được. Trên nhánh demo backend-first,
Phase 05 đã bổ sung domain core cho compatibility, reachability và charging estimate;
Phase 06 đã bổ sung persistence occupancy forecast và Erlang C wait estimator.
Phase 07 đã bổ sung route cache/Goong/OSRM, recommendation, runtime events,
planned-arrival lifecycle và backend demo APIs.
Phase 08 đã bổ sung frontend dùng API thật, Goong Maps chính với Leaflet/OSM fallback,
journey controls, station details, recommendation, route và event/model indicators.
Phase 09 đã hoàn thiện journey tích hợp: Goong Places, origin/destination động, live/cache
routing, route geometry trong recommendation và planned-arrival commit/cancel.
Phase 10 đã khóa bốn scenario deterministic, route cache cho toàn bộ 15 trạm public,
reset/replay và API regression tests cho low-SOC, congestion và outage reranking.
Phase 03–04 vẫn deferred và chưa được đánh dấu hoàn thành, vì vậy Phase 06 chỉ đạt
demo gate chứ chưa đạt release gate. Bản demo không claim đã có occupancy ML artifact:
`prediction_source=persistence` là trạng thái chủ động và được hiển thị trên UI.

## Yêu cầu

- Python 3.12
- Node.js 20.19+ hoặc 22.12+
- pnpm 11.19+

## Cài đặt backend

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.txt
Copy-Item .env.example .env
```

### Persistence profile cho backend (local/integration)

Backend vẫn khởi động bằng fixture/in-memory ở cấu hình demo mặc định. Để kiểm thử tích hợp
PostgreSQL/PostGIS local, xem hướng dẫn và provenance dữ liệu trong
[`data_platform/README.md`](data_platform/README.md), sau đó bootstrap database. Snapshot này
có dữ liệu synthetic; chỉ dùng cho local/integration, không dùng để provision database release:

```powershell
Set-Location data_platform
python -m pip install -e .
python scripts\bootstrap_database.py
Set-Location ..
```

Trong `.env`, cấu hình `DATABASE_URL`, `CATALOG_STORAGE=database` và
`PLANNED_ARRIVALS_STORAGE=database`; bật thêm `REALTIME_TELEMETRY_STORAGE=database`
và `JOURNEY_STORAGE=database` để lưu snapshot telemetry, hành trình và kết quả recommendation;
đặt `OCCUPANCY_HISTORY_STORAGE=database` để serving truy vấn các bucket occupancy đã quan sát.
GPS re-plan dùng `REPLAN_DEVIATION_THRESHOLD_M` và `REPLAN_MIN_INTERVAL_MIN`.
Khi `DEMO_MODE=false`, backend cũng yêu cầu `REDIS_URL`; release compose cấu hình Redis nội bộ cho rate limiting, SSE pub/sub và cache model forecast theo snapshot/horizon (TTL mặc định 300 giây, cấu hình qua `OCCUPANCY_FORECAST_CACHE_TTL_S`). Cache chỉ lưu dự báo model; lỗi cache tự fallback sang inference, còn persistence không bị cache.
PostgreSQL local chạy trên cổng `5433` theo compose của data platform. Trong môi trường release,
hãy giữ `DEMO_MODE=false` để endpoint demo/reset bị khóa;
trong `frontend/.env.local`, đặt `VITE_DEMO_MODE=false` để ẩn Queue Lab và các điều khiển
demo. Chỉ bật demo mode trong môi trường demo riêng. Database snapshot có trường synthetic và
không được xem là telemetry thật.

### Đóng gói Docker cho release

Release stack gồm PostgreSQL/PostGIS, Redis, API, frontend Nginx và Prometheus; web proxy REST và SSE qua cùng origin. Redis yêu cầu password, chỉ mở trong mạng Docker, và không lưu state bền vững. Prometheus chỉ bind loopback ở cổng `9090`; API metrics được scrape trên Docker network và không public qua Nginx. Đóng gói không làm dữ liệu seed synthetic trở thành dữ liệu vận hành thật.

```powershell
Copy-Item .env.release.example .env.release
```

Replace the sample values with unique production secrets before continuing.
Set `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, and the public `OIDC_CLIENT_ID` in `.env.release`. The frontend image receives the issuer, client ID, and scope at build time; register `https://<deployment-host>/auth/callback` as the OIDC redirect URI. The demo `frontend/.env.example` includes the same `VITE_OIDC_*` names for local reference, but release Compose builds with `VITE_DEMO_MODE=false`.

```powershell
python scripts\preflight_release.py
```

Khởi tạo schema release bằng PostgreSQL và migration. Không chạy `bootstrap_database.py` hoặc seed runtime ở profile này: các lệnh đó nạp snapshot demo/synthetic và không tạo database đủ điều kiện release.

```powershell
docker compose --env-file .env.release -f compose.release.yaml build api
docker compose --env-file .env.release -f compose.release.yaml up -d postgres
docker compose --env-file .env.release -f compose.release.yaml run --rm migrate
```

Preview catalog station/port và vehicle đã được duyệt; chỉ apply sau khi người vận hành xác minh nguồn, phạm vi và provenance. Cần cài backend requirements và data-platform package trước khi chạy importer:

```powershell
python -m pip install -r backend\requirements.txt -e .\data_platform
python data_platform\scripts\import_release_catalog.py `
  --stations C:\SecureInput\stations.reviewed.json `
  --vehicles C:\SecureInput\vehicles.reviewed.json
python data_platform\scripts\import_release_catalog.py `
  --stations C:\SecureInput\stations.reviewed.json `
  --vehicles C:\SecureInput\vehicles.reviewed.json `
  --apply --reviewed-by "operator@example.com"
```

Khởi động ứng dụng sau khi catalog đã được nạp:

```powershell
docker compose --env-file .env.release -f compose.release.yaml up -d --build
```

Adapter telemetry phải gửi snapshot vận hành đầy đủ, còn hạn cho ít nhất một trạm eligible trước khi `/api/health/ready` chuyển sang `ready`; readiness sẽ fail closed nếu thiếu catalog hoặc telemetry. Trước cutover, chạy `python scripts\smoke_release.py --allow-persistence` để kiểm tra stack; gate nghiêm ngặt không có flag này còn yêu cầu model occupancy đã promote. Frontend được phục vụ nội bộ tại `http://127.0.0.1:8080`; Compose bind cổng web vào loopback để reverse proxy TLS trên host là lối truy cập công khai. API liveness tại `/api/health/live`, health Nginx tại `/health/live`, còn PostgreSQL cũng chỉ bind vào loopback. Hiện nguồn telemetry của workspace vẫn mô phỏng và chưa có aggregator được chọn, nên không thể hoàn tất bước ingest vận hành hoặc cutover release bằng dữ liệu hiện có.

Prometheus UI nội bộ trên host mở tại `http://127.0.0.1:9090`; metric `smart_ev_http_responses_total` và `smart_ev_http_response_start_duration_seconds` dùng route template, method và status code, không dùng path chứa ID. `smart_ev_occupancy_forecasts_total` và `smart_ev_occupancy_fallbacks_total` theo dõi model/persistence và nhóm nguyên nhân fallback.

Encrypted backup creation, verification, restore, and retention instructions are in [`data_platform/README.md`](data_platform/README.md#encrypted-backups-verification-restore-and-retention).

Sau khi deploy, chạy smoke gate từ thư mục gốc:

```powershell
python scripts\smoke_release.py --allow-persistence # checks web/API, DB/Redis, catalogs and station-status provenance; allows persistence fallback
python scripts\smoke_release.py                    # strict release gate; requires a promoted occupancy model
```

Lệnh thứ nhất chỉ chứng minh stack phục vụ được với persistence fallback, không phải `RELEASE PASS`. Lệnh thứ hai cũng yêu cầu catalog không chứa fixture synthetic và model status báo `release_ready=true`.

Nếu chưa có UrbanEV raw archive:

```powershell
python scripts\acquire_urbanev.py
```

Kiểm tra toàn bộ input Phase 0–1:

```powershell
python scripts\check_data_paths.py
```

Chạy backend:

```powershell
python -m uvicorn backend.app.main:app --reload
```

Health endpoint: `http://127.0.0.1:8000/health`

Các demo endpoints và interactive schema:

```text
http://127.0.0.1:8000/docs
POST /journey/recommend
POST /route
POST /demo/events/{event_id}/apply
POST /demo/reset
GET  /model/status
GET  /demo/scenarios
GET  /geocoding/autocomplete
GET  /geocoding/details/{place_id}
POST /planned-arrivals/commit
```

## Cài đặt frontend

Kiểm tra `pnpm` trước:

```powershell
pnpm --version
```

Nếu PowerShell báo `pnpm is not recognized`, cài đúng phiên bản dùng cho project rồi
đóng và mở lại terminal:

```powershell
npm install --global pnpm@11.19.0
pnpm --version
```

Sau đó chạy:

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

Frontend mặc định chạy tại `http://127.0.0.1:5173`.

## Chạy và kiểm tra demo

Hướng dẫn chi tiết và expected result: [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md).

### 1. Chuẩn bị environment

Chạy tại repository root:

```powershell
Copy-Item .env.example .env
Copy-Item frontend\.env.example frontend\.env.local
```

Điền hai key khác nhau:

- `.env` → `GOONG_API_KEY`: REST key dùng cho Places và Directions ở backend.
- `frontend/.env.local` → `VITE_GOONG_MAPTILES_KEY`: Maptiles key dùng để render Goong map.

Không dùng REST key cho biến `VITE_*` và không commit hai file environment này.

### 2. Khởi động hai service

Terminal 1 — backend:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend, chạy từ repository root:

```powershell
pnpm --dir frontend dev --host 127.0.0.1
```

Nếu terminal đang đứng sẵn trong thư mục `frontend`, dùng lệnh tương đương sau (không
thêm `--dir frontend` lần nữa):

```powershell
pnpm dev --host 127.0.0.1
```

Fallback tạm thời khi chưa cài được `pnpm` nhưng đã có Node.js/npm:

```powershell
npm --prefix frontend install --no-package-lock
npm --prefix frontend run dev -- --host 127.0.0.1
```

Project vẫn ưu tiên `pnpm` để cài dependency đúng theo `frontend/pnpm-lock.yaml`.

Mở:

- Frontend: `http://127.0.0.1:5173`
- Backend health: `http://127.0.0.1:8000/health`
- API documentation: `http://127.0.0.1:8000/docs`

Phải dùng cùng hostname `127.0.0.1`; nếu mở frontend bằng `localhost`, cập nhật
`CORS_ORIGINS` tương ứng rồi restart backend.

### 3. Smoke test đề xuất

1. **Normal journey:** giữ nguyên scenario, nhấn **Tìm trạm phù hợp**. Kiểm tra có ranked
   candidates, route trên map và station detail.
2. **Địa điểm động:** nhập `Cho Ben Thanh`, chọn một gợi ý Goong rồi tìm lại. Kiểm tra route
   và detour thay đổi; request live có thể cần vài giây.
3. **Low-SOC:** chọn `Low-SOC journey`. Kiểm tra vẫn có candidate an toàn và danh sách loại
   có lý do phương tiện không đủ pin để tới.
4. **Congestion:** chọn `Congestion triggers reranking`, chạy một lần khi chưa bật event, sau đó
   bật event và chạy lại. La Vela phải mất hạng đầu vì thời gian chờ tăng.
5. **Port outage:** reset, chọn `La Vela outage triggers reroute`, bật event rồi tìm. La Vela
   phải bị loại vì offline và recommendation đầu tiên phải đổi.
6. **Planned arrival:** chọn một recommendation, nhấn **Xác nhận tuyến đến trạm**, kiểm tra ETA
   xuất hiện, sau đó thử **Hủy planned arrival**.
7. Nhấn **Reset demo** trước khi chạy lại scenario để xóa event và planned-arrival runtime.

Banner `persistence fallback` là trạng thái dự kiến vì Phase 04 chưa có model artifact, không
phải lỗi khởi động. Nếu thiếu Maptiles key hoặc Goong map lỗi lúc load, frontend tự chuyển sang
Leaflet + OpenStreetMap. Fixed demo scenarios vẫn dùng route cache khi REST key/routing live lỗi.

## Kiểm tra

Từ repository root:

```powershell
pytest
ruff check backend
python scripts\validate_static_data.py
python scripts\validate_phase1_data.py
```

Backend hiện có unit tests cho schema/repository và các phép tính Phase 05. Dữ liệu domain
được validate khi FastAPI application khởi tạo; sai capacity hoặc thiếu runtime status sẽ làm
backend fail sớm.

Từ `frontend/`:

```powershell
pnpm lint
pnpm test
pnpm build
```

Phase 08 dùng backend thật khi chạy ứng dụng; API chỉ được mock trong unit/component tests.
Origin/destination có thể chọn từ Goong Places. Tọa độ của demo scenario vẫn dùng route cache;
tuyến tùy chọn dùng Goong Directions và tự fallback sang OSRM.

## Cấu hình

Sao chép `.env.example` thành `.env`. Không commit `.env` hoặc API key thật.

- `GOONG_API_KEY`: REST key đặt trong `.env` ở repository root; Phase 7 dùng cho
  Directions/Distance Matrix và collector dùng cho Places. Không đưa key này vào biến `VITE_*`.
- `DATA_DIR`: thư mục data, mặc định `data`.
- `MODEL_ARTIFACT_PATH`: model occupancy, chưa tồn tại trước Phase 04. Định dạng artifact và
  cách bàn giao: [`docs/ML_INTEGRATION.md`](docs/ML_INTEGRATION.md).
- `MODEL_PREPROCESSOR_PATH`, `MODEL_META_PATH`: artifact phụ của Phase 04.
- `WAIT_SCORING_CAP_MIN`: wait hữu hạn dùng để score station overload/offline.
- `ROUTING_TIMEOUT_S`: timeout cho Goong/OSRM live routing.
- `RECOMMEND_MAX_*`, `RECOMMEND_SOC_RISK_BUFFER`: fixed normalization thresholds;
  recommendation không dùng min-max theo candidate set.
- `DEMO_MODE`: bật dữ liệu/scenario demo.

Frontend dùng file riêng vì Vite không đọc `.env` ở repository root:

```powershell
Copy-Item frontend\.env.example frontend\.env.local
```

- `VITE_API_BASE_URL`: backend URL dùng cho frontend.
- `VITE_GOONG_MAPTILES_KEY`: Maptiles Key hiển thị Goong map; key này được gửi tới browser
  và phải giới hạn theo domain. Nó không thay thế `GOONG_API_KEY` của backend.

## Khi bổ sung trạm

Sau khi promote candidate vào `stations.geojson`, cập nhật/tái sinh runtime và queue assumptions,
thêm route của mọi trạm public vào `config/demo_routes.json`, rồi chạy lại
`scripts/cache_demo_routes.py`. Static validator và Phase 01 validator sẽ fail nếu fixed
scenario không còn đủ route coverage.
