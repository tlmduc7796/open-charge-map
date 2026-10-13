# M2B — Domain engine đề xuất địa điểm

## Prompt giao việc

Bạn phụ trách nhánh M2B (site recommendation/optimization) trong M2. Đọc `../IMPLEMENTATION_PLAN_VI.md`, `../ML_DEMAND_PIPELINE_VI.md`, `SHARED_CONTRACT_VI.md`, `../CONSTRAINT_MATRIX_HCMC_VI.md` và data contract M1. Implement logic thuần, giải thích được, tái lập; không đặt API, không truy cập DB và không tự đặt policy/finance. M2A demand ML là pipeline riêng; M2B tiêu thụ demand output qua interface đã thống nhất, đồng thời phải hỗ trợ baseline/scenario khi model chưa khả dụng.

## Mục tiêu

Với candidate set và cùng một scenario, xác định eligibility, tính các thành phần kỹ thuật, sắp xếp candidate và trả lý do. Kết quả là screening/ranking có giới hạn dữ liệu, không phải dự báo chắc chắn nhu cầu hay đầu tư tối ưu.

## Input P7/P8 đã chốt

Snapshot `data_platform/station_planning/demo_hcmc_v3` có `access_matrix.csv`, `access_model.json`, `technical_constraints_package.json`, `candidate_constraints.csv` và `candidate_eligibility.csv`. Đọc [quyết định P7/P8](../P7_P8_DECISIONS_VI.md). Baseline access profile `normal` là proxy 20 km/h, circuity 1,3, cộng 2 phút và ngưỡng 15 phút. Access profiles không được tự ghép với demand low/base/high. Ma trận có cả cặp khác phường.

P8 dùng 4 DC × 80 kW, budget tham chiếu portfolio 10 tỷ VND theo `base_cost`, utilization target 0,8 và minimum evidence coverage 0,6. Con số portfolio không được dùng làm ngưỡng mặc định cho một candidate; M2 chỉ áp bộ lọc từng candidate khi run nhận `technical.budget_vnd` do người dùng nhập. Weights 30/25/20/15/10; bỏ metric unknown khỏi tử/mẫu nhưng báo trọng số thiếu. Giữ physical feasibility unknown là conditional; không gán readiness cao từ chi phí synthetic. Engine M2B hiện đã triển khai ranking từng candidate, nhưng chưa chọn portfolio hoặc tính ROI.

## Task nhỏ

1. **Domain types:** ánh xạ candidate, site inventory, demand evidence, scenario, constraint result, metric, provenance và recommendation response theo shared contract.
2. **Hard constraints:** boundary, loại candidate, giãn cách, quyền/site access, safety/permit, grid/site capacity, cấu hình sạc và budget từng candidate. `fail` chỉ bằng chứng xác nhận infeasible; thiếu thì `conditional/unknown`.
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
- ROI/finance metrics `unknown/unavailable` nếu chưa có package đủ điều kiện; CAPEX `base_cost` có thể trả như scenario assumption với provenance synthetic, không đưa vào readiness score.

## Handoff

Bàn giao function signature/domain types, ví dụ input/output bám contract, formula/version, giới hạn và cách API service gọi. Báo contract change đề xuất trước khi phá schema.
