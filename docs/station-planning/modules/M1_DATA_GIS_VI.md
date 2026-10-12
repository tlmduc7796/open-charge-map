# M1 — Dữ liệu, GIS và tập ứng viên

## Prompt giao việc

Bạn phụ trách module M1 cho tính năng station planning trong ứng dụng hiện hữu. Đọc `../IMPLEMENTATION_PLAN_VI.md` và `SHARED_CONTRACT_VI.md` trước khi sửa code. Hãy khảo sát baseline `fix/ui` mới nhất, đề xuất/triển khai lớp dữ liệu và GIS nhỏ nhất để tạo demo TP.HCM có provenance. Không tự đổi API hoặc công thức ranking.

## Mục tiêu

Tạo tập dữ liệu không gian có thể giải thích và kiểm tra: địa giới/pilot extent, catalog trạm hiện có, candidate sites, demand cells/proxies và nguồn của từng dữ liệu. Module này cung cấp dữ liệu/adapter để domain engine truy cập; không tự quyết định site nào tốt.

## Phạm vi và task nhỏ

1. **Khảo sát baseline:** kiểm tra bảng/trường station, connector/port, status, occupancy, spatial index, repository, schema loader và quy tắc seed trên `fix/ui` hiện tại. Ghi file/field thật; không dựa duy nhất vào `ideas.md` snapshot.
2. **HCMC boundary:** pin source, version, CRS, effective date và cách lưu pilot extent. Geometry demo phải được ghi rõ là chính thức, tổng hợp hay vẽ minh họa; không gọi hình vẽ tự tạo là ranh giới pháp lý.
3. **Data dictionary:** thống nhất ID, units, timezone, status, source/provenance, quality và synthetic flags cho `existing_sites`, `candidate_sites`, `demand_cells`/OD.
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
