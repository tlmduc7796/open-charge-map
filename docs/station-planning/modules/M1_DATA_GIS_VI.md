# M1 — Dữ liệu, GIS và tập ứng viên

## Prompt giao việc

Bạn phụ trách module M1 cho tính năng station planning trong ứng dụng hiện hữu. Đọc `../IMPLEMENTATION_PLAN_VI.md` và `SHARED_CONTRACT_VI.md` trước khi sửa code. Hãy khảo sát baseline `fix/ui` mới nhất, đề xuất/triển khai lớp dữ liệu và GIS nhỏ nhất để tạo demo TP.HCM có provenance. Không tự đổi API hoặc công thức ranking.

## Mục tiêu

Tạo tập dữ liệu không gian có thể giải thích và kiểm tra: địa giới/pilot extent, catalog trạm hiện có, candidate sites, demand cells/proxies và nguồn của từng dữ liệu. Module này cung cấp dữ liệu/adapter để domain engine truy cập; không tự quyết định site nào tốt.

## Dữ liệu và phạm vi demo đã chốt

- Existing sites chỉ lấy từ `raw_data/charging_stations/hcm_dc80kw/hcm_dc80kw_5wards.geojson` (37 trạm mô phỏng tại 9 phường; CSV cùng tên để đối chiếu). Chọn một định dạng ingest, giữ ID EVC và gắn synthetic; không tự ghép toàn bộ 668 trạm.
- Không sử dụng `raw_data/admin_boundaries/ref.kml` để ingest, enrich, tái sinh fixture hoặc xây feature cho bài toán.
- Pilot extent là hợp 9 polygon tương ứng trong `raw_data/admin_boundaries/hcm_planning_units_2025.geojson`; danh sách phường và ID có trong `five_wards_report.json` của bộ trạm. Demand/candidates/POI/giao thông phải cùng extent; dân số lấy đúng 9 phường.
- Connector, uptime, giá bán sạc, grid/land/permit chưa có bằng chứng phải để unknown hoặc ghi giả định scenario riêng. Không trình bày bộ trạm/capacity mô phỏng như inventory thực.
- Nếu giảm thêm số trạm để demo, lưu selection IDs/rule/version trong snapshot riêng; chỉ tính coverage của fixture được chọn. Mở rộng dữ liệu là scenario riêng.
- Phần 3 lọc dân số/POI/giao thông đã thu thập về pilot, giữ provenance và xử lý trùng. Phần 4–6 synthetic hoàn toàn: candidate dựa trên POI phù hợp và vùng giao thông cao giả định; demand và vận hành có seed, cấu trúc giờ/ngày và capacity checks. Không nhập occupancy/wait từ nguồn khác như observed vào demo mặc định.
- Vị trí candidate có thể tham chiếu POI nguồn nhưng bản ghi candidate là synthetic; “POI chưa có trạm” được kiểm tra với fixture 37 site. Chưa có lưu lượng xe đo được, nên mọi traffic intensity dùng cho sinh candidate/demand phải có nhãn scenario hoặc proxy hạ tầng.
- Phần 9 ghép biểu giá điện nguồn thu thập với chi phí/hệ số giả định; metadata phải tách hai loại input. P7/P8 đã chốt tại `../P7_P8_DECISIONS_VI.md`: ma trận haversine/circuity/speed proxy và technical constraints có provenance/unknown handling. Snapshot hiện hành là `demo_hcmc_v3`; không tự thay công thức/giá trị đã chốt.

## Phạm vi và task nhỏ

1. **Khảo sát baseline:** kiểm tra bảng/trường station, connector/port, status, occupancy, spatial index, repository, schema loader và quy tắc seed trên `fix/ui` hiện tại. Ghi file/field thật; không dựa duy nhất vào `ideas.md` snapshot.
2. **HCMC boundary:** pin source, version, CRS, effective date và cách lưu pilot extent. Geometry demo phải được ghi rõ là chính thức, tổng hợp hay vẽ minh họa; không gọi hình vẽ tự tạo là ranh giới pháp lý.
3. **Data dictionary:** thống nhất ID, units, timezone, status, source/provenance, quality và synthetic flags cho `existing_sites`, `candidate_sites`, `demand_cells`/OD. Phân biệt feature (POI/traffic/land use) với label demand (sessions/kWh/requests); không tự tạo label ML từ proxy.
4. **Candidate input:** MVP nhận candidate IDs từ dataset (mode `provided`). Nếu có chức năng sinh candidate, mô tả thuật toán, resolution, exclusions và lý do; không tạo hàng loạt điểm không có nghĩa địa lý.
5. **Spatial lookup:** cung cấp truy vấn trạm/cổng tương thích trong vùng/coverage threshold qua repository/PostGIS hiện có. Không tải catalog toàn bộ sang browser.
6. **Validation:** kiểm tra CRS/range, duplicates, temporal validity, null-vs-zero, units, source completeness và HCMC/pilot scope.
7. **Sample:** tạo data nhỏ, synthetic/proxy được gắn nhãn từng record, đủ để so sánh 2–5 ứng viên.

## Không thuộc module

- Tính screening score, finance, ROI/payback hoặc chọn portfolio.
- Sửa API route/UI trực tiếp.
- Khẳng định occupancy synthetic là nhu cầu thật hoặc tự thu thập dữ liệu bên ngoài không có quyền sử dụng rõ.
- Thêm bảng DB nếu file seed/repository existing đủ cho MVP.

## Artifact bàn giao

- Data dictionary và nguồn/version của geometry.
- Candidate/demand sample có provenance và nhãn synthetic.
- Nếu có label demand, cung cấp training table theo thời gian/không gian và ghi rõ độ phủ/missingness; nếu chưa có thì bàn giao feature table + baseline scenario cho M2A.
- Repository/query interface hoặc format file seed được M2/M3 dùng.
- Báo cáo completeness/unknowns và quyết định GIS (CRS, distance/network metric).
- Hướng dẫn nạp/reset sample theo workflow DB hiện có.

## Acceptance

- Hai candidate có thể được truy vấn cùng catalog trạm trong đúng pilot extent.
- Mỗi feature/record có source/status; synthetic hiển thị rõ.
- Query không trộn CRS hay timezone; unknown không bị biến thành zero.
- Candidate thiếu grid/permit data trả unknown/conditional.
- Seed nhỏ có thể tái tạo, không chứa dữ liệu nhạy cảm.

## Handoff

Ghi interface thực tế M2/M3 cần dùng, tên file/table/query, sample IDs, cách nạp data, validation đã chạy và giới hạn coverage.
