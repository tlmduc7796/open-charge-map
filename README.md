# EV Charging Site Planning

Nhánh `codex/station-recommendation` tập trung vào **đề xuất vị trí và quy mô trạm sạc mới**. Mục tiêu là xếp hạng các địa điểm ứng viên có giải thích, dựa trên nhu cầu hiện tại và tương lai, độ phủ, áp lực công suất, chi phí và các ràng buộc thực tế.

Đây là bản demo/đề án nghiên cứu, chưa phải hệ thống quyết định đầu tư và chưa có dữ liệu vận hành Việt Nam đủ để khẳng định lợi nhuận. Dữ liệu tổng hợp chỉ dùng để kiểm thử pipeline, thuật toán và trình bày kịch bản; mọi đầu ra phải hiển thị rõ nguồn và nhãn synthetic.

## Tài liệu thiết kế

- [Tổng quan và phạm vi bài toán](docs/station-planning/README.md)
- [Blueprint sản phẩm và thuật toán](docs/station-planning/PROBLEM_BLUEPRINT_VI.md)
- [Kế hoạch dữ liệu và schema](docs/station-planning/DATA_PLAN_VI.md)
- [Kế hoạch mô phỏng và demo](docs/station-planning/SIMULATION_AND_DEMO_PLAN_VI.md)
- [Lộ trình triển khai và tiêu chí hoàn thành](docs/station-planning/ROADMAP_VI.md)
- [Tóm tắt bài báo 442](docs/station-planning/PAPER_442_REVIEW_VI.md)
- [Bối cảnh thị trường và pain points](docs/station-planning/MARKET_AND_PAINPOINTS_VI.md)

## Định nghĩa đầu ra

Một danh sách địa điểm ứng viên, mỗi địa điểm có điểm xếp hạng và phần giải thích: nhu cầu dự báo, số người/luồng di chuyển được phục vụ thêm, độ phủ tăng thêm, số lượng và loại cổng gợi ý, nguy cơ thiếu công suất, chi phí ước lượng, độ tin cậy dữ liệu và độ nhạy theo các kịch bản.

Hệ thống nhận các bộ giả định/kết quả đầu vào về ngân sách, chính sách, chi phí và doanh thu từ doanh nghiệp/đơn vị phụ trách, rồi tính và so sánh chúng cùng các phương án vị trí/công suất. Khi thiếu đầu vào tài chính đáng tin cậy, phần economics được đánh dấu `unknown` hoặc `scenario`; khi có, hệ thống có thể tính các chỉ số theo công thức và phiên bản cấu hình công khai. Đội kỹ thuật xây giao diện tích hợp và tính toán có thể kiểm tra được, không tự đặt chính sách hay tiêu chuẩn đầu tư thay đơn vị ra quyết định.

Vì vậy, đầu ra demo có thể là **tiềm năng địa điểm và độ phủ dưới ngân sách/kịch bản**; khi đối tác cung cấp đủ dữ liệu, đầu ra mở rộng thành các chỉ số kinh tế theo từng phương án và kịch bản. Không gọi một kết quả là tối ưu lợi nhuận nếu mục tiêu, dữ liệu và công thức chưa được đơn vị phụ trách xác nhận.

## Ranh giới với bài toán cũ

Branch cũ xử lý dự đoán thời gian chờ tại các trạm hiện hữu. Các tín hiệu sạc, tình trạng cổng, occupancy và thời gian chờ có thể đóng góp vào bài toán mới như một phần đo **áp lực trên nguồn cung đã quan sát**. Chúng không đại diện đầy đủ cho nhu cầu ở nơi chưa có trạm và không tự chứng minh một địa điểm mới có lãi.

Code ứng dụng có sẵn từ nền repository `main`; các chức năng hành trình/đợi hiện hữu là nền tham khảo, không phải phạm vi sản phẩm site planning. Thiết kế mới nằm độc lập trong `docs/station-planning/`; các giai đoạn sau sẽ thêm data contract, mô phỏng và giao diện quy hoạch theo blueprint này.

## Cách đọc số liệu demo

- `observed`: dữ liệu quan sát có nguồn, thời gian và phạm vi rõ ràng.
- `synthetic`: dữ liệu giả lập theo giả định công khai, chỉ dùng để kiểm chứng luồng và minh họa.
- `scenario`: kết quả khi thay đổi các giả định tương lai; không phải dự báo chắc chắn.
- `unknown`: chưa có dữ liệu; không thay bằng số 0.

Mỗi bảng/biểu đồ và kết quả xếp hạng phải giữ nhãn này để người xem không hiểu mô phỏng thành nhu cầu thật.
