# Giá mua điện cho mô phỏng kinh doanh trạm sạc

File dữ liệu: `evnspc_business_electricity_tariffs.csv`. Thu thập ngày **12/10/2026**, UTF-8 có BOM, dấu phân cách phẩy, số dùng dấu chấm thập phân. CSV có 48 dòng dữ liệu, 9 đơn giá độc lập, 3 cấp điện áp và 2 lịch giờ. Các dòng là **khoảng thời gian**, không phải 48 mức giá khác nhau.

## Danh mục và phạm vi

Thu thập **mục 3: Giá bán lẻ điện cho kinh doanh** của Quyết định 1279/QĐ-BCT ngày 09/05/2025, hiệu lực từ **10/05/2025**. Giá được kiểm tra với bảng dữ liệu trên trang CSKH EVNSPC và trang 3-4 của bản quyết định gốc. Giá này là giá **mua điện**, không phải giá bán dịch vụ sạc cho khách hàng.

| Điện áp mua điện | Bình thường | Thấp điểm | Cao điểm |
| --- | ---: | ---: | ---: |
| Từ 22 kV trở lên | 2887 | 1609 | 5025 |
| Từ 6 kV đến dưới 22 kV | 3108 | 1829 | 5202 |
| Dưới 6 kV | 3152 | 1918 | 5422 |

Đơn vị: đồng/kWh, chưa VAT. Mô hình giả định trạm mua điện trực tiếp theo hợp đồng mục đích kinh doanh và có công tơ ba giá. Cần chọn cấp điện áp **tại điểm mua/đo đếm theo hợp đồng**, không lấy điện áp đầu ra DC của bộ sạc. **80 kW/cổng không xác định được cấp điện áp mua điện**; do chưa có thông tin đấu nối, không tự chọn một cấp làm dữ liệu thực.

Thông tư 60/2025/TT-BCT có Điều 10 về giá cho sạc xe điện và công tơ riêng, nhưng Điều 21 quy định hiệu lực của Điều 10 gắn với lần điều chỉnh giá bán lẻ điện bình quân sau Quyết định 14/2025/QĐ-TTg. Các nguồn đã kiểm tra chưa xác định được một quyết định đơn giá riêng mới cho trạm sạc thay thế 9 giá trên. Vì vậy không gắn nhãn đây là biểu giá riêng sạc xe điện đã có hiệu lực. Với triển khai thực tế, đối chiếu mục đích và biểu giá trong hợp đồng điện.

## Hai lịch giờ và khác biệt giữa các nguồn

**Phải lọc đúng một `schedule_id` và một `voltage_band_id` trước khi tính chi phí.** Hai lịch có cùng 9 giá; ghép cả hai sẽ tính trùng và tạo khoảng giờ chồng lấn.

1. `tt16_reference_2025`: 30 dòng, trạng thái `verified_historical_reference`, mốc tham chiếu **01/07/2025**. Đây là kịch bản lịch giờ đã xác minh cho mốc lịch sử này, không phải khẳng định lịch đang áp dụng trên mọi công tơ tháng 10/2026.
   - Thứ Hai đến thứ Bảy: bình thường 04:00-09:30, 11:30-17:00, 20:00-22:00; cao điểm 09:30-11:30, 17:00-20:00.
   - Chủ nhật: bình thường 04:00-22:00, không có cao điểm.
   - Mọi ngày: thấp điểm 22:00-04:00, được tách tại nửa đêm thành 00:00-04:00 và 22:00-24:00 để ghép dữ liệu dễ hơn.
2. `qd963_evnspc_published_2026`: 18 dòng, trạng thái `published_by_evnspc_application_date_unverified`. Lưu đúng lịch mà trang CSKH EVNSPC công bố tại ngày thu thập; **chưa xác minh ngày bắt đầu áp dụng thực tế**.
   - Thứ Hai đến thứ Bảy: bình thường 06:00-17:30 và 22:30-24:00; cao điểm 17:30-22:30.
   - Chủ nhật: bình thường 06:00-24:00, không có cao điểm.
   - Mọi ngày: thấp điểm 00:00-06:00.
   - Trang CSKH ghi “Áp dụng từ 22/4/2026”; CSV giữ ngày này ở `schedule_claimed_effective_from`, **không coi đây là ngày áp dụng thực tế đã được xác minh**. Cục Điện lực và Bộ Công Thương đã giải thích quy định chuyển tiếp và đăng dự thảo sửa đổi tháng 5/2026. Bài EVN ngày 30/07/2026 mô tả lịch mới, nhưng không cung cấp văn bản sửa đổi hoặc ngày bắt đầu tính hóa đơn. Chỉ sử dụng lịch này như kịch bản theo công bố EVNSPC cho đến khi xác minh với công tơ/hợp đồng hoặc văn bản áp dụng.

Trang ban đầu người dùng cung cấp hiện hiển thị quyết định năm 2019, bảng giá cũ và nhãn cấp điện áp không khớp biểu giá kinh doanh trong quyết định 1279. Do vậy lấy trang đó làm điểm xuất phát và nguồn lịch giờ lịch sử; lấy **trang CSKH cùng hệ thống EVNSPC + quyết định gốc** làm nguồn đơn giá, không sao chép các giá cũ.

## Các cột dùng để ghép nhu cầu và tính OPEX

| Cột | Ý nghĩa |
| --- | --- |
| `schedule_id`, `schedule_status`, `schedule_reference_date` | Chọn lịch và biết mốc tham chiếu/trạng thái xác minh. |
| `tariff_group` | Danh mục chính thức: giá bán lẻ điện cho kinh doanh. |
| `voltage_band_id`, `voltage_band` | Mã ổn định và tên nhóm điện áp. |
| `voltage_min_kv_inclusive`, `voltage_max_kv_exclusive` | Biên dưới có tính, biên trên không tính; trống biên trên nghĩa là không có giới hạn trên. |
| `day_group`, `iso_weekdays` | `mon_sat` = 1;2;3;4;5;6, `sunday` = 7; thứ Hai là 1. |
| `period_code`, `period_name` | `normal`, `off_peak`, `peak` và tên tiếng Việt. |
| `start_time`, `end_time` | Khoảng **[bắt đầu, kết thúc)** theo giờ Việt Nam. `24:00` là cuối ngày, không phải khoảng đầu ngày kế tiếp. |
| `start_minute`, `end_minute` | Số phút từ 00:00, 0-1440; thuận tiện cho lập trình. |
| `price_vnd_per_kwh_ex_vat` | Giá gốc trong quyết định, số nguyên đồng/kWh. |
| `vat_rate`, `price_vnd_per_kwh_inc_vat` | VAT dạng thập phân (0.08), giá gốc nhân (1 + VAT), lưu 2 chữ số thập phân. |
| `price_effective_from` | Ngày hiệu lực **đơn giá** 10/05/2025, không phải ngày hiệu lực của mọi cột trong dòng. |
| `vat_effective_from`, `vat_effective_to` | 01/07/2025-31/12/2026 theo Nghị định 174/2025/NĐ-CP; không ngoại suy VAT này sang kỳ khác. |
| `schedule_claimed_effective_from` | Chỉ có ở lịch 2026; ngày mà EVNSPC ghi trên trang, còn cần xác minh áp dụng. |
| `timezone` | `Asia/Ho_Chi_Minh`, UTC+7. |
| `source_url`, các cột `*_document_url`, `collected_on`, `notes` | Truy nguồn và các giới hạn áp dụng từng dòng. |

Tính `chi_phi_dien = tổng(kWh_mua_tu_luoi_trong_khoang × đơn_giá)`. Dùng giá trước VAT để so sánh OPEX/lợi nhuận trên cơ sở trước thuế; giá có VAT để mô phỏng dòng tiền thanh toán. Nếu tính chi phí thực tế sau thuế, còn phụ thuộc khả năng khấu trừ VAT đầu vào của doanh nghiệp.

Nhu cầu theo giờ phải tách ở ranh giới **:30**, hoặc phân bổ điện năng theo dữ liệu công suất/thời gian sạc trong từng phần giờ. Không gán toàn bộ giờ 09:00-10:00 hoặc 17:00-18:00 cho một giá khi khoảng đó cắt ranh giới của lịch đang chọn. Nếu chỉ có tổng kWh mỗi giờ, chia đều theo thời lượng là **giả định mô phỏng**, cần ghi nhận riêng.

80 kW là công suất, không phải sản lượng cố định mỗi giờ. Sản lượng còn phụ thuộc số cổng hoạt động, thời gian sạc, hệ số sử dụng và tổn hao. Điện mua từ lưới có thể cao hơn điện giao cho xe. Các đầu vào này chưa có trong nguồn giá điện và không được thêm như dữ liệu thực trong CSV.

Khi các vị trí dùng cùng nhóm giá, chi phí điện khác nhau do lượng điện và phân bố thời gian sạc. Trong bài toán tối đa phục vụ theo ngân sách xây trạm, dùng dữ liệu này để đánh giá chi phí vận hành; trong bài toán lợi nhuận/hoàn vốn, ghép thêm giá bán dịch vụ và sản lượng. Không tự thay đổi chi phí xây dựng hoặc hàm mục tiêu từ dữ liệu biểu giá.

## Nguồn

- Trang ban đầu: https://evnspc.vn/CMS_BieuGiaDien?categoryId=F02-MNU201904-00000054
- Bảng giá và lịch giờ CSKH EVNSPC: https://www.cskh.evnspc.vn/TraCuu/ThongTinGiaDien
- QĐ1279, mục 3, trang 3-4: https://www.cskh.evnspc.vn/FileUploads/files/vanbannganhdien/QD1279-QD-BCT.pdf
- Thông báo hiệu lực 10/05/2025 của Điện lực Đồng Nai: https://pcdongnai.evnspc.vn/CMS_Article?AID=F02F21WEB-202505-0000000042&MID=F02-MNU202105-00000008
- TT16/2014: https://www.cskh.evnspc.vn/FileUploads/files/vanbannganhdien/16_2014-TT-BCT.pdf
- TT60/2025, Điều 10, 20-21: https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/12/60-bct.pdf
- QĐ963/2026: https://moit.gov.vn/upload/2005517/20260423/1_QD-BCT_2026_963_30f7a.pdf
- Cục Điện lực giải thích thời gian áp dụng: https://npc.com.vn/van-ban-phap-quy/cuc-dien-luc-thong-tin-ve-thoi-gian-ap-dung-khung-gio-cao-diem-thap-diem-va-gio-binh-thuong-cua-he-thong-dien-quoc-gia-48997.html
- Bộ Công Thương về dự thảo sửa TT60, 27/05/2026: https://www.eav.gov.vn/d/vi-VN/news-o/Bo-Cong-Thuong-lay-y-kien-hoan-thien-du-thao-Thong-tu-so-602025TT-BCT-de-som-ap-dung-khung-gio-cao-diem-thap-diem-moi-60-40-59100
- EVN về lịch mới, 30/07/2026: https://www.evn.com.vn/d/vi-VN/news/Dieu-chinh-khung-gio-cao-diem-Doanh-nghiep-duoc-loi-gi-60-3557-509124
- VAT, NĐ174/2025, Điều 1-2: https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/7/174nd.signed.pdf

## Kiểm tra

Đối chiếu đủ 9 giá với quyết định gốc; kiểm tra mỗi tổ hợp lịch × cấp điện áp × nhóm ngày phủ kín 1440 phút, không trùng/thiếu khoảng, Chủ nhật không có cao điểm; kiểm tra giá có VAT và đọc lại file CSV sau xuất. Không kiểm chứng hợp đồng hoặc công tơ của một trạm cụ thể.
