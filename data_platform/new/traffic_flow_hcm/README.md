# Lịch sử điều kiện giao thông tại 9 phường

Thư mục này giữ một nguồn lịch sử công khai theo **đoạn đường** và các JSON đã
lọc/gộp cho 9 phường pilot: Sài Gòn, Bến Thành, Xuân Hòa, Tân Định, Phú Nhuận,
Bình Thạnh, Tân Sơn Hòa, Thạnh Mỹ Tây và Bình Quới.

## Điều dữ liệu này đo được và không đo được

Nguồn có thời điểm quan sát, mã đoạn đường và trường `velocity`; các thuộc tính
đoạn đường có `max_velocity`. Nó **không có số xe**, loại xe, OD, hoặc số xe rẽ.
Vì vậy mọi record JSON đều có:

```json
{
  "vehicle_count": null,
  "vehicle_count_status": "not_available_in_source",
  "source_type": "observed_traffic_condition"
}
```

`observation_count = 0` chỉ có nghĩa không có quan sát nguồn được ghép vào
phường/kỳ đó, tuyệt đối không có nghĩa là lưu lượng bằng 0. Không sử dụng các
JSON này như “lưu lượng xe” hoặc làm nhãn nhu cầu sạc. Đây là lớp **điều kiện
lưu thông lịch sử** để hiển thị/khám phá riêng với proxy hạ tầng và với số xe
đếm được (nếu có nguồn được cấp quyền sau này).

## Tệp đầu ra

- `traffic_segments_9_wards.json`: 5.390 đoạn đường, được gán theo trung điểm
  vào polygon `ADMINISTRATIVE_2025`.
- `traffic_condition_observations_9_wards.json`: 7.509 quan sát vận tốc nguồn
  đã ghép không gian; timestamp nguồn giữ UTC và có thêm giờ Việt Nam.
- `traffic_condition_daily_9_wards.json`: mỗi ngày trong dải dữ liệu × 9
  phường, gồm số quan sát, số đoạn, vận tốc trung bình/trung vị và tỷ lệ so với
  `maximum_velocity_kmh` khi nguồn có thuộc tính đó.
- `traffic_condition_weekly_9_wards.json`: gộp theo tuần bắt đầu thứ Hai.
- `traffic_condition_monthly_9_wards.json`: gộp theo tháng.
- `collection_manifest.json`: nguồn, SHA-256, phạm vi, kết quả lọc và các giới
  hạn bắt buộc phải giữ khi tiêu thụ dữ liệu.

Các tệp trong `source/` là bản CSV nguyên gốc đã giải nén; `archive3.zip` là
gói tải xuống. Chúng được giữ để tái lập và kiểm tra hash.

## Snapshot import Planner

Theo hợp đồng import Planner, bộ chuẩn hóa nằm riêng tại
`data_platform/station_planning/planner_v2/`: `source_registry.csv`,
`boundaries.geojson`, `traffic_segments.geojson`, `traffic_observations.csv`
và `snapshot_manifest.json`. CSV dùng đúng các cột traffic contract; trong đó
`vehicle_count` và `vehicle_volume_vph` để trống (unknown), còn
`average_speed_kph` giữ giá trị tốc độ nguồn. Xem README của snapshot để biết
nhãn provenance/quality và cách import. Các JSON trong thư mục này và trong
snapshot chỉ là summary cho chart/layer, không thay thế bảng observation.

## Nguồn và phạm vi

Nguồn chính là bộ [Traffic Flow data in Ho Chi Minh City, Viet Nam trên
Kaggle](https://www.kaggle.com/datasets/thanhnguyen2612/traffic-flow-data-in-ho-chi-minh-city-viet-nam),
được trang nguồn công bố giấy phép CC0. Bản tải lúc thu thập dùng mirror công
khai của [Transport Data Commons](https://ckan.transport-data.org/dataset/traffic-flow-data-in-ho-chi-minh-city-viet-nam-hochiminhcity).
`collection_manifest.json` chứa URL đầy đủ, dung lượng và hash của từng tệp.

Quan sát nguồn trải từ tháng 7/2020 đến tháng 4/2021 và lấy mẫu không đều.
Các ranh giới 9 phường là snapshot 2025 của dự án; vì khác thời điểm, phép ghép
này chỉ là chuẩn hóa không gian, không khẳng định ranh giới năm 2020 giống hệt
snapshot hiện dùng. Đoạn đường vượt ranh giới không bị cắt theo chiều dài mà
được gán theo trung điểm, và được ghi rõ trong metadata.

## Tạo lại

Sau khi có đủ năm CSV trong `source/`, chạy:

```powershell
python scripts/prepare_traffic_flow_hcm.py
```

Script chỉ dùng thư viện chuẩn Python, ghi lại tất cả JSON và manifest. Không
cần gọi mạng khi chạy lại.
