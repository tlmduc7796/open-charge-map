# Smart EV Journey — Hợp đồng backend để chuyển từ demo sang release

**Trạng thái:** Các hợp đồng backend/frontend trong workspace đã được triển khai; mục 9–11 ghi nhận tiến độ, tiêu chí kiểm chứng và các gate vận hành còn thiếu trước release.
**Phạm vi tài liệu:** Quy ước dữ liệu, API, response hành trình, tiêu chí xếp hạng và trạng thái thực thi hiện tại; các mục đã triển khai trong code không còn chỉ là đề xuất.

Tài liệu này bổ sung hợp đồng MVP hiện tại. Hợp đồng MVP vẫn dùng được cho demo; khi triển khai release, các API và model mới cần tuân theo các quyết định dưới đây. Dữ liệu synthetic/runtime phải luôn phân biệt với dữ liệu thực và dữ liệu suy ra.

## 1. Quy ước chung

| Khái niệm | Quy ước |
|---|---|
| ID | Chuỗi ổn định; ID từ nhà cung cấp lưu riêng với ID nội bộ |
| Timestamp | ISO-8601 có timezone; lưu UTC, chuyển sang `Asia/Ho_Chi_Minh` ở giao diện |
| Tọa độ | WGS84 / EPSG:4326; thứ tự GeoJSON là `[longitude, latitude]` |
| Khoảng cách | mét |
| Tốc độ/công suất | kW |
| Năng lượng | kWh |
| Thời gian tuyến | giây trong dữ liệu routing; phút trong breakdown hành trình |
| SOC và occupancy ratio | số thực từ `0` đến `1` |
| Nguồn | `station_provider`, `map_real`, `synthetic`, `urbanev_real`, `model`, `routing_api`, `derived`, `runtime` |

Mỗi dữ liệu có thay đổi theo thời gian cần có `observed_at` hoặc `generated_at`, `data_source` và `is_stale`/quy tắc stale tương ứng. Không diễn giải dữ liệu synthetic, persistence fallback hoặc dữ liệu cũ thành trạng thái thực.

## 2. Các entity chuẩn

### 2.1 Trạm và cổng

**Station** cần có: `station_id`, `provider_station_id` (nullable), `name`, `address`, `location`, `operator`, `access`, `opening_hours`, `is_active`, `source`, `source_updated_at`.

**Port** cần có: `port_id`, `station_id`, `connector_type`, `current_type` (`AC`/`DC`), `max_power_kw`, `label`, `source`.

Trạng thái cổng là dữ liệu riêng theo snapshot, không ghi đè cấu hình tĩnh:

```json
{
  "port_id": "PORT_01",
  "status": "available",
  "session_started_at": null,
  "estimated_release_at": null,
  "observed_at": "2026-10-09T08:30:00Z",
  "data_source": "synthetic"
}
```

`status` thuộc `available | charging | out_of_service | unknown`. Telemetry chấp nhận `offline` như alias tương thích cho `out_of_service`. Snapshot trạm gồm `station_id`, `observed_at`, danh sách trạng thái cổng, `queue_length` (nullable nếu không quan sát được), nguồn và cờ stale. Invariants: số cổng theo trạng thái không vượt số cổng cấu hình; occupancy ratio null khi không có cổng hoạt động. Cổng `unknown` không được tính là cổng hoạt động; nếu có cổng chưa rõ trạng thái, DES không phát wait estimate và recommendation mang cờ/lý do ổn định.

### 2.2 Hồ sơ xe

Giữ các trường hiện có và chuẩn hóa thành: `vehicle_id`, `make`, `model`, `variant`, `battery_capacity_kwh`, `usable_battery_kwh`, `consumption_wh_km`, `max_ac_power_kw`, `max_dc_power_kw`, `ac_connectors`, `dc_connectors`, `reserve_soc`, `default_target_soc`, `charging_efficiency`, `source`, `synthetic_fields`.

Không giả định `battery_capacity_kwh` bằng dung lượng khả dụng nếu `usable_battery_kwh` đã có. Dữ liệu giả định phải được gắn provenance.

### 2.3 Occupancy forecast

Mỗi điểm dự báo gắn với trạm, thời điểm đích và phiên bản model:

```json
{
  "station_id": "ST001",
  "generated_at": "2026-10-09T08:30:00Z",
  "target_at": "2026-10-09T08:45:00Z",
  "horizon_min": 15,
  "predicted_occupancy_ratio": 0.75,
  "predicted_occupied_ports": 6.0,
  "predicted_available_ports": 2.0,
  "prediction_source": "persistence",
  "model_version": null,
  "flags": ["PERSISTENCE_FALLBACK"]
}
```

Horizon sản phẩm MVP: `5, 10, 15, 20, 25, 30` phút. Số cổng dự báo là giá trị thực để giữ độ phân giải của mô hình; số cổng hiển thị có thể làm tròn, nhưng quyết định xếp hạng dùng giá trị chưa làm tròn. Khi trạm offline, ratio là null và không được trình bày là dự báo occupancy bình thường.

### 2.4 Wait estimate

Kết quả chờ phải biểu diễn được cả phân phối và các tóm tắt dùng trong sản phẩm:

```json
{
  "station_id": "ST001",
  "evaluation_at": "2026-10-09T09:00:00Z",
  "probability_wait": 0.4,
  "expected_wait_min": 6.0,
  "wait_p90_min": 18.0,
  "method": "markov",
  "data_source": "synthetic",
  "flags": []
}
```

`expected_wait_min` dùng để xếp hạng; `wait_p90_min` và `probability_wait` phục vụ hiển thị rủi ro. Nếu chưa có mô hình phân phối được kiểm định, backend phải công bố phương pháp/nguồn và không gọi kết quả là ground truth.

### 2.5 Journey và recommendation

Request hành trình chuẩn gồm `origin`, `destination`, `vehicle_id`, `initial_soc`, `target_soc` (nullable, mặc định theo xe), `departure_at`, cùng lựa chọn cho phép sai lệch tuyến nếu sản phẩm cần.

Kết quả cần có:

- `journey_id` (khi đã lưu), `generated_at`, `request`, `direct_route`.
- `outcome`: `direct_no_charge | charging_stops | no_reachable_station`. New recommendation requests still rank charging stations when direct travel can meet reserve SOC; `direct_no_charge` remains for legacy snapshots only.
- Danh sách recommendation đã xếp hạng, mỗi mục có station, route/legs, compatibility, arrival SOC, dự báo/chờ, lượng điện và thời gian sạc, tổng thời gian, thành phần thời gian, nguồn/cờ và lý do.
- Danh sách ứng viên bị loại kèm `reason_codes` có tính ổn định.
- `ranking_policy_version` để có thể tái hiện thứ tự xếp hạng.

Mỗi recommendation tối thiểu trả `drive_to_station_min`, `wait_expected_min`, `wait_p90_min`, `charge_min`, `drive_station_to_destination_min`, `total_time_min`, `arrival_soc`, `soc_after_charge`, `predicted_free_ports`, `prediction_source`, `model_version` khi dùng model, `wait_method`, `flags`. API giữ thêm các tên legacy `estimated_wait_min`, `estimated_charge_min` và `destination_soc` để client/snapshot cũ tương thích; `soc_after_charge` là SOC mục tiêu ngay sau phiên sạc, còn `destination_soc` là SOC ước tính khi tới đích. `predicted_free_ports` là số cổng hoạt động trừ occupancy dự báo, có thể là số thực.

## 3. Tiêu chí xếp hạng đã chốt

### 3.1 Mục tiêu

**Xếp tăng dần theo tổng thời gian dự kiến đến đích**, đúng với kế hoạch sản phẩm:

```text
total_time_min = drive_to_station_min
               + expected_wait_min
               + charge_min
               + drive_station_to_destination_min
```

Với luồng “Tìm trạm” không có điểm đến, bỏ thành phần đi tiếp; xếp theo đi đến trạm + chờ + sạc. Đây là thứ tự xếp hạng chính thức cho release. `wait_score`, `detour_score`, `charging_time_score`, `soc_risk_score` và `final_score` vẫn được trả để tương thích và chẩn đoán; chúng không quyết định `rank`. Contract OpenAPI đánh dấu ý nghĩa này trên các trường score.

### 3.2 Điều kiện khả thi trước khi xếp hạng

Một ứng viên chỉ được xếp hạng khi:

1. Trạm đang hoạt động, có cổng tương thích và có route khả dụng.
2. Xe tới được trạm mà vẫn giữ `reserve_soc`.
3. Sau khi sạc, xe tới được điểm đến với mức SOC dự trữ. Backend phải tính mức SOC tối thiểu cần sau sạc từ năng lượng tuyến sau trạm; nếu vượt `target_soc` người dùng/xe, ứng viên không khả thi trừ khi sản phẩm cho phép nạp cao hơn mục tiêu.
4. Thời gian sạc được tính theo công suất hiệu dụng `min(port.max_power_kw, vehicle.max_*_power_kw)` và dữ liệu sạc có nguồn/giả định rõ.

Ứng viên không đạt điều kiện bị loại với lý do, ví dụ `STATION_OFFLINE`, `NO_COMPATIBLE_CONNECTOR`, `ROUTE_NOT_AVAILABLE`, `INSUFFICIENT_SOC_TO_STATION`, `INSUFFICIENT_SOC_AFTER_CHARGE`.

### 3.3 Tie-break và tính ổn định

Backend sắp xếp theo tổng thời gian trước, sau đó tạo từng nhóm bằng cách đo dung sai `0.1` phút từ ứng viên nhanh nhất chưa được xếp nhóm. Chỉ tie-break bên trong nhóm theo: (1) SOC thấp nhất trên hành trình cao hơn; (2) xác suất phải chờ thấp hơn; (3) `station_id` tăng dần. Dung sai được neo vào ứng viên đầu nhóm để các trường hợp chênh lệch dây chuyền không làm một ứng viên chậm hơn đáng kể nhảy lên trên ứng viên nhanh nhất. `0.1` phút là dung sai số học, không phải ưu tiên sản phẩm. Ghi `ranking_policy_version` cùng kết quả.

Không dùng score chuẩn hóa có trọng số để đảo thứ tự giữa hai ứng viên có tổng thời gian khác nhau. Các chỉ số như detour, SOC risk, wait P90 vẫn trả về để người dùng hiểu lựa chọn và để đánh giá chính sách.

### 3.4 Không đủ pin để tới trạm

Nếu không có ứng viên khả thi, trả `outcome: no_reachable_station`, danh sách lý do loại trạm và một fallback gần nhất nếu tìm được. Fallback chọn theo khoảng cách đường chim bay từ điểm xuất phát trong tập candidate đã xét, trả `straight_line_distance_m` và lý do loại; phải có `is_reachable: false`, không được đưa vào danh sách khuyến nghị khả thi hoặc gán rank như phương án an toàn.

## 4. Route breakdown bắt buộc

Mỗi route có một hoặc nhiều legs với `from`, `to`, `distance_m`, `duration_s`, `geometry` (có thể null nếu nhà cung cấp không trả), `provider`, `retrieved_at` và `flags`. Tối thiểu phân biệt:

- `origin_to_station`;
- `station_to_destination`.

Không suy ra thời gian từng leg bằng tỷ lệ chiều dài geometry nếu route provider có thể cung cấp thời lượng leg thật. Nếu bắt buộc nội suy, đánh dấu `LEG_METRICS_APPROXIMATED`; mục tiêu release là lưu/đọc metrics từng leg từ routing provider.

## 5. Planned arrival và telemetry

Planned arrival biểu diễn **ý định có xác suất**, không phải xe đã có mặt tại queue:

```json
{
  "arrival_id": "ARR_123",
  "journey_id": "JRN_123",
  "station_id": "ST001",
  "eta_at": "2026-10-09T09:00:00Z",
  "eta_window_start": "2026-10-09T08:55:00Z",
  "eta_window_end": "2026-10-09T09:05:00Z",
  "arrival_probability": 0.85,
  "expected_energy_kwh": 24.0,
  "expected_charge_duration_min": 25.0,
  "status": "planned",
  "expires_at": "2026-10-09T09:15:00Z",
  "data_source": "runtime"
}
```

Trạng thái thuộc `planned | cancelled | arrived | expired`. Tất cả thời điểm phải có timezone; ETA window phải chứa ETA và `expires_at` phải sau khi ETA window kết thúc. Arrival chỉ ảnh hưởng tải dự kiến khi `planned`, chưa hết hạn và thuộc cửa sổ đánh giá. Chỉ telemetry xác nhận thực địa mới được đưa vào queue thực tế.

Both `POST /planned-arrivals` and `POST /planned-arrivals/commit` require a client-generated `arrival_id` (1–128 characters). The client must reuse that ID and the original request payload when retrying an uncertain request; the backend returns the existing arrival when the same ID and payload are submitted again, and rejects a conflicting reuse. Cancellation is idempotent: retrying cancellation of an already cancelled arrival returns its cancelled record.

## 6. Quy tắc freshness và thiếu dữ liệu

- Trạng thái cổng phải kèm `observed_at`; cấu hình timeout freshness do server cấu hình. Snapshot quá hạn được trả cờ `STALE_STATUS` và không được diễn giải là realtime.
- Dự báo phải kèm `generated_at`, `target_at`, nguồn và cờ fallback. Không có lịch sử đầu vào thì phải đánh dấu rõ; release model không được âm thầm coi history lặp từ trạng thái hiện tại là quan sát lịch sử.
- Thiếu route hoặc dữ liệu cần cho kiểm tra khả thi thì loại ứng viên với lý do; không tự thay bằng thời gian 0.
- Thiếu wait model có thể dùng fallback được cấu hình, nhưng response phải ghi `method`, `data_source` và `flags`; monitor tỷ lệ fallback.
- `null` có nghĩa là không biết/không áp dụng, không phải 0.

## 7. Phạm vi lưu trữ được suy ra từ hợp đồng

Các entity cần lưu bền vững khi triển khai database: `stations`, `ports`, `connector_types`, `vehicles`, `port_status`/station snapshots, occupancy observations, `predictions`, journeys và legs, recommendation results, planned arrivals, GPS pings, incident reports, re-plan events, model releases/metadata. Redis chỉ là cache/truyền tin; PostgreSQL/PostGIS là nguồn chuẩn, chuỗi thời gian có thể đặt trong TimescaleDB hoặc bảng phân vùng.

Không cần tạo toàn bộ bảng ngay ở bước hiện tại. Bước database cần map từng entity/quan hệ, khóa, unique constraint, index không gian/thời gian, retention và migration từ JSON demo.

## 8. Các khác biệt cần xử lý so với code hiện tại

- `RecommendationItem` có breakdown bốn thành phần thời gian, `total_time_min`, xác suất chờ, P90 chờ và SOC ở đích; rank theo tổng thời gian với tie-break SOC/wait/station ID. P90 hiện là xấp xỉ Erlang C, chưa hiệu chuẩn.
- Goong/OSRM routing uses provider-reported per-leg distance/duration. Release requires an explicit HTTPS `OSRM_BASE_URL` for the operator-managed fallback and refuses the public demo endpoint; development retains the public default. Routing and Goong geocoding GETs use `ROUTING_TIMEOUT_S` and retry at most once for transport errors or HTTP 429/5xx (with `Retry-After` capped at 500 ms); other routing errors move directly to the fallback provider. Demo mode can still use legacy cached waypoint routes with interpolated leg durations and marks them `LEG_METRICS_APPROXIMATED`; release mode bypasses those cache entries, treats live responses without complete requested legs as provider failures, tries the fallback provider, and fails closed if neither provider supplies complete metrics.
- Wait API phân biệt `wait_expected_min` (ước tính tại ETA, điều chỉnh theo occupancy dự báo và queue đã quan sát) với `wait_probability` (xác suất ổn định M/M/c/Erlang C theo tải trạm) và `wait_p90_min` (P90 xấp xỉ Erlang C có current-state floor). Hai metric Erlang C không phải phân phối đã điều kiện hóa theo snapshot ETA; P90 chưa hiệu chuẩn bằng telemetry vận hành. OpenAPI và giao diện phải thể hiện đúng khác biệt này.
- Demo forecasting can construct synthetic history from current occupancy for legacy scenarios. Release serving requires timestamped observed history; when 12 contiguous buckets are unavailable it uses persistence fallback and marks `OBSERVED_HISTORY_UNAVAILABLE`.
- Backend đã có tùy chọn database riêng cho catalog, planned-arrival, telemetry, occupancy history và journey. Schema hiện ở migration `0020_path_safe_ids`; station codes and planned-arrival IDs are constrained to URL-safe path segments; recommendation động được ghi atomically vào `trips` và `journey_recommendations` khi `JOURNEY_STORAGE=database`. Telemetry quan sát tạo bucket occupancy 5 phút; model chỉ nhận đủ 12 bucket liên tục có `data_origin=observed`. Hồ sơ xe lưu riêng dung lượng danh định và khả dụng. Chế độ mặc định vẫn là memory để giữ demo; event overlay và Queue Lab vẫn là mô phỏng trong memory.
- In release mode, synthetic catalog records and recommendation candidates are filtered. Stations are rejected when a source-provider or field-provenance provider label contains `synthetic`, even if its `origin` says observed; the importer, release SQL filter, telemetry guard, and smoke probe enforce this. Vehicle profiles are ineligible when `is_synthetic` is true, `synthetic_fields` is nonempty, or the record/source-field provider contains `synthetic`; the importer, database mapper, API, readiness, recommendation, and smoke probe share this rule. Synthetic/unknown/runtime station snapshots are marked stale in REST and SSE. The release frontend hides their operational counts; demo mode may show simulated counts and labels their source, so demo data is not presented as live operational telemetry. Station details show catalog provider and source update time alongside live-status and forecast provenance.
- Demo-scenario geocoding suggestions and `demo:` place details are available only in demo mode. Autocomplete accepts 2–200 characters; provider place IDs are capped at 256 characters before a details lookup. Release preflight/startup requires `GOONG_API_KEY`, the only configured geocoder; release geocoding returns provider results (including an empty result) and fails with 503 when the configured provider cannot be used. It does not suggest or resolve static demo locations.
- Snapshot telemetry per-port đầy đủ, còn hạn (`REALTIME_TELEMETRY_MAX_AGE_S`) được chuyển thành station status dùng bởi `/stations/{id}/status` và recommendation. Wait capacity và queue có connector detail được giới hạn theo connector tương thích với xe; occupancy tương lai, queue thiếu connector detail và arrival demand vẫn là ước lượng cấp trạm, được đánh dấu `CONNECTOR_SCOPED_WAIT_APPROXIMATED`. Nếu không có cổng tương thích đang hoạt động, candidate bị loại với reason code cụ thể. Cần gửi `avg_session_duration_min` trong snapshot để estimator tính wait; thiếu thì candidate bị loại với `WAIT_INPUT_UNAVAILABLE`.
- Release telemetry ingest and authenticated snapshot reads reject synthetic catalog stations, in addition to rejecting `simulated` telemetry; an API key cannot turn demo catalog rows into operational observations.
- Legacy `simulated` snapshots already present in PostgreSQL are marked stale by the release runtime, excluded from recommendation eligibility, and hidden by the raw telemetry endpoint. This prevents a database reused from demo mode from promoting old simulator data to live status.
- Nếu 12 bucket observed không có hoặc không liên tục, serving không lặp occupancy hiện tại thành history; trả persistence fallback cùng cờ `OBSERVED_HISTORY_UNAVAILABLE`. Model release cũng cần `OCCUPANCY_HISTORY_STORAGE=database`.
- Telemetry API yêu cầu `X-Telemetry-API-Key` khi cấu hình `TELEMETRY_INGEST_API_KEY`; nếu release mode chưa có key thì trả `503`, còn `simulated` bị từ chối khi `DEMO_MODE=false`. Snapshot giới hạn 1.000 cổng, 2.000 xe queue và 16 loại connector trên mỗi cổng; release đối chiếu chính xác từng `port_id` với `ports.external_id` hoặc catalog label, cùng connector của chính cổng đó, ngoài việc kiểm tổng connector; migration 0019 cũng đặt unique index cho external ID không rỗng giữa các cổng active của từng trạm. Reverse proxy giới hạn body 1 MiB. Cần quản lý/rotate secret bằng secret manager khi deploy.
- Gửi lại cùng station và `observed_at` với snapshot giống hệt là idempotent kể cả khi đã có snapshot timestamp mới hơn; retry không làm lùi snapshot mới nhất và không phát Redis/SSE update trùng. Payload khác tại cùng timestamp bị từ chối. Adapter aggregator cần giữ timestamp gốc ổn định khi retry.
- DES `/realtime/stations/{station_id}/simulate-wait` và Queue Lab là công cụ mô phỏng demo; release mode từ chối các endpoint này với `403`. Kết quả mô phỏng không được dùng như ước lượng wait vận hành.
- Frontend nhận status qua SSE (`/realtime/stations/status/events`), tự reconnect và fetch REST làm fallback tối đa mỗi 30 giây khi stream lỗi. Backend phát Redis pub/sub sau telemetry ingest và vẫn polling repository theo `REALTIME_POLL_INTERVAL_S` để phục hồi.
- API `POST /journeys/{journey_id}/positions` lưu GPS có timestamp, loại ping cũ/trùng dữ liệu khác, đo lệch khỏi route đang chọn và áp dụng hysteresis (`REPLAN_DEVIATION_THRESHOLD_M`, `REPLAN_MIN_INTERVAL_MIN`). Khi đủ lệch và có SOC mới, service tính lại recommendation, cập nhật route/version và lưu `reroute` event cùng kết quả mới.
- Incident reports are idempotent per journey and limited to stations in that journey recommendation; submission requires its capability token. Operators use `GET /admin/incidents` and `PATCH /admin/incidents/{incident_id}/review` with `INCIDENT_REVIEW_API_KEY`. Only operator-triaged `safety_concern` and `access_problem` incidents exclude a station from recommendations until resolved or rejected; open reports do not affect ranking. Port and queue reports do not alter ranking because reports lack port-level details and a quantified correction. Journey read/GPS/re-plan APIs use the journey capability token, stored hashed by the backend and in session storage by the frontend; tokens expire and can be revoked. Release recommendation/routing/geocoding require OIDC bearer tokens; telemetry and operator routes retain dedicated API keys.

## 9. Tiến độ chuyển đổi

### Đã đưa vào workspace

- Data platform từ branch `open-charge-map-main`: PostgreSQL/PostGIS, 20 migrations gồm telemetry snapshots, journey recommendations, partition occupancy, capability token, incident review, token expiry và planned-arrival ownership, observation retention indexes, expiry sau ETA window, bootstrap snapshot và runtime seed. Migration 0018 chuẩn hóa các planned-arrival cũ hết hạn trước cuối ETA window trước khi bật constraint. Snapshot có dữ liệu synthetic; phải xem `data_platform/README.md` trước khi dùng như dữ liệu vận hành.
- Backend có repository database cho catalog, planned arrivals, telemetry, occupancy history và journey. Khi `DEMO_MODE=false`, khởi động từ chối nếu một trong các repository còn ở memory hoặc chưa có `TELEMETRY_INGEST_API_KEY`; `/health/ready` kiểm tra schema revision, `/health/live` chỉ kiểm tra process, `/health/checks` báo trạng thái model/fallback.
- API station/vehicle/status dùng repository được cấu hình; recommendation tìm candidate qua hành lang tuyến khi repository hỗ trợ PostGIS.
- Recommendation response trả thời gian đi/chờ/sạc/đi tiếp và xếp theo `total_time_min`; feasibility còn kiểm tra SOC dự phòng ở điểm đến.
- Frontend hiển thị tổng thời gian và các thành phần theo cùng response contract.
- Có `Dockerfile.backend`, `Dockerfile.frontend` và `compose.release.yaml` để đóng gói API/frontend/PostGIS/Redis/Prometheus; Nginx proxy cùng origin cho REST/SSE. Build context bỏ UrbanEV raw archive. Cấu hình kiểm tra DB trước; stack không tự chạy bootstrap/migration và seed hiện tại vẫn synthetic.
- Health tách `/health/live` khỏi `/health/ready`; readiness kiểm tra schema khi dùng database và `/health/checks` bộc lộ persistence fallback/model status.
- Rate limiting fixed-window dùng Redis, chia quota read/write theo client IP và dùng chung giữa workers. Release yêu cầu Redis; Redis lỗi thì API trả `503` cho request nghiệp vụ thay vì fail open. SSE nhận thông báo Redis sau telemetry ingest và có polling DB làm đường phục hồi.
- API xuất HTTP response/status, thời gian tới response headers, nguồn occupancy và nhóm lý do persistence fallback theo route template qua `/metrics`; Prometheus scrape nội bộ mỗi 15 giây, UI chỉ bind loopback và Nginx chặn public metrics path.
- Release backup CLI requires age encryption, streams PostgreSQL dump/restore through pipes, and checks ciphertext SHA-256 plus archive readability. The archive-list check drains age output through EOF even if `pg_restore --list` exits after reading the header, so age verifies the complete ciphertext authentication tag. The CI workflow is configured to create an encrypted backup from its disposable PostgreSQL/PostGIS database, verify it, restore it into a new database, then check migration revision and a round-trip data marker; this workflow has not been run remotely yet. Before release: schedule backups, replicate off-host, enable WAL/PITR, and run a restore drill against the actual deployment database.
  `scripts/run_release_backup.ps1` creates and verifies an encrypted archive, copies both archive and manifest to a UNC destination, verifies the copied backup, then publishes the set by renaming its staging folder. Register it in Windows Task Scheduler under a protected service account with Docker, age-key, and share access. Scheduling, off-site restore-drill evidence, and WAL/PITR still require deployment-level setup.

### Còn phải hoàn tất trước release

- A real telemetry provider and adapter have not been selected; the current simulator is demo-only and is rejected in release mode. Production telemetry integration, operator validation, and operational occupancy history (12 consecutive observed five-minute buckets per station) remain release gates. Serving falls back when data is missing and Prometheus alerts on coverage gaps. Release Compose prunes observations daily after an initial 24-hour delay; approve and set `OBSERVATION_RETENTION_DAYS` before deployment. Historical backfill remains preview/apply and never invents telemetry for gaps.
- Tạo/promotion occupancy model từ một evaluation window mới; benchmark hiện tại cho thấy XGBoost không đạt ngưỡng cải thiện MAE tối thiểu 5% so với persistence tại bất kỳ horizon test nào (0/6). Artifact production chưa có; backend tiếp tục persistence fallback.
- Pipeline preprocessing UrbanEV đã được đưa vào workspace và chạy từ archive có checksum khớp manifest: 50 trạm, 2.606.400 quan sát, split thời gian và cadence 5 phút được kiểm tra. Benchmark exploratory sáu horizon theo contract backend 2.2 đã chạy; XGBoost không đạt ngưỡng Phase 04 trên test window đã xem (0/6 horizon đạt 5%). Cần holdout độc lập và kiểm định HCMC trước khi tạo artifact release.
- Hiệu chuẩn phân phối/P90 của wait bằng dữ liệu vận hành; P90 Erlang C hiện là xấp xỉ. Routing leg metrics use provider-reported segments; legacy interpolation is demo-only. Release rejects live or cached waypoint routes without complete legs, retries the fallback provider, and fails closed if neither provider supplies metrics.
- Dynamic journeys persist atomically with recommendation snapshots; GPS/re-plan, idempotent incident reports, planned arrivals, expiry/revocation, and operator review are implemented. OIDC bearer auth protects recommendation/routing/geocoding; station catalog/status/SSE remain public by design. Telemetry, operator, and journey APIs use dedicated API keys or capability tokens. WebSocket is not implemented; the frontend currently uses SSE for station status.
- UI release mode bỏ điều khiển demo, hiển thị trạng thái nguồn/freshness/fallback và các trạng thái lỗi/không khả thi. Khi REST status fallback cũng lỗi sau khi SSE gián đoạn, dữ liệu status đang giữ trong giao diện được đánh dấu stale và thanh trạng thái báo status feed unavailable; lần cập nhật SSE/REST thành công sẽ khôi phục trạng thái hiện tại.
- Prometheus alerts now route through Alertmanager to a webhook URL mounted from an external secret file; release preflight requires that file and validates HTTPS without printing its value. Configure it with `ALERTMANAGER_WEBHOOK_URL_FILE` in `.env.release`. Grafana now provisions a release operations dashboard from the API's bounded-cardinality metrics; its listener binds to loopback and its admin password is mounted from `GRAFANA_ADMIN_PASSWORD_FILE`. Access it through a secure operator tunnel. The Compose stack now runs retention daily after a 24-hour initial delay, but requires the deployment's approved `OBSERVATION_RETENTION_DAYS`; off-host replication/PITR, that approved retention policy, and release/load validation remain open gates. OIDC bearer authentication is implemented for recommendation, routing, and geocoding APIs; provider-specific deployment configuration is still required.
- The GitHub Actions workflow is configured to build the API/web images, migrate a fresh PostGIS database, then start both containers and check web/API liveness plus frontend delivery. Its JWKS uses a deliberately unreachable test issuer and its release database has no operational catalog; readiness must therefore fail closed with identity unavailable. This exercises the not-ready gate, not a positive operational release. No remote workflow run has been recorded; this workstation has no Docker/Podman for Compose runtime checks.
- `GET /stations/{station_id}/forecast?horizon_min=5|10|15|20|25|30` now exposes an independent timestamped forecast contract for station details. It loads only contiguous observed history when available, labels persistence fallback and flags, and refuses stale/unverified station status; the release UI fetches it for the selected station without requiring a journey recommendation. Seasonal model features are evaluated at the forecast target time. `confidence` stays null and the UI says it is uncalibrated until an operational calibration dataset exists.
- Telemetry now accepts explicit `unknown` and canonical `out_of_service` per-port states (`offline` remains a compatibility alias). Unknown ports are excluded from known operational capacity and occupancy denominators; DES returns no wait estimate when any port state is unknown. An omitted `queue` means queue state was not observed, while `queue: []` explicitly means an observed empty queue; the former yields null queue length and no wait estimate. Journey exclusions distinguish unknown-only stations from known offline stations. Release readiness requires at least one fresh, eligible station with a known operational port.
- `GET /stations/search` now supports a bounded geodesic center/radius query or WGS84 bounding box, including antimeridian-crossing boxes and a maximum 200-result limit. The memory repository uses Haversine distance; the release database repository uses indexed PostGIS geography operations and filters synthetic catalog rows.

Database profile cần bật `CATALOG_STORAGE=database`, `PLANNED_ARRIVALS_STORAGE=database`, `REALTIME_TELEMETRY_STORAGE=database`, `OCCUPANCY_HISTORY_STORAGE=database` và `JOURNEY_STORAGE=database`; đồng thời cấu hình `TELEMETRY_INGEST_API_KEY`, `PLANNED_ARRIVAL_ADMIN_API_KEY`, `INCIDENT_REVIEW_API_KEY` và `REDIS_URL`. Backend kiểm tra các điều kiện này khi `DEMO_MODE=false`. Bootstrap snapshot trong `data_platform/README.md` chỉ dành cho local/integration vì chứa dữ liệu synthetic. Release chỉ chạy migrations, sau đó import catalog đã duyệt và ingest telemetry vận hành; tuyệt đối không dùng bootstrap/runtime seed để provision database release. Mặc định `memory` giữ luồng demo hiện hữu. Telemetry được lưu dưới dạng snapshot JSONB theo station và timestamp; API đọc snapshot mới nhất, còn history có thể truy vấn từ bảng.

Grafana is provisioned by the release Compose stack at `http://127.0.0.1:3000` by default. Set `GRAFANA_ADMIN_PASSWORD_FILE` to an external secret file containing a unique password of at least 32 characters. The bundled `Smart EV Release Operations` dashboard reads the Prometheus API, error, latency, forecast-source, fallback, station-freshness, and observed-history metrics. Keep the listener loopback-only and access it through an operator tunnel; it is not part of the customer frontend.

## 10. Tiêu chí chấp nhận cho bước hợp đồng

- Mọi timestamp có timezone và mọi metric có đơn vị rõ.
- Mọi dữ liệu biến động có thời điểm quan sát/tạo, nguồn và quy tắc stale/fallback.
- Candidate có thể tái hiện lý do được xếp hoặc bị loại.
- Với mỗi candidate hành trình, tổng thời gian bằng tổng các thành phần đi + chờ kỳ vọng + sạc + đi tiếp (sai số làm tròn tối đa `0.01` phút).
- Thứ hạng tăng dần theo tổng thời gian; tie-break cố định như mục 3.3.
- Trạm không khả thi không được xuất hiện như khuyến nghị an toàn.
- Không trộn planned arrivals với queue đã xác nhận.
- Version policy/model được trả về để kết quả có thể kiểm toán và so sánh.

Release implementation update: Redis supports rate limiting, SSE pub/sub, and snapshot/horizon keyed model forecast caching with configurable TTL; the CI workflow is configured to exercise quota, pub/sub, and cache paths against live Redis. Cache failures do not interrupt inference and persistence fallback is not cached. Prometheus alerts cover 5xx rate, response-start latency, inference failures, API availability, station freshness, and incomplete observed-history coverage; Alertmanager sends grouped firing/resolved alerts to the configured webhook secret file. The CI workflow includes an encrypted backup/verify/restore round-trip against a disposable PostgreSQL database, but no remote workflow run or deployment backup drill has been recorded. A preflight script rejects missing/weak/duplicate secrets, invalid CORS origins, invalid dependency timeouts, and missing/invalid alert webhook configuration before rendering Compose config. It validates effective Compose values after shell environment overrides for keys declared in `.env.release`, including secret-file paths. The deployment smoke command checks ready DB/Redis/identity, source-fresh station/vehicle catalogs, and at least one fresh station with an operational port; it does not make mocked CI data eligible for release. A bounded read-only staging load probe reports throughput, status counts, and p50/p95/p99 latency against operator-approved thresholds; no staging load run has been recorded. Local secret/policy preflight and release Compose rendering passed with the official Compose client; Prometheus 3.5.0, Alertmanager 0.34.1, and Grafana provisioning files passed local static checks. Container builds/runs and the remote workflow remain unverified without a Docker daemon.






## 11. Lộ trình từ code hiện tại đến release

Các hợp đồng dữ liệu/API, persistence PostgreSQL/Redis, ranking, realtime/SSE, luồng hành trình và giao diện release đã được triển khai trong workspace như ghi ở các mục trên. Phần còn lại chủ yếu là đưa cấu hình và dữ liệu đã được tổ chức phê duyệt vào môi trường đích, rồi thu thập bằng chứng vận hành. Thứ tự thực hiện:

1. **Chuẩn bị dữ liệu vận hành:** xác nhận nguồn và provenance catalog trạm/cổng/xe, loại bỏ trường synthetic, review importer preview rồi mới apply vào PostgreSQL. Preview read-only của `data/static/stations.geojson` và `data/static/vehicles.json` bị từ chối: 9/16 station có synthetic fields/connectors và cả 3 vehicle đều synthetic. Rà soát thêm catalog nguồn trên `origin/codex/open-charge-map-main`: 16 station có provenance, nhưng 9 vẫn đánh dấu `synthetic_fields`; 7 station không mang cờ này vẫn cần operator review trước khi import. Vehicle source có 20 hồ sơ nhưng `catalog_complete=false`, thiếu công suất AC ở 5 hồ sơ và DC ở 2 hồ sơ, connector của 17 hồ sơ chỉ có provenance `inferred`; các mặc định SOC/hiệu suất chung có nguồn `synthetic`. Importer giữ provenance theo từng trường xe, yêu cầu `operator_policy` có `policy_id` cho reserve/target/efficiency và không nhận synthetic provenance. Bản review candidate, danh sách station và hạn chế của từng vehicle ở [`release_catalog_review.md`](release_catalog_review.md). Chưa apply dữ liệu nào; cần operator duyệt station subset, hoàn thiện/duyệt hồ sơ xe và các planning defaults trước release.
2. **Chọn nguồn telemetry:** telemetry hiện hoàn toàn mô phỏng, chưa có aggregator được chọn. Hợp đồng adapter trung lập với vendor và schema snapshot ingest hiện tại ở [`TELEMETRY_ADAPTER_CONTRACT.md`](TELEMETRY_ADAPTER_CONTRACT.md). Khi có quyết định, lấy hợp đồng API/webhook/MQTT, credentials, giới hạn tần suất và quy tắc retry/idempotency; triển khai adapter chuyển dữ liệu nguồn sang snapshot ingest chuẩn. Simulator hiện tại chỉ dùng cho demo và kiểm thử.
3. **Cấu hình môi trường đích:** đăng ký OIDC issuer/audience/JWKS và frontend client; đặt secrets, CORS, timeout, retention policy đã duyệt, backup off-site/PITR và reverse proxy TLS theo preflight. Không dùng credentials mẫu trong CI.
4. **Nạp và kiểm tra dữ liệu realtime:** ingest snapshot thật, kiểm tra freshness/provenance/coverage và đạt `/health/ready`. Thu thập tối thiểu 12 bucket occupancy quan sát được liên tiếp cho mỗi trạm cần forecast; không backfill khoảng trống bằng synthetic data.
5. **Đánh giá model và wait:** chạy holdout độc lập theo thời gian, hiệu chuẩn tại HCMC và so sánh với persistence; chỉ promote artifact nếu đạt release gate. Hiện XGBoost chưa vượt baseline ở 6 horizon và backend vẫn dùng persistence. Hiệu chuẩn wait/P90 và đánh giá chính sách chống dồn tải cũng cần dữ liệu vận hành.
6. **Chứng minh khả năng vận hành:** chạy GitHub Actions release workflow thành công; trên staging chạy smoke/load theo SLO đã duyệt, kiểm tra quota routing provider, thực hiện restore drill và xác nhận backup off-site/WAL-PITR. CI với dịch vụ dùng một lần không thay thế các bằng chứng này.
7. **Cutover có kiểm soát:** chỉ mở customer traffic khi readiness, model policy đã chọn, identity, backup/restore và staging gates đều được chủ hệ thống chấp thuận; giữ persistence fallback nếu model chưa đạt gate và không bật chính sách phân phối tải khi chưa đánh giá.

Các bước 1–2 và 4 phụ thuộc nguồn dữ liệu/nhà cung cấp thật; bước 3 và 6 phụ thuộc cấu hình cùng hạ tầng triển khai. Cho đến khi các đầu vào đó tồn tại, workspace có thể kiểm tra luồng release fail-closed nhưng chưa thể chứng minh hệ thống đã sẵn sàng phục vụ vận hành.

**Đánh giá ML/data cho release:** xem [`release_readiness_ml_data.md`](release_readiness_ml_data.md). UrbanEV đã có provenance và pipeline tham chiếu, nhưng chưa có artifact đạt release gate; backend tiếp tục dùng persistence fallback cho đến khi có đánh giá holdout độc lập và artifact tương thích.
Thứ tự thực hiện hiện tại và trạng thái từng gate được duy trì tại [mục 11](#11-lộ-trình-từ-code-hiện-tại-đến-release); các đề xuất triển khai ban đầu đã được thay thế vì schema, persistence và các API nghiệp vụ đã có trong workspace.

## Release Compose database lifecycle

`compose.release.yaml` runs a one-shot `migrate` service before starting the API. It applies Alembic migrations to `head`; it does not import the checked-in demo snapshot or synthetic runtime fixtures. `data_platform/scripts/import_release_catalog.py` provides a validated, preview-first importer for reviewed operational station/port and vehicle catalogs. Its default applies partial upserts; `--replace-snapshot` explicitly reconciles complete station-provider snapshots and the release vehicle catalog, deactivating reviewed records missing from those complete inputs. Do not use bootstrap or synthetic demo seeders to provision a customer-facing release database. The importer does not create runtime port status; an actual telemetry source is still required before `/health/ready` can report fresh eligible stations. The web proxy starts after the API process starts so the telemetry adapter can send authenticated snapshots during bootstrap. Nginx gates other `/api/` routes on `/health/ready`, so business API traffic is unavailable until the API has an eligible catalog and fresh operational station status.

## Release routing leg metrics

Route cache records now preserve optional provider-reported `legs`. In release mode, a cached waypoint route without one metric leg per segment is bypassed and the configured live routing providers are queried; if no provider can supply a route, recommendation fails closed instead of estimating segment time from geometry. Demo mode retains the approximate cache path and labels it `LEG_METRICS_APPROXIMATED`. Direct cached routes use their whole-route distance/duration and do not need waypoint segmentation.

Release recommendation requests now reject `scenario_id` and scenario-event simulation outside demo mode. Release clients must provide the dynamic journey fields; static demo scenarios and event overlays cannot enter the production recommendation path even if their IDs are known.

The API now accepts a syntactically safe `X-Request-ID` (up to 128 ASCII letters, digits, dots, underscores, colons, or hyphens), generates a UUID otherwise, echoes it on every HTTP response including rate-limit responses, and includes it in request completion/error logs. The ID is not used as a metric label, avoiding unbounded Prometheus cardinality. Compose assigns the web proxy a stable address outside the dynamic IP allocation range, and Uvicorn trusts forwarded headers from that address only. Preflight checks that `FORWARDED_ALLOW_IPS` matches `RELEASE_WEB_PROXY_IP` and validates the private subnet, dynamic range and proxy address. Nginx overwrites `X-Forwarded-For` with its connected client address before proxying.

The release web port is bound to `127.0.0.1` on the host by default. Keep `RELEASE_WEB_HOST_BIND=127.0.0.1` so public traffic reaches Nginx through the host TLS reverse proxy; release preflight rejects other bind addresses because the Compose Nginx listener itself serves HTTP.

HTTP errors preserve their existing `detail` field and include a stable `error_code` by category (`AUTHENTICATION_REQUIRED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `VALIDATION_FAILED`, `RATE_LIMITED`, `DEPENDENCY_UNAVAILABLE`, or `INTERNAL_ERROR`). OpenAPI documents the common `{detail, error_code}` envelope for validation and default error responses. The frontend wraps these as `ApiRequestError` with status, code, and request ID while keeping the current human-readable message.

GPS re-plan requires the driver's current battery percentage. The release UI does not reuse the journey's starting SOC for later position pings; the driver enters current SOC before enabling the GPS/re-plan action, and the value is cleared after a successful ping so the next update requires a fresh reading.

The release Compose stack runs an operational-history retention worker once per day, with its first prune delayed by 24 hours. `OBSERVATION_RETENTION_DAYS` is mandatory and has no default: set it only to the approved deployment policy. The worker prunes forecasts, telemetry, and occupancy history in bounded database batches and does not delete journeys, GPS positions, or incident reports. Forecast-history writes are best-effort after inference: a write failure increments `smart_ev_occupancy_prediction_persistence_failures_total` and logs only the exception type, while the computed forecast response continues. Alert on that counter because forecast history will be incomplete until PostgreSQL writes recover. Its logs are the operation record; monitor failures and database disk use.

Telemetry ingest rejects observations more than `REALTIME_TELEMETRY_MAX_FUTURE_SKEW_S` seconds ahead of the API clock (default 60). This prevents a clock error from advancing the station's monotonic snapshot timestamp and blocking subsequent valid telemetry. Keep API and telemetry-provider clocks synchronized; the future-skew setting must be finite and positive. API domain models also reject `NaN` and infinite numeric values.

## Bounded staging load probe

`scripts/load_test_release.py` defaults to a read-only bounded probe against an isolated release staging stack. It verifies release readiness and a non-empty catalog first, then distributes GET requests across station catalog, vehicle catalog, station status, and model status. For the authenticated customer path, an optional journey mode sends dynamic `POST /journey/recommend` requests with an OIDC token read from `SMART_EV_STAGING_BEARER_TOKEN`. This mode requires both `--confirm-staging` and `--confirm-journey-writes`, accepts at most 100 requests and 50 workers, and persists one journey per request; use only disposable/isolated staging data. Both modes print throughput, status counts, p50/p95/p99 latency, and fail against explicit operator-provided p95 and error-rate limits. This does not define production SLOs. The read-only mode caps at 100,000 requests and 200 workers.

```powershell
python scripts/load_test_release.py `
  --api-url https://staging.example.net/api `
  --requests 1000 --concurrency 20 `
  --max-p95-ms 800 --max-error-rate 0.01 `
  --confirm-staging
```

Use the actual approved SLO values and a staging catalog/telemetry snapshot representative of the expected deployment. A local passing run with demo data is not release evidence.

To include the customer recommendation path, provide a dynamic request JSON and a short-lived staging access token through the environment. The journey mode requires HTTPS for remote API URLs (HTTP is accepted only for `localhost`/loopback) so the bearer token is not sent in cleartext. Each successful request creates a distinct persisted journey, so keep this probe small and clear the test journeys through the staging data reset procedure afterward.

```powershell
$env:SMART_EV_STAGING_BEARER_TOKEN = "<short-lived-staging-access-token>"
python scripts/load_test_release.py `
  --api-url https://staging.example.net/api `
  --journey-request-file C:\SecureInput\journey-request.json `
  --requests 20 --concurrency 5 `
  --max-p95-ms 2500 --max-error-rate 0.02 `
  --confirm-staging --confirm-journey-writes
Remove-Item Env:\SMART_EV_STAGING_BEARER_TOKEN
```

## Journey persistence and retry semantics

Dynamic journey creation in release requires `Idempotency-Key`. The API first scopes that client key to the verified OIDC issuer and subject with `JOURNEY_TOKEN_SIGNING_KEY`; PostgreSQL stores only the scoped key's SHA-256 hash and a canonical request fingerprint. Retries by the same principal check this record before route/recommendation work; with the same key and payload they return the original recommendation snapshot and the same HMAC-derived journey capability, refreshing that capability's expiry. A different principal cannot replay the same client key to obtain another user's journey capability. Reusing a scoped key with a different payload or one whose capability was revoked returns HTTP 409. Configure a distinct random `JOURNEY_TOKEN_SIGNING_KEY` of at least 32 characters. Journey creation and its recommendation snapshot are written in one transaction so `GET /journeys/{journey_id}` can read the created journey immediately. Re-plan now writes one recommendation snapshot per successful re-plan.
The release frontend stores the active journey ID and its capability token in `sessionStorage`, then restores the latest persisted recommendation, request, route, selected station, and unexpired planned arrival after a page reload. It binds that session state to the OIDC issuer and subject, and clears journey IDs, capability tokens, and pending idempotency keys when the identity changes, signs out, unloads, or expires. `GET /journeys/{journey_id}` includes only that journey's active planned arrival after capability validation. The token remains in the request's explicit Authorization header and is never placed in the URL.
Release API workers expire planned arrivals every 30 seconds; expired records are excluded from demand queries immediately, including during the interval before their status update. The database expiry operation fetches only rows transitioned by that batch.

Prometheus reports eligible/fresh/stale station status counts from the configured catalog and raises a bounded-cardinality alert when no eligible station is fresh or when more than half are stale for 10 minutes. It also reports the oldest eligible station timestamp whose basis is the provider/source, plus counts of source timestamps, database-update-time fallbacks, missing, and future timestamps. Release preflight requires operator-approved `CATALOG_SOURCE_MAX_AGE_S`; `/health/ready` fails closed if any eligible station lacks a source timestamp, has a future timestamp, or exceeds that age. The health check includes freshness counts and the configured threshold. The station detail UI distinguishes provider source time from the database row update time. The exporter refreshes aggregates from catalog/runtime repositories without station-ID labels.

Routing provider outcomes are exposed as `smart_ev_routing_provider_events_total{provider,event}` with bounded values for Goong/OSRM and success/failure/fallback/not-configured. This captures fallback routing even when it happens inside a recommendation request, without adding route IDs or exception text as metric labels.
# Identity and customer API access

When `APP_ENV` is `production`, `prod`, or `staging`, the backend defaults `DEMO_MODE` to false and refuses an explicit demo-mode setting; development retains the demo default. Release mode uses provider-neutral OpenID Connect access-token validation. Configure `OIDC_ISSUER`, `OIDC_AUDIENCE`, and `OIDC_JWKS_URL` for the API, plus `OIDC_CLIENT_ID` and `OIDC_SCOPE` for the browser build. Register the frontend as a public client using Authorization Code with PKCE, with the exact callback URI `https://<deployment-host>/auth/callback` and the application origin as the post-logout URI. The identity provider must issue API access tokens whose issuer and audience exactly match the backend settings and expose the signing keys at the configured HTTPS JWKS URL. Support refresh tokens for `offline_access` so browser sessions can renew access tokens. The client attempts silent renewal; if the session still expires, it clears the bearer token and requires sign-in again. The frontend also clears its bearer token when the OIDC client reports that its user session was unloaded or signed out. Never put a client secret in the frontend build.

Release preflight requires `OIDC_SCOPE` to contain `openid` and `offline_access` and rejects duplicate scopes; an empty value uses the documented default scope. `CORS_ORIGINS` must use HTTPS for public hosts; HTTP is accepted only for `localhost` or loopback IP origins used by local smoke checks. The API enforces the same rule during release startup.

Release `/health/ready` checks that the configured JWKS endpoint returns signing keys before marking the API ready; it reports identity unavailable without exposing the endpoint URL or response body. `/health/live` remains independent of external identity availability.

Readiness and health responses return bounded, generic dependency failure reasons for PostgreSQL, the catalog, and Redis. Detailed exception text is kept out of public HTTP responses so connection strings and internal hostnames are not disclosed; logs retain only the exception type for these check failures.

Journey recommendation, route calculation, and geocoding require a valid OIDC bearer token. Station/vehicle catalog, station status, model status, and station-status SSE remain public. Telemetry ingestion and operator operations retain their dedicated API keys; journey reads/updates retain their journey-scoped capability token. The browser attaches its OIDC token only where no route-specific Authorization header already exists.

## Station occupancy history API

`GET /stations/{station_id}/history` returns up to 1000 timestamped, five-minute occupancy observations from PostgreSQL, oldest first. The default window is the previous 24 hours; callers may request a timezone-aware range up to 30 days. The query is capped, indexed by station and bucket time, and only includes `data_origin=observed`; inferred and synthetic rows never appear as operational history. A station with no observations returns an empty list. Release returns `503` when the database history adapter is not configured. The frontend plots the most recent observed buckets and explicitly shows empty/unavailable states. The demo's in-memory setup has no observed history and therefore renders an empty state rather than invented data.

Latest workspace verification (2026-10-10): default `pytest -ra` discovers backend, data-platform, and release tests; with local PostgreSQL/PostGIS and Redis integration enabled together it reports 449 passed and 2 skipped (the two backup round-trip tests require age/age-keygen); without integration services it reports 427 passed and 22 skipped; `backend/tests/conftest.py` isolates app-singleton Redis clients so the full suite can run with `REDIS_URL` configured; application shutdown attempts every resource close and logs individual failures; A fresh local PostgreSQL/PostGIS database migrated through revision 0020; Alembic reports no schema drift among mapped tables; PostGIS geography types are resolved from pg_catalog after SQLAlchemy reflection; PostGIS filtering, frontend request contracts for journey, route, position, incident, and planned arrival plus response contract checks, release catalog reconciliation/import (including reviewed provider-port mapping, CLI preview and `--apply`, snapshot invalidation, database uniqueness, and PostgreSQL path-safe station/arrival ID constraints), and a database-backed positive `/health/ready` path all pass locally. Recommendation regression coverage confirms a direct trip with sufficient reserve SOC still returns ranked charging stations on request. Release routing also rejects live waypoint results with incomplete leg metrics, uses a valid fallback provider when available, and fails closed otherwise. OIDC coverage also exercises a protected release geocoding request: missing bearer returns 401, while an RS256 token validated through a local HTTP JWKS endpoint reaches the handler. The readiness integration imports a provenance-reviewed catalog, verifies invalid telemetry credentials and simulated data are rejected, ingests an authenticated snapshot through the API, rejects unknown port IDs, confirms identical retries are idempotent and conflicting same-timestamp payloads fail, reads the persisted snapshot back through the API, and confirms readiness from persisted state; OIDC signing-key and Redis checks are stubbed at their external boundaries. Three Redis integration checks passed against the live local Redis service. The concurrent provider-reference ownership check also ran against the migrated PostgreSQL test database. The CI-targeted Ruff file set passes. Frontend verification: 32 tests pass, including release auth token-expiry cleanup and URL path-segment encoding for station/arrival IDs; ESLint, TypeScript, and the production build pass. `MapView` is lazy-loaded: the initial application bundle is 336.61 kB (100.63 kB gzip) and the `MapView` chunk is 158.13 kB (46.48 kB gzip). The release workflow now runs `alembic check` after migration; workflow YAML and its test-step shell syntax were parsed locally; `actionlint` and a remote workflow run were unavailable in this environment. Earlier local runs verified an encrypted database backup/restore round-trip; this session did not repeat that check. Production readiness still depends on approved operational catalog and telemetry, identity-provider configuration, model validation/calibration, retention policy, deployment backup/restore drill, and staging SLO/load evidence.

## Bounded station map data

The browser now requests station features by the current map viewport through `GET /stations/search` with the existing 200-station cap, rather than downloading the whole catalog. `GET /stations/statuses` returns a maximum of 200 requested, active, release-eligible station snapshots in one batch. SSE subscriptions validate a maximum of 200 visible station IDs at query parsing and release mode rejects an unscoped all-stations stream. Both map providers report viewport bounds, and the Goong map updates markers/statuses without reconstructing the map on every telemetry event. A selected recommendation outside the viewport is pinned by its station ID and fetched through station detail/status APIs.

The map implementation and its Leaflet styles load as a separate frontend chunk, keeping the initial release application bundle smaller while preserving the existing map behavior and OSM fallback.

The public `GET /stations` catalog route is also keyset-paginated by `after_station_id`, with a hard maximum of 200 records per page; release database queries apply the cursor and limit in PostgreSQL.

Release status detail, forecast, batch status, and SSE polling query PostgreSQL only for the requested station IDs. Status rows and each station's latest telemetry snapshot are fetched in bounded `ANY(station_ids)` queries; the release path no longer refreshes or scans the full status/telemetry catalog for a station or viewport update. Demo mode keeps full refresh behavior so in-memory scenario overlays continue to work.

Release recommendation also loads status and latest telemetry in one bounded batch for the route-corridor candidate set; it does not refresh the full runtime catalog or issue one status query per candidate. Status retains per-port connector/state details internally from PostgreSQL and telemetry snapshots; the public status contract does not expose those details. Each persisted port state is checked against its own `reported_at`; missing/expired observations become `unknown` even when another port has a fresh update. Recommendation excludes a station when no compatible port is operational and scopes wait capacity/observed queue to compatible connectors. Demo recommendation still refreshes runtime state so scenario overlays remain effective.

Release recommendation limits route-corridor candidates to `RECOMMEND_MAX_CANDIDATES` (default 50, allowed 1–500). PostgreSQL selects the nearest candidates and fetches only one extra row to identify truncation; the API sets `RECOMMENDATION_CANDIDATE_LIMIT_REACHED`, returns the applied `candidate_limit`, and the frontend discloses that it considered the nearest stations up to that limit. Tune this limit against the station density and routing-provider budget when deploying.

The API PostgreSQL engine has a 5-second connection-pool wait limit, a configurable connection timeout (`DATABASE_CONNECT_TIMEOUT_S`, default 5 seconds), and a configurable per-session statement timeout (`DATABASE_STATEMENT_TIMEOUT_MS`, default 15000 ms). Connection failures, query cancellation, and pool exhaustion return a generic HTTP 503 without exposing database details. Set the statement limit against the approved query/SLO budget; migrations and bulk catalog imports run in their separate CLI processes and are not constrained by the API engine setting. CI has an integration check that runs `pg_sleep` beyond the configured limit and expects PostgreSQL to cancel it.

## Demo-only telemetry ingest simulator

Telemetry is currently wholly simulated; no aggregator/vendor or production feed has been selected. `scripts/simulate_telemetry.py` exercises the same complete-snapshot ingest endpoint and SSE update path with explicitly synthetic port states, confirmed queues, or an unknown queue state. The command requires `--confirm-demo-simulation`, a telemetry API key, and a readiness response with `demo_mode: true`; it refuses release mode. It labels every request `data_source: simulated`, respects the default write-rate limit, and cannot create operational data or satisfy release readiness. This simulator is sufficient for development and demo verification only. A production release remains blocked until an operator selects a real telemetry source and its adapter supplies provider timestamps, documented field mappings, authentication/secret rotation, retry behavior, and verified port/queue semantics. Example:

```powershell
$env:TELEMETRY_INGEST_API_KEY = "<demo-telemetry-key>"
python scripts/simulate_telemetry.py `
  --api-url http://127.0.0.1:8000 `
  --station-id ST_EVO_AUDI_HCM `
  --cycles 4 --interval-s 15 --queue-length 2 `
  --confirm-demo-simulation
Remove-Item Env:\TELEMETRY_INGEST_API_KEY
```

For network-level queue pressure, `scripts/simulate_hcmc_network_load.py` replays the synthetic HCMC station catalog, runtime status, and arrival-rate assumptions under paired seeded demand. It calls the backend `WaitEstimator` with persistence forecasts and synthetic live state, compares nearest-station selection with drive-time plus estimated wait, and reports realized and estimated wait, station assignment, sampled occupancy, and a persistence baseline MAE. The road-time proxy and all demand/session values are synthetic; this is a logic study only, not operational calibration, a training dataset, or release evidence.

```powershell
python scripts/simulate_hcmc_network_load.py `
  --duration-hours 24 --network-arrivals-per-hour 12 --seed 42 `
  --report build\simulation\hcmc_network_load.json
```

Both Redis clients have configurable connection and command timeouts (`REDIS_CONNECT_TIMEOUT_S`, default 2 seconds; `REDIS_COMMAND_TIMEOUT_S`, default 3 seconds). SSE's blocking Pub/Sub read supplies its own poll interval, so ordinary quiet periods do not use the shorter command timeout. A Redis timeout follows existing dependency-failure behavior: release rate limiting fails closed with 503, telemetry persistence remains committed and SSE recovers by polling PostgreSQL, and forecast cache errors fall back to inference.

Verification for bounded map loading: backend and data-platform suites, including PostgreSQL/PostGIS database integration, frontend tests, ESLint, and frontend production build pass locally. The batched-ID PostGIS filter was exercised against the migrated local integration database.
