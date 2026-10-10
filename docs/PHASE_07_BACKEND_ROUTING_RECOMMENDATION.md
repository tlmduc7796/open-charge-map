# Smart EV Journey — Phase 07 — Routing, Recommendation & Runtime Events

**Phase:** 07 / 11  
**Depends on:** Phase 06  
**Primary outcome:** Backend có thể tạo candidate stations, route, estimate total stop impact, rank và phản ứng với event.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.

> Nhánh `demo/backend-first` dùng persistence occupancy từ Phase 06. Toàn bộ business flow
> Phase 07 chạy được, nhưng release tổng thể vẫn phụ thuộc Phase 03–04 và Phase 06 release gate.


## 1. Goal

Hoàn thành business flow phía backend: route → candidate station → compatibility/reachability → wait/charging estimate → recommendation → reroute khi state thay đổi.

## 2. Tasks

### 2.1 Routing integration

- Dùng Goong làm routing provider chính khi API sẵn sàng; dùng route cache trước và OSRM public làm fallback.
- Dùng cache `routes/*.json` khi:
  - API lỗi;
  - demo offline;
  - cần deterministic scenario.
- Chuẩn hóa:
  - `distance_m`
  - `duration_s`
  - geometry.

### 2.2 Candidate filtering

Loại station:

- incompatible;
- unreachable;
- offline hoàn toàn.
- có `access != public`, trừ khi request sau này có eligibility tương ứng.

### 2.3 Recommendation scoring

Score chỉ dùng scope MVP:

- detour;
- estimated wait;
- charging time;
- SOC risk.

Chuẩn hóa từng component bằng ngưỡng cố định đã cấu hình, không dùng min-max theo tập candidate.

Không dùng price/cost.

Lưu cả component score và final score để explainable.

### 2.4 Planned arrivals

- Register planned arrival khi system route user tới station.
- Expire/cancel khi user đổi route hoặc quá ETA window.
- Dùng planned load trong projected wait nếu estimator support.

### 2.5 Event engine

Apply:

- congestion;
- queue spike;
- port outage;
- recovery.

Event phải update runtime state nhưng không sửa static master data.

### 2.6 API endpoints

Tối thiểu:

- stations/list/detail;
- vehicles/list;
- journey/recommend;
- route;
- station/status;
- event/apply/reset hoặc demo control;
- model/status.

## 3. Exit Gate

- [x] Routing API hoặc route cache trả geometry/distance/duration đúng schema.
- [x] Incompatible/unreachable station bị filter đúng.
- [x] Recommendation không dùng cost/price.
- [x] Mỗi recommendation có explainable component values.
- [x] Planned arrival lifecycle hoạt động.
- [x] Event có thể làm recommendation thay đổi trong scenario đã định.
- [x] Tất cả backend integration tests pass cho ít nhất 2 end-to-end scenarios.

**Exit Gate result:** `DEMO PASS / RELEASE BLOCKED BY PHASE 04–06` — 2026-09-25.

Chi tiết kiểm chứng: `data/validation/phase7_backend_demo_report.md`.

## 4. Implementation notes

### 4.1 Routing

- Resolution order: exact route cache → Goong Directions → public OSRM.
- Route cache được ưu tiên cho demo scenario để kết quả deterministic và chạy offline.
- Goong Directions live đã được xác minh với key local; response được normalize thành
  GeoJSON LineString, meter và second.
- OSRM fallback được test bằng provider injection, không phụ thuộc network trong test suite.
- Cache Phase 01 không lưu per-leg metrics. Distance/duration từ origin tới station được
  nội suy theo tỷ lệ chiều dài geometry tới coordinate gần waypoint nhất. Đây là demo
  approximation; cache mới nên lưu legs thật.

### 4.2 Candidate and scoring

Pipeline lọc cố định:

```text
public access → operational ports → connector compatibility → route → reserve-SOC reachability
```

Trong phiên bản demo, score cao hơn là tốt hơn và dùng fixed thresholds từ environment:

```text
component_score = 1 - min(value / configured_max, 1)
final_score = weighted sum(wait, detour, charging time, SOC safety)
```

Đây là score chẩn đoán/legacy còn được trả để tương thích và phân tích; nó không quyết
định `rank` trong release. Hợp đồng hiện hành được chốt tại
[`from_demo_to_release.md`](from_demo_to_release.md#3-tiêu-chí-xếp-hạng-đã-chốt):
xếp theo `total_time_min` với `ranking_policy_version` và tie-break xác định.

SOC score dùng khoảng cách từ arrival SOC tới reserve SOC. Không có price/cost component.

### 4.3 Mutable demo state

- Event engine giữ runtime copy, không sửa station static master data.
- Apply idempotent; reset rebuild state từ snapshot gốc.
- Planned arrivals hỗ trợ register, cancel, arrived, expire và reset.
- State chỉ tồn tại in-memory và reset khi backend restart; phù hợp demo nhưng chưa phải
  production persistence.
- Event được kích hoạt chủ động qua demo endpoint/scenario, chưa có background scheduler
  tự apply theo `start_at`/`end_at`.

### 4.4 API

```text
GET  /stations
GET  /stations/{station_id}
GET  /stations/{station_id}/status
GET  /vehicles
POST /route
POST /journey/recommend
POST /demo/events/{event_id}/apply
POST /demo/reset
GET  /planned-arrivals
POST /planned-arrivals
POST /planned-arrivals/expire
POST /planned-arrivals/{arrival_id}/cancel
POST /planned-arrivals/{arrival_id}/arrived
GET  /model/status
```
