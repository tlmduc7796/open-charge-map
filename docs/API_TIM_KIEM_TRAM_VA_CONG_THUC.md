# API tìm trạm, tìm đường và công thức ước tính

Tài liệu này mô tả hai API tìm kiếm chính của backend và cách hệ thống hiện tính quãng đường theo pin, SOC, thời gian đi, thời gian chờ và thời gian sạc.

## API chính

| API | Dùng khi | Kết quả chính |
|---|---|---|
| `POST /api/v1/search/stations` | Tìm trạm có thể đi tới quanh một điểm | Danh sách trạm xếp theo tổng thời gian đi + chờ + sạc |
| `POST /api/v1/search/route` | Kiểm tra có đi thẳng tới đích được không và tìm trạm ghé nếu cần | Tuyến thẳng, trạng thái pin, danh sách trạm đề xuất hoặc trạm gần nhất dự phòng |

Các API dùng JSON camelCase, tọa độ theo dạng `{ "lat": ..., "lng": ... }`. SOC gửi lên là phần trăm từ 0 đến 100.

### Tìm trạm quanh một điểm

```http
POST /api/v1/search/stations
Content-Type: application/json
```

```json
{
  "origin": { "lat": 10.7769, "lng": 106.7009 },
  "vehicleId": "EV_VF5_PLUS",
  "batteryPct": 70,
  "limit": 10
}
```

`origin` là tâm tìm kiếm. Bán kính tìm trạm được suy ra từ quãng đường an toàn xe có thể đi với SOC hiện tại. `limit` có giá trị từ 1 đến 25, mặc định 10.

### Tìm tuyến và trạm ghé

```http
POST /api/v1/search/route
Content-Type: application/json
```

```json
{
  "origin": { "lat": 10.7769, "lng": 106.7009 },
  "destination": { "lat": 10.8231, "lng": 106.6297 },
  "vehicleId": "EV_VF5_PLUS",
  "batteryPct": 70,
  "limit": 10,
  "includeOptionalStops": false
}
```

Backend tính tuyến trực tiếp trước. Nếu pin đủ tới đích mà vẫn giữ SOC dự trữ, mặc định trả tuyến thẳng và không đề xuất điểm dừng. Đặt `includeOptionalStops: true` để nhận thêm các trạm có thể ghé tự nguyện. Nếu pin không đủ tới đích, backend tìm trạm cần ghé dù cờ này là `true` hay `false`.

Trường `case` trong phản hồi có các giá trị:

- `enough`: pin đủ đi thẳng tới đích; danh sách trạm chỉ có khi yêu cầu điểm dừng tự nguyện.
- `needCharge`: tìm được phương án trạm ghé khi pin không đủ đi thẳng.
- `fallback`: không tìm được phương án trạm ghé hợp lệ; backend có thể trả trạm gần nhất làm gợi ý dự phòng. Gợi ý này không bảo đảm xe còn đủ pin để tới trạm.

## Tìm trạm dọc tuyến hoạt động thế nào

Khi cần tạo danh sách trạm trên tuyến, `RecommendationService` lấy các trạm ứng viên rồi định tuyến qua từng ứng viên. Trong database mode, ứng viên ban đầu nằm trong hành lang 5.000 m quanh **đường thẳng** nối điểm đi và điểm đến. Đây là bước lọc sơ bộ, không phải vùng đệm quanh đường lái xe thực tế. Trong memory mode, repository hiện đưa toàn bộ trạm vào làm ứng viên.

Với từng ứng viên, backend yêu cầu Goong tạo tuyến qua tọa độ trạm; nếu Goong không khả dụng thì thử OSRM. Trạm bị loại nếu không tạo được tuyến, xe không đủ pin tới trạm mà vẫn giữ dự trữ, hoặc sau khi sạc không thể đi tiếp đến đích. Trạm còn phải công cộng, có cổng hoạt động và giờ mở cửa được xác nhận trong luồng tìm trạm trên tuyến.

Backend tính thời lượng đường vòng và xếp hạng các phương án theo tổng thời gian ước tính. Hiện chưa có ngưỡng cứng giới hạn khoảng cách trạm tới đường lái xe hoặc số phút đường vòng. Mỗi phương án chỉ xét một điểm dừng, chưa tối ưu chuỗi nhiều trạm cho hành trình dài.

## Nguồn dữ liệu xe và SOC

- **SOC hiện tại:** client gửi `batteryPct`; backend đổi từ phần trăm sang tỷ lệ bằng cách chia 100. Giá trị này không được tự đọc từ xe trong API tìm kiếm.
- **SOC dự trữ:** mức pin tối thiểu dùng làm biên an toàn. Database mode hiện gán giả định 10% (`0.1`); memory mode đọc từ `database/fixtures/demo/vehicles.json`.
- **Dung lượng pin dùng để tính:** `usable_battery_kwh` nếu có, nếu không dùng `battery_capacity_kwh`.
- **Mức tiêu thụ:** đơn vị nội bộ là Wh/km. Database lưu kWh/100 km và đổi bằng cách nhân 10; fixture memory lưu trực tiếp Wh/km.
- **SOC mục tiêu sạc:** hiện mặc định 100% (`1.0`) cho tìm trạm đơn lẻ và tìm trạm trên tuyến. Database mode lấy từ giả định `ASSUMED_TARGET_SOC`; memory mode lấy từ `default_target_soc` trong fixture.

## Công thức

Ký hiệu:

- `SOC_start`, `SOC_arrival`, `SOC_reserve`, `SOC_target`: tỷ lệ từ 0 đến 1.
- `C`: dung lượng pin dùng để tính, kWh.
- `c`: mức tiêu thụ, Wh/km.
- `d`: quãng đường thực tế trên tuyến, km.
- `P`: công suất sạc hữu hiệu, kW.
- `η`: hiệu suất sạc, tỷ lệ từ 0 đến 1.

### Năng lượng tiêu thụ và SOC lúc đến

```text
năng_lượng_tuyến_kWh = d × c ÷ 1.000
SOC_arrival = SOC_start − năng_lượng_tuyến_kWh ÷ C
```

Ví dụ: xe tiêu thụ 150 Wh/km, đi 40 km thì dùng `40 × 150 ÷ 1.000 = 6 kWh`. Với pin tính toán 60 kWh, SOC giảm `6 ÷ 60 = 0,10`, tức 10 điểm phần trăm.

### Quãng đường an toàn còn đi được

```text
range_km = max(0, (SOC_start − SOC_reserve) × C × 1.000 ÷ c)
```

Ví dụ: pin 60 kWh, SOC hiện tại 70%, dự trữ 10%, mức tiêu thụ 150 Wh/km:

```text
(0,70 − 0,10) × 60 × 1.000 ÷ 150 = 240 km
```

Trong tìm trạm quanh một điểm, backend dùng quãng đường này làm bán kính địa lý ban đầu, rồi vẫn định tuyến thực tế tới từng trạm và kiểm tra SOC khi đến.

### SOC cần có để từ trạm tới đích

```text
SOC_required = SOC_reserve + năng_lượng_từ_trạm_đến_đích_kWh ÷ C
```

Nếu `SOC_required > 1`, trạm bị loại vì ngay cả sạc đầy cũng không đủ theo mức tiêu thụ ước tính. Mục tiêu sạc hiện tại là:

```text
SOC_target = max(SOC_required, default_target_soc)
```

Vì mặc định hiện tại là 100%, các trạm được đề xuất nhắm đến `SOC_target = 1.0`.

### Thời gian sạc

```text
SOC_to_add = max(0, SOC_target − SOC_arrival)
energy_to_add_kWh = SOC_to_add × C
charge_min = energy_to_add_kWh ÷ (P × η) × 60
```

Luồng tìm kiếm hiện dùng công suất sạc giả định 80 kW và hiệu suất 90%. Công thức coi công suất không đổi trong suốt phiên sạc, chưa mô hình hóa đường cong sạc chậm dần khi SOC cao.

### Thời gian di chuyển, chờ và tổng thời gian

Goong được ưu tiên để lấy thời lượng tuyến; nếu lỗi, backend thử OSRM. Với tìm trạm quanh điểm, `travel_min` là thời lượng tuyến từ điểm tìm kiếm tới trạm.

Với phương án ghé trạm trên hành trình:

```text
travel_min = thời gian từ điểm đi đến trạm
to_dest_min = max(0, tổng thời gian tuyến qua trạm − travel_min)
total_min = travel_min + wait_min + charge_min + to_dest_min
```

Với tìm trạm quanh một điểm:

```text
total_min = travel_min + wait_min + charge_min
```

Thời gian chờ do `WaitEstimator` ước tính từ trạng thái cổng/trạm và đầu vào hàng đợi. Kết quả được xếp tăng dần theo `total_min`; nếu bằng nhau thì dùng mã trạm để ổn định thứ tự.

## Giới hạn của ước tính hiện tại

- SOC đầu vào đến từ request; kết quả không tự đồng bộ SOC thực tế từ xe.
- Tính năng lượng dùng mức tiêu thụ Wh/km gần như cố định; chưa điều chỉnh theo tốc độ, kẹt xe, địa hình, nhiệt độ, điều hòa hoặc tải xe.
- Công suất sạc 80 kW và hiệu suất 90% là giả định hiện dùng trong luồng tìm kiếm; công thức chưa xét đường cong sạc theo SOC.
- Thời gian đến trạm trên tuyến được tách từ hình học tuyến bằng tỷ lệ khoảng cách dọc polyline; đây là ước tính.
- Bộ dự báo occupancy hiện được cấu hình gateway mặc định; không nên hiểu kết quả thời gian chờ như dự báo ML đã được huấn luyện từ dữ liệu thật.

## Mã nguồn liên quan

- API routes: `backend/app/api_v1.py`
- Request/response models: `backend/app/api_v1_models.py`
- Luồng tìm kiếm và xếp hạng: `backend/app/domain/search.py`
- Lọc ứng viên và định tuyến qua trạm: `backend/app/domain/recommendation.py`
- Goong, OSRM và đo tuyến: `backend/app/domain/routing.py`
- Công thức reachability và sạc: `backend/app/domain/services.py`
- Ánh xạ dữ liệu xe database và giả định: `backend/app/catalog_repository.py`
