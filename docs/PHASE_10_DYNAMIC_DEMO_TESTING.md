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

- có nhiều candidate;
- ít nhất một station compatible/reachable;
- recommendation trả rank.

### Scenario B — Low SOC

Expected:

- station ngoài khả năng tới bị loại;
- arrival SOC không vi phạm reserve.

### Scenario C — Queue congestion

Expected:

- event tăng queue;
- estimated wait tăng;
- recommendation có thể đổi nếu station khác tốt hơn.

### Scenario D — Port outage

Expected:

- operational capacity giảm;
- occupancy ratio/effective availability cập nhật;
- projected wait không giảm vô lý;
- reroute có thể xảy ra.

### Scenario E — Routing API failure

Expected:

- cache được dùng;
- demo vẫn hoàn thành.

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

- [ ] Tất cả required scenarios có expected-result document.
- [ ] Mỗi scenario chạy lặp lại được từ reset state.
- [ ] Congestion và outage làm state thay đổi đúng.
- [ ] Dynamic recommendation/reroute có ít nhất một scenario demonstrable.
- [ ] Test suite không có failing test blocker.
- [ ] Không cần chỉnh tay JSON giữa lúc demo.
- [ ] Có script `reset_demo` hoặc equivalent.

**Exit Gate result:** `PASS / FAIL`
