# Open Charge Map

Nền tảng bản đồ số hỗ trợ giao thông xanh, được xây dựng trên lớp bản đồ và dịch vụ bản đồ của [Goong](https://goong.io/). Dự án tập trung vào việc giúp người dùng, đơn vị vận hành và nhà quy hoạch ra quyết định tốt hơn về phương tiện điện, hạ tầng sạc và các hình thức di chuyển phát thải thấp.

## Mục tiêu

Open Charge Map hướng tới một lớp ứng dụng web có thể:

- Hiển thị vị trí và trạng thái hoạt động của các trạm sạc.
- Ước tính thời gian chờ, công suất khả dụng và nhu cầu sạc theo khu vực.
- Đề xuất trạm sạc phù hợp dựa trên hành trình, quãng đường, loại đầu sạc và mức pin.
- Phân tích các khu vực còn thiếu hạ tầng sạc để hỗ trợ quy hoạch mở rộng.
- Dự báo mức tiêu thụ pin hoặc năng lượng theo tuyến đường, tình trạng giao thông và địa hình.
- Tính toán, so sánh lượng phát thải CO₂ giữa các phương án di chuyển.
- Gợi ý lựa chọn phát thải thấp như xe điện, xe buýt, đi bộ, xe đạp hoặc kết hợp nhiều phương thức.

## Các lớp dữ liệu chính

Ứng dụng được thiết kế theo mô hình các lớp bản đồ có thể bật/tắt độc lập:

| Lớp | Nội dung |
| --- | --- |
| Bản đồ nền | Bản đồ Goong, địa điểm, địa chỉ, tìm kiếm và chỉ đường |
| Trạm sạc | Vị trí, loại đầu nối, công suất, giá, giờ hoạt động và trạng thái |
| Tình trạng sạc | Số cổng trống, cổng đang sử dụng, thời gian chờ dự kiến và hàng đợi |
| Nhu cầu | Mật độ yêu cầu sạc, thời điểm cao điểm và dự báo quá tải |
| Năng lượng | Mức tiêu thụ dự kiến theo tuyến, độ dốc, giao thông và điều kiện vận hành |
| Phát thải | CO₂ ước tính theo phương tiện, nhiên liệu và quãng đường |
| Quy hoạch | Khu vực ưu tiên phát triển trạm sạc dựa trên nhu cầu và độ phủ hiện tại |
| Di chuyển xanh | Tuyến đi bộ, xe đạp, giao thông công cộng và phương án kết hợp |

## Luồng sử dụng tiêu biểu

1. Người dùng nhập điểm đi, điểm đến và thông tin phương tiện.
2. Hệ thống tính các tuyến khả thi dựa trên bản đồ, giao thông và địa hình.
3. Bộ phân tích ước tính mức tiêu thụ pin, thời gian di chuyển và nguy cơ thiếu năng lượng.
4. Hệ thống đề xuất các trạm sạc phù hợp trên hành trình, có tính đến thời gian chờ.
5. Người dùng so sánh chi phí, thời gian, năng lượng và phát thải CO₂ trước khi chọn tuyến.

## Kiến trúc đề xuất

```text
Người dùng / Dashboard
				|
Web map UI - Goong Maps SDK/API
				|
API ứng dụng
	|        |         |
Trạm sạc  Tuyến đi  Phân tích năng lượng & CO2
	|
CSDL không gian + dữ liệu thời gian thực + dữ liệu giao thông
```

Các thành phần có thể được triển khai độc lập:

- **Map layer:** hiển thị bản đồ Goong, marker, vùng nhiệt và tuyến đường.
- **Charging service:** quản lý trạm sạc, đầu nối, công suất và trạng thái cổng.
- **Routing service:** tìm tuyến và chèn các điểm sạc vào hành trình.
- **Energy model:** ước tính tiêu thụ theo loại xe, tốc độ, độ dốc, tải và điều hòa.
- **Emission model:** quy đổi năng lượng hoặc nhiên liệu thành CO₂ tương đương để so sánh.
- **Planning analytics:** xác định khu vực có nhu cầu cao nhưng độ phủ trạm thấp.

## Dữ liệu và tích hợp

Ứng dụng cần kết nối các nhóm dữ liệu sau:

- **Goong:** bản đồ nền, geocoding, tìm kiếm địa điểm, ma trận khoảng cách và chỉ đường theo gói dịch vụ phù hợp.
- **Trạm sạc:** dữ liệu vị trí, loại cổng, công suất, giá và trạng thái theo thời gian thực.
- **Giao thông:** tốc độ hoặc thời gian di chuyển theo thời điểm.
- **Địa hình:** độ cao, độ dốc và hướng di chuyển trên tuyến.
- **Phương tiện:** dung lượng pin, hiệu suất tiêu thụ và giới hạn sạc.
- **Phát thải:** hệ số phát thải theo loại nhiên liệu, nguồn điện và phương thức di chuyển.

Thông tin xác thực và khóa API không được commit vào repository. Khi triển khai, hãy cấu hình chúng bằng biến môi trường, ví dụ:

```env
GOONG_API_KEY=your_goong_api_key
GOONG_MAP_STYLE=your_map_style
CHARGING_DATA_URL=https://example.com/charging-data
```

## Trạng thái dự án

Đây là dự án đang phát triển. Các giai đoạn dự kiến:

- [ ] Xây dựng giao diện bản đồ nền với Goong.
- [ ] Chuẩn hóa mô hình dữ liệu trạm sạc và trạng thái cổng.
- [ ] Hiển thị bộ lọc, chi tiết trạm và thời gian chờ dự kiến.
- [ ] Tích hợp tìm tuyến và đề xuất điểm sạc.
- [ ] Xây dựng mô hình tiêu thụ pin theo tuyến đường.
- [ ] Bổ sung tính toán CO₂ và so sánh phương án di chuyển.
- [ ] Xây dựng lớp phân tích nhu cầu và hỗ trợ quy hoạch.
- [ ] Bổ sung kiểm thử, giám sát dữ liệu và triển khai production.

## Phát triển cục bộ

Repository hiện được tổ chức để có thể bổ sung frontend, backend và các mô hình phân tích độc lập. Khi các thành phần chạy được được thêm vào, cập nhật phần này với lệnh cài đặt, biến môi trường bắt buộc và lệnh khởi động tương ứng.

Quy trình cơ bản:

```bash
git clone https://github.com/<owner>/open-charge-map.git
cd open-charge-map
```

## Nguyên tắc thiết kế

- Ưu tiên dữ liệu gần thời gian thực và hiển thị rõ độ tin cậy của dự báo.
- Tách dữ liệu quan sát được khỏi dữ liệu ước tính hoặc mô phỏng.
- Cho phép giải thích vì sao một trạm sạc hoặc tuyến đường được đề xuất.
- Bảo vệ khóa API và dữ liệu vị trí nhạy cảm.
- Để người dùng so sánh nhiều tiêu chí thay vì tối ưu duy nhất theo thời gian.

## Đóng góp

Issue và pull request nên mô tả rõ phạm vi thay đổi, nguồn dữ liệu sử dụng, giả định của mô hình và cách kiểm thử kết quả. Với các thay đổi liên quan đến bản đồ hoặc dự báo, nên kèm một ví dụ dữ liệu hoặc ảnh chụp màn hình minh họa.

## Giấy phép

Giấy phép của dự án sẽ được bổ sung khi phạm vi mã nguồn và các nguồn dữ liệu bên thứ ba được xác định đầy đủ.
