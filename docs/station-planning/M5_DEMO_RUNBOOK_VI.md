# M5 — Kịch bản demo và nghiệm thu

## Câu chuyện demo

So sánh ba giả thuyết địa điểm trong pilot 9 phường: nếu siết vùng tiếp cận từ 15 xuống 5 phút, thứ hạng và độ phủ tăng thêm thay đổi thế nào? Các vị trí là candidate synthetic lấy ngữ cảnh từ POI; chúng chưa phải parcel/site đã khảo sát. Kết quả dùng để trình diễn cách engine áp dụng cùng một demand/access snapshot cho các cấu hình khác nhau.

## Seed đã pin

- Snapshot: `hcmc-nine-wards-demo-v3`, seed `20261013`, boundary `ADMINISTRATIVE_2025`.
- Study area: pilot 9 phường; 37 existing-site fixtures, 18 candidate hypotheses, 27 demand nodes.
- Chọn ba candidate: `cand-hcm_2025_26911-02`, `cand-hcm_2025_26929-01`, `cand-hcm_2025_27073-01`. Nhãn và geometry đọc từ snapshot API, không nhập lại thủ công.
- Cấu hình kỹ thuật mặc định: DC 4 × 80 kW; demand `base`; access profile `normal`; ngân sách riêng từng candidate để trống. 10 tỷ VND của M1 là tham chiếu portfolio, chưa phải thuật toán chọn nhiều site.
- Không có thao tác ghi/reset dữ liệu: API đọc snapshot bất biến từ file; mỗi lần chạy tính lại từ cùng IDs, seed và config.

## Chạy demo

Từ thư mục gốc repo:

```powershell
docker compose up --build
```

Mở `http://127.0.0.1:5173`, chuyển sang Planner, xác nhận pilot/snapshot hiển thị đúng, giữ ba candidate mặc định, chọn coverage `5` phút và demand `base`, để budget trống rồi bấm **Chạy scenario**. Có thể đổi coverage sang `15`, hoặc demand sang `low`/`high`, rồi chạy lại để so sánh. Swagger backend ở `http://127.0.0.1:8000/docs`.

Để chạy acceptance backend mà không cần database:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_planning_recommendation_engine.py backend/tests/test_planning_integration.py backend/tests/test_api_v1.py --basetemp=.pytest-tmp -k "not test_internal_port_status_requires_configuration_and_key" -q
```

Kiểm tra snapshot và các helper dữ liệu:

```powershell
.venv\Scripts\python.exe scripts\validate_station_planning_demo.py
.venv\Scripts\python.exe -m unittest tests.test_station_planning_demo tests.test_station_planning_rules tests.test_station_planning_data_plan -v
```

`validate_station_planning_contract.py` cần `jsonschema`; cài requirements của station-planning trước khi chạy validator này (xem [hướng dẫn dữ liệu](../../data_platform/station_planning/README.md#tạo-lại-và-kiểm-tra)). Không chạy generator cho một buổi demo thường lệ.

## Kết quả tham chiếu

Điểm được làm tròn một chữ số; demand là expected sessions trong tuần synthetic, không phải số lượt thực tế.

| Cấu hình | Thứ tự xếp hạng | Độ phủ tăng thêm theo thứ tự |
|---|---|---|
| 5 phút, demand base | `26911-02` → `27073-01` → `26929-01` | 0% → 3,55% → 5,57% |
| 15 phút, demand base | `26929-01` → `26911-02` → `27073-01` | 0% → 0% → 0% |

Khi giữ 5 phút và đổi demand `low` → `base` → `high`, thứ hạng vẫn giữ nguyên; demand tuần của candidate đầu tiên lần lượt xấp xỉ `644`, `1.073`, `1.717` expected sessions. Đây là độ nhạy theo ba kịch bản tổng hợp, không phải xác suất hay forecast thị trường. Mốc 15 phút phủ hết các demand nodes có thể tiếp cận trong fixture hiện tại nên marginal coverage gain bằng 0; giữ nguyên kết quả này khi trình bày.

Nếu đặt budget từng candidate rất thấp (ví dụ `1` VND), run trả `no_feasible_candidates` và đánh dấu candidate bị loại bởi ràng buộc ngân sách kịch bản. Điều đó không khẳng định site không thể xây được. Cost chỉ là CAPEX giả định theo `base_cost` khi cấu hình khớp; không có ROI, payback hay lợi nhuận.

## Checklist khi trình bày

- Giới thiệu đây là pilot 9 phường, không phải coverage toàn TP.HCM.
- Nêu `synthetic`, `scenario`, `proxy` và `unknown` đúng theo nhãn trên UI. Access time là proxy từ ma trận, không phải route thời gian thực.
- Giải thích thứ hạng bằng demand/access/coverage và reason codes; không gọi điểm kỹ thuật là xác suất thành công.
- Nhấn mạnh candidate vẫn conditional khi quyền sử dụng đất, đấu nối/lưới, cấp phép và các bằng chứng vật lý chưa được xác nhận.
- Để trống budget cho run mặc định; nếu trình diễn no-feasible, nói rõ đây là ngưỡng ngân sách nhập vào.
- Thử so sánh hai candidate và kiểm tra luồng Planner không làm đổi luồng tìm trạm/hành trình cũ.

## Nghiệm thu và giới hạn môi trường

- PASS: snapshot và contract validators; 19 kiểm tra helper dữ liệu/rule; 20 test API/engine/planning integration; frontend TypeScript/Vite production build, ESLint và 80 Vitest tests (gồm 2 PlannerView tests); full backend suite.
- Browser click-through thủ công chưa được ghi nhận; hoàn tất các kịch bản ở trên bằng trình duyệt trước khi trình diễn.
- Full backend run skip module trip persistence khi các route `/api/v1/trips` không thuộc OpenAPI hiện hành; test cần PostgreSQL chỉ chạy khi cấu hình test database. Đây là phạm vi có chủ đích, không phải pass của các route trip.
- Production build có cảnh báo bundle JavaScript lớn hơn 500 kB (bundle hiện khoảng 1,2 MB); đây là tối ưu hiệu năng tải trang, không làm build thất bại.
- Chưa xác minh integration với dữ liệu vận hành PostGIS. Adapter M3 hiện pin file snapshot để bảo toàn tính tái lập; không trộn candidate/demand synthetic với station catalog live.

## Dữ liệu cần có trước pilot thực

Ranh giới và ngày hiệu lực có nguồn chính thức; parcel, quyền tiếp cận, giá đất/thuê và cấp phép; capacity/điều kiện đấu nối từng khu vực; giao thông hoặc OD và nhu cầu chưa được đáp ứng; dữ liệu vận hành trạm có thời điểm; cùng CAPEX/OPEX, tariff và mục tiêu đầu tư do đơn vị có thẩm quyền cung cấp.
