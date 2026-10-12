# Blueprint: xếp hạng vị trí và quy mô trạm sạc

## 1. Người dùng và nhu cầu

### Đơn vị đầu tư/quy hoạch

- Chưa biết khu vực nào có cầu sạc tăng nhanh hoặc đang bị giới hạn bởi nguồn cung.
- Có vốn hữu hạn; cần so sánh xây trạm mới với mở rộng trạm hiện có.
- Cần cân nhắc mặt bằng, công suất điện, thời gian đấu nối, cấp phép, đối thủ, khả năng tiếp cận và rủi ro dự báo.
- Cần hiểu vì sao hệ thống xếp hạng một vị trí cao và giả định nào làm thứ hạng thay đổi.

### Tài xế, đội xe và cộng đồng

- Có thể thiếu trạm phù hợp trên tuyến hoặc quanh điểm đến; độ tin cậy, loại cổng, giá và thời gian tiếp cận đều quan trọng.
- Đội xe dịch vụ/tour có lịch vận hành, điểm tập kết và luồng đi lại lặp lại; có thể tạo nhu cầu tập trung hơn nhu cầu xe cá nhân.
- Khu dân cư/chung cư có ít khả năng sạc tại nhà có thể cần tiếp cận sạc công cộng nhiều hơn.

Các điểm trên là giả thuyết sản phẩm cần kiểm chứng bằng phỏng vấn, dữ liệu và đối tác. Quy hoạch dân cư, giá nhiên liệu hay xe tự lái là biến/kịch bản; không tự thân chứng minh pain point tại một tọa độ.

## 2. Câu hỏi và đầu ra

**Câu hỏi MVP:** với tập địa điểm ứng viên, nhu cầu ước lượng và một bộ cấu hình kỹ thuật/chính sách/tài chính do người dùng cung cấp, tập vị trí/quy mô nào phù hợp nhất với mục tiêu và ràng buộc của kịch bản đó?

Hệ thống không sở hữu “một chính sách đúng” hay một định nghĩa phổ quát về lợi nhuận. Nó cung cấp interface và calculation engine để đơn vị đầu tư/chính sách đưa assumptions/rules của họ vào; cùng một bộ địa điểm và nhu cầu có thể được đánh giá theo nhiều bộ cấu hình có phiên bản. Như vậy team vẫn làm bài toán kỹ thuật, còn tổ chức sử dụng quyết định giá trị tham số và tiêu chí ra quyết định.

Mỗi đề xuất cần hiển thị:

1. Vị trí, loại địa điểm, vùng dân cư/hành lang/POI liên quan.
2. Nhu cầu nền và nhu cầu theo thời gian (session, kWh, peak concurrency); nêu nguồn và mức tin cậy.
3. Phần nhu cầu được phục vụ thêm sau khi tính các trạm hiện hữu và các đề xuất đã chọn.
4. Độ phủ tăng thêm (ví dụ cư dân/luồng di chuyển/POI trong ngưỡng tiếp cận), không cộng trùng người/vùng đã được phục vụ.
5. Quy mô gợi ý: loại sạc và số cổng/dải công suất, kèm giả định utilization/SLA.
6. Áp lực hoặc nguy cơ quá tải theo giờ/mùa/kịch bản.
7. Economics theo kịch bản (nếu cấu hình tài chính được cung cấp): CAPEX/OPEX/revenue/tariff, payback/NPV theo công thức cấu hình; hiển thị input, nguồn, version và khoảng bất định.
8. Chất lượng, độ mới, khoảng trống dữ liệu và độ nhạy thứ hạng khi thay đổi giả định.
9. Nếu thiếu đầu vào finance/policy, hiển thị phần nào chưa thể tính; vẫn trả technical/coverage results nếu các đầu vào đó đủ.

## 3. Cách ra quyết định

### Tách dự báo khỏi tối ưu

1. **Ước lượng nhu cầu** theo cell/vùng hoặc luồng tuyến và khoảng thời gian. Tách nhu cầu quan sát được với nhu cầu bị giới hạn bởi thiếu trạm.
2. **Đánh giá cung hiện có:** cổng/loại sạc, uptime, giá, khả năng tiếp cận, công suất, occupancy và chờ.
3. **Sinh phương án:** ứng viên mới và tùy chọn mở rộng trạm hiện tại.
4. **Tính phần đóng góp biên:** số nhu cầu/nhóm luồng mới được phục vụ, độ phủ mới, tải dự kiến lên lưới, vốn/cost proxy.
5. **Xếp hạng hoặc chọn tập phương án** dưới ngân sách, độ phủ, điện lưới và ngưỡng chất lượng dữ liệu.
6. **Giải thích và chạy kịch bản** để người dùng thấy trade-off thay vì chỉ nhận một điểm đen hộp.

### Hàm mục tiêu và bộ cấu hình tích hợp

Tách ba khái niệm để thay đổi chính sách/tài chính không làm lệch nghĩa các feature kỹ thuật:

1. **Technical facts:** topology trạm, nhu cầu, giao thông, công suất/capacity, candidate và feasibility đã biết.
2. **Policy config:** hard rules và mục tiêu công như vùng phải có coverage, nhóm ưu tiên, tiêu chuẩn/điều kiện được cung cấp, ưu đãi/trợ cấp.
3. **Finance config:** ngân sách, CAPEX/OPEX, giá điện/tariff, pricing/revenue assumptions, thời hạn và phương pháp đánh giá vốn do đơn vị đầu tư cung cấp.

Mỗi lần chạy nhận `scenario_id`, `scenario_version`, phạm vi/thời hạn áp dụng, nguồn và đơn vị của mỗi input. Policy hard rules được kiểm tra trước khi xếp hạng; finance assumptions được tính trong economics layer; soft objectives/weights được cấu hình riêng. Cùng input version phải cho output tái lập được. Khi policy/tariff/chi phí đổi, chạy lại trên cùng data snapshot và hiển thị chênh lệch kết quả.

Ví dụ cấu trúc interface (tên trường là minh họa, cần chốt contract ở Gate 1):

```yaml
scenario_id: investor_demo_base
scenario_version: 1
technical:
  planning_horizon_years: 3
  target_access_minutes: 15
policy:
  minimum_coverage_share: null
  priority_zones: []
  grant_per_port_vnd: null
finance:
  budget_vnd: null
  capex_per_port_vnd: null
  annual_opex_per_site_vnd: null
  electricity_tariff_vnd_per_kwh: null
  revenue_vnd_per_kwh: null
  discount_rate: null
  payback_limit_years: null
```

`null` nghĩa là chưa cung cấp/unknown; không mặc định bằng 0. `not_applicable` phải là trạng thái riêng trong metadata của field. Nếu tổ chức có mô hình tài chính riêng, interface có thể nhận forecast/metric đã tính sẵn kèm định nghĩa, kỳ tính, đơn vị và provenance thay vì bắt team tái tạo toàn bộ kế toán.

### Hàm mục tiêu giai đoạn demo

Không có dữ liệu doanh thu đáng tin cậy thì dùng mục tiêu đa tiêu chí rõ ràng, ví dụ:

```text
maximize  w1 * unmet_demand_served
        + w2 * new_access_coverage
        + w3 * underserved_equity
        - w4 * estimated_capex_proxy
        - w5 * grid_risk
        - w6 * overlap_or_competition_penalty

subject to: budget <= B
            grid_capacity(candidate) is feasible or explicitly unknown
            selected_port_count >= capacity needed for stated service target
```

Các trọng số và ngưỡng là cấu hình scenario, không phải “chân lý” học từ dữ liệu. Báo cáo xếp hạng theo từng kịch bản và phân tích độ nhạy; có thể so sánh phương án Pareto thay vì ép tất cả trade-off thành một điểm duy nhất.

Khi có finance config, tính chỉ số theo công thức/metric do đối tác chọn hoặc xác nhận, ví dụ dòng tiền, NPV, payback, margin theo kWh/session, demand charge, thuê đất, vốn thiết bị và chi phí đấu nối. Phải version hóa công thức, đơn vị, thời hạn và quy ước dòng tiền. Không tính ROI từ `capex_proxy`; nếu đối tác truyền NPV/payback đã tính sẵn thì giữ kèm nguồn và không coi đó là output do hệ thống tự xác minh.

### Baseline dễ giải thích

- **Baseline 0:** điểm theo nhu cầu quan sát và vùng phủ hiện tại, không tối ưu tập hợp.
- **Baseline 1:** greedy capacitated maximum coverage; mỗi ứng viên chọn thêm nhu cầu chưa được phủ trên một ngưỡng đường đi.
- **Baseline 2:** greedy marginal gain / cost proxy dưới ngân sách.
- **So sánh:** mở rộng trạm có sử dụng cao, xây mới tại vị trí top-ranked, và chọn ngẫu nhiên hợp lệ.

MVP dùng thuật toán baseline có thể giải thích được trước. ML chỉ thêm khi có nhãn và dữ liệu đủ; không cần deep learning để chứng minh bài toán quy hoạch.

## 4. Vai trò của dữ liệu branch `fix/ui`

Occupancy, phiên sạc, công suất/cổng và thời gian chờ tại trạm hiện hữu tạo **tín hiệu áp lực trên cung đã triển khai**:

- Mức dùng theo giờ/ngày/mùa; kWh và lượt phiên.
- Tỷ lệ cổng khả dụng, lỗi/uptime, thời gian chiếm cổng.
- Wait/P90 queue hoặc xác suất đến nơi không có cổng rảnh (nếu dữ liệu hỗ trợ).
- So sánh giữa các trạm sau khi hiệu chỉnh dung lượng, loại sạc, giá và tình trạng hoạt động.

Diễn giải cẩn trọng:

- Utilization cao + chờ lâu + uptime tốt có thể chỉ ra nơi nên xem xét tăng công suất; chưa đủ kết luận lãi.
- Utilization thấp không nhất thiết là cầu thấp: trạm hỏng, giá cao, sai connector, vị trí khó vào hoặc đối thủ gần đó có thể làm số giao dịch thấp.
- Khu không có trạm gần như không thể có session của chính trạm để đo; cần traffic/OD, yêu cầu tìm kiếm, survey hoặc mô hình nhu cầu tiềm ẩn.
- Wait-time forecast là đầu vào/risk signal; không chuyển nguyên mô hình wait thành mô hình site ranking. Đúng theo phân chia của team, dự đoán thời gian chờ/occupancy tiếp tục thuộc branch `fix/ui`; branch hiện tại chỉ nhận dữ liệu aggregate/feature export nếu hữu ích.

## 5. Dữ liệu và độ tin cậy

Thiết kế chuẩn hóa theo cell thời gian và vùng không gian, giữ `source_type`, `observed_at`, `valid_from/to`, `spatial_resolution`, `quality_status`, `scenario_id`, `is_synthetic`. Không join hai bộ dữ liệu chỉ vì cùng tên tỉnh; cần hệ tọa độ, thời gian và độ phân giải tương thích.

Chấm chất lượng riêng cho mỗi thành phần: source quality, freshness, coverage, imputation share và domain match. Điểm địa điểm phải nói rõ khi nhu cầu dựa chủ yếu vào proxy hoặc synthetic.

## 6. Cách đánh giá

- **Dự báo:** temporal holdout, spatial/corridor holdout; MAE/RMSE/Poisson deviance cho counts, MAE cho kWh, calibration cho interval.
- **Độ phủ:** nhu cầu/nhóm dân cư/luồng OD được phục vụ thêm, travel distance/time to nearest compatible point, overlap được khấu trừ.
- **Công suất:** peak concurrency, utilization phân phối theo giờ, tỷ lệ vượt mục tiêu chờ khi có mô hình vận hành hợp lệ.
- **Đầu tư:** tổng chi phí dữ liệu đáng tin cậy; còn lại hiển thị cost proxy hoặc unknown.
- **Độ bền:** thứ hạng/top-k thay đổi thế nào khi EV adoption, home charging, traffic, giá, capex, kết nối điện đổi trong khoảng hợp lý.
- **Kiểm chứng:** review với chuyên gia/đối tác và pilot quan sát trước khi biến ranking thành quyết định.

Không đánh giá bằng cách chỉ so điểm synthetic với dữ liệu synthetic được sinh từ cùng một giả định mà không nêu điều đó.

## 7. Kiến trúc đề xuất

```text
Nguồn dữ liệu / file demo
  -> adapter + provenance + spatial/time validation
  -> vùng nhu cầu và inventory cung hiện có
  -> demand scenarios (baseline / growth / constrained-home-charging / fleet-tourism)
  -> candidate generator + grid/land feasibility flags
  -> marginal coverage / capacity / cost model
  -> ranking or budgeted site portfolio
  -> map + comparison table + scenario sensitivity + export
```

Hệ thống cần cho phép người dùng nhìn thấy assumptions và điều chỉnh ngân sách, horizon, ngưỡng tiếp cận, tỷ lệ xe điện, home charging, công suất lưới và trọng số. Mỗi lần chạy lưu `run_id`, input snapshot, configuration và phiên bản thuật toán để tái lập.

### Đồng bộ thay đổi từ đơn vị chính sách/tài chính

Một policy/finance package có schema, owner, version, effective date, units, validation status và provenance. Technical engine nhận package qua form/API/file import; validate đủ trường và đơn vị; liên kết với cùng `data_snapshot` và `algorithm_version`; sau đó trả portfolio/ranking cùng component metrics, violations, missing inputs và delta so với scenario gốc. Nhờ vậy thay ngân sách/ưu đãi/tariff không đòi viết lại model hoặc copy dữ liệu sang bảng tính rời.
