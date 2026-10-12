# Bối cảnh thị trường và kiểm chứng pain point

Tài liệu này giúp đội thi lập luận vì sao site planning đáng nghiên cứu và đâu là bằng chứng còn thiếu. Kế hoạch/công bố của doanh nghiệp cho thấy hoạt động thị trường; nó không xác nhận mọi trạm trong kế hoạch sẽ có lãi hoặc một địa điểm cụ thể đang thiếu nguồn cung.

## Nhà đầu tư và nhà vận hành

### Pain point có cơ sở

- Chọn địa điểm cần cân bằng lưu lượng, utilization dự kiến, độ phủ, mặt bằng, chi phí đấu nối/nâng cấp lưới và khả năng vận hành.
- Hạ tầng lưới, giá điện/điện demand charge, quyền sử dụng site và thời gian triển khai có thể làm thay đổi economics; cần được xem là ràng buộc trong ranking.
- Lựa chọn giữa xây mới và mở rộng trạm hiện tại là quyết định thực tế, không thể chỉ xếp hạng “điểm đông”.

EVgo trong báo cáo 10-K năm 2025 mô tả site selection dựa trên các yếu tố như traffic, utilization và financial return; đồng thời nêu site control, grid upgrades, interconnection costs/delays và utility tariffs trong các thách thức vận hành. Đây là bằng chứng từ operator Hoa Kỳ, hữu ích làm taxonomy painpoint; cần phỏng vấn operator Việt Nam để xác nhận mức độ và cấu trúc chi phí địa phương.

Bản 10-K cũng nói công cụ network planning của họ kết hợp EV penetration, charging availability, traffic, fleet partners, site hosts, OEM input, incentive programs và government policies; họ cân bằng financial return, incentive capture, usage và network coverage. Đây là căn cứ cho nhóm yếu tố trong ma trận của team, không phải bằng chứng cho weights nội bộ của EVgo.

Nguồn: [EVgo 2025 Form 10-K, SEC](https://www.sec.gov/Archives/edgar/data/1821159/000110465926024827/evgo-20251231x10k.htm).

NREL công bố hai lớp công cụ bổ sung cho cách phân ranh của team: EVI-LOCATE hỗ trợ thiết kế site, charger layout và ước lượng chi phí với charger needs/utility assets; EVI-FAST tính financial scenario như payback/NPV/break-even từ power, usage, cost, electricity price và demand charges. Điều này là precedent cho kiến trúc technical planner + optional finance adapter; không có nghĩa team phải sao chép công thức của họ.

Nguồn: [NREL EVI-X / EVI-FAST](https://www.nrel.gov/transportation/evi-x), [NREL EVI-LOCATE](https://evi-locate.nrel.gov/).

### Dấu hiệu ở Việt Nam

V-Green công bố kế hoạch đầu tư 10.000 tỷ đồng cho 99 siêu trạm trên quốc lộ/tỉnh lộ, dự kiến trong năm 2026. Điều này cho thấy hành lang đường dài là một chiến lược hạ tầng được doanh nghiệp Việt Nam theo đuổi. Cần gọi đúng là **kế hoạch công bố**, không phải 99 trạm đã vận hành hay bằng chứng lợi nhuận.

Nguồn: [V-Green công bố kế hoạch 99 siêu trạm](https://www.vingroup.net/tin-tuc-su-kien/bai-viet/4850/v-green-xay-dung-99-sieu-tram-tren-toan-quoc).

## Tài xế, khách đường dài và đội xe

- Tài xế cần biết trạm tương thích, hoạt động và có thể tiếp cận trên đường đi; Google Maps và Tesla đã tích hợp việc tìm charger/điểm dừng vào định tuyến xe điện. Đây là pain point trải nghiệm hành trình; dữ liệu về các tuyến đó có thể làm input cho quy hoạch hành lang.
- Đội xe dịch vụ/tour có lịch, depot và hành trình lặp lại nên nhu cầu có thể dự báo theo ca/điểm tập kết. VinFast công bố thỏa thuận để Xe Nhanh Việt Nam mua 3.000 xe điện đến 2027 để vận hành trên nền tảng Green SM; đây là kế hoạch/biên bản công bố, không phải toàn bộ xe đã triển khai.
- Xe tự hành có thể tạo bài toán depot/fleet charging về dài hạn, nhưng chưa nên là giả định nền cho demo Việt Nam.

Nguồn: [Google Maps EV charging stops](https://support.google.com/maps/answer/9773205?hl=en), [Tesla Supercharging/Trip Planner](https://www.tesla.com/support/charging/supercharging), [VinFast: kế hoạch Xe Nhanh Việt Nam](https://vinfastauto.com/vn_vi/xe-nhanh-viet-nam-mua-3000-o-to-dien-vinfast-de-van-doanh-tren-nen-tang-green-sm-platform), [NREL EVI-X](https://www.nrel.gov/transportation/evi-x.html).

## Nhà ở và quy hoạch

Chính phủ Việt Nam đã có chỉ đạo thúc đẩy hạ tầng sạc tại chung cư. Đây là căn cứ để đưa access-to-home-charging, dự án nhà ở và mật độ cư trú vào các kịch bản. Một khu dân cư đông không tự động đồng nghĩa cần trạm công cộng: cần biết người dân có chỗ sạc riêng, chính sách quản lý tòa nhà và khoảng cách tới mạng sạc sẵn có.

Nguồn: [Công điện 27/CĐ-TTg về thúc đẩy hạ tầng sạc tại chung cư](https://chinhphu.vn/?docid=217406&pageid=27160).

Đối với bài toán economics, giá điện sạc phải là input có phiên bản theo loại hợp đồng/đo đếm. Thông tư 60/2025/TT-BCT quy định giá điện cho dịch vụ sạc và nêu trường hợp lắp công tơ riêng. Do đó demo nên có trường `tariff_regime`/`effective_date` để cập nhật được; không hard-code một giá điện chung cho mọi site.

Nguồn: [Chinhphu.vn: quy định giá bán lẻ điện cho sạc xe điện](https://xaydungchinhsach.chinhphu.vn/quy-dinh-moi-ve-gia-ban-le-dien-cho-sac-xe-dien-119251209083343081.htm).

## Ranh giới TP.HCM trong nghiên cứu này

Nghị quyết 202/2025/QH15 sắp xếp toàn bộ địa giới cấp tỉnh của TP.HCM, Bình Dương và Bà Rịa–Vũng Tàu thành TP.HCM mới, hiệu lực từ 01/07/2025. Vì team chốt “TP.HCM”, docs lấy địa giới hiện hành này làm macro study area. Nguồn trạm, dân số và giao thông cũ vẫn có thể giữ `legacy_area` để phân tích, nhưng cần crosswalk sang boundary version hiện hành.

Nguồn: [Nghị quyết 202/2025/QH15, Công báo Chính phủ](https://congbao.chinhphu.vn/van-ban/nghi-quyet-so-202-2025-qh15-45050.htm).

## Bối cảnh tăng trưởng không phải demand map

IEA ghi nhận doanh số xe điện toàn cầu vượt 20 triệu năm 2025, chiếm khoảng một phần tư doanh số ô tô mới; số điểm sạc công cộng toàn cầu vượt 7 triệu cuối năm 2025. Các tổng số toàn cầu chỉ xác nhận bối cảnh chuyển dịch, không cho biết Việt Nam, tỉnh/thành hay parcel nào đang thiếu trạm. Dữ liệu địa phương, mức sạc tại nhà, chính sách, traffic, cạnh tranh và uptime vẫn quyết định kết quả site planning.

Nguồn: [IEA Global EV Outlook 2026: electric car trends](https://www.iea.org/reports/global-ev-outlook-2026/trends-in-electric-cars), [IEA: EV charging](https://www.iea.org/reports/global-ev-outlook-2026/electric-vehicle-charging-chap-6-and-10).

## Câu hỏi phỏng vấn để xác thực trước khi chốt MVP

### Hỏi operator/investor

1. Quyết định hiện tại là chọn land/parcel, chọn khu vực hay chọn corridor? Ai là người duyệt cuối?
2. Dữ liệu nào họ thực sự dùng để chọn site? Nguồn nào thiếu, đắt hoặc đến trễ?
3. Họ tối ưu utilization, NPV, coverage, fleet contracts hay một tổ hợp? Hurdle rate/payback nào được dùng?
4. Bao nhiêu thời gian và vốn thường mất cho đất, đấu nối, nâng cấp điện và cấp phép?
5. Có lựa chọn mở rộng trạm hiện tại hoặc depot charging thay cho trạm public mới không?
6. Có thể chia sẻ aggregate nào, theo thời gian/độ phân giải nào, và có điều kiện privacy/competition nào?

### Hỏi tài xế/đội xe

1. Khó khăn thường là thiếu trạm, trạm hỏng, phải vòng xa, không hợp connector/giá, hay chờ lâu?
2. Trên chuyến dài, hành trình nào và thời điểm nào có rủi ro không tìm được trạm phù hợp?
3. Đội xe có depot/home charging không? Xe nằm ở đâu giữa ca và chạy tuyến nào lặp lại?
4. Người dùng hiện chọn trạm thế nào; có tìm kiếm thất bại, bỏ đi hoặc đổi kế hoạch không?

## Cách dùng bằng chứng trong bài thi

- Dùng IEA làm bối cảnh adoption/infrastructure toàn cầu, không dùng làm dự báo site-level Việt Nam.
- Dùng V-Green và đội xe làm ví dụ thị trường/segment đang được đầu tư, nêu trạng thái “đã công bố kế hoạch”.
- Dùng chính sách chung cư làm lý do kiểm tra home charging và quy hoạch, không suy ra trạm public là giải pháp duy nhất.
- Dùng EVgo/NREL như tham khảo thực hành/thành phần model, ghi rõ bối cảnh nước ngoài.
- Để xác nhận pain point tại vùng demo, lấy phỏng vấn, inventory, luồng đi lại và dữ liệu operator làm bằng chứng địa phương.
