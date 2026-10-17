# Cập nhật bố cục và UX Planner

Ngày cập nhật: **15/10/2026**.

## 1. Thông tin được chuyển khỏi giao diện

- Cảnh báo giới hạn dữ liệu và các đoạn giải thích mô phỏng lặp lại.
- Danh sách đất, điện, giấy phép, lối vào và các điều kiện chưa được xác minh.
- Các tiêu chí chưa có điểm, tỷ trọng bằng chứng và thông tin nguồn chi tiết.
- Run ID, snapshot ID, phiên bản thuật toán/cấu hình và các tham số phục vụ tái lập.
- Danh sách lý do ứng viên chưa được xếp hạng hoặc bị loại.
- Mã kỹ thuật, loại nội bộ và ghi chú nguồn trong popup địa điểm.

Giao diện giữ nhãn **Planner · Demo**, các số liệu so sánh có giá trị, chú giải bản đồ và thông báo lỗi thao tác. Các lỗi như không tải được địa điểm hoặc không chạy được đánh giá vẫn cần hiển thị để người dùng biết cách tiếp tục.

## 2. Báo cáo thay thế

Thêm nút **Tải báo cáo** sau khi có kết quả đánh giá. File tải xuống là Markdown, gồm:

1. Trạng thái, mã lần đánh giá, snapshot và phiên bản thuật toán/cấu hình.
2. Cảnh báo của bộ dữ liệu và của lần đánh giá.
3. Thứ hạng, chỉ số, trạng thái và tỷ trọng bằng chứng của từng địa điểm.
4. Toàn bộ thành phần điểm, kể cả tiêu chí thiếu dữ liệu; lý do và trọng số tương ứng.
5. Điều kiện, nguồn dữ liệu, ghi chú và thời điểm nguồn.
6. Ứng viên chưa được xếp hạng hoặc bị loại, cùng lý do.
7. Request đầu vào của chính lần đánh giá đó để đối chiếu.

Báo cáo gắn với request đã tạo ra kết quả, không lấy lại các giá trị đang chỉnh trên form. Khi thay đổi đầu vào, kết quả cũ và khả năng tải báo cáo được xóa để tránh xuất nhầm lần đánh giá.

## 3. Bản đồ lớn hơn

- Desktop thông thường: cột thiết lập **320 px**, thay cho cột chia sẻ 440 px; điều chỉnh thành 290 hoặc 350 px ở các kích thước khác.
- Chiều cao vùng bản đồ desktop **66dvh**, tối thiểu 420 px; trước đây khoảng 43vh. Ở cửa sổ 1280 × 720, vùng bản đồ đo được khoảng 475 px chiều cao.
- Màn hình nhỏ: bản đồ **58dvh**, tối thiểu 360 px. Ở viewport 390 × 844, vùng bản đồ đo được khoảng 490 px chiều cao.
- Chú giải nhu cầu và bộ lọc vùng xa trạm được đặt dưới bản đồ, không phủ lên vùng quan sát.
- Nút **Phóng to bản đồ** ẩn bảng điều khiển và kết quả để tận dụng bề ngang. Nút **Thu gọn bản đồ** hoặc phím **Esc** đưa về bố cục thông thường.
- Map giữ nguyên instance, tâm nhìn và dữ liệu khi đổi chế độ. ResizeObserver cập nhật kích thước Goong và bản đồ OSM dự phòng.

## 4. Thao tác được rút gọn

- Thiết lập chính gồm mức nhu cầu, ngưỡng thời gian tiếp cận và giới hạn chi phí mỗi trạm.
- Cấu hình loại sạc, số cổng và công suất được thu gọn trong một mục có dòng tóm tắt.
- Danh sách địa điểm dùng tên dễ đọc, bỏ mã nội bộ lặp lại.
- Tên ứng viên demo dùng **Vị trí ứng viên A/B – Tên phường**. Chữ A/B gắn với thứ tự ID trong từng phường của toàn bộ snapshot, giữ nguyên khi lọc hoặc đổi thứ hạng. Danh sách, popup bản đồ, kết quả, bảng so sánh và báo cáo cùng dùng nhãn từ API catalog.
- Thêm tìm kiếm tên không dấu. Tìm kiếm chỉ lọc danh sách, không làm mất các địa điểm đang chọn.
- Khi có bộ lọc tìm kiếm, chọn/bỏ chọn áp dụng cho các kết quả đang hiện; số địa điểm được chọn luôn hiển thị trên nút đánh giá.
- Nút đánh giá nằm ở chân bảng thiết lập, dễ tiếp cận khi cuộn nội dung.
- Mobile có nút **Thiết lập** để mở/đóng form. Đánh giá xong tự thu gọn form và đưa người dùng về phần bản đồ/kết quả.
- Có liên kết **Xem kết quả** để chuyển nhanh từ bản đồ đến danh sách xếp hạng.
- Thẻ kết quả chỉ giữ tên, thứ hạng, điểm và bốn chỉ số: nhu cầu, độ phủ, công suất, chi phí.
- Điểm thành phần có dữ liệu được giữ trong mục thu gọn; phần so sánh không còn các bảng điều kiện/nguồn và dòng thiếu dữ liệu.
- Giá trị chưa xác định hiển thị dấu `—`; không đổi thành 0. Số hiển thị được làm tròn để dễ đọc, giá trị chi tiết vẫn có trong báo cáo.

## 5. Phạm vi và kiểm tra

Thay đổi ở frontend; không đổi công thức xếp hạng, dữ liệu mô phỏng, API hoặc cấu hình reset database. Bộ tính số cổng, tối ưu danh mục ngân sách và dashboard hiệu suất chưa được triển khai trong lần sửa bố cục này.

Kiểm tra đã thực hiện:

- TypeScript, ESLint và production build đạt.
- Toàn bộ **91 kiểm tra frontend** đạt.
- Trình duyệt thực: đánh giá, tìm kiếm không dấu, tải báo cáo, phóng to/thu gọn, Esc, bố cục desktop 1280 × 720 và màn hình nhỏ 390 × 844.
- Báo cáo Markdown đã tải được và kiểm tra có cảnh báo, phần thiếu bằng chứng, điều kiện, nguồn và request gốc.
- Không thấy tràn ngang ở các viewport kiểm tra.

Backend dùng catalog bộ nhớ và frontend chỉ được chạy tạm để kiểm tra giao diện; không khởi động PostgreSQL. Dịch vụ kiểm tra được dừng sau khi hoàn tất.

Các file chính: [PlannerView.tsx](../../frontend/src/planning/PlannerView.tsx), [PlannerMap.tsx](../../frontend/src/planning/PlannerMap.tsx), [planner.css](../../frontend/src/planning/planner.css), [plannerReport.ts](../../frontend/src/planning/plannerReport.ts).
