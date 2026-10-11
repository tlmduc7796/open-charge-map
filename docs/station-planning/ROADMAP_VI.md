# Lộ trình triển khai branch station recommendation

Lộ trình đi từ câu hỏi sản phẩm đến demo có thể kiểm tra. Mỗi gate có đầu ra và điều kiện hoàn thành; chưa cần bắt đầu bằng model ML.

## Gate 0 — Đóng phạm vi

- Chốt một study area/hành lang, decision owner, horizon và loại trạm/capacity được đề xuất.
- Chốt một câu hỏi demo, một danh sách outputs và các claims được phép.
- Phỏng vấn nhanh tài xế/đội xe và một người đầu tư/quy hoạch; ghi pain points quan sát được vs giả thuyết.

**Hoàn thành khi:** product brief 1 trang có scope, user, decision, data status và out-of-scope.

## Gate 1 — Data inventory và schema

- Lập inventory station, demand/queue, traffic/OD, population/home charge, POI/fleet, candidates, grid/cost.
- Ghi provenance/license/freshness/coverage, permission cần xin từ doanh nghiệp.
- Chốt CSV/GeoJSON contracts trong [DATA_PLAN_VI.md](DATA_PLAN_VI.md), validate CRS/time/units/null.
- Map dữ liệu từ branch cũ vào `existing_sites` và `demand_observations` với nhãn đúng.
- Chốt interface versioned cho policy/finance packages: owner, effective date, units, null semantics, hard constraints vs objectives.

**Hoàn thành khi:** schema mẫu và data-gap matrix được review; observed/proxy/synthetic/unknown tách biệt.

## Gate 2 — Baseline không gian

- Tạo inventory cung hiện tại và candidate generator cho study area.
- Tạo baseline coverage theo road travel time; ghi rõ fallback straight-line nếu thiếu road graph.
- Tạo marginal gain/overlap và phương án expand-existing.
- Tạo demand aggregation theo giờ/ngày và baseline ranking dễ giải thích.

**Hoàn thành khi:** kết quả tính tay trên toy fixture khớp với hệ thống, overlap không bị cộng trùng và có giải thích score.

## Gate 3 — Synthetic scenario

- Tạo demand cells/OD + candidate + existing station data có seed.
- Thêm growth/home-charge/fleet/tourism và capacity/outage scenarios.
- Thêm ít nhất hai policy/finance packages minh họa trên cùng một data snapshot để kiểm tra đồng bộ/reproducibility khi rule hoặc budget thay đổi.
- Dùng cùng schema sản xuất dự kiến; gắn `is_synthetic=true`, config + assumptions.
- Sensitivity và rank stability; so no-build, expand-first, greedy, random feasible.

**Hoàn thành khi:** demo end-to-end tái lập được và không diễn giải synthetic thành ground truth.

## Gate 4 — Bản đồ/UX demo

- Map layers, controls, ranking table, explanation, compare portfolio, export.
- Trình bày confidence, missing data, provenance, scenario IDs.
- Ghi walkthrough 5–7 phút cùng một thông điệp và một use case thống nhất.

**Hoàn thành khi:** người xem có thể đổi assumptions, hiểu vì sao gợi ý thay đổi và phân biệt mô phỏng với dữ liệu quan sát.

## Gate 5 — Dữ liệu đối tác và pilot

- Xin inventory/cổng/status/pricing/transactions aggregate/candidate parcels/grid feasibility.
- Thỏa thuận quyền sử dụng, PII minimization, retention và aggregation.
- Validate completeness, temporal coverage, site identity, outages, connector/capacity semantics.
- Spatial-temporal backtest; review với operator/planner; triển khai pilot một vài candidate.

**Hoàn thành khi:** có data quality approval, benchmark độc lập và một quy trình đo kết quả sau triển khai.

## Gate 6 — Kinh tế đầu tư (chỉ khi đủ dữ liệu)

- Bổ sung capex thiết bị, đất/lease, đấu nối, tariff, demand charge, OPEX, downtime, pricing, utilization ramp và subsidy assumptions.
- Phân tích NPV/payback theo range và rủi ro; review tài chính của operator.
- Không xuất “profit maximizing” cho đến khi economics được hiệu chỉnh và backtest.
- Kiểm tra công thức/metric theo ví dụ chuẩn do finance owner cung cấp; engine phải ghi formula version, units, period và input lineage.
- Cho phép cắm finance engine ngoài qua adapter nếu doanh nghiệp có hệ thống riêng; không buộc họ phải thay cách kế toán để dùng site planner.

## Phân chia công việc gợi ý cho team

| Workstream | Việc chính | Handoff |
|---|---|---|
| Problem/product | phỏng vấn, use case, claims, demo narrative | Gate 0 brief |
| Data | inventory, source/licensing, schema, validation | Gate 1 contracts |
| Spatial/optimization | road access, coverage, candidate selection, capacity | Gate 2 baseline |
| Simulation | synthetic assumptions, scenario generator, rank sensitivity | Gate 3 fixtures |
| UX/demo | map, ranking, explainability, export | Gate 4 walkthrough |
| Partnerships | data request, feasibility/economics, pilot | Gate 5/6 evidence |

## Rủi ro cần theo dõi

- **Observed-demand bias:** giao dịch chỉ có ở nơi có trạm.
- **Supply confounding:** offline/giá/connector/access làm thay đổi utilization.
- **Overclaiming:** synthetic hoặc proxy bị trình bày như dữ liệu thật.
- **Spatial leakage:** test ngẫu nhiên làm trạm gần nhau xuất hiện đồng thời ở train/test.
- **False precision:** chi phí lưới/đất và EV growth chưa biết nhưng điểm số trông chính xác.
- **Forecast uncertainty:** quy hoạch/migration/adoption có thể đổi; cần scenario/range.
- **Objective mismatch:** coverage/social access và investor economics có thể xung đột; hiển thị trade-off.
