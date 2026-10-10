# Báo cáo thay đổi workspace trong phiên làm việc (~15 giờ)

Ngày lập: 2026-10-10
Branch đang mở: `full-stack-main`
Trạng thái: các thay đổi được mô tả dưới đây đang nằm trong workspace; chưa được commit/merge.

## Mốc so sánh và giới hạn

Mốc đã commit gần nhất của chính branch này là `aa85e92` (`2026-10-08 21:37:40 +07:00`, “feat: implement expandable Queue Lab section with updated styling and toggle functionality”). Git hiện không có commit hay snapshot working tree của branch này vào ngày hôm qua (2026-10-09). Vì vậy không thể xác nhận chính xác từng khác biệt so với toàn bộ filesystem ngày hôm qua; báo cáo này đối chiếu workspace hiện tại với commit gần nhất nói trên của cùng branch, không lấy một branch khác làm mốc. Các thay đổi chưa commit cũng có thể bao gồm công việc đã tồn tại trước phiên 15 tiếng.

## Khác biệt chính so với mốc đã commit

| Khu vực | Workspace hiện tại đã bổ sung hoặc thay đổi |
|---|---|
| Lưu trữ và dữ liệu | Bổ sung PostgreSQL/PostGIS làm nguồn dữ liệu cho chế độ release; thêm repository và migration cho catalog, journey/đề xuất, telemetry snapshot, occupancy history, prediction, arrival rate, incident và planned arrival. Redis được dùng cho rate limit, thông báo SSE và cache forecast. Schema hiện có migration đến `0020_path_safe_ids`. |
| API và bảo mật | Thêm xác thực OIDC cho luồng recommendation, routing và geocoding; token capability theo journey; khóa riêng cho operator/telemetry; idempotency, request ID, mã lỗi ổn định, giới hạn input/rate và các readiness gate. Chế độ release từ chối hoặc loại dữ liệu synthetic/simulated. |
| Recommendation, routing và realtime | Tìm ứng viên trạm có giới hạn bằng PostGIS, đọc trạng thái theo lô, xếp hạng theo tổng thời gian, lưu recommendation theo journey, kiểm tra route-leg metrics và có fallback provider. Bổ sung SSE, freshness và nguồn dữ liệu lịch sử. Khi người dùng chủ động tìm trạm sạc, SOC đủ đi thẳng đến đích không còn chặn danh sách trạm được đề xuất. |
| Frontend | Bổ sung sign-in gate/OIDC token handling cho release, khôi phục journey đã lưu, xử lý contract request/response, tải trạm theo viewport, hiển thị freshness/fallback, lịch sử/forecast của trạm và lazy-load bản đồ. Demo hiển thị số cổng mô phỏng kèm nguồn; release tiếp tục ẩn số liệu vận hành chưa được xác minh. |
| ML và dữ liệu | Thêm pipeline tiền xử lý UrbanEV có kiểm tra checksum, benchmark khám phá sáu horizon và evaluator holdout HCMC độc lập với kiểm tra provenance/calibration/coverage/hash. Kết quả XGBoost khám phá là `NO_GO_HISTORICAL_TEST_MAE_THRESHOLD` (0/6 horizon đạt mức cải thiện 5% yêu cầu); persistence vẫn là fallback và chưa promote model. |
| Triển khai và vận hành | Thêm Dockerfile backend/frontend, `compose.release.yaml`, migration trước khi chạy API, readiness qua Nginx, preflight/smoke/load tools, cấu hình Prometheus/Alertmanager/Grafana, retention và quy trình backup/restore mã hóa. Đây là artifacts và kiểm tra triển khai, chưa phải bằng chứng hệ thống đã chạy production. |

## Thay đổi giao diện gần nhất theo yêu cầu

- Bỏ thông báo “pin hiện tại đủ để tới đích an toàn” khỏi thao tác tìm trạm tốt nhất; thao tác vẫn tìm và đề xuất trạm sạc.
- Trong demo, chi tiết trạm có thể hiển thị số cổng hoạt động/trống/đang sử dụng từ dữ liệu mô phỏng/runtime và ghi rõ nguồn. Không coi các số liệu mô phỏng này là telemetry vận hành ở release.

## Kiểm tra đã chạy trên workspace

- Backend, data-platform và release suite: **449 passed, 2 skipped** khi chạy cùng PostgreSQL/PostGIS và Redis. Hai test backup mã hóa bị skip do máy chưa có `age`/`age-keygen`.
- Frontend suite: **32 passed**; ESLint, TypeScript và production build đã qua sau thay đổi station detail gần nhất.
- Database mới đã migrate đến `0020_path_safe_ids`; `alembic check` không phát hiện upgrade operation mới.
- Không có Docker/Podman cục bộ để xác minh Compose; chưa có kết quả CI từ remote, staging SLO/load, hoặc diễn tập restore production.

## Việc còn thiếu để vận hành thật

Catalog trạm/cổng/xe cần operator duyệt; telemetry hiện hoàn toàn mô phỏng và aggregator chưa được chọn; chưa có occupancy history và holdout HCMC thực tế; chưa có model đạt release gate. Còn cần cấu hình OIDC production, chính sách retention được duyệt, backup/WAL-PITR ngoài site và bằng chứng staging/restore. Theo đó, workspace đã có thêm đường chạy release và các gate fail-closed nhưng chưa đủ dữ liệu và bằng chứng để coi là production-ready. Các gate theo thứ tự được theo dõi trong [from_demo_to_release.md](from_demo_to_release.md).
