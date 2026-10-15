# Ranh giới hành chính TP.HCM từ bản đồ chính thức

Nguồn: [Bản đồ số Thành phố Hồ Chí Minh](https://bando.tphcm.gov.vn/). Tải ngày **11/10/2026** bằng luồng truy cập công khai do chính trang cấp; không sử dụng tài khoản riêng.

Đã bổ sung bộ dữ liệu gọn kèm dân số cho xử lý quy hoạch: `hcm_planning_units_2025.geojson`, `hcm_planning_units_2025.csv`, `hcm_planning_units_2025.kml`. Xem `README_PLANNING.md` về schema và giới hạn thời điểm dân số. Các file ranh giới gốc bên dưới giữ để đối chiếu.

Bản dành cho xem trên Google My Maps: `hcm_admin_2025_mymaps.kml`, khoảng 3,87 MB. Xem `README_MYMAPS.md` về làm tròn tọa độ và cách tách các polygon rời; bản gốc vẫn được giữ nguyên.

## Dữ liệu đã xuất

- `hcm_admin_2025.kml`: 169 đối tượng, chia hai nhóm: 1 ranh giới thành phố và 168 ranh giới cấp phường/xã/đặc khu.
- `hcm_admin_2025.geojson`: cùng các hình học, thuận tiện tích hợp bản đồ và kiểm tra điểm nằm trong vùng.
- `administrative_2025_source.json`: các bản ghi nguồn được tải, giữ thuộc tính và hình học `COLLECTION` để đối chiếu.
- `source_manifest.json`: địa chỉ nguồn, cấu hình lớp, thời điểm tải UTC, số đối tượng, bbox, hash và thông tin chuyển đổi.
- `export_official_admin_boundaries.py`: script tải lại và xuất dữ liệu; nằm trong thư mục scripts của project. Chạy từ thư mục gốc project; mặc định xuất vào thư mục admin_boundaries bên trong input_data.

Phạm vi cấp cơ sở: **113 phường, 54 xã, 1 đặc khu Côn Đảo**. Đây là lớp hiện được cổng dùng, bao gồm cả khu vực Bình Dương và Bà Rịa–Vũng Tàu trong phạm vi TP.HCM sau sắp xếp. Không phải 22 địa bàn quận/huyện/thành phố thuộc dữ liệu paper 1.

## Lớp và cách truy xuất

Trang lấy cấu hình từ `/api/administrative/config`; tại thời điểm tải, cấu hình chỉ tới lớp **`ADMINISTRATIVE_2025`** trong vùng dữ liệu hành chính **2025**. API truy vấn: `/service/vdms/api/v1/query`.

Chỉ tải bản ghi thành phố có `TYPE=P`, `AdminID=79`, `AdministrativeID=33`, và các đơn vị con có `TYPE=W`, `ParentID=33`. `AdminID` và `AdministrativeID` là hai trường khác nhau; không tự coi ID nội bộ là mã hành chính chuẩn. Ví dụ Phường Bến Thành có `AdminID=26743`, khớp tham số `Ward` hiển thị trên giao diện.

Sử dụng hình học đầy đủ trong **`COLLECTION`**, không dùng trường `ShapeE3` được đơn giản hóa. Giữ các phần của MultiPolygon, đảo rời và vòng trong. KML lưu tọa độ theo thứ tự kinh độ,vĩ độ,độ cao; độ cao đặt bằng 0 và dùng clampToGround.

Các giá trị tọa độ là kinh/vĩ độ thập phân phù hợp bản đồ web/WGS84. Phản hồi nguồn không kèm khai báo CRS/EPSG rõ ràng; vì vậy không khẳng định hệ quy chiếu gốc chỉ từ API. Không thực hiện chuyển đổi từ VN-2000.

KML chuẩn hóa hướng vòng: vòng ngoài ngược chiều kim đồng hồ, vòng trong theo chiều kim đồng hồ. Chỉ đảo thứ tự 186 vòng; không thay tọa độ, không cắt/gộp hay giảm số đỉnh. GeoJSON và dữ liệu nguồn giữ thứ tự vòng của nguồn.

## Kiểm tra đã thực hiện

- API trả tổng 168 đơn vị con; đã tải đủ theo phân trang và kiểm tra ID không trùng.
- 169 Placemark; 232 vòng; 159.506 đỉnh tính cả đỉnh đóng vòng và ranh giới cấp thành phố.
- Kiểm tra vòng đóng, số đỉnh tối thiểu, tọa độ hữu hạn và phạm vi kinh/vĩ độ.
- Đọc lại KML, đối chiếu tên, thuộc tính ID, các phần polygon, vòng trong và toàn bộ tọa độ với GeoJSON; chỉ cho phép đảo hướng vòng.
- Chưa kiểm tra topology đầy đủ như tự giao cắt, chồng lấn hoặc khe hở giữa các đơn vị; chưa xác nhận bằng hồ sơ địa giới pháp lý.

Phiên bản **2025** là tên lớp nguồn. Trang/API được kiểm tra chưa cung cấp ngày hiệu lực pháp lý và độ chính xác đo đạc của lớp; ngày tải 11/10/2026 không đồng nghĩa ranh giới có hiệu lực từ ngày đó.

## Dùng với dữ liệu paper 1

Dùng lat/lon của `inputPOI.csv` và `PEOPLE.csv` để gán lại đơn vị bằng point-in-polygon trên lớp mới. Giữ `Unit` cũ làm trường truy vết, tạo ID/tên đơn vị mới riêng. Không nối tên địa bàn cũ sang phường/xã mới bằng tên gần giống. Điểm nằm trên ranh giới cần quy tắc gán rõ ràng.

KML có thể nhập vào QGIS hoặc Google Earth để xem trước. Nếu làm việc với phạm vi TP.HCM cũ của paper 1, lọc theo vùng nghiên cứu đã chọn; không giả định toàn bộ lớp này có dữ liệu demand tương ứng.
