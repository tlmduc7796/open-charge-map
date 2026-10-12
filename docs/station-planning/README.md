# Thiết kế bài toán quy hoạch trạm sạc

## Mục đích

Nhánh này nghiên cứu câu hỏi đầu tư: **nên đặt trạm mới ở đâu, với quy mô nào, để phục vụ nhu cầu hiện tại và tương lai với ngân sách và năng lực lưới điện hữu hạn?** Người dùng chính của kết quả là nhà quy hoạch/đơn vị đầu tư; tài xế, đội xe và cộng đồng là nhóm được hưởng lợi từ độ phủ, tính sẵn sàng và thời gian tiếp cận.

**Study area đã chốt:** Thành phố Hồ Chí Minh theo ranh giới hành chính hiện hành sau hợp nhất năm 2025, gồm địa bàn TP.HCM cũ, Bình Dương cũ và Bà Rịa–Vũng Tàu cũ. Lớp địa giới, mã vùng và ngày hiệu lực phải được version hóa. Nếu demo chỉ dựng/đánh giá một phần địa bàn thì phải hiển thị rõ pilot extent; không gọi đó là coverage toàn TP.HCM.

Tên gọi giai đoạn demo là **xếp hạng phương án địa điểm theo các kịch bản được cấu hình**. Tài chính/chính sách là một giao diện đầu vào hạng nhất: đơn vị đầu tư hoặc cơ quan phụ trách đưa vào các ràng buộc, mục tiêu và giả định; hệ thống ghép chúng với nhu cầu, bản đồ, công suất và các phương án site để tính lại kết quả đồng bộ. Đội kỹ thuật triển khai schema, bộ tính, kiểm tra và so sánh kịch bản; đơn vị chuyên môn sở hữu giá trị/ý nghĩa của chính sách và ngưỡng ra quyết định.

## Phạm vi

**Trong phạm vi:**

- Tạo/nhập các vùng nhu cầu và địa điểm ứng viên.
- Ước lượng nhu cầu sạc theo không gian, thời gian và kịch bản.
- Đánh giá khoảng trống độ phủ, khả năng tiếp cận trạm hiện có và áp lực công suất.
- Đề xuất quy mô sơ bộ: AC/DC, số cổng hoặc dải công suất; nêu rõ đây là gợi ý dựa trên giả định.
- Xếp hạng có giải thích, báo cáo dữ liệu thiếu, độ tin cậy và độ nhạy theo kịch bản.
- Nhận cấu hình chính sách/tài chính có version; tính lại phương án vị trí/công suất và so sánh các kết quả trong cùng một lần chạy.

**Ngoài phạm vi MVP:**

- Dự đoán xe cụ thể sẽ chọn một trạm cụ thể.
- Lập lịch ghé nhiều trạm cho một hành trình cá nhân.
- Điều khiển/vận hành trạm theo thời gian thực.
- Tự đặt chính sách, hurdle rate, cách ghi nhận doanh thu hoặc chuẩn hoàn vốn thay doanh nghiệp/cơ quan có thẩm quyền.
- Dự báo tác động xe tự lái ở Việt Nam như một nguồn cầu chính.

## Ba lớp quyết định liên quan

| Lớp | Câu hỏi | Vai trò ở nhánh này |
|---|---|---|
| Quy hoạch vị trí | Đặt trạm mới ở đâu, quy mô nào? | Sản phẩm chính |
| Áp lực/vận hành hiện hữu | Trạm đang bận, chờ lâu hay thiếu cổng khi nào? | Tín hiệu đầu vào có thể import từ branch `fix/ui`; không phải toàn bộ nhu cầu |
| Hành trình tài xế | Trên chuyến đi này nên sạc ở đâu? | Bài toán riêng, có thể dùng hạ tầng được quy hoạch |

## Tích hợp chính sách và tài chính

Không hard-code một bộ giá/chi phí/ưu đãi thành “chân lý”. Mỗi `scenario` nhận các nhóm cấu hình có schema và phiên bản:

- `policy`: mục tiêu độ phủ, nhóm/khu vực ưu tiên, điều kiện bắt buộc, trợ cấp/ưu đãi, quy tắc cấp phép nếu được cung cấp.
- `finance`: ngân sách, CAPEX/OPEX, giá đất/thuê, đấu nối, tariff/demand charge, pricing/revenue assumptions, discount rate hoặc tiêu chí payback nếu đơn vị cung cấp.
- `technical`: loại cổng, số cổng, công suất lưới, service target, vùng tiếp cận và cách tính nhu cầu/capacity.

Hard constraints (ví dụ: candidate không đủ quyền tiếp cận) được tách khỏi soft objectives (ví dụ: ưu tiên coverage). Hệ thống validate đơn vị/phạm vi, ghi provenance/version, chạy cùng thuật toán trên cùng bộ dữ liệu, rồi trả metric và lý do thay đổi khi cấu hình đổi. Thiếu trường bắt buộc thì báo thiếu/không khả thi; không âm thầm gán 0. Khi chưa có economics, vẫn chạy technical/coverage ranking và hiển thị economics là unavailable.

## Nguyên tắc dữ liệu và diễn giải

Mọi trường phải có provenance, thời gian, phạm vi địa lý và trạng thái chất lượng. Phân biệt `observed`, `synthetic`, `scenario`, `proxy` và `unknown`. Thiếu dữ liệu không có nghĩa là nhu cầu bằng 0. Synthetic dùng để kiểm tra tính đúng đắn của hệ thống và minh họa giả định, không phải bằng chứng về nhu cầu Việt Nam.

Không dùng lượt sạc hiện tại làm đại diện duy nhất cho nhu cầu: vị trí trạm hiện hữu quyết định nơi có thể ghi nhận giao dịch. Cần bổ sung luồng giao thông/OD, khả năng sạc tại nhà, lượt tìm kiếm/yêu cầu chưa được đáp ứng nếu có, và kiểm tra độ nhạy cho phần nhu cầu tiềm ẩn.

## Tài liệu

- [Kế hoạch triển khai tổng thể](IMPLEMENTATION_PLAN_VI.md)
- [Hợp đồng API/domain và brief triển khai theo module](modules/README.md)
- [Blueprint sản phẩm và mô hình quyết định](PROBLEM_BLUEPRINT_VI.md)
- [Kế hoạch dữ liệu và schema đầu vào](DATA_PLAN_VI.md)
- [Kịch bản synthetic, mô phỏng và demo](SIMULATION_AND_DEMO_PLAN_VI.md)
- [Lộ trình theo gate](ROADMAP_VI.md)
- [Đọc bài báo 442](PAPER_442_REVIEW_VI.md)
- [Định hướng ML cho bài toán đề xuất trạm](ML_DEMAND_PIPELINE_VI.md)
- [Bằng chứng thị trường và kiểm chứng pain point](MARKET_AND_PAINPOINTS_VI.md)
- [Ma trận ràng buộc tham khảo cho TP.HCM](CONSTRAINT_MATRIX_HCMC_VI.md)
- [JSON Schema của scenario](schemas/planning-scenario.schema.json)
- [Scenario JSON mẫu](examples/hcmc-scenario-base.json)

## Cơ sở nghiên cứu và bối cảnh

Bài báo 442 trình bày dự báo nhu cầu từ dữ liệu sạc/POI/giao thông và chọn vị trí dưới ràng buộc ngân sách, độ phủ và SLA chờ. Công cụ NREL EVI-X cũng tách bài toán quy hoạch theo vùng, hành lang, đội xe và hiệu quả kinh tế. Google Maps/Tesla đã giải bài toán khác ở phía tài xế: định tuyến đến trạm phù hợp và chọn điểm dừng. Các ví dụ này củng cố ranh giới giữa **quy hoạch hạ tầng** và **gợi ý điểm sạc cho chuyến đi**.

- [NREL EVI-X](https://www.nrel.gov/transportation/evi-x.html)
- [Google Maps: tìm trạm sạc và thêm điểm dừng](https://support.google.com/maps/answer/9773205?hl=en)
- [Tesla Supercharging và Trip Planner](https://www.tesla.com/support/charging/supercharging)
