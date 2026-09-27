# Smart EV Journey — Demo Guide

Hướng dẫn này áp dụng cho trạng thái sau Phase 09 trên nhánh `demo/backend-first`.
Occupancy forecast hiện dùng persistence fallback vì Phase 03–04 chưa hoàn thành.

## 1. Điều kiện cần

- Python 3.12.
- Node.js 20.19+ hoặc 22.12+.
- pnpm 11.19+.
- Goong REST key cho Places và Directions nếu muốn thử địa điểm tùy chọn.
- Goong Maptiles key nếu muốn dùng Goong làm bản đồ chính.

Kiểm tra package manager:

```powershell
pnpm --version
```

Nếu PowerShell báo `pnpm is not recognized`, cài phiên bản dùng cho project rồi mở lại
terminal:

```powershell
npm install --global pnpm@11.19.0
pnpm --version
```

Nếu chưa cài dependencies, từ repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.txt
pnpm --dir frontend install --frozen-lockfile
```

## 2. Cấu hình key

```powershell
Copy-Item .env.example .env
Copy-Item frontend\.env.example frontend\.env.local
```

Trong `.env`:

```dotenv
GOONG_API_KEY=your_rest_key
```

Trong `frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_GOONG_MAPTILES_KEY=your_maptiles_key
```

`GOONG_API_KEY` là secret backend. Không đặt key này vào biến `VITE_*`. Maptiles key được gửi
tới browser nên cần giới hạn domain trong Goong Console. `.env` và `.env.local` đã được ignore.

## 3. Kiểm tra dữ liệu và test suite

Tại repository root:

```powershell
.\.venv\Scripts\python.exe scripts\check_data_paths.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check backend
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
```

Baseline sau Phase 09:

- backend: 47 tests pass;
- frontend: 8 tests pass;
- Ruff, ESLint, TypeScript và Vite build pass.

Build có thể cảnh báo chunk của map SDK lớn hơn 500 kB. Đây là cảnh báo tối ưu hiệu năng,
không chặn demo.

## 4. Khởi động

Mở hai PowerShell terminal tại repository root.

Terminal 1:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
pnpm --dir frontend dev --host 127.0.0.1
```

Lệnh trên phải chạy tại repository root. Nếu terminal đang ở `frontend`, chạy:

```powershell
pnpm dev --host 127.0.0.1
```

Nếu chưa thể cài `pnpm`, có thể dùng npm làm fallback cho demo:

```powershell
npm --prefix frontend install --no-package-lock
npm --prefix frontend run dev -- --host 127.0.0.1
```

Fallback này không tạo `package-lock.json`; luồng chuẩn của project vẫn dùng
`frontend/pnpm-lock.yaml`.

Kiểm tra preflight:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/model/status
```

Kết quả health phải có `status: ok`. Model status hiện trả `prediction_source: persistence` và
flag `PHASE_04_ARTIFACTS_UNAVAILABLE`; frontend cũng hiển thị banner tương ứng.

Mở `http://127.0.0.1:5173`. Không đổi sang `localhost` trừ khi đã thêm origin đó vào
`CORS_ORIGINS`.

## 5. Kịch bản kiểm tra bằng UI

### A. Normal journey và route cache

1. Chọn `Normal journey`.
2. Giữ điểm đi/đến của scenario.
3. Nhấn **Tìm trạm phù hợp**.

Expected:

- Lavida và Deutsches Haus là ranked candidates trong trạng thái mặc định;
- Audi bị loại vì private access;
- map có route geometry và ba station markers;
- station detail hiển thị connector, capacity, queue, occupancy, wait và charging time;
- route có flag/cache source ở API; demo không cần live routing cho tọa độ scenario.

### B. Địa điểm tùy chọn qua Goong

1. Trong **Điểm đi**, nhập `Cho Ben Thanh`.
2. Chờ dropdown rồi chọn `Chợ Bến Thành`.
3. Giữ điểm đến hoặc chọn một gợi ý Goong khác.
4. Nhấn **Tìm trạm phù hợp**.

Expected:

- nút tìm bị disable cho đến khi chọn một suggestion có tọa độ;
- backend gọi Goong Directions, hoặc OSRM nếu Goong routing lỗi;
- route và detour thay đổi theo tọa độ mới;
- URL/browser không chứa `GOONG_API_KEY`.

Live smoke result đã xác minh:

- Chợ Bến Thành → Phú Nhuận direct: 5.879 m / 1.129 giây;
- qua Lavida: detour khoảng 41,3 phút;
- qua Deutsches Haus: detour khoảng 1,9 phút.

Live result có thể thay đổi khi routing data thay đổi; không dùng các số này làm assertion cứng.

### C. Low SOC và compatibility

1. Chọn `Low-SOC journey`.
2. Nhấn **Tìm trạm phù hợp**.
3. Giảm SOC hiện tại gần mức reserve và chạy lại nếu muốn kiểm tra no-reachable.
4. Chọn `Demo GB/T City EV` nếu muốn kiểm tra no-compatible.
5. Mở danh sách **trạm đã bị loại**.

Expected:

- candidate chỉ tồn tại khi arrival SOC không vi phạm reserve;
- GB/T vehicle không được ghép với trạm chỉ có CCS2/Type2;
- UI hiển thị lý do loại thay vì lỗi trắng hoặc recommendation không an toàn.

### D. Port outage và reranking

1. Nhấn **Reset demo**.
2. Chọn `Lavida outage triggers reroute`.
3. Bật **Áp dụng event của kịch bản**.
4. Nhấn **Tìm trạm phù hợp**.

Expected:

- marker/status Lavida chuyển offline;
- Lavida xuất hiện trong exclusions với lý do offline;
- Deutsches Haus trở thành recommendation đầu tiên;
- UI refresh mà không reload toàn trang.

### E. Planned arrival

1. Chọn một recommendation.
2. Nhấn **Xác nhận tuyến đến trạm**.
3. Kiểm tra trạng thái **Đã xác nhận tuyến** và ETA.
4. Nhấn **Hủy planned arrival**.

Có thể kiểm tra state trực tiếp:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/planned-arrivals
```

## 6. Kiểm tra fallback

### Map fallback

1. Để trống `VITE_GOONG_MAPTILES_KEY`.
2. Restart frontend.

Expected: chip provider hiển thị `Leaflet · OSM fallback`; journey và recommendation vẫn chạy.

### Route-cache fallback

1. Dừng backend.
2. Để trống `GOONG_API_KEY` trong `.env` và restart backend.
3. Chạy lại `Normal journey` với tọa độ scenario.

Expected: fixed scenario vẫn hoàn thành bằng route cache. Autocomplete chỉ còn demo-location
fallback và hành trình tùy chọn cần OSRM; nếu cả Goong/OSRM không dùng được, backend trả 503 rõ.

Khôi phục key sau khi kiểm tra.

### Reset runtime

Trong UI dùng **Reset demo**, hoặc:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/demo/reset
```

Reset xóa event đã apply và khôi phục planned arrivals về snapshot ban đầu.

## 7. Troubleshooting

- **CORS error:** mở đúng `http://127.0.0.1:5173`, hoặc thêm frontend origin vào
  `CORS_ORIGINS` rồi restart backend.
- **Có map nhưng không autocomplete:** Maptiles key và REST key là hai key khác nhau; kiểm tra
  `GOONG_API_KEY` trong root `.env`.
- **Autocomplete có kết quả nhưng nút tìm vẫn disable:** phải click một suggestion để lấy tọa độ.
- **Goong map không hiện:** kiểm tra `VITE_GOONG_MAPTILES_KEY`, restart Vite; OSM fallback vẫn
  phải xuất hiện nếu Goong init thất bại.
- **Không có recommendation:** mở exclusions để xem private/offline/incompatible/low-SOC reason.
- **Port 8000 hoặc 5173 đã được dùng:** dừng process demo cũ trước khi chạy lại.
- **Thay environment nhưng không có tác dụng:** backend và Vite chỉ đọc environment khi start;
  restart service tương ứng.

## 8. Dừng demo

Nhấn `Ctrl+C` trong cả hai terminal. Không cần chỉnh hoặc xóa JSON runtime sau khi demo; state
event và planned arrival là in-memory và sẽ reset khi backend restart.
