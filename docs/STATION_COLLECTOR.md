# Station candidate collector

## Mục đích

Collector tìm và hợp nhất các địa điểm có khả năng là trạm sạc trong vùng demo. Output `station_candidates.json` là vùng staging để con người xác minh trước khi đưa record vào `stations.geojson`; collector không tự ghi đè master data.

Nguồn được dùng theo thứ tự:

1. danh sách trạm công khai của EV ONE;
2. OpenStreetMap Overpass và Nominatim;
3. Goong Places khi có `GOONG_API_KEY`.

Collector chuẩn hóa tên, địa chỉ, tọa độ và provider reference; gộp candidate trùng theo provider ID hoặc khoảng cách/tên; giữ provenance và trạng thái review qua các lần chạy. Các field kỹ thuật chưa được nguồn xác nhận vẫn để trống thay vì tự suy diễn.

## Chạy

Chạy offline để tạo/kiểm tra output từ master data hiện có:

```powershell
python scripts/collect_station_candidates.py --offline
```

Chạy EV ONE và OSM qua mạng:

```powershell
python scripts/collect_station_candidates.py --providers evone,osm
```

Để bật Goong, sao chép `.env.example` thành `.env`, điền key và chạy collector. Không commit `.env`.

```text
GOONG_API_KEY=your_key_here
```

```powershell
python scripts/collect_station_candidates.py
```

Nếu không có key, provider Goong được bỏ qua và collector vẫn tạo output từ các nguồn còn lại.

## Xem vùng tìm kiếm trên Google Maps

Mỗi lần chạy, collector tạo `data/collection/station_search_area.kml` gồm bounding box và các candidate có tọa độ. Để xem chính xác trên nền Google Maps:

1. mở <https://www.google.com/mymaps> và tạo một map;
2. chọn **Import** ở layer đầu tiên;
3. tải file `station_search_area.kml` lên.

Có thể mở nhanh tâm vùng hiện tại tại <https://www.google.com/maps/@10.76,106.70,13z>; link này chỉ đặt viewport, còn KML mới thể hiện chính xác bốn cạnh của vùng tìm kiếm.

## Review workflow

Mỗi candidate có `review_status` thuộc `pending`, `verified` hoặc `rejected`, cùng `review_notes`. Khi chạy lại, collector cố giữ các giá trị review dựa trên `candidate_id` hoặc provider reference. Chỉ record `verified` mới nên được chuyển sang `stations.geojson`.
