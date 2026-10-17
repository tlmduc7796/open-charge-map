# Mạng đường thực tế của 9 phường (OpenStreetMap)

`hcm_nine_wards_roads.geojson`: các đoạn đường (`highway` = motorway, trunk, primary, secondary, tertiary, unclassified, residential và các `_link`) trong khung bao của vùng pilot 9 phường, lấy từ OpenStreetMap qua Overpass API bằng [`scripts/collect_osm_roads.py`](../../scripts/collect_osm_roads.py). Thời điểm lấy, bộ lọc và hash ghi trong `collection_manifest.json`.

- Giấy phép: ODbL 1.0, © những người đóng góp OpenStreetMap. Dữ liệu dẫn xuất (khối đường trong `data_platform/station_planning/gap_v1/`) phải giữ ghi nguồn này.
- Mỗi feature là một LineString kèm `highway`, `name`, `lanes`, `oneway`, `ref` nếu có. Hình học nằm trên khung bao chữ nhật nên có đoạn nằm ngoài ranh giới phường; bước tạo khối sẽ cắt theo ranh giới phường.
- `residential` gồm cả hẻm (tên bắt đầu bằng Hẻm, Ngõ, Ngách, Kiệt) và đường chưa đặt tên. Bước tạo khối chỉ dùng đường có tên và loại bỏ hẻm; xem `route_division` trong `config/gap_analysis_demo.json`.
- OpenStreetMap do cộng đồng cập nhật nên chưa chắc đầy đủ và không phải dữ liệu địa chính. Sông, kênh và các đường nội bộ không được vẽ thì không chặn khối.
