# Planner v2 — snapshot điều kiện giao thông lịch sử

Snapshot này tuân theo hợp đồng import tại
`DU_LIEU_THU_THAP_VA_HOP_DONG_IMPORT_PLANNER_VI.md` và được tạo song song với
`demo_hcmc_v3`; nó không ghi đè demo và chưa được API/UI hiện tại tự động nạp.

## Tệp canonical

- `source_registry.csv`: registry hai nguồn (traffic và ranh giới) mà mọi record
  tham chiếu bằng `source_id`.
- `boundaries.geojson`: ranh giới `ADMINISTRATIVE_2025` của đúng 9 phường,
  GeoJSON `EPSG:4326` với tọa độ `[longitude, latitude]`.
- `traffic_segments.geojson`: 5.390 đoạn đường. Geometry là `LineString` từ
  node đầu/cuối nguồn; mỗi đoạn được gán phường theo trung điểm và có nhãn
  provenance/quality.
- `traffic_observations.csv`: 7.509 observation nguyên tử. Các cột contract
  bắt đầu bằng `segment_id, interval_start, interval_minutes, vehicle_count,
  vehicle_volume_vph, average_speed_kph, ...`.
- `traffic_condition_{daily,weekly,monthly}_9_wards.json`: JSON đã gộp phục vụ
  chart/layer; mỗi kỳ luôn có đủ 9 phường và giữ `null` cho dữ liệu chưa có.
- `snapshot_manifest.json`: ID snapshot, hash SHA-256, record count, phạm vi
  thời gian và cảnh báo bắt buộc.

## Quy tắc semantic bắt buộc

Đây là dữ liệu **tốc độ/trạng thái đoạn đường lịch sử**, không phải dữ liệu đếm
lưu lượng xe. Do nguồn không có số xe, thời lượng đo, hướng, loại xe hoặc mô tả
phương pháp đếm:

- `vehicle_count` và `vehicle_volume_vph` để trống trong CSV; JSON dùng `null`.
- `measurement_method` ghi rõ phương pháp nguồn không được tài liệu hóa đủ.
- `source_type=unknown`, `quality_status=unknown`, `is_proxy=false`,
  `is_synthetic=false`; không nâng nhãn lên `measured`.
- `average_speed_kph` chỉ là tốc độ nguồn cung cấp. Nó không được dùng để suy ra
  số xe, nhu cầu EV, hoặc `scenario_traffic_level`.
- Kỳ không có observation phải giữ metric `null`; `observation_count=0` không
  có nghĩa lưu lượng xe bằng 0.

Nguồn ở 2020–2021 còn boundary ở snapshot 2025. Việc gán phường là chuẩn hóa
không gian bằng trung điểm đoạn, không phải tuyên bố ranh giới hai thời điểm
hoàn toàn giống nhau.

Tái tạo toàn bộ snapshot và JSON summary:

```powershell
python scripts/prepare_traffic_flow_hcm.py
```
