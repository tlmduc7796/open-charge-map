# Kế hoạch dữ liệu cho bài toán đề xuất trạm

## Nguyên tắc

1. Ưu tiên dữ liệu thật có nguồn, phạm vi, thời gian và quyền sử dụng rõ ràng.
2. Dùng dữ liệu branch cũ làm một lớp tín hiệu hiện trạng; không xem nó là toàn bộ nhu cầu.
3. Mock/synthetic cho phần còn thiếu, nhưng lưu giả định thành cấu hình và gắn nhãn ở mọi sản phẩm.
4. `unknown` khác `0`; thiếu cost/grid/traffic không được âm thầm biến thành địa điểm rẻ/khả thi.
5. Lưu đủ khóa không gian-thời gian để có thể backtest theo vùng và theo thời gian.

## Ma trận ưu tiên thu thập

| Ưu tiên | Nhóm | Tối thiểu cần có | Tác dụng |
|---|---|---|---|
| P0 | Trạm hiện có | tọa độ, loại/cổng/công suất, access, uptime, giá, trạng thái, thời gian hiệu lực | Biết cung và đối thủ; kiểm tra vùng phủ |
| P0 | Nhu cầu/áp lực quan sát | session start/end, kWh, port occupancy/status, queue/wait nếu có, timestamp | Đo revealed demand và thiếu công suất ở trạm đã mở |
| P0 | Địa điểm ứng viên | tọa độ/parcel hoặc cell, loại địa điểm, quyền tiếp cận, diện tích/khả dụng nếu có | Không đề xuất điểm không thể triển khai |
| P1 | Di chuyển | traffic counts theo thời gian, road graph/speed, OD hoặc tuyến xe | Ước lượng nhu cầu dọc hành lang và thời gian tiếp cận |
| P1 | Dân cư và sạc tại nhà | population/building units, cư trú theo khu, home-charging access/proxy | Suy ra nhu cầu khu dân cư chưa được phản ánh qua giao dịch |
| P1 | POI/điểm đến | du lịch, khách sạn, trung tâm thương mại, depot, bến xe; giờ hoạt động | Tạo profile điểm đến và dwell time |
| P1 | Đội xe | loại xe, số xe/điểm tập kết, lịch chạy/ca, mức sạc tại depot | Mô hình nhu cầu tập trung của taxi/tour/fleet |
| P2 | Quy hoạch/scenario | dự án nhà ở, di dân, chính sách, dự báo EV, thời điểm hiệu lực | Kiểm tra nhu cầu dài hạn theo kịch bản |
| P2 | Lưới và kinh tế | công suất khả dụng, khoảng cách/chi phí đấu nối, tariff, đất, thiết bị, OPEX | Chuyển từ tiềm năng sang feasibility/economics |

Chính sách và kinh tế không nằm ngoài hệ thống. Đây là các **scenario inputs** mà đơn vị có thẩm quyền/đầu tư cung cấp qua contract ổn định; technical engine dùng chúng để lọc phương án, tính component metrics và chạy lại kết quả. Team kỹ thuật sở hữu schema, validation, provenance, versioning và calculation integration; policy/finance owner sở hữu quy tắc, giá trị và cách diễn giải nghiệp vụ.

## Vai trò cụ thể của dữ liệu cũ

| Có thể tái sử dụng nếu có | Dùng thế nào | Không thể kết luận riêng từ nó |
|---|---|---|
| Tọa độ và inventory trạm | Phân vùng nguồn cung hiện có, tìm gap không gian | Rằng vị trí chưa có trạm có cầu cao |
| Connector, số cổng, công suất | Capacity/compatibility và quy mô đối thủ | Khả năng đấu nối điện tại parcel mới |
| Session và kWh | Profile revealed demand theo thời gian | Nhu cầu bị bỏ lỡ hoặc mọi xe lưu thông |
| Occupancy/wait/port availability | Chỉ báo nghẽn/áp lực khi kiểm soát uptime/capacity | Lợi nhuận; nguyên nhân low utilization |
| Synthetic queue/session | Kiểm thử tính toán và trình diễn sensitivity | Độ chính xác thực tế tại Việt Nam |

Trong dữ liệu branch cũ hiện có các bộ nguồn/bộ mô phỏng dành cho occupancy, RDM và Queue Lab. Chúng có thể cung cấp cấu trúc schema, timing semantics, topology và mô phỏng áp lực, nhưng không nên đem nguyên mô hình đó sang làm demand forecaster/site ranker. Xem [repo README](../../README.md) và bài báo tham khảo để thống nhất ranh giới.

## Schema logic gợi ý

### `existing_sites.csv`

| Cột | Kiểu/đơn vị | Bắt buộc | Ghi chú |
|---|---|---:|---|
| `site_id` | string | Có | ID ổn định, không chứa PII |
| `lat`, `lon` | degree | Có | WGS84; validate trong vùng nghiên cứu |
| `site_type` | enum | Có | highway, urban, mall, depot, residential… |
| `connector_type` | enum/list | Có | Nêu rõ chuẩn/compatibility |
| `port_count`, `power_kw` | integer/number | Có | Công suất theo port và/hoặc site |
| `access_type`, `opening_hours` | string | Nên có | public/private, giờ mở |
| `price_vnd_per_kwh` | VND/kWh | Nên có | null nếu unknown; effective time |
| `uptime_ratio` | 0–1 | Nên có | Thời kỳ và phương pháp tính |
| `valid_from`, `valid_to` | datetime | Nên có | Lịch sử thay đổi inventory |
| `source_type`, `source_url`, `quality_status` | string | Có | provenance |

### `demand_observations.csv`

| Cột | Kiểu/đơn vị | Bắt buộc | Ghi chú |
|---|---|---:|---|
| `observation_id`, `site_id` | string | Có | site_id null nếu cell/OD aggregate |
| `interval_start`, `interval_minutes` | datetime/int | Có | Chuẩn hóa timezone |
| `session_count`, `energy_kwh` | count/kWh | Có nếu source có | Không thay null bằng 0 |
| `peak_ports_busy`, `available_ports` | count | Nên có | Chỉ rõ outage/maintenance |
| `wait_p50_min`, `wait_p90_min`, `abandon_count` | minutes/count | Tuỳ nguồn | Ghi rõ đo hay ước tính |
| `demand_class` | enum | Có | observed, proxy, synthetic |
| `source_type`, `is_synthetic`, `quality_status` | string/bool | Có | Nhãn bắt buộc |

### `candidate_sites.csv`

| Cột | Kiểu/đơn vị | Bắt buộc | Ghi chú |
|---|---|---:|---|
| `candidate_id`, `lat`, `lon` | string/degree | Có | ID và vị trí |
| `candidate_type` | enum | Có | parcel, grid_cell, corridor_node, existing_site_upgrade |
| `access_feasible` | bool/unknown | Có | Unknown phải hiện rõ |
| `land_cost_vnd`, `grid_capacity_kw`, `interconnection_cost_vnd` | VND/kW | Tuỳ nguồn | Không giả làm số thật |
| `permit_status`, `source_type`, `quality_status` | string | Có | feasibility/provenance |

### `demand_cells.csv` / `od_flows.csv`

Đơn vị có thể là cell theo lưới H3/geohash hoặc vùng hành chính; mọi phiên bản phải ghi `spatial_resolution`. Các trường cơ bản: `cell_id` hoặc `origin_id,destination_id`, `period`, `population_or_flow`, `ev_share_scenario`, `home_charging_share`, `poi_mix`, `estimated_sessions`, `estimated_kwh`, `source_type`, `scenario_id`, `is_synthetic`.

### `scenario_config` (JSON/YAML hoặc API payload)

Mỗi run dùng một package versioned. Các trường dưới đây là gợi ý contract, không bắt buộc tất cả phải có trong demo:

| Nhóm | Ví dụ trường | Ý nghĩa |
|---|---|---|
| Identity | `scenario_id`, `version`, `owner`, `effective_from`, `created_at` | Ai cung cấp, phiên bản nào, thời điểm hiệu lực |
| Run scope | `study_area`, `horizon_years`, `data_snapshot_id`, `algorithm_version` | Phạm vi tái lập |
| Technical | `coverage_minutes`, `capacity_target`, `connector_mix`, `candidate_rules` | Giả định/ràng buộc kỹ thuật |
| Policy | `priority_zones`, `minimum_coverage_share`, `grant_per_port`, `eligibility_rules` | Chính sách/mục tiêu được đơn vị phụ trách cấu hình |
| Finance | `budget_vnd`, `capex`, `opex`, `tariff`, `pricing`, `discount_rate`, `payback_limit` | Input hoặc tiêu chí theo định nghĩa của investor |
| Provenance | `source`, `units`, `value_status`, `quality_status`, `is_synthetic`, `notes` | Nguồn/chất lượng; `value_status` phân biệt provided, estimated, unknown, not_applicable |

Null/unknown phải khác 0 và khác “không áp dụng”. `null` chỉ biểu diễn chưa biết/chưa cung cấp; `not_applicable` phải là status tường minh. Với tổ chức đã có finance engine, có thể nhận metric/forecast đã tính sẵn qua adapter; contract vẫn yêu cầu định nghĩa, units, thời kỳ, nguồn và version. Hệ thống ghi lại chính xác package nào đã tạo ranking nào.

### `scenario_run_results`

Mỗi kết quả cần giữ `run_id`, `scenario_id/version`, `data_snapshot_id`, `algorithm_version`, selected sites/ports, component scores, hard-constraint violations, missing inputs, technical metrics, finance metrics, uncertainty/sensitivity summary và lineage. Nếu đổi chính sách hoặc giá, tạo run mới rồi so sánh delta; không ghi đè output cũ.

## Kiểm tra chất lượng

- CRS/tọa độ hợp lệ và nằm trong study area; loại trùng site/candidate.
- Timestamp timezone-aware, không có khoảng âm; hiệu lực inventory không chồng lấn bất thường.
- Session/energy không âm; session không vượt công suất/vật lý theo ràng buộc hợp lý.
- Tách `0` thực, `null/unknown` và `not applicable`.
- Đối soát status/outage với occupancy: cổng offline không tính là cung sẵn sàng.
- Spatial join/route distance dùng road network khi có thể; buffer đường chim bay chỉ là baseline.
- Ghi tỷ lệ thiếu, impute và độ phủ theo thời gian/vùng cho từng source.

## Kịch bản thu thập cho đội thi

1. **Ngày 1:** chốt một study area/hành lang nhỏ, người dùng quyết định và horizon.
2. **Ngày 2:** lập inventory nguồn mở/được phép dùng; ghi license, hạn chế độ phủ và ngày truy cập.
3. **Ngày 3:** hỏi mentor/đối tác bộ tối thiểu cần xin: inventory, transaction aggregate, outages, prices, candidate parcels/grid feasibility.
4. **Trong lúc chờ:** tạo synthetic theo schema y hệt, mọi dòng `is_synthetic=true`; không đặt giả định synthetic trong file “observed”.
5. **Khi nhận dữ liệu:** chạy validation, provenance review và so sánh phạm vi; không gộp nguồn nếu semantics khác nhau.

Với dữ liệu tài chính/chính sách, xin một ví dụ package đã ẩn thông tin nhạy cảm: metric nào họ dùng, đơn vị, kỳ tính, luật hard/soft, cách xử lý ưu đãi và ngày hiệu lực. Team không cần tự sáng tác policy; cần chứng minh hệ thống nhận package, validate được và đồng bộ kết quả khi package version đổi.
