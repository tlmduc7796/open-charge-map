# KML nhẹ để xem trên Google My Maps

Sử dụng `hcm_admin_2025_mymaps.kml`: **3.868.303 byte ≈ 3,87 MB**, nhỏ hơn 5.000.000 byte. Bản gốc `hcm_admin_2025.kml` được giữ nguyên, dung lượng 5.688.159 byte.

## Các thay đổi

- Làm tròn tọa độ kinh/vĩ độ tới 6 chữ số thập phân; độ dịch chuyển lớn nhất đo được tại các đỉnh là **0,07781 m**, khoảng 7,8 cm.
- Giữ nguyên toàn bộ **159.506 đỉnh**, 232 vòng và 169 đơn vị hành chính gốc, gồm thành phố và cấp phường/xã/đặc khu; không loại đảo hoặc polygon nhỏ.
- Tách các phần polygon rời của MultiGeometry thành **232 Placemark**, đặt trực tiếp trong Document. Một đơn vị có nhiều phần sẽ xuất hiện nhiều đối tượng cùng tên và cùng `AdminID`; dùng `polygon_part` và `polygon_parts` để phân biệt.
- Giữ tên, mã, nguồn và các thuộc tính gốc; giữ kiểu hiển thị ranh giới thành phố và các đơn vị con.

[Hướng dẫn nhập dữ liệu của Google My Maps](https://support.google.com/mymaps/answer/3024836?hl=en) quy định KML/KMZ sau giải nén tối đa 5 MB và lưu ý MultiGeometry/Folder có thể không được nhập đầy đủ. Bản xuất này đáp ứng giới hạn byte và chuyển thành từng polygon riêng. Chưa tải thử lên tài khoản My Maps.

## Cách xem

Trong My Maps, mở hoặc tạo bản đồ → thêm lớp → Import/Nhập → chọn `hcm_admin_2025_mymaps.kml`.

Đây là bản phục vụ hiển thị. Khi gán POI/RP vào địa bàn hoặc xử lý quy hoạch, tiếp tục dùng hình học đầy đủ trong bộ GeoJSON gốc.

Kiểm tra đã thực hiện: đọc lại XML/KML, kiểm tra số polygon/vòng/đỉnh, vòng khép kín và tối thiểu ba đỉnh khác nhau, đối chiếu tên/thuộc tính và sai lệch tọa độ với bản gốc. Chi tiết dung lượng và hash lưu trong `mymaps_export_report.json`; script tạo file là `make_mymaps_kml.py` trong thư mục scripts.
