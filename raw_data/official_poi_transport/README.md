# POI và giao thông từ bản đồ chính thức TP.HCM

Nguồn: [Bản đồ số Thành phố Hồ Chí Minh](https://bando.tphcm.gov.vn/). Thu thập ngày **12/10/2026** qua danh mục lớp và API truy vấn công khai do chính trang sử dụng, không dùng tài khoản riêng hoặc repo tác giả paper.

## Hai bộ dữ liệu

| Bộ | File xử lý | File xem bằng GIS | Số bản ghi xuất |
|---|---|---|---:|
| POI | `hcm_poi_official.geojson` | `hcm_poi_official.kml` | 24698 |
| Giao thông | `hcm_transport_official.geojson` | `hcm_transport_official.kml` | 11100 |

GeoJSON giữ tọa độ nguồn khi có thể, KML làm tròn tới 6 chữ số thập phân để hiển thị. Có thể mở bằng QGIS/Google Earth. **KML POI khoảng 21,17 MB và KML giao thông khoảng 10,12 MB**, vượt giới hạn 5 MB và số đối tượng cho một lần nhập Google My Maps; bộ đầy đủ này chưa được chia thành các lớp nhỏ cho My Maps.

Phạm vi lọc là polygon TP.HCM trong `hcm_admin_2025.geojson`, gồm địa bàn sau sắp xếp và Côn Đảo. Gán đơn vị theo `hcm_planning_units_2025.geojson`. Lớp nào chưa được cơ quan nguồn cập nhật đủ ở Bình Dương/Bà Rịa–Vũng Tàu thì kết quả vẫn phản ánh phạm vi dữ liệu hiện công khai, không tự bổ sung điểm giả.

### POI

Gồm **38 lớp nguồn**: trường học theo cấp và trường học tích hợp; bệnh viện/phòng khám/trung tâm y tế/cơ sở trợ giúp xã hội; chợ, siêu thị, trung tâm thương mại, cửa hàng tiện lợi, ngân hàng; công viên, hội nghị, khách sạn, chùa, nhà thờ, bảo tàng/di tích, khu du lịch, nhà hàng; doanh nghiệp; công sở/công an và các điểm tiếp nhận dịch vụ hành chính; nhà vệ sinh.

Nhà vệ sinh nằm trong nhóm giao thông trên trang nhưng được đưa sang POI tiện ích trong bản xuất. Các bãi xe, bến/trạm và trạm xăng giữ trong bộ giao thông; khi xây feature nhóm transportation của paper 2, có thể dùng những đối tượng điểm của bộ giao thông mà không cần sao chép thành POI thứ hai.

POI có dữ liệu tại đủ **168 đơn vị cấp cơ sở** theo phép gán tọa độ. Đây là sự hiện diện của ít nhất một bản ghi trong mỗi vùng, không phải xác nhận đã thu thập đầy đủ mọi địa điểm thực tế.

### Giao thông

Gồm **11 lớp nguồn**: xe đạp công cộng, bến buýt đường sông, bến xe/trạm dừng, bãi xe, tuyến đường cấm dừng/cấm đậu, cầu, đường, đèn tín hiệu, trạm xăng, trạm xe buýt và nhà ga MRT.

Hình học xuất: **9210 Point, 1259 LineString, 631 MultiLineString**. Dữ liệu giao thông giao với **119 đơn vị cấp cơ sở**; không suy 49 đơn vị còn lại không có hạ tầng giao thông. Bộ này không được xác nhận là toàn bộ mạng đường có thể định tuyến hoặc toàn bộ trạm dừng thực tế.

**Chưa có lưu lượng xe theo giờ, tốc độ quan sát thời gian thực hoặc mật độ giao thông tại nút giao.** Các trường tốc độ thiết kế/khai thác và quy định vận hành của đường/cầu nếu có được giữ dưới `source_transport_attributes`; không gọi chúng là số đo traffic density của paper 2. Các trường `traffic_volume_vehicles_per_hour` và `traffic_observation_time` để null.

## Các trường chung

| Trường | Ý nghĩa |
|---|---|
| `feature_id` / `Feature.id` | ID duy nhất, kết hợp lớp và UUID bản ghi nguồn |
| `name` | Tên địa điểm/đối tượng từ nguồn; nếu thiếu, tên lớp + ID làm nhãn hiển thị |
| `category` | Tên lớp cụ thể bằng tiếng Việt |
| `category_group` | Nhóm tổng quát cho phân tích; không phải phân loại 11 nhóm đã tái lập MDR |
| `address` | Địa chỉ nguồn khi có; không dùng địa chỉ để thay việc lọc tọa độ |
| `unit_id` | ID địa bàn nếu hình học khớp đúng một vùng; null khi đi qua nhiều vùng |
| `unit_ids`, `unit_names` | Các địa bàn giao với hình học; một tuyến đường có thể có nhiều đơn vị |
| `source_layer`, `source_record_id` | Truy vết tới lớp và bản ghi nguồn |
| `source_modified_at` | Thời điểm cập nhật bản ghi nếu nguồn có, không phải thời điểm đo lưu lượng xe |
| `source_geometry_field` | Trường hình học/tọa độ đã dùng |
| `geometry_clipped_to_city` | Hình học có được cắt phần ngoài phạm vi thành phố hay không |
| `geometry_repaired` | Có áp dụng sửa hình học không hợp lệ để có thể xử lý hay không |
| `possible_duplicate_group` | Chỉ có ở POI có tên chuẩn hóa và ô tọa độ giống nhau; cờ kiểm tra, không xác nhận cùng một thực thể |

`geometry` chứa tọa độ kinh/vĩ độ theo JSON của trang, phù hợp bản đồ web/WGS84; không tự chuyển từ VN-2000 hoặc khẳng định EPSG gốc khi chưa có khai báo nguồn. `unit_id` theo bộ đơn vị 2025 đã chuẩn bị, không tự cập nhật tên/loại đơn vị bằng các bài tin mới.

Không xuất thông tin người tạo/sửa bản ghi, số điện thoại, fax, email hoặc tên người phụ trách của cơ sở. Giữ các thuộc tính địa điểm và hạ tầng cần cho mục tiêu dữ liệu.

## Độ đầy đủ và kiểm tra

- Đã đọc đủ **49 lớp được chọn**, tổng **36105 bản ghi**, kiểm tra tổng API và ID khi phân trang/tải toàn bộ.
- **72 bản ghi ngoài polygon thành phố** được ghi trong `excluded_outside_city.json`.
- **235 bản ghi thiếu hình học hợp lệ** được ghi trong `missing_geometry.json`: 173 đường, 60 cầu và 2 trung tâm giáo dục thường xuyên. Các bản ghi này không được gán tọa độ giả.
- 18 đối tượng giao thông được cắt theo ranh giới thành phố; 9 hình học nguồn được sửa bằng `make_valid`. Hình học sửa có thể đổi loại nếu hình học gốc suy biến; trường `geometry_repaired` đánh dấu từng bản ghi. GeoJSON lưu kết quả xử lý; snapshot thuộc tính/hình học tải về được giữ trong cache để kiểm tra.
- 256 nhóm POI được gắn cờ có thể trùng theo tên chuẩn hóa + ô tọa độ làm tròn 4 số. Không tự gộp vì hai cơ sở khác nhau có thể cùng tòa nhà; trường học tích hợp có thể lặp với các lớp theo cấp. Trước khi đếm POI quanh trạm, chọn một hệ lớp giáo dục hoặc đối chiếu/gộp thực thể; không cộng mọi lớp như các địa điểm khác nhau.
- Tất cả đối tượng xuất đều được gán ít nhất một xã/phường/đặc khu; 701 đối tượng giao thông đi qua nhiều vùng. Không ép đường qua nhiều vùng vào một `unit_id` tùy ý.
- Không gọi tổng bản ghi POI là tổng số cơ sở duy nhất ngoài thực tế. Không coi bản ghi có tên trong danh mục là địa điểm đã được xác minh còn hoạt động tại ngày tải.

Các lớp ranh giới hành chính và báo cáo ngập không nằm trong hai bộ này. Lớp ranh giới đã có bộ riêng; báo cáo ngập không tự được coi là lưu lượng giao thông. `source_layers.json` và `collection_manifest.json` liệt kê chính xác các lớp được chọn, số bản ghi từng lớp, kết quả lọc, thời điểm tải và hash file.

## Dùng cho bài toán quy hoạch

1. Dùng POI ngữ cảnh để tính feature số địa điểm quanh ứng viên/trạm theo bán kính; phải xử lý trùng lớp và ánh xạ category sang taxonomy đã chọn.
2. Dùng bãi xe/bến/trạm/đường để tham khảo ứng viên, khả năng tiếp cận và điều kiện giao thông. Một POI hoặc bãi xe trên bản đồ chưa xác nhận quyền lắp trạm, capacity nguồn điện hay chi phí đất.
3. Có thể dùng vị trí đèn tín hiệu làm tập điểm tham khảo khi tìm nút gần nhất; một nút có thể có nhiều đèn, nên phải nhóm theo nút trước khi dùng. Vẫn thiếu số đo lưu lượng tại các nút để tái lập feature giao thông MDR.
4. Giữ nhu cầu sạc và usage trạm thành bảng riêng; không suy nhu cầu trực tiếp bằng cách cộng số POI hoặc số trạm xe buýt.

## Tái lập

`discover_official_map_layers.py` đọc danh mục lớp và mẫu schema; `collect_official_poi_transport.py` tải thuộc tính địa điểm/hạ tầng cần thiết, lọc hình học và xuất hai bộ. Chạy từ gốc project bằng Python + curl.exe; cần Shapely (lần này dùng 2.2.0 trong thư mục dependency tạm). Cache tránh tải lại lớp đã hoàn thành; muốn lấy snapshot mới cần dùng cache mới thay vì coi dữ liệu cũ là lần tải mới.

Ngày kiểm tra file, phiên bản và thông số tải nằm trong manifest; bộ này chưa được dùng để huấn luyện hoặc chạy solver.
