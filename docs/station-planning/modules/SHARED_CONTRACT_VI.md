# Hợp đồng chung v0.1 — Station Planning

> Đây là điểm đồng bộ giữa các module. Không tự ý đổi semantics trong lúc triển khai song song. Nếu thay đổi, integration owner cập nhật file này trước, tăng contract version, rồi thông báo các module phụ thuộc.

Các quy ước trong file này là nguồn chuẩn cho request/response của API planning. JSON trên wire dùng `snake_case`; không tái sử dụng alias camelCase mặc định của API hiện hữu cho các model planning. Error envelope vẫn theo API v1 hiện có (`error.code`, `error.message`, `error.details`, `requestId`). Scenario JSON Schema là định dạng cấu hình/preset riêng, không phải request HTTP.

## 1. Tên và trách nhiệm API

Namespace dự kiến: `/api/v1/planning`. Tên này tách quy hoạch hạ tầng khỏi driver journey và khỏi wait/occupancy forecasting. Backend owner cần đối chiếu router thực tế trên `fix/ui` trước khi thêm.

### MVP endpoint

```http
POST /api/v1/planning/recommendations
```

Endpoint nhận một request bất biến mô tả study area, data snapshot, candidate set, technical/policy/finance scenario tùy chọn và trả một run kết quả. MVP không cần endpoint save project, user management hoặc cập nhật dữ liệu nguồn.

Planner cần metadata để chọn candidate và vẽ đúng snapshot trước khi chạy; endpoint bootstrap chỉ đọc này trả catalog demo đã pin:

```http
GET /api/v1/planning/demo-snapshot
```

Response gồm study area/snapshot ID, boundary GeoJSON, candidate options, existing-site markers, demand nodes kèm access-time proxy và các giá trị scenario mặc định. Endpoint không thay thế request run và không chứa ranking.

Các API chuyên biệt như candidate generation, capacity compare, run history và finance adapter chỉ được tách thêm khi implementation cho thấy cần. Không tạo nhiều endpoint `score`, `simulate`, `ROI` trước khi biết luồng UI/API thực sự cần chúng.

## 2. Request contract (khái niệm v0.1)

```json
{
  "contract_version": "0.1",
  "study_area": {
    "city_id": "VN-HCMC",
    "boundary_version": "hcmc-2025-v1",
    "pilot_extent_id": "pilot-demo-01"
  },
  "run": {
    "as_of": "2026-10-12T00:00:00Z",
    "horizon_years": 3,
    "data_snapshot_id": "demo-hcmc-v1",
    "seed": 42,
    "config_version": null,
    "demand_scenario": "base"
  },
  "candidate_source": {
    "mode": "provided",
    "candidate_ids": ["cand-001", "cand-002"]
  },
  "profile": "technical_opportunity",
  "technical": {
    "coverage_minutes": 15,
    "charger_options": [
      {"charger_type": "DC", "port_count": 4, "power_kw_per_port": 120}
    ],
    "budget_vnd": null
  },
  "policy_package": null,
  "finance_package": null
}
```

Trên API thật, field bắt buộc và optional phải được biểu diễn bằng Pydantic/OpenAPI. Trên JSON, thời gian ISO-8601 có timezone; tọa độ dùng WGS84 (EPSG:4326); khoảng cách tính bằng m/km; công suất kW; tiền VND; năng lượng kWh; thời lượng phút. `null` nghĩa là chưa có giá trị/unknown nếu schema cho phép; không dùng `0` thay unknown.

`contract_version`, `study_area`, `run`, `candidate_source`, `profile` và `technical` là bắt buộc. Trong `run`, `as_of`, `horizon_years`, `data_snapshot_id`, `seed` và `config_version` đều là field bắt buộc; `as_of` phải có timezone, `horizon_years` là số nguyên dương, `data_snapshot_id` phải chỉ rõ snapshot được dùng. `demand_scenario` nhận `low`, `base` hoặc `high` và mặc định là `base` cho client cũ. `config_version: null` chọn cấu hình mặc định hiện hành; nếu truyền phiên bản cụ thể thì backend phải dùng đúng phiên bản đó hoặc trả `invalid_input`. Backend trả lại phiên bản cấu hình thực tế trong response. Muốn chạy lại đúng cấu hình, client gửi lại `config_version` đã được echo.

`technical.budget_vnd` là ngưỡng sàng lọc CAPEX do người dùng nhập cho từng candidate trong run xếp hạng đơn điểm. Nó không thực hiện chọn portfolio hoặc kiểm tra tổng chi phí nhiều site. Snapshot demo có `portfolio_budget_vnd` tham chiếu 10 tỷ VND nhưng không dùng giá trị đó làm ngân sách từng candidate. `base_cost` chỉ minh họa cấu hình DC 4 × 80 kW; khi cấu hình khác, cost/budget gate là unknown.

`candidate_source.mode` v0.1 chỉ nhận `provided`; `candidate_ids` phải là mảng ID dạng chuỗi, không trùng nhau. Sai kiểu, enum, đơn vị, miền giá trị hoặc thiếu field bắt buộc là lỗi HTTP 422. Mảng `candidate_ids` rỗng là request đúng cấu trúc nhưng sai miền dữ liệu, trả run `invalid_input`. ID không tồn tại, snapshot không khả dụng hoặc package không hợp lệ cũng là lỗi miền dữ liệu theo semantics ở mục 4. Không âm thầm bỏ qua candidate không hợp lệ.

`study_area.boundary_version` và `pilot_extent_id` phải phân giải được trong snapshot được chọn; không tự thay bằng boundary mới nhất. Chỉ đánh giá containment/coverage trong geometry của đúng boundary/extent đó. Nếu geometry không có hoặc không khớp phiên bản thì trả `invalid_input`; không tuyên bố kết quả áp dụng cho toàn thành phố dựa trên một tập con. Candidate ở ngoài boundary đã xác nhận là hard constraint fail; thiếu geometry không phải bằng chứng candidate fail.

`candidate_source.mode` v0.1 nhận `provided` cho candidate đã có ID trong dataset. Mode `generated` (tạo grid/corridor candidates) là khả năng mở rộng và chỉ được bật khi M1 có thuật toán, resolution và provenance cụ thể.

## 3. Response contract (khái niệm v0.1)

```json
{
  "contract_version": "0.1",
  "run_id": "run-demo-0001",
  "status": "completed_with_unknowns",
  "scenario": {
    "profile": "technical_opportunity",
    "as_of": "2026-10-12T00:00:00Z",
    "horizon_years": 3,
    "seed": 42,
    "data_snapshot_id": "demo-hcmc-v1",
    "demand_scenario": "base",
    "algorithm_version": "site-ranker-0.1",
    "config_version": "technical-default-v0",
    "policy_package_id": null,
    "policy_package_version": null,
    "finance_package_id": null,
    "finance_package_version": null
  },
  "recommendations": [
    {
      "rank": 1,
      "candidate_id": "cand-001",
      "location": {"lat": 10.0, "lon": 106.0},
      "eligibility": "conditional",
      "technical_score": 72.0,
      "evidence_coverage": 0.8,
      "metrics": {
        "demand_potential": {"value": null, "unit": "sessions_per_day", "status": "unknown"},
        "coverage_gain": {"value": 12.5, "unit": "percent", "status": "scenario"},
        "recommended_capacity": {"value": 480, "unit": "kW", "status": "scenario"},
        "overload_risk": {"value": null, "unit": "category", "status": "unknown"},
        "estimated_cost": {"value": null, "unit": "VND", "status": "unknown"}
      },
      "constraints": [
        {"id": "grid_capacity", "status": "unknown", "reason": "Chưa có dữ liệu đấu nối"}
      ],
      "score_breakdown": [
        {
          "component_id": "marginal_coverage",
          "score": 72.0,
          "weight_percent": 25.0,
          "contribution_points": 18.0,
          "status": "scenario",
          "reason": "Giá trị minh họa cho cấu hình demo."
        },
        {
          "component_id": "demand_potential",
          "score": 90.0,
          "weight_percent": 30.0,
          "contribution_points": 27.0,
          "status": "scenario",
          "reason": "Giá trị minh họa cho cấu hình demo."
        },
        {
          "component_id": "grid_site_readiness",
          "score": 60.0,
          "weight_percent": 20.0,
          "contribution_points": 12.0,
          "status": "scenario",
          "reason": "Giá trị minh họa cho cấu hình demo."
        },
        {
          "component_id": "network_segment_fit",
          "score": 80.0,
          "weight_percent": 15.0,
          "contribution_points": 12.0,
          "status": "scenario",
          "reason": "Giá trị minh họa cho cấu hình demo."
        },
        {
          "component_id": "network_gap_fit",
          "score": 30.0,
          "weight_percent": 10.0,
          "contribution_points": 3.0,
          "status": "scenario",
          "reason": "Giá trị minh họa cho cấu hình demo."
        }
      ],
      "provenance": [
        {
          "field": "metrics.coverage_gain",
          "source_id": "demo-planning-fixture-v1",
          "source_ref": null,
          "status": "scenario",
          "is_synthetic": true,
          "observed_at": null,
          "note": "Giá trị minh họa, không phải số đo thực tế."
        }
      ]
    }
  ],
  "unranked_candidates": [],
  "excluded_candidates": [],
  "warnings": ["Đây là dữ liệu demo tổng hợp; không đại diện nhu cầu thực tế TP.HCM."]
}
```

Số liệu ví dụ ở trên chỉ minh họa hình dạng payload, không phải dự báo hay ngưỡng đã chốt. Response thật phải trả các metric thực sự tính được, không tạo placeholder có vẻ như kết quả thật.

`scenario` là cấu hình đã resolve và phải echo `profile`, `as_of`, `horizon_years`, `seed`, `data_snapshot_id`, `demand_scenario`, `algorithm_version`, `config_version` cùng ID/version của package đã áp dụng; ID/version package không dùng là `null`. Các field vẫn có mặt ở `invalid_input`; giá trị chưa resolve được là `null`, còn input đã nhận (profile, thời điểm, horizon, seed, snapshot ID và demand scenario) được echo để giải thích lỗi. Mỗi lần xử lý request hợp lệ về cấu trúc có `run_id` mới; MVP không lưu run bền vững. Cùng input, snapshot, algorithm và config phải cho cùng kết quả xếp hạng. `run_id` có thể khác giữa các lần chạy.

`recommendations` chỉ chứa candidate còn đủ điều kiện xếp hạng và có `technical_score` so sánh được trong profile đang chạy; `rank` liên tục từ 1. `eligibility` là `eligible` hoặc `conditional`. Candidate chưa bị hard constraint loại nhưng thiếu evidence đến mức không thể tính score so sánh được nằm trong `unranked_candidates`, kèm `candidate_id` và `reason`; không gán rank/score giả. Candidate có hard constraint đã xác nhận `fail` nằm trong `excluded_candidates`. Mỗi phần tử bị loại có `candidate_id` và danh sách `constraints` gồm `id`, `status: "fail"`, `reason`. Cả `unranked_candidates` và `excluded_candidates` luôn có mặt, kể cả khi rỗng.

Mỗi metric có dạng `{ "value": number|string|null, "unit": string, "status": <data status> }`. `unknown` và `not_applicable` luôn đi với `value: null`; không thay bằng 0. `score_breakdown` là danh sách item có `component_id`, `score` (0–100 hoặc `null`), `weight_percent` (0–100 hoặc `null`), `contribution_points` (number hoặc `null`), `status`, `reason`. Với `weighted_sum`, contribution là đúng số điểm thành phần dùng để tạo `technical_score` và tổng contribution phải bằng `technical_score`; phương pháp không cộng trọng số trả `contribution_points: null`.

`provenance` là danh sách theo từng field/nguồn, với `field`, `source_id`, `source_ref`, `status`, `is_synthetic`, `observed_at`, `note`. Các trường định danh/thời điểm/ghi chú có thể `null` nếu không biết. `is_synthetic` chỉ là `true` khi dữ liệu được sinh tổng hợp/demo; phải giữ nhãn này kể cả khi kết quả suy ra từ dữ liệu tổng hợp.

## 4. Enum/status semantics

- `observed`: đo/ghi nhận từ nguồn xác định.
- `proxy`: đại diện gián tiếp cho đại lượng quan tâm, có phương pháp và nguồn nêu rõ.
- `synthetic`: sinh để kiểm thử/demo; không phải telemetry.
- `scenario`: giá trị đầu vào hoặc kết quả điều kiện theo giả định.
- `unknown`: chưa biết/chưa được cung cấp.
- `not_applicable`: không áp dụng theo quy tắc có giải thích.

Constraint status: `pass`, `fail`, `conditional`, `unknown`, `not_applicable`. Chỉ `fail` khi có bằng chứng xác nhận infeasible; thiếu dữ liệu là `conditional/unknown`, không tự động loại trừ. Một hard constraint `fail` loại candidate khỏi feasible ranking nhưng phải trả lý do.

Run status: `completed`, `completed_with_unknowns`, `invalid_input`, `no_feasible_candidates`, `failed`. Không biến lỗi thiếu dữ liệu thành lỗi hệ thống nếu vẫn tính được một phần.

Quy tắc phản hồi lỗi:

- Lỗi cấu trúc/type/enum/unit/range của request: HTTP 422, error envelope hiện có với `error.code = "VALIDATION_ERROR"`; không có response run thành công.
- Request đúng cấu trúc nhưng candidate ID/snapshot/package không hợp lệ hoặc không tương thích profile: trả run `status: "invalid_input"`, `recommendations`, `unranked_candidates` và `excluded_candidates` rỗng, `warnings` nêu rõ nguyên nhân. Request loại này đã vào service nên có `run_id`.
- `no_feasible_candidates` chỉ dùng khi đã đánh giá ít nhất một candidate hợp lệ và tất cả đều bị loại bởi hard constraint có bằng chứng xác nhận; giải thích từng candidate trong `excluded_candidates`. Danh sách đầu vào rỗng là `invalid_input`.
- Có kết quả xếp hạng hoặc candidate chưa đủ evidence để xếp hạng nhưng một hay nhiều field chưa biết/đang dùng proxy thì trả `completed_with_unknowns`; thiếu dữ liệu không tự nó làm candidate infeasible. Khi tất cả candidate còn lại unranked, trạng thái vẫn `completed_with_unknowns` và lý do nằm trong `unranked_candidates`.
- Lỗi tính toán có kiểm soát có thể trả `failed`. Lỗi DB/repository/hạ tầng trả HTTP 503 theo error envelope; không giả thành điểm thấp hoặc `no_feasible_candidates`.

## 5. Ranking semantics

- Hard feasibility được đánh giá riêng trước soft score.
- Enum profile chuẩn: `technical_opportunity`, `public_policy`, `investor_economic`. `technical_opportunity` không cần package policy/finance. `public_policy` bắt buộc policy package hợp lệ; `investor_economic` bắt buộc finance package hợp lệ. Không tự dựng giả định policy/finance mặc định. Trong MVP, M4 chỉ hiển thị profile `technical_opportunity` cho tới khi package và adapter tương ứng được hỗ trợ; backend vẫn validate mọi profile nhận được.
- Score 0–100 là screening score, không phải xác suất thành công, ROI hay bằng chứng đầu tư.
- Score direction phải thống nhất: giá trị cao luôn có nghĩa tốt hơn cho profile đang chạy. Feature gốc (ví dụ số trạm lân cận) không được dùng trực tiếp nếu ý nghĩa thay đổi theo profile.
- `evidence_coverage` là tỷ trọng tiêu chí có bằng chứng theo profile, nằm trong khoảng 0–1 và không phải confidence probability. Candidate thiếu một số trường nhưng vẫn đủ score so sánh được có thể được gắn `conditional`; thiếu evidence đến mức không tính được score thì chuyển sang `unranked_candidates`.
- Multi-site selection phải dùng marginal coverage sau các site đã chọn; ranking độc lập từng điểm chỉ phù hợp so sánh candidate đơn.
- Trọng số demo trong `CONSTRAINT_MATRIX_HCMC_VI.md` là tạm thời; engine nhận profile/version config, không hard-code chúng thành policy.

## 6. Finance/policy package

Package có `package_id`, `version`, `owner`, `source`, `effective_from/to`, `units`, `rules`, `formula_version`, `quality_status`. Finance/policy là optional đối với profile kỹ thuật; profile yêu cầu package phải cung cấp package hợp lệ. Package hợp lệ tối thiểu phải có `package_id`/`version` không rỗng, được adapter hỗ trợ, có đơn vị tương thích, và có hiệu lực tại `as_of`; adapter kiểm tra thêm schema/formula/rule fields mà profile dùng. Nếu client gửi package nhưng adapter chưa hỗ trợ hoặc package sai schema/phiên bản thì trả `invalid_input`, không bỏ qua âm thầm. Input không bắt buộc cho profile đang chạy có thể để thiếu; metric tương ứng là `unknown`/`not_applicable`, không giả định giá trị. Response echo package ID/version đã áp dụng. Đổi package tạo `run_id` mới và giữ lineage trong payload (MVP không lưu lịch sử bền vững).

Scenario preset (`planning-scenario.schema.json`) chỉ là đầu vào cấu hình để người dùng/chuyên gia soạn thảo. M4 phải ánh xạ rõ ràng những giá trị được hỗ trợ sang HTTP request; không gửi nguyên preset làm payload và không suy diễn trường không có trong request contract. Schema preset version hiện hành là `1.1`; version này độc lập với `contract_version` của API (`0.1`).

Fixture/demo phải được gắn provenance `synthetic`/`scenario` và cảnh báo trong response; không trình bày như dữ liệu vận hành, dự báo nhu cầu thật hoặc xác nhận khả thi đầu tư. Preset có `boundary_geometry_ref: null` vẫn chỉ là cấu hình, chưa đủ điều kiện chạy đánh giá không gian cho đến khi M1 cung cấp geometry có version.

## 7. Tách layer và quyền sở hữu

### Payload nội bộ M2A → M2B (demand estimate)

M2A (demand ML/baseline) và M2B (site engine) trao đổi một record cho mỗi candidate hoặc demand cell, target và time window. Đây là interface nội bộ; không bắt frontend gửi thẳng prediction của model. Ví dụ:

```json
{
  "candidate_id": "cand-001",
  "target": "charging_sessions",
  "value": 18.4,
  "unit": "sessions_per_day",
  "time_window": {"start": "2027-01-01", "end": "2027-01-31"},
  "status": "synthetic",
  "source_id": "synthetic-demand-v1",
  "model_version": "gbdt-demo-0.1",
  "data_snapshot_id": "demo-hcmc-v1",
  "scenario": "base",
  "uncertainty": {"low": 12.0, "high": 25.0, "method": "synthetic_scenario_range"}
}
```

- `status` dùng enum ở mục 4; `unknown` phải được biểu diễn tường minh, không giả làm 0. Khi chưa chạy model, `model_version` có thể null và `source_id` trỏ baseline/scenario.
- `target` và `unit` phải đi cùng nhau; không cộng hoặc so sánh target khác nhau như thể tương đương.
- `scenario` và `uncertainty` chỉ nêu khoảng low/base/high nếu có căn cứ; không mặc định đó là xác suất hay confidence interval.
- M2B giữ provenance này trong component `demand_potential` của output; API adapter ánh xạ sang response contract ở mục 3.
- M1 cung cấp geometry/features/label và data provenance cho M2A; M1 không chịu trách nhiệm train/evaluate model.

### Artifact P7/P8 của demo v3

`data_platform/station_planning/demo_hcmc_v3` cung cấp `access_model.json`, `access_matrix.csv`, `technical_constraints_package.json`, `candidate_constraints.csv` và `candidate_eligibility.csv`. Package giữ metadata source/version/owner/units và rules có envelope `rule_id`, `category`, `effect`, `value_status`, `source_ref`; đây là technical demo config, không tự bật public-policy overlay. Xem [quyết định P7/P8](../P7_P8_DECISIONS_VI.md).

Adapter ánh xạ artifact vào domain theo request hiện hữu; không đưa travel proxy thành road routing hoặc unknown thành pass. Contract API v0.1 giữ nguyên; các artifact mới bổ sung input chuẩn bị dữ liệu, không phải endpoint/ranking output mới.

```text
HTTP/Pydantic router -> planning application service -> pure domain engine
                                          -> repository/PostGIS adapter
                                          -> package validation/adapters
```

- Router không chứa công thức hoặc SQL nghiệp vụ.
- Domain engine không import FastAPI, React hoặc DB driver.
- Repository truy vấn dữ liệu hiện có và ánh xạ sang domain types.
- Frontend chỉ trình bày API response và gửi request; không tự tính score.
- Không lưu durable runs/projects trong MVP. Khi cần persistence, tạo thiết kế riêng có owner/retention/version trước khi DDL.

## 8. Quy tắc thay đổi hợp đồng

1. Hợp đồng `0.1` là baseline được chốt trước khi implementation bắt đầu; các quyết định hoàn thiện từ bản nháp đã được gộp vào version này. Mở PR sửa file này và tăng version nếu về sau thay đổi breaking semantics.
2. Cập nhật JSON examples, Pydantic/OpenAPI và TypeScript types cùng một PR hoặc theo chuỗi PR được ghi rõ.
3. Thông báo module bị ảnh hưởng trước khi merge.
4. Không thêm dữ liệu nhạy cảm/giả định doanh nghiệp vào sample; dùng dữ liệu tổng hợp có gắn nhãn.
