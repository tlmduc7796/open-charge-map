# Bộ đơn vị hành chính và dân số cho quy hoạch trạm sạc

## File nên sử dụng

- `hcm_planning_units_2025.geojson`: 168 ranh giới cấp cơ sở kèm thuộc tính gọn; dùng gán POI/RP/trạm vào đơn vị bằng point-in-polygon.
- `hcm_planning_units_2025.csv`: cùng 168 đơn vị và dân số, không lặp tọa độ polygon; dùng tổng hợp và làm đầu vào mô hình.
- `hcm_planning_units_2025.kml`: cùng dữ liệu để kiểm tra trên QGIS/Google Earth.

Hình học giữ nguyên các phần polygon/đảo/vòng trong của nguồn. Bản gọn **chỉ thu gọn thuộc tính và bỏ polygon cấp thành phố**, không giảm độ chi tiết ranh giới. Bộ ranh giới gốc được giữ để đối chiếu.

## Sáu trường xử lý

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `unit_id` | string | ID của ứng dụng, ví dụ `hcm_2025_27637`; dẫn xuất từ `AdminID` của nguồn. Không mặc nhiên coi là mã hành chính quốc gia đã kiểm chứng |
| `unit_name` | string | Tên theo lớp bản đồ 2025, ví dụ `Xã Bình Chánh` |
| `unit_type` | string | `ward` = phường; `commune` = xã; `special_zone` = đặc khu, theo tên trong lớp 2025 |
| `population` | integer hoặc null | Số người được trường `DANSO` của nguồn báo cáo |
| `population_reference_date` | date hoặc null | Ngày thống kê dân số; hiện tất cả null vì thuộc tính đã lấy không nêu ngày thống kê |
| `population_status` | string | Hiện tất cả là `source_reported_date_unknown`: lấy trực tiếp từ nguồn, chưa biết thời điểm thống kê |

GeoJSON lưu hình học riêng tại `geometry`; `Feature.id` trùng `unit_id`. KML dùng Placemark và ExtendedData cho cùng các trường; giá trị null là ô trống. CSV dùng UTF-8 có BOM, dân số viết bằng số nguyên không có dấu phân cách hàng nghìn.

Đã bỏ khỏi bảng xử lý: UUID nguồn, `AdministrativeID`, `ParentID`, tên trường hình học nguồn, URL/lớp nguồn lặp ở từng đối tượng và metadata kỹ thuật. Thông tin truy vết chuyển sang các file riêng; không mất khả năng đối chiếu.

## Nguồn dân số và cách ghép

Nguồn trực tiếp: [Bản đồ số Thành phố Hồ Chí Minh](https://bando.tphcm.gov.vn/), lớp **`ADMINISTRATIVE_2025`**, trường **`DANSO`**. Thu thập ngày **11/10/2026** qua API công khai của chính trang. Không lấy số dân từ repo paper 1, không sinh synthetic, không cộng các đơn vị cũ hoặc ghép tên gần giống.

Ghép bản ghi dân số với ranh giới bằng UUID nguồn `Id`, rồi kiểm tra thêm `Title`, `AdminID`, `AdministrativeID`, `ParentID`. Kết quả đủ **168/168 đơn vị**, không có dân số thiếu/không hợp lệ trong lần tải này.

| Ví dụ | `unit_id` | `population` |
|---|---|---:|
| Xã Bình Chánh | `hcm_2025_27637` | 76187 |
| Phường Bến Thành | `hcm_2025_26743` | 71875 |
| Đặc khu Côn Đảo | `hcm_2025_26732` | 6502 |

**Năm 2025 trong tên file là phiên bản ranh giới, không phải năm thống kê dân số.** `CreatedDate`/`ModifiedDate` của bản ghi chỉ phản ánh metadata cập nhật dữ liệu; không dùng làm ngày điều tra dân số. Ngày tải năm 2026 cũng không biến số liệu thành dân số năm 2026. Các trường đã lấy chưa giải thích rõ là dân số thường trú, dân số thực tế hay quy mô dân số quy đổi.

Tổng các giá trị `DANSO` tải được là **14.767.344**; đây chỉ là tổng số liệu nguồn theo 168 bản ghi, chưa được đối chiếu thành tổng dân số thống kê chính thức cùng thời điểm. Không dùng số tổng để khẳng định population đã được xác minh mới nhất.

`DIENTICH` có trong nguồn nhưng chưa đưa vào bảng xử lý vì thiếu xác minh đơn vị/định nghĩa trong thuộc tính đã tải. Nếu cần mật độ dân số, bổ sung diện tích có đơn vị được xác nhận hoặc tính diện tích từ hình học với phương pháp phù hợp; không tính diện tích bằng độ kinh/vĩ độ.

## File kiểm tra và tái lập

- `population_source_2025.json`: các thuộc tính nguồn, truy vấn, tổng số bản ghi và phân trang; không chứa token truy cập.
- `population_sources_2025.csv`: mapping ID ứng dụng ↔ ID nguồn, số dân gốc, tên trường, URL/lớp nguồn, thời điểm cập nhật bản ghi và thời điểm tải.
- `planning_manifest.json`: schema, cách ghép, tình trạng số dân, tổng kiểm tra, hash và dung lượng file.
- `prepare_planning_boundaries.py`: script trong thư mục scripts; chạy từ gốc project bằng Python và curl.exe. Script sử dụng ranh giới đã lưu cùng luồng public-access bình thường của cổng.

Kiểm tra đã thực hiện: đủ 168 bản ghi; ID duy nhất; số dân là số nguyên dương; mapping khớp chính xác; hình học GeoJSON giữ nguyên; KML giữ toàn bộ tọa độ với phép đảo hướng vòng; số dân và thuộc tính khớp giữa CSV, GeoJSON, KML và nguồn. Không tuyên bố đã kiểm tra đầy đủ topology hay kiểm chứng thời điểm thống kê dân số.

## Áp dụng vào bài toán quy hoạch

1. Gán `unit_id` cho POI/RP/trạm từ tọa độ; giữ `Unit` cũ của paper 1 làm trường truy vết riêng.
2. Tổng hợp mạng cũ và capacity theo `unit_id`; dùng dân số làm feature hoặc cơ sở xây dựng kịch bản nhu cầu.
3. Chuẩn bị riêng tỷ lệ EV, tỷ lệ sạc công cộng, số lượt/điện mỗi xe và profile giờ. **Dân số không phải số EV hoặc demand sạc.** Các hệ số không có nguồn được ghi là giả định/synthetic.
4. Nếu chia demand cấp xã/phường xuống RP, cần trọng số có tổng bằng 1 trong mỗi vùng; không gán toàn bộ dân số vùng cho từng RP. Vùng chưa có RP phải được báo thiếu đại diện nhu cầu.
5. Nếu cần dự báo dân số/nhu cầu tương lai, tạo bảng kịch bản riêng; không sửa số nguồn để làm như quan sát thực.

Phạm vi và loại đơn vị giữ theo lớp 2025 đang dùng để ghép dữ liệu. Đã thấy [thông tin trên Cổng Chính phủ về thay đổi loại hình 29 xã thành phường trong năm 2026](https://xaydungchinhsach.chinhphu.vn/sap-xep-to-chuc-lai-bo-may-thanh-lap-29-phuong-moi-ho-tro-dao-tao-bac-si-noi-tru-toi-da-100-trieu-dong-nam-119260828095714869.htm); vì vậy không gọi `unit_type` của bộ này là phân loại hiện hành năm 2026. Chưa thay đổi tên/loại/hình học dựa vào bài tin đó; muốn cập nhật phải đối chiếu văn bản và mapping chính thức riêng.
