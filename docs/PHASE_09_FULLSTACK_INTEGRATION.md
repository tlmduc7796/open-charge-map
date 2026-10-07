# Smart EV Journey — Phase 09 — Frontend–Backend Integration

**Phase:** 09 / 11  
**Depends on:** Phase 08  
**Primary outcome:** Một journey có thể chạy end-to-end qua UI với backend thật, model thật và route data thật/cache.

> Không bắt đầu phase tiếp theo nếu **Exit Gate** của phase này chưa đạt.


## 1. Goal

Thay mock bằng API thật và hoàn thành flow người dùng từ input đến recommendation.

## 2. Integration Flow to Verify

1. User chọn xe.
2. Nhập origin/destination.
3. Nhập SOC.
4. Frontend gửi request.
5. Backend tìm candidate stations.
6. Compatibility/reachability được tính.
7. Occupancy forecast được gọi.
8. Wait và charging duration được estimate.
9. Stations được rank.
10. Route/recommendation trả về frontend.
11. Map và details cập nhật.

## 3. Tasks

- Chốt request/response schemas.
- Handle timezone.
- Handle model unavailable.
- Handle routing API unavailable bằng cache.
- Handle no compatible/reachable station.
- Đồng bộ station status refresh.
- Đồng bộ planned arrival khi user chọn recommendation.
- Bảo đảm event refresh không cần reload toàn app.
- Add integration logging đủ để debug demo.

## 4. Exit Gate

- [x] Scenario bình thường chạy hoàn toàn từ frontend.
- [x] Scenario low SOC trả kết quả hợp lý hoặc no-route rõ ràng.
- [x] Routing API failure vẫn chạy qua cache cho demo scenarios.
- [x] Model service failure có fallback/error message rõ.
- [x] Không có mismatch field/unit giữa frontend và backend.
- [x] Planned arrival được tạo khi user commit route.
- [x] Browser console và backend log không có error chưa xử lý trong happy path.

**Exit Gate result:** `DEMO PASS / RELEASE BLOCKED BY PHASE 03–04` — 2026-09-26.

Chi tiết kiểm chứng: `data_platform/data/validation/phase9_fullstack_integration_report.md`.

## 5. Implementation notes

- Origin/destination hỗ trợ Goong Places autocomplete + details qua backend để REST key
  không đi vào frontend. Demo locations là fallback khi Places không khả dụng.
- Journey request có thể override origin, destination, vehicle, SOC và departure time.
- Với tọa độ scenario, backend ưu tiên deterministic route cache. Với tọa độ tùy chọn,
  backend gọi Goong Directions rồi OSRM; failure được trả thành lỗi 503 rõ ràng.
- Goong Directions biểu diễn waypoint bằng danh sách `destination` phân tách bởi `;`.
  Backend có regression test bảo đảm waypoint không bị bỏ qua.
- Mỗi recommendation mang route geometry đã normalize, tránh frontend phải truy vấn lại
  một live route ID không tồn tại trong static cache.
- UI xác nhận/hủy planned arrival qua backend. ETA window và arrival probability được tạo
  ở backend, không hard-code scoring hoặc domain calculation trong frontend.
- Request timestamp bắt buộc timezone-aware. Distance dùng meter, duration dùng second trong
  API; frontend chỉ format thành minute/percent để hiển thị.
- Integration middleware log method/path/status/duration. Logger của `httpx` bị hạ xuống
  WARNING để không ghi Goong API key trong query string.
