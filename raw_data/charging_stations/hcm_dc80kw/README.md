# Trạm sạc mô phỏng TP.HCM — DC 80kW

Ba file `hcm_dc80kw.kml`, `hcm_dc80kw.csv`, `hcm_dc80kw.geojson` chứa cùng dữ liệu, theo cùng thứ tự từ nguồn `input_data/admin_boundaries/ref.kml`.

- Lọc theo thuộc tính `Địa chỉ:` có ghi Hồ Chí Minh, HCM hoặc TPHCM, không phân biệt hoa/thường/dấu. Loại trường hợp chỉ có tên đường Hồ Chí Minh/HCM ở tỉnh khác.
- Bao gồm địa chỉ có ghi TP.HCM nhưng vẫn kèm địa danh Bình Dương/Bà Rịa–Vũng Tàu trong nguồn. Không bổ sung trạm chỉ ghi Bình Dương/Bà Rịa–Vũng Tàu mà không nhắc TP.HCM; không lọc bằng đa giác ranh giới.
- Loại trạm có kinh độ > 108 **hoặc** vĩ độ > 12, cùng điểm `EVC-529` có kinh độ `106.43845280110354`. Còn 668 trạm. Loại các mã `EVC-529`, `EVC-642`, `EVC-670`, `EVC-671`, `EVC-672`, `EVC-673`; giữ nguyên mã của các trạm còn lại.
- Địa chỉ mới: `Điểm sạc EVC-xx, Thành phố Hồ Chí Minh`. Đây là địa chỉ mô phỏng; không giữ địa chỉ đường/phường của trạm gốc.
- `Ghi chú:` chỉ là `Dữ liệu mô phỏng`. `description` được tạo lại từ các thuộc tính mới.
- `Nhãn:` luôn là `DC 80kW`. `Trụ sạc:` chỉ ghi `DC 80kW có N cổng sạc` hoặc `DC 80kW - số cổng sạc chưa xác định`. Không chứa hãng/đơn vị vận hành hoặc dòng liên kết của nguồn.
- Tổng số cổng đã biết nằm trong `export_report.json`. 10 trạm không có số cổng trong nguồn: ghi `số cổng sạc chưa xác định`, không gán thành 0. Danh sách mã nằm trong `export_report.json`.
- Kinh độ, vĩ độ và tọa độ Point đều giữ nguyên từng giá trị nguồn. Một số trạm trong nguồn có giá trị thuộc tính kinh/vĩ độ khác nhẹ so với Point; bản sao giữ cả hai như yêu cầu. Thống kê nằm trong `export_report.json`.
- Giữ nguyên `Hoạt động:` và `Trạng thái:`. Thư mục trạm (`Folder`) được đặt tên `Trạm mô phỏng (1)`, `Trạm mô phỏng (2)`, `Trạm mô phỏng (3)`. KML dùng Style nội bộ `evc-dc80kw`, với icon ghim xanh có tia sét trắng tự tạo, không có logo. Icon nằm tại `icons/evc-dc80kw.png`; giữ thư mục `icons` bên cạnh KML khi sao chép để trình xem tải được icon.
- CSV dùng UTF-8 BOM, dấu phẩy, đặt dấu ngoặc kép đúng quy tắc với trường nhiều dòng hoặc chứa dấu phẩy. Cột `coordinates` là `kinh độ,vĩ độ,độ cao`.
- GeoJSON dùng `FeatureCollection`, hình học `Point`, tọa độ `[kinh độ, vĩ độ, độ cao]`. Các giá trị tọa độ dạng chuỗi trong `properties` giữ cách ghi của nguồn.

`export_report.json` ghi số lượng, dấu vân tay SHA-256 nguồn và kết quả đối chiếu. File gốc không bị sửa.

## Các trạm thuộc chín phường

`hcm_dc80kw_5wards.kml` chứa các trạm thuộc Sài Gòn, Bến Thành, Xuân Hòa, Tân Định, Phú Nhuận, Bình Thạnh, Tân Sơn Hòa, Thạnh Mỹ Tây và Bình Quới, chia thành thư mục theo phường. Giữ tên file cũ để các liên kết vẫn hoạt động; tiêu đề bên trong đã cập nhật thành chín phường. Đối chiếu tọa độ Point với đa giác phường trong `input_data/admin_boundaries/hcm_admin_2025.geojson`, không dùng địa chỉ mô phỏng để xác định phường. Bao gồm điểm trên đường biên, loại điểm trong lỗ đa giác; điểm khớp nhiều phường chỉ xuất một lần theo thứ tự danh sách trên. Giữ nguyên mã, dữ liệu trạm và icon. Số lượng từng phường cùng danh sách mã nằm trong `five_wards_report.json`.

Tổng cộng 37 trạm. Năm phường ban đầu vẫn có đủ 21 trạm: Sài Gòn 6, Bến Thành 5, Xuân Hòa 5, Tân Định 3, Phú Nhuận 2. Bổ sung 16 trạm: Bình Thạnh 2, Tân Sơn Hòa 3, Thạnh Mỹ Tây 8, Bình Quới 3. Không có điểm khớp nhiều phường. Đã đối chiếu độc lập bằng phép tính tổng góc quanh điểm.

Bản trích có thêm `hcm_dc80kw_5wards.csv` và `hcm_dc80kw_5wards.geojson`, cùng 37 trạm và cùng thứ tự với KML. Trường `Phường:` ghi phường của mỗi trạm; `Folder` phản ánh thư mục phường trong KML. CSV dùng UTF-8 BOM. GeoJSON chứa Point với tọa độ `[kinh độ, vĩ độ, độ cao]`. Chạy `scripts/extract_hcm_evc_5wards.py` để cập nhật KML/GeoJSON, rồi chạy `scripts/export_hcm_evc_csv.mjs` với đường dẫn GeoJSON bản trích để cập nhật CSV.

## SQL chèn vào bảng stations

`insert_hcm_dc80kw_37stations.sql` chứa một lệnh `INSERT INTO public.stations` với 37 bản ghi trong giao dịch `BEGIN`/`COMMIT`. Dùng UUID v5 cố định theo mã EVC; `code` và `name` là mã EVC, `address` giữ địa chỉ mô phỏng. `operator_name` mặc định là `VinFast` theo yêu cầu cho bộ dữ liệu mô phỏng. `location` dùng `ST_GeogFromText('SRID=4326;POINT(kinh_độ vĩ_độ)')` giữ nguyên tọa độ bản trích. `opening_hours` là chuỗi JSONB theo giờ hoạt động: 35 trạm `"24/7"`, một trạm `"07:00 - 22:00"`, một trạm `"05:30 - 20:00"`. `access_level` là `public`, `access_note` là `Dữ liệu mô phỏng`, `is_active` là true. Hai trường thời gian sử dụng mặc định của bảng. Bảng, enum `public.access_level` có giá trị `public`, và PostGIS phải tồn tại khi chạy file; chưa thực thi vào cơ sở dữ liệu. Chạy `scripts/export_hcm_evc_sql.py` để tạo lại.
