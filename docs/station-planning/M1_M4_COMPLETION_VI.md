# Handoff M1–M4 — Station planning

## Baseline và contract của demo

- Snapshot: `hcmc-nine-wards-demo-v3`.
- API `city_id`: `VN-HCMC`; boundary: `ADMINISTRATIVE_2025`; pilot extent ID: `hcmc-nine-wards-demo-v3`.
- Phạm vi dữ liệu: 9 phường, 37 existing-site fixtures, 18 candidate hypotheses và 27 demand nodes.
- Access baseline: profile `normal`; travel time là proxy từ access matrix, không phải routing trên đường thật.
- Demand scenario: low/base/high, tổng expected sessions của một tuần mẫu; dữ liệu tổng hợp, không phải dự báo thị trường.
- Cấu hình cost có nguồn hiện tại là `base_cost` cho DC 4 × 80 kW. Snapshot giữ ngân sách tham chiếu 10 tỷ VND ở phạm vi portfolio; bộ lọc ngân sách từng candidate để trống nếu người dùng chưa nhập ngưỡng riêng. Engine chưa chọn portfolio nhiều site.

## Bàn giao theo module

### M1 — Data & GIS

Snapshot v3, schema, dictionary, manifest, alignment report và validation reports đã có trong `data_platform/station_planning/demo_hcmc_v3`. Backend adapter xác minh SHA-256 các file được dùng, kiểm tra ID/count/CRS và giữ nguyên status/provenance. Tọa độ demand và candidate được kiểm tra trong polygon pilot đã pin.

### M2B — Recommendation engine

`TechnicalOpportunityEngine` nhận node-level weekly demand và access matrix đã ánh xạ. Thay `coverage_minutes` sẽ lọc lại reachable nodes; `demand_scenario` chọn đúng một trong low/base/high. Candidate spacing và individual budget được đánh giá riêng khỏi soft score. CAPEX base cost chỉ là scenario estimate; không cộng vào readiness, không tính ROI. Candidate thiếu evidence vật lý vẫn conditional/unknown.

M2A chưa có model demand được huấn luyện. Planner hiện dùng baseline low/base/high tổng hợp có version/provenance; tài liệu ML yêu cầu baseline hoạt động khi model chưa khả dụng và cấm gọi đây là forecast HCMC. M2A model là nhánh follow-up riêng khi có target labels phù hợp.

### M3 — Backend integration

- `GET /api/v1/planning/demo-snapshot`: trả metadata, candidate choices và geometry/layers cho Planner.
- `POST /api/v1/planning/recommendations`: gọi application service → pinned M1 repository → M2 engine → response theo shared contract.
- Repository là read-only file adapter vì snapshot M1 hiện được bàn giao dưới dạng seed files và access matrix bất biến. Adapter không nạp bản sao vào database, không trộn với station catalog live và không tạo bảng/run persistence.
- Repository/data errors không được đổi thành score thấp; lỗi snapshot trả `invalid_input`, lỗi truy cập dữ liệu trả HTTP 503.

### M4 — Frontend Planner

Planner nạp cấu hình từ metadata endpoint, chọn candidate và demand scenario, chỉnh coverage threshold/cấu hình kỹ thuật, rồi gọi typed API client. Bản đồ dùng boundary, candidate, existing sites và demand nodes của cùng snapshot. Nhãn phân biệt scenario, synthetic, proxy và dữ liệu thiếu; có trạng thái loading/error/empty/invalid/partial unknowns, giải thích candidate và so sánh hai phương án. Luồng driver giữ nguyên.

## Nghiệm thu tích hợp M1–M4 và bàn giao M5

Acceptance backend qua snapshot M1 → API M3 → engine M2B đã chạy: endpoint metadata và recommendation, sensitivity theo coverage/demand, null finance/no ROI và no-feasible budget được kiểm tra. Snapshot và contract validators, 19 unit tests data/rules, frontend build/lint và 80 Vitest tests đều pass. Full backend suite cũng pass; module test trip persistence được skip vì các route đó không thuộc API contract hiện tại, còn test yêu cầu PostgreSQL chỉ chạy khi có test database. Planner interactions được kiểm tra bằng component tests; browser click-through thủ công chưa được ghi nhận.

Đây chưa phải tích hợp dữ liệu vận hành PostGIS: M1 chưa phát hành bộ candidate/demand tương đương trong DB, nên adapter không thay bằng station catalog live làm mất tính tái lập. M2 cũng chưa làm portfolio selection, finance/policy ranking, hay xác nhận feasibility vật lý. Kịch bản M5, kết quả tham chiếu và các giới hạn demo nằm trong [runbook M5](M5_DEMO_RUNBOOK_VI.md).

Contract v0.1 được mở rộng tương thích ngược bằng `run.demand_scenario` (mặc định `base`) và endpoint chỉ đọc `GET /demo-snapshot`; response luôn echo demand scenario. Xem [shared contract](modules/SHARED_CONTRACT_VI.md).
