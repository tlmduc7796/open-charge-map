# Hợp đồng chung v0.1 — Station Planning

> Đây là điểm đồng bộ giữa các module. Không tự ý đổi semantics trong lúc triển khai song song. Nếu thay đổi, integration owner cập nhật file này trước, tăng contract version, rồi thông báo các module phụ thuộc.

## 1. Tên và trách nhiệm API

Namespace dự kiến: `/api/v1/planning`. Tên này tách quy hoạch hạ tầng khỏi driver journey và khỏi wait/occupancy forecasting. Backend owner cần đối chiếu router thực tế trên `fix/ui` trước khi thêm.

### MVP endpoint

```http
POST /api/v1/planning/recommendations
```

Endpoint nhận một request bất biến mô tả study area, data snapshot, candidate set, technical/policy/finance scenario tùy chọn và trả một run kết quả. MVP không cần endpoint save project, user management hoặc cập nhật dữ liệu nguồn.

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
    "seed": 42
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

`candidate_source.mode` v0.1 nhận `provided` cho candidate đã có ID trong dataset. Mode `generated` (tạo grid/corridor candidates) là khả năng mở rộng và chỉ được bật khi M1 có thuật toán, resolution và provenance cụ thể.

## 3. Response contract (khái niệm v0.1)

```json
{
  "contract_version": "0.1",
  "run_id": "run-demo-0001",
  "status": "completed_with_unknowns",
  "scenario": {
    "profile": "technical_opportunity",
    "data_snapshot_id": "demo-hcmc-v1",
    "algorithm_version": "site-ranker-0.1",
    "policy_package_version": null,
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
      "score_breakdown": [],
      "provenance": []
    }
  ],
  "warnings": ["Đây là dữ liệu demo tổng hợp; không đại diện nhu cầu thực tế TP.HCM."]
}
```

Số liệu ví dụ ở trên chỉ minh họa hình dạng payload, không phải dự báo hay ngưỡng đã chốt. Response thật phải trả các metric thực sự tính được, không tạo placeholder có vẻ như kết quả thật.

## 4. Enum/status semantics

- `observed`: đo/ghi nhận từ nguồn xác định.
- `proxy`: đại diện gián tiếp cho đại lượng quan tâm, có phương pháp và nguồn nêu rõ.
- `synthetic`: sinh để kiểm thử/demo; không phải telemetry.
- `scenario`: giá trị đầu vào hoặc kết quả điều kiện theo giả định.
- `unknown`: chưa biết/chưa được cung cấp.
- `not_applicable`: không áp dụng theo quy tắc có giải thích.

Constraint status: `pass`, `fail`, `conditional`, `unknown`, `not_applicable`. Chỉ `fail` khi có bằng chứng xác nhận infeasible; thiếu dữ liệu là `conditional/unknown`, không tự động loại trừ. Một hard constraint `fail` loại candidate khỏi feasible ranking nhưng phải trả lý do.

Run status: `completed`, `completed_with_unknowns`, `invalid_input`, `no_feasible_candidates`, `failed`. Không biến lỗi thiếu dữ liệu thành lỗi hệ thống nếu vẫn tính được một phần.

## 5. Ranking semantics

- Hard feasibility được đánh giá riêng trước soft score.
- Profile v0.1: `technical_opportunity`; `public_policy` và `investor_economic` bật khi có package tương ứng.
- Score 0–100 là screening score, không phải xác suất thành công, ROI hay bằng chứng đầu tư.
- Score direction phải thống nhất: giá trị cao luôn có nghĩa tốt hơn cho profile đang chạy. Feature gốc (ví dụ số trạm lân cận) không được dùng trực tiếp nếu ý nghĩa thay đổi theo profile.
- `evidence_coverage` là tỷ trọng tiêu chí có bằng chứng theo profile, không phải confidence probability. Candidate thiếu các trường quan trọng có thể bị gắn `conditional` hoặc không xếp hạng.
- Multi-site selection phải dùng marginal coverage sau các site đã chọn; ranking độc lập từng điểm chỉ phù hợp so sánh candidate đơn.
- Trọng số demo trong `CONSTRAINT_MATRIX_HCMC_VI.md` là tạm thời; engine nhận profile/version config, không hard-code chúng thành policy.

## 6. Finance/policy package

Package có `package_id`, `version`, `owner`, `source`, `effective_from/to`, `units`, `rules`, `formula_version`, `quality_status`. Finance/policy là optional. Input thiếu thì metric tương ứng `unknown/unavailable`; chỉ tính output được hỗ trợ bởi các trường đã có. Đổi package tạo `run_id` mới và giữ lineage (run cũ không bị ghi đè).

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

1. Mở PR sửa file này và tăng version nếu thay đổi breaking semantics.
2. Cập nhật JSON examples, Pydantic/OpenAPI và TypeScript types cùng một PR hoặc theo chuỗi PR được ghi rõ.
3. Thông báo module bị ảnh hưởng trước khi merge.
4. Không thêm dữ liệu nhạy cảm/giả định doanh nghiệp vào sample; dùng dữ liệu tổng hợp có gắn nhãn.
