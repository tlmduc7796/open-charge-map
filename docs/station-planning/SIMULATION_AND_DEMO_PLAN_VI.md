# Mô phỏng và demo đề xuất trạm

## Mục tiêu demo

Cho người xem thấy một quyết định có thể kiểm tra: khi chọn một ngân sách và kịch bản nhu cầu, hệ thống đề xuất một tập vị trí, cho thấy vùng/luồng được phục vụ thêm, quy mô sơ bộ, các trade-off và điều gì làm thứ hạng thay đổi.

Demo cần nói rõ **data synthetic, scenario minh họa** trên bản đồ, bảng, file export và lời thuyết trình. Không trình bày kết quả như bản đồ nhu cầu thật của Việt Nam.

## Khu vực minh họa

Chọn một study area nhỏ, dữ liệu có thể kiểm tra được: ví dụ một đoạn hành lang du lịch/đường cao tốc cùng cụm đô thị-điểm đến, hoặc một quận/thành phố. Không dùng toàn quốc làm prototype đầu vì độ phân giải và giả định sẽ khó giải thích.

Tạo các lớp:

1. **Nhu cầu hiện tại giả lập:** cells/OD theo khung giờ và ngày thường/cuối tuần.
2. **Nhu cầu tăng trưởng:** 3 scenario `low/base/high` cho EV share; một biến riêng cho khả năng sạc tại nhà.
3. **Dòng du lịch/fleet:** luồng qua hành lang, điểm đến, depot và thời gian hoạt động; `autonomous` chỉ là sensitivity tùy chọn.
4. **Cung hiện có:** trạm, số cổng, loại sạc, uptime/availability và giá; nếu là data thật thì trích nguồn/ngày; thiếu thì gắn synthetic.
5. **Ứng viên:** nút trên road graph, bãi/parcel giả định hoặc các điểm có thể triển khai; thêm cờ grid/land/permit `feasible`, `infeasible`, `unknown`.
6. **Policy/finance packages:** cấu hình ngân sách, grant, vùng ưu tiên, capex/opex, tariff, pricing hoặc ngưỡng payback; mọi giá trị demo gắn `illustrative_assumption` và `scenario_version`.

## Sinh synthetic có kiểm soát

Không sinh từng điểm ngẫu nhiên độc lập. Sinh cấu trúc có thể giải thích:

- Đặt các demand cells/OD theo các trung tâm dân cư, POI và luồng tuyến.
- Gán intensity theo loại vùng/ngày/giờ; thêm seasonal/tourism multiplier như tham số scenario.
- Sample session count từ Poisson/negative binomial với seed cố định; energy/session theo phân phối cấu hình.
- Bắt đầu EV share, home-charging share, fleet fraction và tăng trưởng bằng config JSON có đơn vị, range, nguồn tham khảo/nhãn `illustrative_assumption`.
- Tạo trạm hiện có và availability độc lập với cầu, để mô phỏng outage; sinh occupancy/queue theo capacity để thử tín hiệu áp lực.
- Không tạo nhãn “optimal site” trực tiếp từ cùng công thức score rồi dùng nó để tuyên bố model học được optimum. Thuật toán phải tính giải pháp từ demand/candidate inputs.

Ví dụ cấu hình cần ghi (giá trị demo phải chọn và công khai trong file, không chôn trong code):

```yaml
scenario_id: base_demo_v1
scenario_version: 1
data_status: synthetic
study_area: to-be-selected
technical:
  horizon_years: 3
  coverage_threshold_minutes: 15
demand:
  ev_share: 0.12
  home_charging_share: 0.35
  tourism_multiplier_weekend: 1.4
  fleet_share_of_sessions: 0.20
policy:
  priority_zones: []
  minimum_coverage_share: null # unknown/unprovided; not zero
  grant_per_port_vnd: null
finance:
  budget_vnd: null
  capex_per_port_vnd: null
  annual_opex_per_site_vnd: null
  tariff_vnd_per_kwh: null
  revenue_vnd_per_kwh: null
  discount_rate: null
  payback_limit_years: null
random_seed: 20261011
```

Các con số demand phía trên chỉ minh họa dạng trường; các trường `null` nghĩa là unknown/chưa cung cấp, không được coi là số 0. “Không áp dụng” phải có trạng thái riêng trong schema. Trước khi chạy demo, nhóm phải chọn khu vực, lý do chọn từng value, khoảng sensitivity và kiểm tra units; không trình bày các giá trị mẫu này là số liệu thị trường. Có thể thêm một package minh họa thứ hai với ngân sách/grant/tariff giả định để chứng minh hệ thống đồng bộ ranking khi đầu vào đổi; kết quả đó vẫn phải ghi rõ `scenario`.

## Thuật toán demo

1. Chuyển demand cells/OD thành điểm nhu cầu có trọng số theo scenario.
2. Tính thời gian tiếp cận đến trạm hiện có theo road graph; gắn compatibility/access/uptime.
3. Tính unmet/underserved weight. Nếu không mô hình được censored demand thì gọi là proxy, không gọi là ground truth.
4. Với mỗi candidate, tính marginal demand/coverage mới trừ overlap đã được phục vụ.
5. Loại candidate infeasible; giữ unknown nhưng gắn risk/uncertainty rõ.
6. Greedy chọn candidate/capacity theo marginal gain và budget, hoặc chạy capacitated maximum coverage.
7. Ước lượng charger count từ peak concurrency scenario và mục tiêu wait/utilization; ghi rõ đây là capacity model, chưa phải forecast chính xác nếu arrival/service data synthetic.
8. Xếp hạng, hiển thị lý do đóng góp; nếu có finance/policy package thì tính các metric được cấu hình, nếu thiếu thì để `unknown/unavailable`.
9. Khi user đổi package hoặc version (ví dụ budget, grant, vùng ưu tiên, tariff), chạy một `run_id` mới trên cùng data snapshot và hiển thị chênh lệch ranking/coverage/cost/finance metrics.

## Luồng trình diễn (5–7 phút)

1. Chọn khu vực và xem trạm hiện có cùng demand layers; legend hiển thị nguồn và synthetic.
2. Chọn horizon, ngân sách và `low/base/high`; hiển thị hệ số giả định có thể chỉnh.
3. Chạy xếp hạng; chọn một candidate để xem nhu cầu/luồng gần đó, vùng tiếp cận mới, capacity đề xuất, grid status và dữ liệu còn thiếu.
4. So sánh xây mới với mở rộng một trạm đang có utilization cao.
5. Tắt/giảm home charging, thay growth, traffic hoặc outage; quan sát top sites thay đổi.
6. So với greedy baseline/no-build và export bảng kết quả + assumptions.
7. Kết luận bằng giới hạn và danh sách dữ liệu doanh nghiệp cần cung cấp để chuyển từ prototype sang quyết định thật.

## Thành phần UI gợi ý

- **Bản đồ:** existing sites, candidates, demand cells/OD, service areas, candidate status.
- **Bảng ranking:** tổng điểm/từng thành phần, incremental coverage, demand served, cost status, confidence, scenario.
- **Panel giải thích:** “xếp cao vì…”, “bị trừ vì…”, “không biết vì thiếu…”.
- **Scenario controls:** budget, time horizon, home charging, EV growth, fleet/tourism, grid feasibility, coverage threshold.
- **Policy/finance import:** nạp/chọn package version; cho biết owner, effective date, units, trường thiếu và validation status.
- **Compare:** selected portfolio vs baseline, expand-existing vs build-new.
- **Audit/export:** run ID, config, source, assumptions, output CSV/JSON.

## Báo cáo metric

- Nhu cầu proxy được phục vụ có trọng số; tách new coverage khỏi overlap.
- Thời gian/độ dài tiếp cận giảm; số demand cells/OD mới đạt ngưỡng.
- Candidate portfolio cost units và công suất; không gọi là VND/ROI nếu là proxy.
- Peak ports/utilization/wait SLA theo kịch bản; trình bày distribution, không chỉ mean.
- Top-k rank stability qua low/base/high và perturbation.
- Tỷ lệ từng score dựa trên observed/proxy/synthetic/unknown.
- Chênh lệch phương án khi thay policy/finance package; phân biệt thay đổi do technical data với thay đổi do business rules.

## Baseline và kiểm tra

- No-build: chỉ dùng hạ tầng hiện hữu.
- Expand-first: thêm cổng vào trạm có áp lực cao và feasibility tốt.
- Greedy coverage/cost: chọn site theo marginal gain dưới budget.
- Random feasible: đối chứng đơn giản, seed cố định.
- Sensitivity: bỏ một nhóm feature; biến thiên EV growth, home charging, traffic, uptime, grid/cost ranges.

Chưa dùng accuracy trên synthetic làm claim ngoài demo. Nếu team có dữ liệu thật sau khi thu hút đối tác, làm temporal và spatial holdout, đối chiếu nhu cầu dự báo với aggregate session/energy, đồng thời kiểm tra vùng không có trạm bằng nguồn proxy/requests độc lập.

## Demo gate

Demo đạt yêu cầu khi:

- Toàn bộ nguồn/giả định hiển thị trên UI và export; synthetic luôn có watermark/label.
- Một run tái lập được từ `scenario_id`, seed, config và data version.
- Policy/finance package được validate, version hóa và liên kết với `run_id`; thay package tạo kết quả mới có thể so sánh, không ghi đè lịch sử.
- Trạm hiện có được khấu trừ trước khi tính marginal coverage; không cộng trùng người/luồng.
- Có phương án expand-existing để so với build-new.
- Người xem thay được ít nhất ba giả định và thấy giải thích thứ hạng thay đổi.
- Infeasible/unknown được phân biệt; không xếp một vị trí unknown như đã chắc chắn triển khai được.
- Nếu chưa có economics thật, chỉ hiển thị scenario metrics/unknown và gắn nhãn; khi có package đối tác, chỉ gọi ROI/NPV là kết quả theo input/công thức đã xác nhận.
