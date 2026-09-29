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
Phase 03–04 vẫn deferred và chưa được đánh dấu hoàn thành, vì vậy Phase 06 chỉ đạt
demo gate chứ chưa đạt release gate.

ML pipeline, feature contracts và hướng dẫn chạy cloud: [`ml/README.md`](ml/README.md).
Phase 04 chưa có model release; không đưa UrbanEV/model artifact vào production trước khi
đội chốt dữ liệu thật theo data-gap analysis và đánh giá temporal backtest.

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
3. **Low-SOC:** chọn `Low-SOC journey`. Kiểm tra arrival SOC không thấp hơn reserve; có thể
   giảm SOC gần mức reserve để xem lý do `Không đủ SOC dự phòng`.
4. **Port outage:** chọn `Lavida outage triggers reroute`, bật event rồi tìm. Lavida phải bị
   loại vì offline và Deutsches Haus trở thành candidate đầu tiên.
5. **Planned arrival:** chọn một recommendation, nhấn **Xác nhận tuyến đến trạm**, kiểm tra ETA
   xuất hiện, sau đó thử **Hủy planned arrival**.
6. Nhấn **Reset demo** trước khi chạy lại scenario để xóa event và planned-arrival runtime.

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
- `MODEL_ARTIFACT_PATH`: model occupancy, chưa tồn tại trước Phase 04.
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

Sau khi promote candidate vào `stations.geojson`, cập nhật/tái sinh runtime và queue assumptions; chỉ cache route cho trạm thực sự tham gia recommendation hoặc demo. Chạy lại static validator và Phase 01 validator trước khi tiếp tục.
