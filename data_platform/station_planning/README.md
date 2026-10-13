# Bộ dữ liệu station planning cho demo 9 phường

Snapshot hiện hành: [`demo_hcmc_v3/`](demo_hcmc_v3/), ID `hcmc-nine-wards-demo-v3`, seed `20261013`. Cấu hình sinh: [`../../config/station_planning_demo.json`](../../config/station_planning_demo.json).

V1/v2 và các báo cáo kiểm tra tương ứng được lưu trong Git stash local với tên `archive station-planning demo v1-v2 before publishing v3`, không nằm trong commit hiện hành và không được push. V1 chưa có P7/P8; v2 chưa có các bổ sung chuẩn hóa DATA_PLAN của v3. V3 bổ sung cấu trúc theo DATA_PLAN; xem [bảng đối chiếu](../../docs/station-planning/DATA_PLAN_ALIGNMENT_VI.md) và `data_plan_alignment_report.json` trong snapshot.

Xem [tổng kết dữ liệu và sơ đồ luồng sử dụng](../../docs/station-planning/NORMALIZED_DATA_SUMMARY_VI.md) để đối chiếu các phần, khóa liên kết và cách đưa snapshot vào bài toán quy hoạch.

Bộ dữ liệu phục vụ chuẩn bị input cho engine. Chưa chạy ranking hoặc tích hợp API/DB. Existing sites là đúng 37 trạm của `hcm_dc80kw_5wards`; không đọc `ref.kml` và không ghép bộ 668 trạm. [P7/P8 đã chốt](../../docs/station-planning/P7_P8_DECISIONS_VI.md), với access proxy và technical rule package; physical feasibility chưa xác minh vẫn unknown/conditional.

## Các phần đã tạo

| Phần | File | Nội dung |
|---|---|---|
| 1 | `pilot_units.geojson`, `pilot_extent.geojson` | 9 polygon nguồn và polygon hợp để lọc pilot; giữ ngày hiệu lực pháp lý unknown |
| 2 | `existing_sites.csv`, `existing_sites.geojson` | 37 trạm mô phỏng; giữ ID EVC, tọa độ, số cổng, giờ mở cửa; công suất demo 80 kW/cổng, connector unknown |
| 3 | `population.csv`, `context_poi.geojson`, `context_transport.geojson` | Dân số 9 phường, 3.708 POI, 1.640 đối tượng giao thông trong pilot; tuyến được cắt theo ranh giới |
| 3 | `poi_model_weights.csv` | Giữ mọi bản ghi nguồn; 30 nhóm nghi trùng được giảm trọng số để mỗi nhóm có tổng trọng số 1 khi mô hình hóa. Không khẳng định đã gộp đúng thực thể |
| 4 | `candidate_sites.csv`, `candidate_sites.geojson` | 18 ứng viên synthetic, 2/phường; có POI/bãi xe tham chiếu, lý do sinh và khoảng cách đến existing site gần nhất |
| 5 | `demand_nodes.csv`, `demand_nodes.geojson`, `demand_intervals.csv` | 27 điểm hỗ trợ nhu cầu, 27.216 dòng nhu cầu nửa giờ cho low/base/high |
| 6 | `station_operations.csv`, `charging_requests.csv` | 37.296 dòng vận hành và 24.410 yêu cầu synthetic; có served/abandoned/pending, outage, queue và năng lượng |
| 5 | `demand_cells.csv`, `demand_node_cell_map.csv` | 9.072 dòng theo phường/profile/interval; 27 mapping node → phường, giữ các node P7 riêng |
| 6 | `demand_observations.csv` | 37.296 dòng observation của mô phỏng: session/kWh, peak busy, wait p50/p90, abandon count và provenance |
| 7 | `access_matrix.csv`, `access_model.json` | 4.455 dòng: 27 điểm nhu cầu × 55 mục tiêu × 3 access profiles; haversine × 1,3, tốc độ 25/20/12 km/h, cộng 2 phút, ngưỡng 15 phút |
| 8 | `technical_constraints_package.json`, `candidate_constraints.csv`, `candidate_eligibility.csv` | Package rule demo, 180 kết quả kiểm tra và 18 ứng viên conditional; option 4 DC × 80 kW, budget 10 tỷ, evidence threshold 0,6 |
| 9 | `selected_electricity_tariffs.csv`, `finance_package.json`, `candidate_cost_assumptions.csv` | Một lịch biểu giá nguồn, cấp điện áp giả định; chi phí tham chiếu cho cấu hình 4 cổng và ba mức chi phí giả định |
| 9 | `electricity_cost_intervals.csv`, `finance_period_summary.csv` | Điện mua theo hiệu suất giả định, chi phí điện theo từng nửa giờ và tổng cho kỳ synthetic; revenue minus electricity chưa trừ các chi phí khác |
| 10 | `generation_config.json`, `scenario.json`, `data_dictionary.json`, `manifest.json`, `validation_report.json` | Tham số, đơn vị, nguồn, hash, phiên bản và kết quả kiểm tra |
| 10 | `scenario_config.json`, `boundary_metadata.json`, `data_plan_contract.schema.json`, `data_plan_alignment_report.json` | Các nhóm field DATA_PLAN và kết quả schema validation cho bảng chuẩn |

CSV dùng UTF-8 BOM; ô trống là unknown, không phải 0. Các GeoJSON dùng kinh độ/vĩ độ cho xử lý bản đồ; mô tả CRS nguồn chưa được xác nhận độc lập. File CSV và GeoJSON của cùng bảng chỉ là hai cách biểu diễn, không ingest thành hai tập khác nhau.

V3 giữ các trường cũ và bổ sung `power_kw` tổng nameplate site. `source_url` fixture local là null/not_applicable, `source_ref` xác định file đầu vào. Candidate thuộc loại `parcel` synthetic (giả thuyết site chưa có parcel boundary), giữ nhãn POI cũ ở `candidate_subtype`. View observations/cells là cách biểu diễn khác của dữ liệu hiện hữu, không cộng thêm vào tổng nhu cầu. Wait quantiles null khi không có phiên phục vụ; `poi_mix` là JSON trong CSV. Finance `value_status=provided` nghĩa là giá trị cấu hình đã cung cấp, vẫn là giả định với nhãn scenario/synthetic.

## Cách sinh và diễn giải

- Context giữ số dân/POI/giao thông từ nguồn thu thập. Ngày thống kê dân số vẫn unknown. Dữ liệu này không đo nhu cầu sạc hoặc lưu lượng xe.
- Ứng viên synthetic lấy tọa độ từ các POI/bãi xe phù hợp, cách trạm fixture ít nhất 150 m và cách ứng viên đã chọn ít nhất 250 m. Chọn theo khoảng trống fixture và ngữ cảnh hạ tầng giao thông để có tập địa điểm đa dạng; đây không phải kết quả ranking đầu tư. Traffic intensity là scenario/proxy, không phải số xe đo được. Đất/điện/tiếp cận/cấp phép giữ unknown, candidate là conditional.
- Nhu cầu sinh độc lập với tập ứng viên: 3 cụm điểm/phường, phân bổ dân số có tổng trọng số bằng 1; EV share, home charging, profile giờ/ngày và số phiên theo Poisson là giả định. Low/base/high là ba kịch bản, không phải xác suất dự báo.
- Mô phỏng vận hành đưa các yêu cầu synthetic của từng phường vào trạm cùng phường theo trọng số số cổng. Đây là cơ chế phân bổ để kiểm thử, tách khỏi ma trận P7, không phải mô hình lựa chọn trạm. Ledger yêu cầu cho phép đối soát số phiên và năng lượng với nhu cầu.
- P7 baseline `normal` dùng thời gian proxy, không routing trên đường thực. Matrix gồm cả cặp khác phường; access profile fast/normal/slow độc lập với demand low/base/high. Opening hours, capacity, outage và compatibility phải áp riêng trong engine trước khi tính demand served.
- P8 kiểm tra geometry/pilot/spacing/option/budget và giữ năm physical gates unknown. Rule confirmed infeasible mới loại physical candidate; không có nguồn thì conditional. Utilization target 0,8 chỉ là giả định cho sizing sau; public-policy overlay tắt. Individual budget pass không chứng minh một portfolio đạt budget.
- Mô hình sạc đơn giản dùng 80 kW không đổi, năng lượng 8–38 kWh, tối đa một yêu cầu/cổng trong slot 30 phút; phiên được phục vụ hoàn tất trong slot. Có đóng cửa, outage, queue và bỏ hàng đợi khi vượt 60 phút. Occupied peak khác occupied mean. Không gọi đây là mô hình wait forecast đã được kiểm chứng.
- Lịch synthetic **07–13/07/2025**, giờ Việt Nam, được chọn để dùng `tt16_reference_2025` đúng mốc tham chiếu lịch sử; đây không phải replay dữ liệu năm 2025. Context tải năm 2026 vẫn chỉ là ngữ cảnh. Không khẳng định lịch điện này đang áp dụng năm 2026.
- Chọn `lt_6kv` là giả định cấp điện áp mua điện, không suy từ 80 kW DC. Hiệu suất 0,93, giá bán và CAPEX/OPEX là giả định chỉnh được. Giá nguồn giữ trước VAT/có VAT và provenance. Slot nửa giờ xử lý đúng mốc `:30`.
- Finance chỉ tính các đầu vào chi phí và số liệu của tuần synthetic. Không suy NPV/payback hoặc doanh thu năm từ một tuần. `scenario.json` giữ finance engine disabled vì adapter/metric đầu tư chưa được tích hợp; package tài chính và bảng chi phí đã có để sử dụng sau.

## Tạo lại và kiểm tra

Từ thư mục gốc repository, dùng Python 3.12 với NumPy 2.3.5, Shapely 2.1.2 và JSON Schema 4.25.1. Dependencies được pin trong `scripts/requirements-station-planning.txt`; có thể cài vào môi trường riêng của task. Generator v3 tự kiểm tra các view DATA_PLAN bằng JSON Schema trước khi đóng manifest.

```powershell
python -m pip install -r scripts/requirements-station-planning.txt
python scripts/prepare_station_planning_demo.py
python scripts/validate_station_planning_demo.py
python scripts/validate_station_planning_contract.py
python -m unittest tests.test_station_planning_demo -v
python -m unittest tests.test_station_planning_rules -v
python -m unittest tests.test_station_planning_data_plan -v
```

Nếu dependency nằm trong thư mục riêng, thêm `--dependency-dir <đường dẫn>` khi chạy generator hoặc contract validator. Validator snapshot chỉ dùng standard library; contract validator cần JSON Schema nhưng không cần Shapely. Generator chỉ ghi vào thư mục output đã cấu hình, giữ nguyên raw inputs. Đổi seed/tham số cho một snapshot mới cần tăng `snapshot_id` và đổi `output_directory` trong config, không ghi đè một snapshot đang được sử dụng.

Kiểm tra gồm source/output hashes, ID, phân bổ dân số, số phiên/năng lượng giữa demand–request–operation, hàng đợi, giới hạn cổng, giờ đóng cửa, timestamp phiên, ranh giới biểu giá và phép tính chi phí. Geometry clipping kiểm tra với sai số số học 1e-9 độ (khoảng 0,1 mm); đây không phải ngưỡng coverage. `manifest.json` lưu hash từng file và phiên bản thư viện để đối chiếu khi tái tạo.
