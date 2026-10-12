# Kế hoạch mở rộng OpenChargeMap thành công cụ lập kế hoạch đầu tư trạm sạc

## Mục tiêu tài liệu

Tài liệu này chuyển ý tưởng sản phẩm sang lộ trình có thể triển khai trên `origin/fix/ui`. Phạm vi là bổ sung công cụ phân tích cho nhà đầu tư/vận hành trạm, đồng thời giữ nguyên luồng tìm trạm và hành trình hiện có cho tài xế.

Phần khảo sát mã nguồn bên dưới dựa trên remote-tracking ref `origin/fix/ui` tại commit `fe2ccd4`. Checkout hiện tại có thể đang ở branch khác; trước khi bắt đầu code, cần checkout hoặc tạo branch công việc từ `fix/ui` và xác nhận ref chưa được cập nhật trên remote.

## 1. Trạng thái dự án trên `fix/ui`

| Khu vực | Hiện trạng cần thiết kế dựa vào |
| --- | --- |
| Backend | FastAPI; API phiên bản nằm dưới `/api/v1` trong `backend/app/api_v1.py`. Repository và service được tạo ở `backend/app/main.py` rồi gắn vào `app.state`. |
| Domain | Tách logic tìm kiếm, forecast, routing, wait estimation và chuyến đi trong `backend/app/domain/`. `backend/app/domain/ml_gateway.py` hiện có `DefaultMlGateway`; các giá trị mặc định phải được nhận diện là default. |
| Forecast/ML | Có pipeline offline ở `ml/build_dataset.py`, `ml/features.py`, `ml/train_eval.py`. Dữ liệu huấn luyện là synthetic. Model artifacts nằm trong vùng bị ignore, không được đảm bảo có sẵn khi chạy app. |
| Simulator | `simulator/` là công cụ CLI riêng để sinh dữ liệu phiên sạc/occupancy synthetic; hiện chưa phải dịch vụ mô phỏng mà API đầu tư có thể gọi trực tiếp. |
| Database | PostgreSQL/PostGIS, schema viết tay dưới `database/schema/`; `database/tables.toml` quản lý thứ tự schema và dữ liệu. Không dùng Alembic migrations. Có PostGIS và chỉ mục GIST cho tọa độ trạm. |
| Dữ liệu | Catalog trạm/cổng/xe, occupancy 5 phút và profile theo thời gian. Dữ liệu occupancy hiện có được sinh từ simulator, không phải telemetry thị trường. Trường `synthetic_fields`, nguồn dữ liệu và cờ forecast cần được giữ trong phản hồi UI. |
| Frontend | React/Vite. Luồng chính hiện ở `frontend/src/App.tsx`, gọi API qua `frontend/src/api.ts`; các component bản đồ và hành trình nằm trong `frontend/src/components/`. Không giả định đã có router hoặc trang Investor Planner. |
| Demo | `fix/ui` dùng demo clock và occupancy history nạp sẵn. README của branch ghi rõ không còn QueueLab, event demo, route cache hay API `/planned-arrivals`. |

### Các ràng buộc thiết kế

1. Các con số hiện tại hỗ trợ minh họa và phát triển; không mô tả occupancy synthetic như nhu cầu thực tế của TP.HCM.
2. Điểm vị trí ban đầu là **chỉ số sàng lọc theo giả định công khai**, không phải khuyến nghị đầu tư đã kiểm chứng.
3. Khi thiếu dữ liệu cho một tiêu chí, trả trạng thái thiếu dữ liệu và giảm mức tin cậy; không tự gán dữ liệu giả.
4. Tính toán mới phải dùng cùng demo clock khi sử dụng occupancy theo thời gian. Không đọc bucket sau thời điểm phân tích.
5. Không đưa API, bảng DB hoặc component vào code path hiện hữu của tài xế nếu tính năng mới không cần chúng.

## 2. Sản phẩm mục tiêu và phạm vi MVP

### Câu hỏi người dùng cần trả lời

1. Khu vực nào đang thiếu hạ tầng sạc tương đối so với các trạm trong catalog?
2. Với một địa điểm đã chọn, cần quy mô bao nhiêu cổng để đáp ứng một kịch bản nhu cầu?
3. Nếu dùng các giả định CAPEX, OPEX, giá điện và giá bán do người dùng nhập, phương án có thể hoàn vốn trong bao lâu?

### Đưa vào MVP

- Chọn và so sánh tối đa một số ít vị trí ứng viên trên bản đồ TP.HCM.
- Tính coverage gap, khoảng cách đến trạm hiện hữu, mức cạnh tranh đơn giản, khả năng tương thích hạ tầng và độ đầy đủ dữ liệu.
- Cho người dùng chọn trạm tương đồng làm nguồn tham chiếu cho kịch bản nhu cầu; ghi rõ khi nguồn tham chiếu là synthetic.
- So sánh một nhóm cấu hình cổng/công suất theo cùng một bộ giả định.
- Tính mô hình tài chính minh bạch theo low/base/high case và hiển thị giả định đã nhập.
- Chạy trước trong một phiên frontend; chưa lưu dự án đầu tư vào database.

### Để sau MVP

- Tuyên bố có dự báo nhu cầu thực tế theo địa điểm mới.
- Dùng ML để dự báo doanh thu hoặc đánh giá lợi nhuận.
- Tự thu thập mật độ dân cư, POI, giao thông, giá thuê, biểu giá điện hoặc giấy phép nếu chưa có nguồn dữ liệu và quyền sử dụng phù hợp.
- Lưu nhiều dự án, chia sẻ dự án, phân quyền người dùng hoặc audit lịch sử.
- Tối ưu hóa toàn cục hoặc tìm vị trí tối ưu cho cả thành phố.

## 3. Tính năng A — Sàng lọc và chấm điểm địa điểm

### 3.1. Luồng người dùng

1. Mở chế độ **Lập kế hoạch đầu tư** từ giao diện hiện tại.
2. Chọn một điểm trên bản đồ hoặc nhập tọa độ.
3. Chọn phạm vi phân tích và các trọng số trong giới hạn cấu hình được công khai.
4. Xem các thành phần điểm, trạm tham chiếu, trường dữ liệu còn thiếu và provenance.
5. Thêm tối đa 3–5 ứng viên vào bảng so sánh trong phiên làm việc.

### 3.2. Chỉ số MVP

| Chỉ số | Cách tính khả thi ở branch hiện tại | Giới hạn phải hiển thị |
| --- | --- | --- |
| Khoảng trống hạ tầng | Đếm trạm/cổng trong bán kính hoặc vùng phân tích; tính khoảng cách đến trạm gần nhất. PostGIS có thể lọc theo tọa độ và chỉ mục GIST. | Không đồng nghĩa với thiếu nguồn cung nếu catalog chưa đầy đủ. |
| Cạnh tranh | Số trạm, số cổng và công suất danh mục trong vùng phân tích. | Không có thị phần, lưu lượng khách hoặc hiệu suất kinh doanh của đối thủ. |
| Khả năng tiếp cận | Dùng tuyến đường từ provider hiện có khi API trả tuyến; nếu không, dùng khoảng cách địa lý làm proxy và gắn nhãn nguồn. | Không tự suy ra chất lượng lối vào, bãi đỗ hoặc giấy phép. |
| Nhu cầu tham chiếu | Dùng occupancy/profile của trạm được chọn làm peer, hoặc một giả định thủ công do người dùng nhập. | Lịch sử trong branch là synthetic; không gán nó thành nhu cầu của điểm mới. |
| Mức phù hợp hạ tầng | So sánh loại đầu nối/công suất dự kiến với cấu hình người dùng chọn và catalog trạm lân cận. | Không thay thế khảo sát lưới điện, mặt bằng hoặc khả năng đấu nối. |
| Độ tin cậy dữ liệu | Tổng hợp độ đầy đủ và nguồn của các trường đầu vào, bao gồm `synthetic_fields`. | Không dùng một phần trăm confidence mang nghĩa xác suất nếu chưa hiệu chuẩn. |

Chuẩn hóa từng chỉ số về cùng thang điểm, ví dụ 0–100. Công thức và trọng số phải nằm trong response để UI giải thích được kết quả:

```text
screening_score =
    w_gap × coverage_gap
  + w_access × accessibility
  + w_fit × infrastructure_fit
  + w_demand × demand_proxy
  - w_competition × competition
```

Trọng số được validate, tổng trọng số hợp lệ phải bằng 1 (hoặc được chuẩn hóa ở backend). Điểm tổng hợp phải có tên **screening score**; không gọi là ROI, xác suất thành công hay vị trí tối ưu.

### 3.3. Tích hợp code

- Frontend: thêm feature riêng dưới `frontend/src/investor/` hoặc `frontend/src/features/investor/`; cập nhật `App.tsx` để chuyển giữa hành trình tài xế và planner. Không nhét logic đầu tư vào `RecommendationList`.
- Bản đồ: tái sử dụng provider và kiểu tọa độ của ứng dụng. Nếu `MapView` phụ thuộc chặt vào trạng thái hành trình, tạo view bản đồ planner riêng dùng cùng thư viện/provider thay vì làm component tài xế phình to.
- API client: thêm hàm và kiểu dữ liệu có tên rõ ràng trong `frontend/src/api.ts` và types tương ứng.
- Backend: thêm schema request/response trong `backend/app/api_v1_models.py`; route mới trong `backend/app/api_v1.py` với prefix `/investor`; domain thuần trong `backend/app/domain/investment/` (ví dụ `site_scoring.py`). Route gọi service và repository, không chứa công thức.
- Dữ liệu: lấy station/catalog từ repository hiện có. Bổ sung truy vấn PostGIS vào repository nếu truy vấn hiện tại chưa đáp ứng phạm vi bán kính; không tải toàn bộ catalog vào frontend để tự tính.

### 3.4. API đề xuất

```http
POST /api/v1/investor/sites/score
POST /api/v1/investor/sites/compare
```

Request chấm điểm gồm tọa độ WGS84, bán kính/vùng phân tích, trọng số, cấu hình trạm dự kiến và tham chiếu nhu cầu tùy chọn. Response gồm điểm tổng hợp, điểm con, giá trị đầu vào, đơn vị, nguồn dữ liệu, cờ synthetic, mục thiếu dữ liệu và phiên bản công thức.

Không tạo `GET /investor/stations` nếu `GET /api/v1/stations` cùng repository đã cung cấp catalog cần thiết. Tránh nhân đôi API chỉ để đổi tên dữ liệu.

### 3.5. Điều kiện nghiệm thu

- Chấm điểm và so sánh ít nhất hai vị trí với cùng công thức.
- Hiển thị được trạm/cổng được dùng trong phạm vi phân tích.
- Thay trọng số làm điểm được tính lại nhất quán.
- Response cho biết dữ liệu synthetic/thiếu và nguồn của từng proxy chính.
- Kết quả không tuyên bố nhu cầu hay tính khả thi tài chính đã được xác minh.

## 4. Tính năng B — Kịch bản nhu cầu và cấu hình công suất

### 4.1. Nguồn nhu cầu theo thứ tự ưu tiên

1. Nhu cầu/session thực có nguồn và quyền sử dụng được xác minh (chưa có trong baseline `fix/ui`).
2. Occupancy lịch sử của một trạm peer do người dùng chọn; branch hiện có profile và chuỗi thời gian nhưng dữ liệu seed là synthetic.
3. Mức lượt đến/đường cong nhu cầu do người dùng nhập.

Nếu dùng nhánh 2 hoặc 3, UI ghi rõ **kịch bản synthetic/giả định**, thời gian, peer và đơn vị. Không quảng bá kết quả là forecast thị trường.

### 4.2. MVP tối ưu công suất

Người dùng cấu hình số cổng, công suất mỗi cổng, hệ số đồng thời/giới hạn công suất tổng, thời gian hoạt động và kịch bản nhu cầu. Backend tính cho từng cấu hình:

- lượt đến và phiên có thể phục vụ;
- mức sử dụng cổng và năng lượng bán ra ước tính;
- thời gian chờ hoặc tỷ lệ nhu cầu không được phục vụ nếu mô hình hàng đợi có đủ đầu vào;
- CAPEX/OPEX giả định;
- lý do cấu hình bị loại (ngân sách, giới hạn công suất hoặc ngưỡng dịch vụ).

Đầu tiên triển khai một bộ mô phỏng xác định, có thể tái lập, với bộ tham số và seed rõ ràng. Không phụ thuộc vào một `QueueLab` trong frontend: nhánh `fix/ui` không có component đó. `simulator/` hiện là CLI độc lập; chỉ trích xuất/chia sẻ logic sau khi xác nhận ranh giới module và định dạng đầu vào/đầu ra phù hợp.

Có thể dùng occupancy profile, forecast service và wait estimator hiện tại làm dữ liệu tham khảo, nhưng cần kiểm tra rõ nguồn: predictor XGBoost chỉ khả dụng nếu artifact được tạo và cấu hình đúng; gateway mặc định vẫn có thể trả giá trị default. Kết quả phải trả `prediction_source`, flags và provenance xuyên suốt.

### 4.3. API và UI

API đề xuất:

```http
POST /api/v1/investor/capacity/simulate
POST /api/v1/investor/capacity/compare
```

UI feature có thể gồm form giả định, đồ thị nhu cầu, bảng cấu hình và bảng so sánh. Dùng thư viện hiện có hoặc biểu đồ SVG/CSS đơn giản; không thêm thư viện lớn trước khi cần.

Response phải chứa request đã chuẩn hóa, các giả định, metric theo từng cấu hình, nguồn nhu cầu, phạm vi thời gian, flags synthetic/default và công thức/phiên bản mô hình. Chưa cần endpoint lưu scenario.

### 4.4. Điều kiện nghiệm thu

- So sánh ít nhất ba cấu hình trên cùng một kịch bản đầu vào.
- Kết quả tái lập với cùng request và seed.
- Có baseline đơn giản để đối chiếu với XGBoost khi model artifact không có.
- Hiển thị nhãn synthetic/default và không dùng dữ liệu tương lai so với demo clock.
- Giải thích được giới hạn mô hình hàng đợi và mọi cấu hình bị loại.

## 5. Tính năng C — ROI và thời gian hoàn vốn

### 5.1. Đầu vào do người dùng kiểm soát

- CAPEX: chi phí đất/mặt bằng nếu có, thiết bị, xây dựng, đấu nối và chi phí dự phòng.
- OPEX: thuê mặt bằng, bảo trì, nhân sự, phí cố định và chi phí khác.
- Giá mua điện, giá bán theo kWh, tổn thất điện và thuế/phí nếu người dùng có dữ liệu.
- Kịch bản lượt đến/năng lượng bán, công suất và thời gian vận hành lấy từ bước B hoặc nhập thủ công.
- Thời hạn phân tích, tăng trưởng giả định và tỷ lệ chiết khấu nếu cần NPV.

MVP không tự điền giá thị trường. Mọi giá trị mặc định (nếu có) phải gắn nhãn giả định và cho phép sửa.

### 5.2. Phép tính MVP

```text
energy_sold_kwh = min(demand_kwh, service_capacity_kwh)
revenue = energy_sold_kwh × selling_price_per_kwh
energy_cost = energy_purchased_kwh × purchase_price_per_kwh
operating_cash_flow = revenue - energy_cost - other_opex
```

Tính dòng tiền theo kỳ và thời điểm dòng tiền tích lũy bù CAPEX. Nếu không hoàn vốn trong kỳ mô phỏng hoặc dòng tiền âm, trả trạng thái rõ ràng; không trả số năm vô hạn hoặc một con số suy diễn.

Chạy low/base/high case và phân tích độ nhạy theo từng biến. Không gán xác suất cho các case khi chưa có phân phối thống kê được hiệu chuẩn. Phân biệt gross revenue, operating cash flow, payback, NPV và EBITDA; chỉ báo những chỉ số mà bộ giả định thực sự hỗ trợ.

### 5.3. API và điều kiện nghiệm thu

```http
POST /api/v1/investor/roi/simulate
POST /api/v1/investor/roi/compare
```

Response có dòng tiền theo kỳ, tổng doanh thu/chi phí, trạng thái hoàn vốn, các giả định đã áp dụng và cảnh báo thiếu dữ liệu. Với cùng đầu vào, kết quả phải xác định và có thể tái lập. UI trình bày công thức/đơn vị, không chỉ hiển thị một số ROI tổng hợp.

## 6. Lưu dữ liệu và thay đổi schema

### MVP

- Giữ ứng viên và giả định trong state của frontend; kết quả tính qua API, không lưu lâu dài.
- Không thêm bảng chỉ để lưu điểm số tạm thời.
- Có thể thêm cấu hình mặc định phi nhạy cảm vào `app_config` nếu thật sự cần; không lưu dữ liệu dự án cá nhân vào cấu hình chung.

### Khi cần lưu dự án

Branch này quản lý DDL bằng tay. Thêm DDL vào `database/schema/<group>/`, khai báo bảng theo đúng thứ tự trong `database/tables.toml`, cập nhật seed/export nếu phù hợp, rồi chạy `python database/scripts/verify.py`. Không tạo Alembic migration hoặc TimescaleDB/Redis dependency theo kế hoạch cũ.

Các bảng có thể cân nhắc sau MVP: `investment_projects`, `site_candidates`, `investment_scenarios`, `simulation_results`. Mỗi bản ghi cần lưu version công thức, giả định đầu vào, nguồn dữ liệu, cờ synthetic và thời điểm tính để tái hiện kết quả.

## 7. Kiến trúc đích

```text
React Investor Planner
  ├── chọn vị trí, cấu hình, giả định
  ├── bản đồ/catalog hiện hữu
  └── biểu đồ và so sánh kết quả
          │ typed API client
          ▼
FastAPI /api/v1/investor/*
  ├── Pydantic request/response
  ├── investment domain services (công thức thuần, kiểm thử được)
  └── repository hiện có + truy vấn PostGIS cần thiết
          │
          ├── catalog trạm/cổng/xe
          ├── occupancy history/profile (synthetic ở demo hiện tại)
          └── forecast service (model hoặc default/persistence, luôn có provenance)
```

Tách phép tính thuần khỏi API và database để có thể kiểm tra riêng. Tái sử dụng `app.state.station_repository`, `station_status_repository`, `occupancy_forecast_service` và các repository phù hợp; không truy cập trực tiếp database từ component frontend.

## 8. Lộ trình triển khai

### Giai đoạn 0 — Chốt baseline và hợp đồng dữ liệu

- Làm việc từ `fix/ui`; xác nhận commit/ref hiện tại.
- Chạy ứng dụng theo README và kiểm tra endpoint/schema đang có trước khi sửa.
- Chốt station fields, ID, units, timezone, nguồn occupancy và cách truyền synthetic flags.
- Tạo ví dụ request/response cho site score, capacity simulation và ROI.

**Đầu ra:** tài liệu hợp đồng API, bộ giả định demo có nguồn rõ ràng, danh sách endpoint/file cần đổi.

### Giai đoạn 1 — Site Screening vertical slice

- Backend: scoring service thuần, schemas và endpoint score/compare.
- Data: catalog query theo tọa độ/phạm vi, PostGIS nếu cần.
- Frontend: mode planner, chọn điểm, score panel, candidate comparison.
- Hoàn thiện provenance và thiếu-dữ-liệu behavior trước khi chuyển sang optimizer.

**Gate:** người dùng so sánh được hai vị trí và giải thích được điểm.

### Giai đoạn 2 — Capacity scenarios

- Chốt demand inputs; hỗ trợ user-entered baseline và peer profile synthetic.
- Xây mô phỏng deterministic cho một địa điểm và nhiều cấu hình.
- Chỉ tích hợp model predictor nếu artifact/version/metric/source được xác minh; baseline vẫn chạy độc lập.
- Thêm chart/bảng so sánh, labels synthetic/default và giới hạn mô hình.

**Gate:** ba cấu hình cho kết quả tái lập, có baseline và giải thích được.

### Giai đoạn 3 — ROI/payback

- Thêm form CAPEX/OPEX/giá bán/giá mua điện và validation đơn vị.
- Tính dòng tiền theo kỳ từ kết quả capacity hoặc giả định nhập tay.
- Thêm low/base/high case và sensitivity analysis.

**Gate:** người dùng thay đổi được giả định và thấy tác động lên dòng tiền/payback.

### Giai đoạn 4 — Lưu dự án và hoàn thiện

- Chỉ khi có yêu cầu lưu qua nhiều phiên: thiết kế bảng, quyền sở hữu và retention.
- Bổ sung snapshot/version của assumptions, công thức và provenance.
- Hoàn thiện loading/error/empty state, API docs và tài liệu giới hạn.

## 9. Rủi ro và cách xử lý

| Rủi ro | Cách xử lý trong sản phẩm |
| --- | --- |
| Catalog trạm thiếu hoặc cũ | Hiện nguồn và thời điểm cập nhật; gọi score là screening; hỗ trợ danh sách ứng viên tự nhập khi phù hợp. |
| Occupancy synthetic bị hiểu là telemetry thật | Gắn nhãn synthetic trong API và UI; không trộn với dữ liệu thật nếu chưa phân biệt được nguồn. |
| XGBoost artifact không có hoặc chất lượng chưa đạt | Dùng baseline/default có tên nguồn rõ ràng; không đổi nhãn thành ML forecast. |
| Điểm site quá phụ thuộc trọng số | Công khai weights, hiển thị điểm con và sensitivity theo weights. |
| Queue model quá giản lược | Công khai giả định arrival/service, giới hạn theo thời gian và tỷ lệ nhu cầu không phục vụ. |
| ROI bị xem như tư vấn đầu tư | Hiện assumptions, phạm vi tính, dữ liệu còn thiếu và khoảng/kịch bản; không khẳng định chắc chắn lợi nhuận. |
| Thay đổi làm hỏng luồng tài xế | Tách investor feature, giữ API driver tương thích và kiểm tra các luồng tìm trạm/hành trình hiện hữu. |

## 10. Định nghĩa hoàn thành

Một bản MVP hoàn thành khi nhà đầu tư có thể chọn vị trí, xem và so sánh screening score, thay cấu hình cổng/công suất, nhập giả định tài chính và xem các kịch bản dòng tiền/payback trong cùng giao diện. Mọi điểm số và kết quả đều nêu rõ công thức, đầu vào, đơn vị, nguồn dữ liệu và trường synthetic/default; luồng tài xế vẫn hoạt động độc lập.

MVP này là công cụ **khám phá kịch bản**, không phải dự báo thị trường hay thẩm định khả thi dự án.\n