# Kế hoạch dữ liệu cho bài toán đề xuất trạm

## Nguyên tắc

1. Ưu tiên dữ liệu thật có nguồn, phạm vi, thời gian và quyền sử dụng rõ ràng.
2. Dùng dữ liệu wait-time/occupancy trên branch `fix/ui` làm một lớp tín hiệu hiện trạng nếu có thể import được; không xem nó là toàn bộ nhu cầu.
3. Mock/synthetic cho phần còn thiếu, nhưng lưu giả định thành cấu hình và gắn nhãn ở mọi sản phẩm.
4. `unknown` khác `0`; thiếu cost/grid/traffic không được âm thầm biến thành địa điểm rẻ/khả thi.
5. Lưu đủ khóa không gian-thời gian để có thể backtest theo vùng và theo thời gian.
6. Pin địa giới TP.HCM theo phiên bản có hiệu lực sau hợp nhất năm 2025; không trộn dữ liệu quận/phường theo các bộ địa giới khác nhau nếu chưa có crosswalk.

## Bộ dữ liệu đã chốt cho demo ban đầu

Quyết định ngày 12/10/2026:

- **Loại khỏi bài toán:** `raw_data/admin_boundaries/ref.kml`. Không đọc file này để dựng catalog, enrich thuộc tính, tái sinh bộ trạm, tạo feature hoặc chạy engine. Các file lịch sử có thể ghi lineage đến `ref.kml`, nhưng pipeline planning chỉ đọc bộ demo đã chọn.
- **Existing sites mặc định:** `raw_data/charging_stations/hcm_dc80kw/hcm_dc80kw_5wards.geojson`; CSV cùng tên dùng để đối chiếu. Bộ này có **37 trạm thuộc 9 phường**, dù tên file còn `5wards`. Không ghép thêm bộ 668 trạm hoặc catalog khác vào cùng run mặc định; mở rộng quy mô phải là snapshot/scenario riêng.
- **Pilot extent:** hợp các polygon Sài Gòn, Bến Thành, Xuân Hòa, Tân Định, Phú Nhuận, Bình Thạnh, Tân Sơn Hòa, Thạnh Mỹ Tây và Bình Quới trong `raw_data/admin_boundaries/hcm_planning_units_2025.geojson`. Đối chiếu ID/phân bố trạm bằng `five_wards_report.json` trong thư mục bộ trạm. TP.HCM vẫn là macro study area; chỉ báo cáo metric trong pilot.
- **Nhãn existing sites:** `source_type=synthetic`, `is_synthetic=true`; giữ mã EVC, tọa độ, số cổng và cấu hình DC 80 kW của fixture. Công suất là giả định demo, không phải cấu hình thực đã xác minh. Không suy connector cụ thể chỉ từ nhãn DC. Giá bán sạc, uptime hoặc compatibility chưa biết để unknown; nếu bổ sung để mô phỏng phải ghi giả định riêng.
- **Bối cảnh (phần 3):** lọc dân số, POI và hạ tầng giao thông đã thu thập về pilot; giữ giá trị nguồn và provenance. Không thêm lưu lượng giao thông giả vào lớp đã lọc.
- **Nhu cầu (phần 5):** synthetic hoàn toàn, có cấu trúc không gian-thời gian hợp lý từ bối cảnh phần 3; EV share, home charging, session/kWh và profile giờ là giả định scenario. Dân số/POI là ngữ cảnh nguồn, không biến session/kWh sinh ra thành quan sát thực. Nếu phân bổ dân số xuống cell, trọng số có tổng bằng 1 trong mỗi phường, không lặp toàn bộ dân số ở mỗi cell.
- **Candidates (phần 4):** synthetic hoàn toàn nhưng có căn cứ địa lý: sinh một tập nhỏ ở POI/bãi xe phù hợp chưa có existing site trong fixture hoặc vùng giao thông cao giả định. Giữ ID POI/đối tượng giao thông tham chiếu và lý do sinh candidate; bản ghi candidate vẫn là synthetic. Build-new loại vị trí trùng existing sites; mở rộng trạm dùng `existing_site_upgrade`. Quyền tiếp cận, đất, điện và cấp phép chưa xác minh để unknown/conditional.
- **Vận hành (phần 6):** synthetic hoàn toàn trên 37 existing sites; sinh availability, outage, occupancy và session/queue nếu demo cần, có seed và kiểm tra nhất quán với số cổng/công suất/giờ mở cửa. Không import occupancy/wait của nhánh khác vào baseline demo này như quan sát thực.
- **Kinh tế (phần 9):** kết hợp biểu giá điện đã thu thập với ngân sách/CAPEX/OPEX/đất/đấu nối/giá bán và các hệ số kinh tế giả định. Chọn một lịch giá và cấp điện áp; giữ trạng thái xác minh của nguồn. Dùng kWh theo thời gian từ phần 5–6; economics chỉ là kết quả scenario, và unavailable khi thiếu input cần thiết.

Existing sites ở đây là nguồn cung nền của **kịch bản mô phỏng**, không phải toàn bộ trạm thực tế trong 9 phường. Khoảng trống độ phủ tính được là gap của fixture này. Nếu giảm tiếp số trạm, lưu danh sách site IDs, quy tắc chọn và snapshot riêng để kết quả tái lập được.

KML/CSV/GeoJSON là các bản biểu diễn cùng dữ liệu; chọn một bản để ingest, không cộng chúng thành nhiều nguồn trạm. Đường dẫn `input_data/...` trong một số báo cáo raw là metadata lịch sử; dùng đường dẫn `raw_data/...` hiện có, không coi đó là yêu cầu đọc lại nguồn bị loại.

## Lựa chọn nguồn theo 10 phần chuẩn bị

| Phần | Dữ liệu | Quyết định nguồn cho demo |
|---|---|---|
| 1 | Phạm vi không gian | Pilot 9 phường theo lớp địa giới đã chọn |
| 2 | Existing sites | Fixture `hcm_dc80kw_5wards`, 37 trạm mô phỏng |
| 3 | Dân cư, POI, giao thông | Lọc dữ liệu đã thu thập về pilot |
| 4 | Candidate sites | Synthetic hoàn toàn, dựa vào ngữ cảnh địa bàn/POI và giao thông giả định |
| 5 | Nhu cầu sạc | Synthetic hoàn toàn; số phiên, kWh, profile giờ theo scenario |
| 6 | Vận hành/áp lực trạm | Synthetic hoàn toàn; chỉ gắn với existing sites đã chọn |
| 7 | Ma trận tiếp cận | Haversine × 1,3; tốc độ giả định fast/normal/slow 25/20/12 km/h; cộng 2 phút; ngưỡng 15 phút |
| 8 | Ràng buộc kỹ thuật/chính sách | Package technical demo: 4 DC × 80 kW, budget 10 tỷ, evidence threshold 0,6; physical feasibility unknown giữ conditional; public-policy overlay tắt |
| 9 | Tài chính | Biểu giá đã thu thập + chi phí và hệ số kinh tế giả định |
| 10 | Metadata/tái lập | Ghi đúng nguồn, units, chất lượng, seed, versions và các phụ thuộc thực tế |

### Quy tắc sinh dữ liệu theo ngữ cảnh

- **Phần 3:** chọn dân số đúng 9 `unit_id`; lọc POI theo tọa độ và cắt giao thông theo polygon pilot. Đối tượng qua nhiều phường giữ danh sách vùng, không cộng trùng thành nhiều thực thể. Xử lý nhóm POI nghi trùng trước khi đếm đặc trưng.
- **Phần 4:** ưu tiên POI/bãi xe có nghĩa với sạc công cộng, kiểm tra vị trí với 37 existing sites. Ghi khoảng cách đến trạm gần nhất và quy tắc loại trùng; ngưỡng khoảng cách là tham số demo. “Chưa có trạm” chỉ nói về fixture, không khẳng định ngoài thực tế. Vị trí candidate có thể lấy từ POI nguồn nhưng sự tồn tại/quyền triển khai trạm mới là giả định.
- **Giao thông cao:** nguồn hiện chỉ có hạ tầng, không có counts/OD theo giờ. Có thể dùng ngữ cảnh đường/bến/bãi/nút giao để đặt vùng `traffic_intensity_scenario` cao, hoặc đặc trưng hạ tầng làm proxy riêng. Không gọi số POI, đèn tín hiệu hay tuyến đường là lưu lượng xe quan sát; lưu lý do và trạng thái scenario/proxy cho từng feature.
- **Phần 5–6:** lưu các phân phối/hệ số và seed; có low/base/high, ngày thường/cuối tuần, giờ cao điểm và outage. Demand/session/energy/occupancy không âm; occupied ports không vượt available ports; session/công suất/điện năng phải phù hợp giả định mô hình. Không sinh nhãn site tối ưu hoặc chỉnh demand để bắt một candidate định trước thắng.
- **Phần 9:** tách input nguồn biểu giá khỏi giả định chi phí, ghi units và kỳ tính từng trường. Không gộp hai lịch giá, không suy cấp điện áp mua điện từ DC 80 kW, không coi giá mua điện là giá bán sạc. Tôn trọng ranh giới giờ nửa tiếng khi ghép kWh.

Snapshot hiện hành ngày 13/10/2026 là `hcmc-nine-wards-demo-v3` tại `data_platform/station_planning/demo_hcmc_v3`; v1/v2 cùng báo cáo tương ứng được lưu trong Git stash local, không được push. Có 37 existing sites, 18 candidates, 27 demand nodes; bối cảnh pilot gồm 3.708 POI và 1.640 đối tượng giao thông. Demand/vận hành giữ 7 ngày, bước 30 phút, ba profile low/base/high. P7 có 4.455 dòng access matrix; P8 có 180 constraint results và 18 eligibility summaries. Chi tiết quyết định, công thức và giới hạn nằm trong [P7_P8_DECISIONS_VI.md](P7_P8_DECISIONS_VI.md). Các phần 1–10 đã có đặc tả/output cho demo; dữ liệu đất/điện/permit vẫn unknown theo quy tắc đã chốt. Xem [hướng dẫn dữ liệu và tạo lại](../../data_platform/station_planning/README.md), `manifest.json`, `data_dictionary.json` và `validation_report.json`. Raw inputs giữ nguyên; snapshot v3 chưa được nối với engine M2/API/DB hiện có.

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

Với địa giới mới, lưu `boundary_id`, `boundary_version`, `valid_from`, `source_url` và crosswalk từ mã địa giới cũ. Địa bàn sau hợp nhất bao gồm TP.HCM cũ, Bình Dương cũ và Bà Rịa–Vũng Tàu cũ; nên giữ thêm trường `legacy_area` để phân tích lịch sử mà không nhầm tên/mã hành chính.

Chính sách và kinh tế không nằm ngoài hệ thống. Đây là các **scenario inputs** mà đơn vị có thẩm quyền/đầu tư cung cấp qua contract ổn định; technical engine dùng chúng để lọc phương án, tính component metrics và chạy lại kết quả. Team kỹ thuật sở hữu schema, validation, provenance, versioning và calculation integration; policy/finance owner sở hữu quy tắc, giá trị và cách diễn giải nghiệp vụ.

## Vai trò cụ thể của dữ liệu cũ

| Có thể tái sử dụng nếu có | Dùng thế nào | Không thể kết luận riêng từ nó |
|---|---|---|
| Tọa độ và inventory trạm | Phân vùng nguồn cung hiện có, tìm gap không gian | Rằng vị trí chưa có trạm có cầu cao |
| Connector, số cổng, công suất | Capacity/compatibility và quy mô đối thủ | Khả năng đấu nối điện tại parcel mới |
| Session và kWh | Profile revealed demand theo thời gian | Nhu cầu bị bỏ lỡ hoặc mọi xe lưu thông |
| Occupancy/wait/port availability | Chỉ báo nghẽn/áp lực khi kiểm soát uptime/capacity | Lợi nhuận; nguyên nhân low utilization |
| Synthetic queue/session | Kiểm thử tính toán và trình diễn sensitivity | Độ chính xác thực tế tại Việt Nam |

Các dữ liệu wait-time/occupancy trên branch `fix/ui` có thể cung cấp schema, timing semantics, topology và một lớp tín hiệu áp lực. Chỉ import aggregate/features được nhóm thống nhất; không chuyển nguyên mô hình wait sang làm demand forecaster/site ranker.

Ma trận rule/score demo và các nguồn để tham khảo nằm trong [CONSTRAINT_MATRIX_HCMC_VI.md](CONSTRAINT_MATRIX_HCMC_VI.md). Scenario payload có JSON Schema tại [`schemas/planning-scenario.schema.json`](schemas/planning-scenario.schema.json), kèm [scenario mẫu](examples/hcmc-scenario-base.json).

Đối với boundary, dùng Nghị quyết 202/2025/QH15 làm căn cứ đơn vị hành chính cấp tỉnh; lấy geometry và mã phường/xã từ bộ dữ liệu hành chính/GIS chính thức có ngày hiệu lực, lưu nguồn/version cụ thể. Không tự vẽ ranh giới từ tên địa danh.

## Schema logic gợi ý

Các bảng chuẩn đã được bổ sung theo mô tả dưới đây trong snapshot **v3**. Xem [đối chiếu DATA_PLAN và dữ liệu v3](DATA_PLAN_ALIGNMENT_VI.md) và [schema máy kiểm tra](schemas/planning-datasets.schema.json). Required nghĩa là có field; giá trị chưa biết giữ null với status/source rõ ràng. Các trường cũ có ý nghĩa chi tiết hơn vẫn được giữ để adapter ánh xạ.

### `existing_sites.csv`

| Cột | Kiểu/đơn vị | Bắt buộc | Ghi chú |
|---|---|---:|---|
| `site_id` | string | Có | ID ổn định, không chứa PII |
| `lat`, `lon` | degree | Có | WGS84; validate trong vùng nghiên cứu |
| `site_type` | enum | Có | highway, urban, mall, depot, residential… |
| `connector_type` | enum/list/null | Có | Có field; null và status unknown khi chưa biết compatibility, không suy từ DC |
| `port_count`, `power_kw` | integer/number | Có | `power_kw` tổng nameplate site, `power_kw_scope=site`; giữ `power_kw_per_port` riêng. Không đồng nhất với grid capacity |
| `access_type`, `opening_hours` | string | Nên có | public/private, giờ mở |
| `price_vnd_per_kwh` | VND/kWh | Nên có | null nếu unknown; effective time |
| `uptime_ratio` | 0–1 | Nên có | Thời kỳ và phương pháp tính |
| `valid_from`, `valid_to` | datetime | Nên có | Lịch sử thay đổi inventory |
| `source_type`, `source_url`, `quality_status` | string; URL nullable | Có | Fixture local dùng `source_ref` và URL null/not_applicable; không tự tạo URL |

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
| `candidate_type` | enum | Có | parcel, grid_cell, corridor_node, existing_site_upgrade; parcel synthetic chỉ là giả thuyết site, không xác nhận parcel boundary. `candidate_subtype` giữ ngữ cảnh POI |
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
| Run scope | `study_area`, `boundary_version`, `pilot_extent`, `horizon_years`, `data_snapshot_id`, `algorithm_version` | Phạm vi tái lập |
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

1. **Ngày 1:** lấy boundary chính thức của TP.HCM hiện hành, pin version/CRS; chọn pilot extent nếu cần, decision owner và horizon.
2. **Ngày 2:** lập inventory nguồn mở/được phép dùng; ghi license, hạn chế độ phủ và ngày truy cập.
3. **Ngày 3:** hỏi mentor/đối tác bộ tối thiểu cần xin: inventory, transaction aggregate, outages, prices, candidate parcels/grid feasibility.
4. **Trong lúc chờ:** tạo synthetic theo schema y hệt, mọi dòng `is_synthetic=true`; không đặt giả định synthetic trong file “observed”.
5. **Khi nhận dữ liệu:** chạy validation, provenance review và so sánh phạm vi; không gộp nguồn nếu semantics khác nhau.

Với dữ liệu tài chính/chính sách, xin một ví dụ package đã ẩn thông tin nhạy cảm: metric nào họ dùng, đơn vị, kỳ tính, luật hard/soft, cách xử lý ưu đãi và ngày hiệu lực. Team không cần tự sáng tác policy; cần chứng minh hệ thống nhận package, validate được và đồng bộ kết quả khi package version đổi.
