# Smart EV Journey — Phase 08 — Frontend Core

**Phase:** 08 / 11  
**Depends on:** Phase 07  
**Primary outcome:** Frontend hiển thị map, station state và journey inputs với mock/API data contract ổn định.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Xây UI chính nhưng chưa cần hoàn thiện mọi dynamic interaction.

## 2. Screens / Components

Tối thiểu:

- Map view
- Origin/destination input
- Vehicle selector
- SOC input
- Station markers
- Station detail panel
- Recommendation result list/card
- Route display
- Occupancy/queue/wait display
- Demo status/event indicator

## 3. Tasks

### 3.1 Map

- Render base map.
- Render station markers từ backend.
- Distinguish state:
  - available;
  - busy/full;
  - affected by event.

### 3.2 Journey form

Input:

- origin;
- destination;
- vehicle;
- initial SOC;
- target SOC/preferences nếu cần.

Validate client-side basic ranges.

### 3.3 Station details

Hiển thị tối thiểu:

- name/address;
- access và notes khi trạm bị giới hạn sử dụng;
- connector;
- total/available/occupied ports;
- queue;
- predicted occupancy;
- estimated wait;
- estimated charging time.

### 3.4 Recommendation UI

Hiển thị:

- ranked candidates;
- detour;
- wait;
- charging time;
- arrival SOC/risk;
- reason station bị loại nếu cần.

## 4. Exit Gate

- [x] Map render ổn định.
- [x] Station markers khớp station IDs từ backend.
- [x] Vehicle/SOC/journey inputs hoạt động.
- [x] Station detail không hiển thị field out-of-scope như cost.
- [x] Recommendation component render được response contract.
- [x] UI xử lý loading/error/empty state.
- [x] Không hard-code business calculation trong frontend.

**Exit Gate result:** `DEMO PASS / RELEASE BLOCKED BY PHASE 03–04` — 2026-09-26.

Chi tiết kiểm chứng: `data_platform/data/validation/phase8_frontend_core_report.md`.

## 5. Implementation notes

- Frontend gọi trực tiếp API Phase 07; mock chỉ được dùng trong unit tests.
- Goong Maps là provider chính khi có `VITE_GOONG_MAPTILES_KEY`. Nếu thiếu key,
  WebGL không được hỗ trợ hoặc Goong lỗi trước khi load, UI tự chuyển sang Leaflet + OSM.
- Origin/destination hiện lấy từ demo scenario và chỉ đọc. Nhập địa điểm bất kỳ, geocoding
  và route động thuộc Phase 09; giới hạn này được hiển thị ngay trên form.
- Marker dùng runtime status để phân biệt available, busy/queue, affected by event và offline.
- Recommendation, compatibility, reachability, wait, charging time và score đều do backend
  tính. Frontend chỉ format và hiển thị dữ liệu contract.
- Cost/price không xuất hiện trong form, station detail hoặc recommendation.
- UI responsive cho desktop/mobile; loading, backend error, chưa chạy và không có candidate
  đều có trạng thái riêng.
