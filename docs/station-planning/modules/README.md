# Brief triển khai theo module

Các file trong thư mục này được thiết kế để giao cho từng thành viên hoặc AI agent làm việc độc lập. Đọc [kế hoạch tổng thể](../IMPLEMENTATION_PLAN_VI.md) trước, rồi đọc [hợp đồng chung](SHARED_CONTRACT_VI.md) và brief của module được giao.

## Quy tắc cho mọi module

1. Không tự đổi tên API, JSON field, enum, đơn vị, CRS, semantics của `unknown`, hard constraint hoặc ý nghĩa score đã chốt trong hợp đồng.
2. Nếu phát hiện hợp đồng thiếu/sai, nêu đề xuất và chờ integration owner cập nhật contract trước khi implement phần phụ thuộc.
3. Chỉ sửa code thuộc ownership của module; liệt kê chính xác file đã đổi và cách tích hợp.
4. Không biến dữ liệu synthetic/proxy thành dữ liệu quan sát thật. Giữ provenance đến đầu ra API/UI.
5. Không thêm package, DB table, migration hoặc endpoint ngoài brief nếu chưa có lý do được thống nhất.
6. Trả lời cuối bằng: thay đổi, quyết định kỹ thuật, kiểm tra đã chạy, giới hạn còn lại và contract nào cần cập nhật.

## Thứ tự và ownership

| Module | Owner area | Phụ thuộc chính | File brief |
|---|---|---|---|
| M1 Data & GIS | Nguồn dữ liệu, HCMC boundary, candidate/demand seed, validation | Shared contract | [M1](M1_DATA_GIS_VI.md) |
| M2 Recommendation engine | Hai nhánh phối hợp: M2A demand ML và M2B site optimization/ranking | Shared contract + sample từ M1 | [M2B engine](M2_RECOMMENDATION_ENGINE_VI.md), [pipeline M2A](../ML_DEMAND_PIPELINE_VI.md) |
| M3 Backend & DB integration | FastAPI contract, service/repository, PostGIS, persistence nếu cần | Shared contract + interface M2 | [M3](M3_BACKEND_DB_VI.md) |
| M4 Frontend Planner | Tab/mode, map, ranked list, explanations, scenario controls | Shared contract + API mock/OpenAPI | [M4](M4_FRONTEND_PLANNER_VI.md) |
| M5 Demo & integration | Seed scenario, integration acceptance, provenance/limitations | M1–M4 | [M5](M5_DEMO_INTEGRATION_VI.md) |

M1, M3 scaffolding và M4 layout có thể bắt đầu song song. Trong M2, M2A xây pipeline ước lượng nhu cầu; M2B xây bộ lọc/ranking/tối ưu vị trí. Hai nhánh có thể phát triển song song sau khi khóa payload demand dùng chung; M2B phải chạy được bằng baseline scenario khi M2A chưa có model phù hợp. M3 không tự viết lại công thức; M4 có thể dùng mock theo contract nhưng không tự tạo API riêng. M5 tích hợp khi các module có artifact bàn giao.

## Quy trình giao việc song song

- Tất cả cùng bắt đầu từ commit chứa `SHARED_CONTRACT_VI.md`.
- Mỗi module làm trên branch riêng dựa trên cùng baseline `fix/ui` feature branch, hoặc worktree riêng nếu agent cần checkout độc lập.
- Pull request ghi `Module: Mx`, checklist acceptance của brief, API/DB changes, dữ liệu mới và lệnh xác minh.
- Integration owner review contract trước; sau đó review file ownership và ghép các PR theo dependency.
- Không merge nhiều PR cùng lúc nếu đang đổi chung `api_v1.py`, app bootstrap, shared TypeScript types hoặc `tables.toml`; chia phần đó theo thứ tự hoặc chỉ định một owner.

## Handoff format tối thiểu

```text
Module:
Branch/base commit:
Files changed:
Contract version:
How to run/check:
Known limitations:
Follow-up/contract change needed:
```
