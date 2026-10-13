# M3 — Backend API và tích hợp database

## Prompt giao việc

Bạn phụ trách tích hợp backend cho station planning trên shared app `fix/ui`. Trước khi code, cập nhật đúng baseline/ref mới nhất và đọc `../IMPLEMENTATION_PLAN_VI.md`, `SHARED_CONTRACT_VI.md`, brief M1/M2. Tái sử dụng backend/repository/PostGIS của app; không dựng service hoặc database thứ hai.

## Mục tiêu

Expose planning domain qua API có schema ổn định, lấy dữ liệu bằng repository và trả response giải thích/provenance. Giữ driver endpoints tương thích.

## Task nhỏ

1. **Baseline audit:** xác nhận cách khai báo router, prefix `/api/v1`, Pydantic version/models, app state/dependency injection, exception format, DB sessions/repository và test fixtures trên branch hiện tại.
2. **API:** expose `POST /api/v1/planning/recommendations` theo `SHARED_CONTRACT_VI.md`; sinh OpenAPI schema và validation cho units/enum/range/unknown.
3. **Application service:** điều phối parse request → validate package → lấy data qua repository → gọi engine M2 → map response. Không chứa formula trong route.
4. **Repository/PostGIS:** tái dùng catalog hiện tại và thêm spatial queries tối thiểu. Tránh N+1 và không trả toàn bộ station catalog nếu chỉ cần vùng phân tích.
5. **Data lineage:** trả data snapshot/source/algorithm/config/package versions, warning và `is_synthetic`/status xuyên suốt.
6. **Persistence:** MVP không tạo bảng project/run nếu request-response cùng demo đủ. Nếu cần lưu, nộp thiết kế bảng/retention/owner trước; dùng đúng schema/table ordering/seeding workflow repo, không tự thêm Alembic.
7. **Failure behavior:** malformed input → validation response; danh sách candidate rỗng → `invalid_input`; chỉ trả `no_feasible_candidates` khi đã đánh giá candidate hợp lệ và tất cả đều fail hard constraint đã xác nhận; partial unknown → `completed_with_unknowns`; DB failure không bị báo nhầm thành kết quả score thấp.

## Không thuộc module

- Sửa thuật toán ranking M2, frontend M4 hoặc tạo duplicate station catalog.
- Tạo finance default hoặc nhận policy free-form không version.
- Đổi semantics wait/occupancy API hiện tại.
- Thêm persistence/API endpoints ngoài MVP không có owner/acceptance.

## Acceptance

- Endpoint khớp shared contract/OpenAPI và gọi domain service, không nhúng công thức.
- Spatial query dùng boundary/pilot scope và unit rõ.
- Response chứa `run_id`, profile/algorithm/data versions, warnings, constraints, score breakdown, metric status và provenance.
- Cùng input + data snapshot + engine version cho kết quả tái lập.
- Existing driver/search/trip APIs không bị đổi semantics.

## Handoff

Ghi route/model/service/repository files, API example/OpenAPI, DB changes (nếu có), cách run, verification và mọi khác biệt với baseline.
