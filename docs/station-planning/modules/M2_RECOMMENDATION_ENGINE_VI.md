# M2B — Domain engine đề xuất địa điểm

## Prompt giao việc

Bạn phụ trách nhánh M2B (site recommendation/optimization) trong M2. Đọc `../IMPLEMENTATION_PLAN_VI.md`, `../ML_DEMAND_PIPELINE_VI.md`, `SHARED_CONTRACT_VI.md`, `../CONSTRAINT_MATRIX_HCMC_VI.md` và data contract M1. Implement logic thuần, giải thích được, tái lập; không đặt API, không truy cập DB và không tự đặt policy/finance. M2A demand ML là pipeline riêng; M2B tiêu thụ demand output qua interface đã thống nhất, đồng thời phải hỗ trợ baseline/scenario khi model chưa khả dụng.

## Mục tiêu

Với candidate set và cùng một scenario, xác định eligibility, tính các thành phần kỹ thuật, sắp xếp candidate và trả lý do. Kết quả là screening/ranking có giới hạn dữ liệu, không phải dự báo chắc chắn nhu cầu hay đầu tư tối ưu.

## Task nhỏ

1. **Domain types:** ánh xạ candidate, site inventory, demand evidence, scenario, constraint result, metric, provenance và recommendation response theo shared contract.
2. **Hard constraints:** boundary, quyền/loại candidate, access, safety/permit, grid/site capacity khi có dữ liệu. `fail` chỉ bằng chứng xác nhận infeasible; thiếu thì `conditional/unknown`.
3. **Metrics:** demand potential; marginal coverage gain; network/segment fit; site/grid readiness; evidence coverage; overload risk/capacity fit khi input đủ.
4. **Score profiles:** technical opportunity mặc định. Đọc weights/version từ config; không hard-code policy của nhà đầu tư. Chuẩn hóa score direction để cao hơn luôn tốt hơn trong profile.
5. **Missing evidence:** không coi null là 0. Trả điểm con cùng status/source và coverage của evidence; áp ngưỡng tối thiểu hoặc conditional status do contract cấu hình.
6. **Portfolio-aware behavior:** v0.1 xếp hạng candidate độc lập; nếu implement chọn nhiều site, metric coverage phải tính marginal gain sau site đã chọn. Không chọn nhiều site trùng lợi ích mà không nêu lý do.
7. **Sensitivity:** chạy lại theo profile/weight/scenario inputs, trả delta/rank movement; không bịa xác suất cho low/base/high case.
8. **Pure module:** không import FastAPI/Pydantic API models/SQL/React; application layer sẽ adapter input/output.

## Nguyên tắc đánh giá

- Giữ các khái niệm `coverage_gap`, `competition`, `network_fit` tách rời; không dùng một biến “competition” vừa phạt lợi nhuận vừa đại diện thiếu coverage.
- Bài toán investor và policy có thể ưu tiên khác nhau. Nếu chưa có package tương ứng, chỉ trả technical profile.
- Occupancy/wait history là signal ở site có quan sát, không phải full-city demand. Synthetic signal chỉ phục vụ sensitivity/demo.
- Công suất đề xuất là dải/cấu hình scenario, không là xác nhận utility connection.

## Không thuộc module

- Huấn luyện/đánh giá model demand (thuộc M2A) hoặc copy wait-time estimator từ `fix/ui`.
- Tính ROI tự đặt CAPEX/OPEX/tariff.
- Query PostGIS hoặc thêm endpoint.
- Tuyên bố vị trí tối ưu toàn TP.HCM khi candidate set/pilot chỉ là một phần.

## Acceptance

- Cùng input/config/version trả cùng output.
- So sánh ít nhất hai candidate cho component metrics, hard-constraint reasons, missing evidence và provenance.
- Candidate có evidence ít không thắng tự động chỉ do thiếu dữ liệu.
- Thay profile/weight/scenario làm kết quả thay đổi nhất quán, có component breakdown.
- Finance metrics `unknown/unavailable` nếu chưa có package đủ điều kiện.

## Handoff

Bàn giao function signature/domain types, ví dụ input/output bám contract, formula/version, giới hạn và cách API service gọi. Báo contract change đề xuất trước khi phá schema.
