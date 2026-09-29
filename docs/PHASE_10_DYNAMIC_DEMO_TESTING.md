# Smart EV Journey — Phase 10 — Dynamic Demo Scenarios & System Testing

**Phase:** 10 / 11  
**Depends on:** Phase 09  
**Primary outcome:** Các scenario cố định chứng minh được occupancy forecast, wait estimation và dynamic rerouting một cách lặp lại.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Biến các dataset demo thành testable scenarios có expected behavior cụ thể và ổn định.

## 2. Required Scenarios

### Scenario A — Normal recommendation

Expected:

- 15 trạm public có cached route và được xếp hạng;
- La Vela đứng đầu với snapshot mặc định;
- Audi bị loại vì private access.

### Scenario B — Low SOC

Expected:

- vẫn có station an toàn để đề xuất;
- các station ngoài khả năng tới bị loại bằng `INSUFFICIENT_SOC_RESERVE`;
- mọi arrival SOC được trả về đều không vi phạm reserve.

### Scenario C — Queue congestion

Expected:

- event làm La Vela full occupancy và tăng queue;
- estimated wait của La Vela tăng từ 0;
- La Vela mất hạng đầu.

### Scenario D — Port outage

Expected:

- hai port La Vela chuyển offline;
- occupancy ratio/effective availability cập nhật;
- projected wait không giảm vô lý;
- La Vela bị loại và recommendation đầu tiên đổi.

### Scenario E — Routing API failure

Expected:

- cache được dùng;
- cả 15 trạm public có route cache;
- demo vẫn hoàn thành khi không có Goong REST key.

## 3. Testing

- Unit tests.
- Backend integration tests.
- Frontend component tests nếu framework support.
- End-to-end smoke test cho scenarios.
- Data integrity tests.
- Model inference smoke test.
- Event reset/replay test.

## 4. Demo determinism

- Scenario phải reset về trạng thái ban đầu.
- Event activation phải deterministic.
- Route cache phải có đủ cho flow demo.
- Không phụ thuộc thời tiết/price/live external state.

## 5. Exit Gate

- [x] Tất cả required scenarios có expected-result document.
- [x] Mỗi scenario chạy lặp lại được từ reset state.
- [x] Congestion và outage làm state thay đổi đúng.
- [x] Dynamic recommendation/reroute có ít nhất một scenario demonstrable.
- [x] Test suite không có failing test blocker.
- [x] Không cần chỉnh tay JSON giữa lúc demo.
- [x] Có `POST /demo/reset` và nút **Reset demo** tương đương.

**Exit Gate result:** `PASS` — 2026-09-27. Backend regression tests chạy cả bốn
scenario; UI dry-run và kết quả chi tiết được lưu tại
`data/validation/phase10_dynamic_demo_report.md`.
