# M4 — Frontend Planner

## Prompt giao việc

Bạn phụ trách giao diện station planning trên frontend hiện có của `fix/ui`. Đọc kế hoạch tổng thể, `SHARED_CONTRACT_VI.md`, khảo sát App/map/API client mới nhất rồi tạo feature riêng cho planner. Không sửa luồng driver thành nơi chứa logic đầu tư.

## Mục tiêu

Người xem có thể chọn pilot/scenario, xem danh sách địa điểm đề xuất trên bản đồ và bảng, mở giải thích cho từng candidate, so sánh các phương án và nhận biết rõ dữ liệu thật/giả định/thiếu.

## Task nhỏ

1. **Điểm vào:** thêm tab/mode Planner theo pattern navigation hiện tại; giữ nguyên màn hình hành trình/tìm trạm của tài xế.
2. **Map interaction:** hiển thị candidate markers, existing stations/coverage layer, selected candidate và pilot boundary. Dùng map provider/types hiện có nếu phù hợp.
3. **Scenario panel:** chọn profile/pilot extent/data snapshot/technical options; finance/policy chỉ hiện khi package hỗ trợ. Dùng default demo có nhãn, không giả làm default thị trường.
4. **Recommendations:** ranking list hiển thị rank, score, evidence coverage, eligibility, demand/coverage/capacity/overload/cost status. Null/unknown phải hiện “chưa có dữ liệu”, không 0.
5. **Explanation/comparison:** component score, constraint reasons, source, timestamp, synthetic/proxy labels, warnings và delta giữa hai phương án.
6. **Typed client:** khai báo TS request/response theo shared API contract; không query DB hoặc tự tính score ở browser.
7. **States:** loading, API error, invalid request, no candidates, partial unknowns, empty state và mobile/viewport behavior phù hợp demo.

## Không thuộc module

- Sửa backend route/schema hoặc tự đổi API endpoint.
- Dựng router/state library/chart library mới trước khi xác minh hiện có.
- Hiển thị finance metrics như verified result khi source unknown.
- Nhét logic ranking vào map marker/list component.

## Acceptance

- Từ tab Planner chạy được một scenario và nhìn thấy recommendation list + map.
- Chọn candidate hiển thị đầy đủ lý do, điều kiện, nguồn và missing data.
- Scenario result phân biệt synthetic/proxy/observed; chi phí/finance chưa có thì unavailable.
- Driver flow vẫn hoạt động như trước.
- UI có thể dùng mock JSON đúng contract nếu backend chưa merge, sau đó thay bằng API client không đổi semantics.

## Handoff

Ghi component/API client ownership, route/nav integration, screenshot hoặc walkthrough, states đã cover, cách chạy và backend fields còn thiếu.
