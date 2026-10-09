# Kế hoạch hoàn thiện Backend theo kế hoạch gốc

**Cập nhật:** 2026-10-09  
**Trạng thái:** Kế hoạch thực thi; chưa phải kết quả nghiệm thu.  
**Mục tiêu:** Hoàn thiện các phần C (Database), D (Backend) và phần kiểm thử liên quan ở [kế hoạch Rule-Based-AI](Rule-Based-AI-Ke-hoach-trien-khai.md). [Bộ Phase 00–11](PHASE_INDEX.md) tiếp tục được dùng để theo dõi kết quả đã đạt, nhưng `RELEASE PASS` chỉ được xét sau khi các chức năng và kiểm định của kế hoạch gốc hoàn tất.

## 1. Phạm vi và phân công

- **Cộng sự phụ trách dữ liệu cho dự báo:** làm sạch/chia tập UrbanEV và chuẩn bị dữ liệu, metadata, báo cáo chất lượng theo [Phase 03](PHASE_03_URBANEV_PREPROCESSING.md). Kế hoạch Backend này không bao gồm việc tạo hoặc sửa dữ liệu huấn luyện đó.
- **Backend phụ trách:** hợp đồng dữ liệu với phần dự báo; tích hợp và vận hành model/artifact được bàn giao; API tìm kiếm, trip/GPS/re-plan, trạng thái trạm, cập nhật thời gian thực, chống dồn tải và kiểm thử tích hợp.
- **Huấn luyện và đánh giá model:** [Phase 04](PHASE_04_OCCUPANCY_MODEL.md) vẫn là công việc bắt buộc; người phụ trách artifact cần được chốt với cộng sự. Backend chỉ đánh dấu tích hợp model hoàn thành khi artifact, metadata và metrics đã được bàn giao và kiểm chứng.
- **Trong lúc chờ model:** giữ `prediction_source=persistence` và Erlang C có nhãn rõ ràng. Không đánh dấu model hoặc release gate là `PASS` dựa trên dữ liệu synthetic/demo.

## 2. Hiện trạng làm mốc

- PostgreSQL/PostGIS đã phục vụ danh mục trạm, cổng, xe, trạng thái hiện tại, planned arrivals và arrival rate; recommendation đã lọc ứng viên bằng PostGIS. Các phần chính: `backend/app/catalog_repository.py`, `backend/app/arrival_rate_repository.py`, `backend/app/planned_arrival_repository.py`, `backend/app/domain/recommendation.py`.
- Backend đang có `/journey/recommend` dựa trên scenario, route cache và điểm có trọng số; chưa có hai API tìm kiếm tổng quát `/search/stations`, `/search/route` theo kế hoạch gốc.
- Forecast hiện là persistence fallback; `OccupancyForecastService` chưa load model artifact thật. Wait estimator hiện dùng Erlang C, chưa trả phân phối Markov.
- Schema `predictions`, `trips`, `trip_positions`, `trip_events`, `app_config` đã có; các API/job tương ứng của kế hoạch gốc chưa được triển khai. `data_platform/compose.yaml` hiện chỉ khai báo PostgreSQL/PostGIS.
- Event demo vẫn là overlay trong bộ nhớ. Dữ liệu trạng thái/queue mới bổ sung cho nhiều trạm là synthetic; phải giữ nguồn dữ liệu hiển thị rõ.

## 3. Những hợp đồng phải chốt trước khi mở rộng

| Chủ đề | Kế hoạch gốc | Hiện tại trong Phase/code | Quyết định cho lộ trình này |
| --- | --- | --- | --- |
| Horizon occupancy | `+5, +10, +15, +20, +25, +30` phút | [Phase 04](PHASE_04_OCCUPANCY_MODEL.md) và service hiện hướng tới `+5/+10/+15` | API và DB hỗ trợ đủ sáu mốc; artifact được bàn giao phải khai báo chính xác các mốc hỗ trợ. Nếu model chỉ có ba mốc, các mốc còn lại trả fallback có nhãn cho tới khi có model tương ứng. |
| Thời gian chờ | Phân phối Markov, `P(W>0)`, `E[W]`, `W90` | [Phase 06](PHASE_06_BACKEND_FORECAST_WAIT.md) dùng Erlang C cho một ước lượng | Giữ Erlang C làm baseline; thêm Markov sau khi có dữ liệu mô phỏng/ground truth để hiệu chỉnh và đánh giá. Không gắn nhãn Markov cho output Erlang C. |
| Xếp hạng | Tổng phút đi + chờ + sạc + đi tiếp | `fixed_threshold_weighted_sum` trong `backend/app/domain/recommendation.py` | Tạo hợp đồng tìm kiếm mới xếp theo `totalMin` tăng dần; endpoint demo cũ tiếp tục phục vụ regression cho tới khi Frontend chuyển sang hợp đồng mới. |
| Hành trình | Tìm kiếm → chọn trạm → GPS → re-plan → kết thúc | Planned arrival và event demo; chưa có trip service/API | Trip là thực thể lưu bền trong PostgreSQL; planned arrival gắn với vòng đời trip. |

**Việc đầu tiên:** cập nhật hợp đồng request/response và quyết định nguồn dữ liệu cho từng trường trong [data contract](SMART_EV_JOURNEY_DATA_CONTRACT_MVP.md) trước khi thay API. Kế hoạch gốc dùng SOC dạng phần trăm và `{lat,lng}`, code demo đang dùng SOC `[0,1]` và `{lat,lon}`; adapter ở ranh giới API phải quy đổi tường minh.

## 4. Các mốc thực thi

### M0 — Hợp đồng API và bàn giao dự báo

- [ ] Chốt schema `/api/v1` cho config, danh mục, availability, tìm kiếm, trip, nội bộ và WebSocket; quy định đơn vị, timezone, mã lỗi, `updatedAt` và version.
- [ ] Chốt payload bàn giao model: artifact, preprocessor, metadata, feature order, lookback 12 bước/5 phút, horizon, model version, metrics, nguồn dữ liệu và fallback.
- [ ] Chốt nguồn `queue_length`, session duration, arrival rate cho 102 trạm; xác định khi nào dữ liệu bị coi là stale/unknown.
- [ ] Cập nhật [data contract](SMART_EV_JOURNEY_DATA_CONTRACT_MVP.md), [Phase 04](PHASE_04_OCCUPANCY_MODEL.md), [Phase 06](PHASE_06_BACKEND_FORECAST_WAIT.md) và mô tả OpenAPI trước khi đổi Frontend.

**File dự kiến:** `backend/app/domain/phase7_models.py`, `backend/app/config.py`, `backend/app/api.py`, các tài liệu trên.  
**Kiểm chứng:** bảng ánh xạ mọi trường API ↔ DB/model có đơn vị và nguồn; test schema cho lỗi đầu vào và tương thích route demo.

### M1 — Trạng thái trạm có thể cập nhật

- [ ] Thêm API nội bộ có API key để nhận batch trạng thái cổng; ghi `port_status` và `port_status_history` trong cùng transaction, bỏ qua bản tin cũ hơn `reported_at` hiện tại.
- [ ] Job đánh dấu trạng thái quá hạn là unknown; availability và recommendation không coi unknown là cổng trống.
- [ ] Hoàn thiện arrival rate/queue/session duration cho các trạm được phép đề xuất; nếu thiếu input, trả lý do loại trạm thay vì ước lượng không có căn cứ.
- [ ] Thêm `GET /config`, danh sách trạm theo bbox, availability hiện tại, chi tiết theo connector và danh sách ports; xác định màu từ `app_config`.

**File hiện có:** `backend/app/api.py`, `backend/app/catalog_repository.py`, `backend/app/arrival_rate_repository.py`, `backend/app/domain/recommendation.py`, `data_platform/migrations/versions/0001_initial_schema.py`, `data_platform/migrations/versions/0004_trips_config.py`. Migration mới chỉ tạo nếu schema hiện tại không biểu diễn được hợp đồng đã chốt.  
**Kiểm chứng:** cập nhật một cổng qua API làm thay đổi status/availability; history có đúng một event; tin cũ không ghi đè tin mới; trạng thái stale chuyển unknown.

### M2 — Tìm kiếm trạm và tuyến tổng quát

- [ ] Thêm `POST /search/stations` và `POST /search/route` nhận điểm đi/đến, xe và mức pin tùy ý; không yêu cầu `scenario_id`.
- [ ] Lọc trạm đang mở, quyền truy cập, chuẩn sạc, bán kính pin an toàn và hành lang tuyến trước routing; dùng quãng đường thật để kiểm tra lại reachability.
- [ ] Tính ETA, wait ở mốc dự báo gần nhất, charge time và `totalMin`; trả `enough`, `needCharge`, `fallback`, `OUT_OF_RANGE` hoặc `NO_ROUTE` đúng trường hợp.
- [ ] Lưu kết quả `searchId` trong 10 phút để tạo trip; áp dụng giới hạn tần suất cho API tìm kiếm.

**File hiện có:** `backend/app/domain/recommendation.py`, `backend/app/domain/routing.py`, `backend/app/domain/services.py`, `backend/app/domain/phase7_models.py`, `backend/app/catalog_repository.py`, `backend/app/api.py`. **File mới dự kiến:** repository/cache cho search result và test API tìm kiếm.  
**Kiểm chứng:** test hành trình đủ pin, cần sạc, pin quá thấp, trạm private/incompatible/offline, không có route và tọa độ ngoài vùng demo; thứ hạng đúng theo `totalMin`.

### M3 — Trip, GPS và re-plan

- [ ] Tạo trip từ `searchId`; lưu tuyến, trạm chọn, ETA, phase và `route_version` trong PostgreSQL.
- [ ] Thêm position ping: bỏ qua timestamp cũ, ghi vị trí/quãng đường, ước tính pin, cập nhật ETA và phase `to_station → at_station → to_destination → arrived`.
- [ ] Thêm accept/decline/cancel và sửa pin; ghi `trip_events`; đồng bộ planned arrival khi đổi trạm, tới trạm hoặc hủy.
- [ ] Re-plan khi lệch tuyến, ETA tăng, trạm không còn dùng được hoặc pin không đủ; áp dụng cooldown/hysteresis và loại trạm đã từ chối.

**Schema hiện có:** `data_platform/migrations/versions/0004_trips_config.py`, `data_platform/migrations/versions/0005_planned_arrivals.py`. **File mới dự kiến:** `backend/app/trip_repository.py`, `backend/app/domain/trips.py`, test vòng đời trip; mở rộng `backend/app/api.py`.  
**Kiểm chứng:** restart Backend vẫn đọc được trip; GPS gửi lặp/cũ không làm lùi trạng thái; re-plan chỉ tăng version khi đổi tuyến; trip kết thúc giải phóng planned arrival.

### M4 — Model prediction và phân phối wait

- [ ] Khi nhận artifact: xác minh metadata/feature contract, load ở startup, chạy inference sáu mốc được hỗ trợ và ghi `predictions` kèm `run_at`, `prediction_source`, `model_version`.
- [ ] Job dự báo mỗi 5 phút; API availability tương lai đọc lượt dự báo mới nhất, dữ liệu thiếu/quá hạn trả unknown hoặc fallback có nhãn.
- [ ] Giữ persistence làm baseline và fallback; test output trong `[0,1]`, đánh giá theo từng horizon và ghi lý do chọn model.
- [ ] Xây Markov và hiệu chỉnh theo mô phỏng khi có ground truth wait; trả `P(W>0)`, `E[W]`, `W90`; so sánh với Erlang C trước khi dùng để xếp hạng.

**File hiện có:** `backend/app/domain/forecasting.py`, `backend/app/domain/wait_estimation.py`, `backend/app/api.py`, `backend/app/main.py`, `data_platform/migrations/versions/0002_predictions.py`. **Đầu vào từ cộng sự:** dữ liệu/metadata Phase 03; artifact và evaluation Phase 04 từ người phụ trách model.  
**Kiểm chứng:** artifact load trong process mới; cùng input/model version cho kết quả lặp lại; lỗi model tự rơi về persistence có nhãn; phân phối wait qua các ca biên và được đối chiếu với ground truth mô phỏng.

### M5 — Chống dồn tải và cập nhật thời gian thực

- [ ] Liên kết planned arrivals/soft commitments với trip; tính tải dự kiến khi nhiều người cùng chọn một trạm, tránh đếm trùng cam kết của chính trip.
- [ ] Hiệu chỉnh ranking khi tải dự kiến tăng; đo hiệu quả bằng mô phỏng nhiều người dùng trước khi bật mặc định.
- [ ] Thêm WebSocket subscribe/unsubscribe theo bbox, station, trip; phát `station.updated`, `prediction.refreshed`, `trip.reroute`.
- [ ] Bổ sung Redis cho search cache, trạng thái nóng và pub/sub; PostgreSQL vẫn là nguồn lưu bền. Thêm job đóng trip bỏ dở và phục hồi sau restart.

**File hiện có:** `backend/app/planned_arrival_repository.py`, `backend/app/domain/recommendation.py`, `data_platform/compose.yaml`; **file mới dự kiến:** realtime/cache/job modules và test đồng thời.  
**Kiểm chứng:** hai yêu cầu đồng thời không tạo cam kết trùng; tăng planned load không làm dự báo wait giảm vô lý; client reconnect nhận snapshot mới; backend restart không mất trip/cam kết đã persist.

### M6 — Kiểm thử hệ thống và tài liệu vận hành

- [ ] Unit/property/API tests cho pin, occupancy, wait, ranking, trip transitions và re-plan hysteresis.
- [ ] E2E từ tìm kiếm → chọn trạm → GPS → sự cố → re-plan → tới đích; test đường fallback khi model/routing/Redis không sẵn sàng.
- [ ] Load test theo mục F của kế hoạch gốc, ghi p95 và cấu hình máy/test data; kiểm định model theo horizon, reliability và stress scenarios.
- [ ] Docker Compose cho stack cần thiết, CI lint/test, clean setup từ checkout mới; cập nhật README, Phase gates và báo cáo kết quả.

**File liên quan:** `backend/tests/`, `tests/`, `README.md`, `data_platform/compose.yaml`, [Phase 11](PHASE_11_FINAL_DEMO_RELEASE.md) và báo cáo trong `data_platform/data/validation/`.  
**Kiểm chứng:** các gate có lệnh chạy và kết quả lưu lại; không còn blocker trong luồng chính; chỉ ghi `RELEASE PASS` khi toàn bộ điều kiện đã được xác nhận.

## 5. Thứ tự và điều kiện bắt đầu

```text
M0 → M1 → M2 → M3
  ↘ nhận dữ liệu/artifact từ cộng sự → M4
M3 + M4 → M5 → M6
```

- M0–M3 có thể thực hiện ngay với PostgreSQL và persistence/Erlang C hiện tại. M2/M3 phải công khai nguồn forecast/wait trong response để không gây hiểu nhầm về model.
- M4 phụ thuộc bàn giao dữ liệu, model artifact và metrics; phần adapter/schema/test bằng fixture có thể chuẩn bị trước.
- M5 chỉ bật chính sách chống dồn tải sau khi có test mô phỏng; realtime và cache có thể phát triển sau M3 mà không chờ Markov.
- Mỗi mốc chỉ đánh dấu hoàn thành khi checklist và kiểm chứng của chính mốc đó đều đạt; thay đổi phạm vi phải được cập nhật ở file này và tài liệu nguồn liên quan.
