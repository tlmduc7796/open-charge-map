# Nhóm Rule-base-AI

Smart EV Journey là lớp điều phối giữa người lái xe điện và mạng lưới trạm sạc hiện có. Thay vì gợi ý trạm gần nhất theo trạng thái lúc tra cứu, hệ thống dự đoán tình trạng trạm tại thời điểm xe tới và xếp hạng theo tổng thời gian phát sinh (di chuyển + chờ + sạc). Không xây thêm trạm, chỉ dùng tốt hơn hạ tầng đang có.

# Tổng hợp các hạng mục

| Hạng mục                        | Mô tả                                                                                                                                                                                                                                                                                                               |
|---------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **A. Chuẩn bị dữ liệu**         | Làm sạch và chuẩn hóa UrbanEV về lưới 5 phút. Bổ sung đặc trưng lịch, thời tiết và mật độ (POI). Thu thập vị trí và cấu hình trạm thật ở Việt Nam. Xây bộ hồ sơ xe điện phổ biến tại Việt Nam. Mô phỏng dữ liệu dựa trên phân phối của UrbanEV và các đặc trưng thật của từng trạm ở Việt Nam.                      |
| **B. ML**                       | XGBoost dự báo occupancy đa mốc thời gian (5 đến 30 phút). Chuỗi Markov với tham số ước lượng theo khung giờ và loại khu vực cho ra phân phối thời gian chờ. Lớp hiệu chỉnh chống dồn tải gồm cam kết mềm có trọng số, tải hiệu chỉnh, phân tán gợi ý và hiệu chỉnh sai số trực tuyến.                                                                       |
| **C. Database**                 | PostgreSQL. Lưu dữ liệu tĩnh: trạm, cổng (chuẩn, công suất), vị trí, hồ sơ xe. Lưu dữ liệu vận hành: số cổng đang dùng theo thời gian, dự báo, hành trình, gợi ý, cam kết mềm, GPS, báo cáo sự cố, sự kiện re-plan.                                                                                                 |
| **D. Backend**                  | FastAPI với các nhóm API: trạm, dự báo, lập hành trình, chọn trạm, GPS ping và re-plan, báo sự cố, WebSocket, điều khiển mô phỏng. Các service: routing, lọc khả thi (chuẩn sạc, tầm với an toàn), tính thời gian sạc, xếp hạng theo tổng thời gian, quản lý cam kết, re-planning.                                  |
| **E. Frontend**                 | React + MapLibre. Bản đồ trạm tô màu theo dự báo (hiện tại và các mốc tương lai), có thanh trượt thời gian. Form hành trình (điểm đi/đến, mẫu xe, % pin). Danh sách xếp hạng có phân rã đi/chờ/sạc, phân phối chờ và lý do gợi ý. Chế độ đang đi có thông báo đổi trạm. Trang chi tiết trạm (lịch sử và dải dự báo) |
| **F. Tích hợp, kiểm thử, demo** | Docker Compose toàn hệ thống. Unit, API, E2E và load test. Kiểm định mô hình (baseline, reliability, stress test, monotonicity). Đánh giá chính sách điều phối bằng mô phỏng. Bốn kịch bản demo có seed cố định và video dự phòng.                                                                                  |

## Các nội dung cần tham khảo ý kiến mentor

Phần này gom các hạng mục nhóm chưa chốt được hướng giải quyết. Mỗi mục gồm bối cảnh, vấn đề cụ thể, hướng nhóm đang cân nhắc và các câu hỏi mong mentor góp ý.

### 1. Mô phỏng dữ liệu trạm Việt Nam (A4)

**Vấn đề** Nhóm không có dữ liệu occupancy lịch sử của trạm sạc ở Việt Nam. Bộ dữ liệu tương tự nhóm tiềm được là UrbanEV (Thâm Quyến, 50 trạm, bước 5 phút).

Cần bộ mô phỏng sinh chuỗi dữ liệu occupancy cho trạm Việt Nam cho việc huấn luyện, đáng giá mô hình và triển khai.

### 2. Chống dồn tải khi nhiều người nhận cùng gợi ý (B2)

**Vấn đề.** Mô hình dự báo học từ dữ liệu lịch sử, khi chưa có hệ thống gợi ý. Khi hệ thống được đưa vào dùng, chính các gợi ý của nó làm thay đổi hành vi người lái. Khi nhiều người cùng tra cứu trong một khu vực, tất cả đều được gợi ý cùng một trạm tốt nhất. Trạm đó bị dồn tải và dự đoán trở thành sai. 

Cần một lớp hiệu chỉnh kết quả dự đoán để tránh dồn tải.


# Chi tiết kế hoạch triển khai

# A. Chuẩn bị dữ liệu

Mục tiêu của chuẩn bị dữ liệu không chỉ là "có dữ liệu để train". Nó còn phải tạo ra ba thứ mà UrbanEV không có: dữ liệu mang bối cảnh Việt Nam, thời gian chờ thực tế để kiểm chứng lớp Markov, và một môi trường để thử chính sách chống dồn tải. Bộ mô phỏng ở A4 vì thế là thành phần trung tâm của cả dự án.

## A1. Khảo sát các bộ dữ liệu tương tự (Đã triển khai)

UrbanEV là dữ liệu sạc công cộng ở Thâm Quyến, giai đoạn 9/2022 đến 2/2023. Theo tài liệu phân tích, bộ nhóm đang dùng có khoảng 2,6 triệu dòng, 50 trạm, bước 5 phút. Các việc cần làm:

- Reindex mỗi trạm về lưới 5 phút đầy đủ để phát hiện mốc bị thiếu. Khoảng trống ngắn ($≤ 15$ phút) thì nội suy tuyến tính. Khoảng trống dài thì đánh dấu missing và không dùng để tạo lag.

- Chuẩn hóa dữ liệu

- Chia train/val/test theo thời gian.

**Đầu ra:** file parquet/csv đã làm sạch.

## A2. Bổ sung đặc trưng (Đã triển khai)

Nguyên tắc quan trọng nhất: mọi đặc trưng phải được tính giống hệt nhau cho trạm Trung Quốc và trạm Việt Nam, và phải có sẵn tại thời điểm dự báo. Nếu không, mô hình sẽ không chuyển giao được.

| Nhóm         | Đặc trưng và cách lấy                                                                                                                                                                                                                                                                 |
|--------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Lịch         | hour_sin/cos, thứ trong tuần, cuối tuần, ngày lễ.                                                                                                                                                                                                                                     |
| Thời tiết    | Nhiệt độ, lượng mưa, độ ẩm, cờ mưa lớn. UrbanEV đã có thời tiết thì forward-fill từ bước giờ xuống 5 phút. Với Việt Nam, lấy từ Open-Meteo (có cả historical và forecast, miễn phí). Lúc suy luận phải dùng thời tiết dự báo tại t_đến.                                               |
| Mật độ       | Số POI trong bán kính 500 m và 1 km theo nhóm (trung tâm thương mại, văn phòng, dân cư, nhà hàng, bệnh viện, bãi đỗ xe) từ OpenStreetMap qua Overpass/OSMnx. Số trạm sạc khác trong 2 km (mức cạnh tranh). Khoảng cách tới trục chính hoặc cao tốc. Mật độ dân số từ raster WorldPop. |
| Loại khu vực | Nội đô, ngoại ô, ven cao tốc, suy ra từ các đặc trưng mật độ.                                                                                                                                                                                                                         |

## A3. Dữ liệu tĩnh cho Việt Nam (Đã triển khai)

### Trạm sạc

- Chọn phạm vi MVP, TP.HCM

- Lấy vị trí từ OpenStreetMap (amenity=charging_station, các tag socket:\*, capacity, operator), OpenChargeMap API, và bản đồ trạm công khai của các hãng.

- Chuẩn hóa mỗi trạm về: id, tên, tọa độ, nhà vận hành, danh sách cổng (chuẩn CCS2/Type 2/..., công suất kW). Trạm thiếu số cổng thì suy theo nhà vận hành và loại trạm.

### Hồ sơ xe

Lập bảng hồ sơ cho các mẫu phổ biến (VinFast VF 3 đến VF 9, BYD...). Các trường cần có: dung lượng pin khả dụng, mức tiêu hao kWh/km, công suất AC và DC tối đa, chuẩn cổng. Số liệu lấy từ thông số chính thức của hãng và ghi nguồn.

## A4. Mô phỏng dữ liệu trạm Việt Nam (Đang nghiên cứu)

# B. ML

Phần ML gồm ba bài toán nối tiếp nhau: B1 dự đoán occupancy của trạm tại các mốc tương lai, B2 suy ra phân phối thời gian chờ khi xe tới trạm, B3 hiệu chỉnh kết quả để tránh dồn tải khi nhiều người nhận cùng một gợi ý.

## B1. Dự đoán occupancy

**Mục tiêu:** tại thời điểm tra cứu $t_0$, dự đoán occupancy $o_s(t_0 + h)$ của mọi trạm với $h ∈ H = \{5, 10, 15, 20, 25, 30\}$ phút. Kết quả dùng để tô màu trạm theo các mốc tương lai trên bản đồ (E1) và ghi vào bảng `predictions` (B2) dưới dạng số cổng trống $c_s (1 − ô_s)$.

### Baseline 1 – Persistence (Đã triển khai)

**Dự đoán:** $$ô_s(t_0 + h) = o_s(t_0) \text{ với mọi } h ∈ H$$

Đây là mốc so sánh tối thiểu: mô hình nào không thắng Persistence thì không được đưa vào dùng.

### Baseline 2 – XGBoost (Đang triển khai)


Bài toán hồi quy. Mỗi mẫu là một cặp (trạm $s$, thời điểm $t_0$):

- **Đầu vào:** vector đặc trưng $x_s(t_0, h)$, chỉ dùng thông tin đã có tại $t_0$, cộng với thông tin biết trước về thời điểm đích $t_0 + h$ (lịch, thời tiết dự báo).
- **Nhãn:** $y_h = o_s(t_0 + h) ∈ [0, 1]$.


Mỗi mốc $h$ có một mô hình riêng $f_h$, tổng cộng 6 mô hình: $ô_s(t_0 + h) = f_h(x_s(t_0, h))$.


| Nhóm                       | Đặc trưng                                                                                                                                             | Ghi chú                                                                                          |
|----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| Lịch sử occupancy          | $o_s(t_0 − 5k)$ với $k = 0, 1, …, 11$ (1 giờ gần nhất)                                                                                                | Nhóm quan trọng nhất cho mốc gần                                                                  |
| Xu hướng                   | $o_s(t_0) − o_s(t_0 − 15)$ và $o_s(t_0) − o_s(t_0 − 30)$                                                                                              | Trạm đang đầy lên hay vơi đi                                                                      |
| Biến động                  | Trung bình và độ lệch chuẩn trong cửa sổ 30 và 60 phút; số phút liên tục ở trạng thái đầy tính đến $t_0$                                              | Trạm đầy lâu thường sắp có xe rời đi                                                              |
| Mùa vụ                     | $o_s(t_0 + h − 7 \text{ ngày})$; trung bình occupancy cùng khung giờ × thứ trong các tuần trước (tối đa 4 tuần)                                       | Lấy tại thời điểm đích của các tuần trước, vẫn là quá khứ nên không rò rỉ. Nhóm quan trọng cho mốc xa |
| Lịch tại $t_0 + h$         | $\sin(2π \cdot \text{giờ}/24)$, $\cos(2π \cdot \text{giờ}/24)$, thứ trong tuần, cuối tuần, ngày lễ                                                                  | Tính tại thời điểm đích, không phải tại $t_0$                                                     |
| Thời tiết tại $t_0 + h$    | Nhiệt độ, lượng mưa, loại thời tiết                                                                                                                   | Lúc train dùng giá trị quan sát, lúc suy luận dùng giá trị dự báo (Open-Meteo)                    |
| Đặc trưng tĩnh của trạm    | Số cổng $c_s$, công suất tối đa, số POI theo nhóm, số trạm cạnh tranh trong 2 km, loại khu vực                                                        | Giúp mô hình chung phân biệt các trạm với nhau                                                    |


Một pipeline đặc trưng duy nhất cho cả train và suy luận (cùng code, cùng thứ tự cột), để tránh lệch giữa hai môi trường.


### Baseline 3 – Học sâu: LSTM, Transformer (Đang nghiên cứu)

## B2. Dự đoán thời gian chờ

**Mục tiêu:** với trạm $s$ và thời điểm tới $t_{đến}$, đưa ra phân phối của thời gian chờ $W$, không chỉ một con số. Từ phân phối này lấy ra xác suất phải chờ $P(W > 0)$, thời gian chờ kỳ vọng $E[W]$ và phân vị $W_{90}$ để xếp hạng trạm và hiển thị dải chờ.

### Baseline 1 – Chuỗi Markov, tham số ước lượng bằng trung bình theo thời gian và địa điểm (Đang nghiên cứu)

### Baseline 2 – LSTM ước lượng tham số Markov (Đang nghiên cứu)

## B3. Hiệu chỉnh kết quả để tránh dồn tải (Đang nghiên cứu)

# C. Database (Đang triển khai)

## C1. Kiến trúc lưu trữ

- **PostgreSQL** **+ PostGIS** cho truy vấn không gian: tìm trạm trong bán kính bằng ST_DWithin trên kiểu geography với index GIST, tìm trạm dọc hành lang tuyến đường.

- **TimescaleDB** (hoặc bảng phân vùng theo thời gian) cho chuỗi occupancy.

- **Redis** cho dữ liệu nóng cần đọc hoặc ghi dưới mili giây.

## C2. Các bảng chính

Dùng PostgreSQL + PostGIS (toạ độ, tìm theo khung bản đồ, đường đi) và Redis (trạng thái nóng, dự đoán mới nhất, pub/sub cho WebSocket). 11 bảng chia 4 nhóm; khóa chính UUID trừ khi ghi khác.

### Nhóm 1 – Trạm và cổng (dữ liệu tĩnh)

`stations` — trạm sạc

| Cột           | Kiểu                   | Ghi chú                                          |
|---------------|------------------------|--------------------------------------------------|
| id            | uuid PK                |                                                  |
| external_id   | text UNIQUE            | Mã trạm bên hệ thống nhà vận hành                |
| name          | text                   |                                                  |
| address       | text                   |                                                  |
| location      | geography(Point, 4326) | Index GIST để lọc theo bbox và bán kính          |
| opening_hours | jsonb                  | Ví dụ {"mon":\["06:00","22:00"\],…}, null = 24/7 |
| is_active     | boolean                | Trạm ngừng hoạt động thì ẩn khỏi bản đồ          |
| updated_at    | timestamptz            | Dùng cho version dữ liệu tĩnh                    |

`connector_types` — danh mục loại cổng

| Cột          | Kiểu    | Ghi chú                    |
|--------------|---------|----------------------------|
| code         | text PK | Ví dụ CCS2, TYPE2, CHADEMO |
| name         | text    | Tên hiển thị               |
| current_type | text    | AC / DC                    |

`ports` — từng cổng sạc vật lý

| Cột            | Kiểu                      | Ghi chú                          |
|----------------|---------------------------|----------------------------------|
| id             | uuid PK                   |                                  |
| station_id     | uuid FK → stations        | Index                            |
| connector_code | text FK → connector_types |                                  |
| max_power_kw   | numeric                   | Công suất tối đa                 |
| label          | text                      | Số hiệu cổng tại trạm ("Cổng 3") |

### Nhóm 2 – Trạng thái và dự đoán (thay đổi liên tục)

`port_status` — trạng thái hiện tại, 1 dòng/cổng (bản sao trong Redis để đọc nhanh)

| Cột                | Kiểu                | Ghi chú                                        |
|--------------------|---------------------|------------------------------------------------|
| port_id            | uuid PK, FK → ports |                                                |
| status             | enum                | available, charging, out_of_service, unknown   |
| session_started_at | timestamptz         | Khi charging                                   |
| est_finish_at      | timestamptz         | Khi charging; dùng để hiện "còn X phút" ở E5   |
| reported_at        | timestamptz         | Thời điểm nguồn báo; quá cũ thì coi là unknown |

`port_status_history` — lịch sử để huấn luyện mô hình (bảng lớn, partition theo tháng)

| Cột        | Kiểu        | Ghi chú                     |
|------------|-------------|-----------------------------|
| port_id    | uuid FK     |                             |
| status     | enum        |                             |
| changed_at | timestamptz | Index (port_id, changed_at) |

`predictions` — số cổng trống dự đoán

| Cột             | Kiểu        | Ghi chú                                              |
|-----------------|-------------|------------------------------------------------------|
| station_id      | uuid FK     | PK gồm 4 cột đầu                                     |
| connector_code  | text FK     | Dự đoán theo loại cổng                               |
| run_at          | timestamptz | Lần chạy mô hình                                     |
| offset_min      | smallint    | 5, 10, …, 30                                         |
| available_ports | numeric     | Số cổng trống dự đoán (có thể lẻ, frontend làm tròn) |
| wait_min        | numeric     | Thời gian chờ ước tính nếu đến lúc T+offset          |
| model_version   | text        |                                                      |

Chỉ lượt chạy mới nhất được đọc; các lượt cũ giữ lại để so với thực tế rồi xóa theo hạn (ví dụ 90 ngày).

### Nhóm 3 – Xe

`vehicle_models` — hồ sơ mẫu xe

| Cột                       | Kiểu    | Ghi chú                           |
|---------------------------|---------|-----------------------------------|
| id                        | uuid PK |                                   |
| brand, model, variant     | text    | Ví dụ VinFast / VF 8 / Plus       |
| battery_kwh               | numeric | Dung lượng pin khả dụng           |
| consumption_kwh_per_100km | numeric | Mức tiêu thụ trung bình           |
| max_ac_kw, max_dc_kw      | numeric | Công suất sạc tối đa xe nhận được |
| is_active                 | boolean |                                   |

`vehicle_connectors` — loại cổng xe tương thích (nhiều–nhiều): vehicle_model_id FK + connector_code FK, PK hai cột.

### Nhóm 4 – Hành trình và cấu hình

`trips` — ẩn danh, không gắn người dùng

| Cột                  | Kiểu                  | Ghi chú                                                     |
|----------------------|-----------------------|-------------------------------------------------------------|
| id                   | uuid PK               | tripId trả cho frontend                                     |
| mode                 | enum                  | find_station, route                                         |
| vehicle_model_id     | uuid FK               |                                                             |
| origin, destination  | geography(Point)      | destination null khi find_station                           |
| start_battery_pct    | numeric               | Pin người dùng nhập                                         |
| station_id           | uuid FK, nullable     | Trạm đang đi tới; null nếu đủ pin                           |
| route                | geography(LineString) | Tuyến hiện tại                                              |
| route_version        | int                   | Tăng mỗi lần đổi tuyến                                      |
| phase                | enum                  | to_station, at_station, to_destination, arrived, cancelled  |
| planned              | jsonb                 | Thời gian dự kiến từng đoạn lúc bắt đầu (để so với thực tế) |
| last_reroute_at      | timestamptz           | Chống đổi tuyến liên tục                                    |
| declined_station_ids | uuid\[\]              | Trạm người dùng đã từ chối, không hỏi lại                   |
| created_at, ended_at | timestamptz           |                                                             |

`trip_positions` — vị trí gửi lên: trip_id FK, recorded_at, location geography(Point), speed_kmh, heading, battery_pct (ước tính), distance_km (cộng dồn). Index (trip_id, recorded_at).

`trip_events` — nhật ký sự kiện: trip_id FK, type (reroute, station_suggested, station_accepted, station_declined, battery_corrected, arrived_station, arrived, cancelled), payload jsonb, created_at.

`app_config` — key/value: key text PK, value jsonb, updated_at. Chứa ngưỡng màu, ngưỡng reroute, bán kính gần trạm / đến nơi, chu kỳ gửi vị trí, thời gian chống đổi tuyến.

### Quan hệ chính

stations 1–n ports;

ports 1–1 port_status, 1–n port_status_history;

stations × connector_types 1–n predictions;

vehicle_models n–n connector_types;

trips 1–n trip_positions, 1–n trip_events;

trips n–1 stations, n–1 vehicle_models.

# D. Backend (Đang triển khai)

## D1. Mô tả API

API công khai gồm 12 endpoint REST (/api/v1) và 1 kênh WebSocket, không cần đăng nhập; API nội bộ cho nguồn dữ liệu trạm và mô hình dự đoán dùng API key. Quy ước: thời gian là phút (số nguyên), mốc thời gian ISO 8601, toạ độ {lat, lng}, tuyến là encoded polyline, mọi response có updatedAt. Chống lạm dụng bằng giới hạn tần suất theo IP và theo tripId.

**Trường trạm dùng chung** (gọi là StationSummary): id, name, address, location, color (green / yellow / red / grey), availablePorts, totalPorts, connectors (danh sách code).

### Khởi động và danh mục

| Endpoint              | Request                       | Response                                                                                                                                                            | Ghi chú                                |
|-----------------------|-------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| GET /config           | —                             | rerouteDeviationM, rerouteEtaDeltaMin, nearStationRadiusM, arrivalRadiusM, positionIntervalSec, rerouteCooldownSec, lowBatteryPct, stationsVersion, vehiclesVersion | Đọc từ app_config; cache 5 phút        |
| GET /vehicles         | —                             | \[{id, brand, model, variant, batteryKwh, consumptionKwhPer100km, connectors\[\]}\]                                                                                 | Cache theo vehiclesVersion             |
| GET /geocode?q=&near= | Chuỗi địa chỉ, toạ độ ưu tiên | \[{label, location}\]                                                                                                                                               | Proxy tới dịch vụ bản đồ, giấu API key |

### Trạm

| Endpoint                                            | Request                                                        | Response                                                                                                                                                           | Ghi chú                                                                         |
|-----------------------------------------------------|----------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| GET /stations?bbox=                                 | bbox=minLng,minLat,maxLng,maxLat                               | \[{id, name, address, location, openingHours, ports:\[{id, label, connector, maxPowerKw}\]}\]                                                                      | Dữ liệu tĩnh; frontend cache theo stationsVersion                               |
| GET /stations/availability?bbox=&offset=&vehicleId= | $offset ∈ \{0,5,…,30\}$; vehicleId tuỳ chọn để chỉ đếm cổng hợp xe | {offset, isPrediction, items:\[{stationId, color, availablePorts, totalPorts}\]}                                                                                   | offset=0 đọc Redis; \>0 đọc lượt dự đoán mới nhất; trạm không có dự đoán → grey |
| GET /stations/{id}                                  | —                                                              | StationSummary + openingHours + byConnector:\[{code, maxPowerKw, now:{color, available, charging, outOfService, total}, forecast:\[{offset, color, available}\]}\] | Nguồn cho E6                                                                    |
| GET /stations/{id}/ports                            | —                                                              | \[{id, label, connector, status, minutesToFinish}\]                                                                                                                | Nguồn cho thẻ gần trạm ở E5                                                     |

### Tìm kiếm

#### `POST /search/stations`

- Request: {origin:{lat,lng}, vehicleId, batteryPct, limit?} (mặc định limit = 10).

- Response: {searchId, reachableKm, stations:\[{rank, station: StationSummary, route, distanceKm, travelMin, waitMin, chargeMin, totalMin, arriveBatteryPct}\]}, xếp theo totalMin tăng dần.

- Lỗi: OUT_OF_RANGE nếu không trạm nào trong tầm pin (kèm trạm gần nhất để hiện fallback).

#### `POST /search/route`

- Request: {origin, destination, vehicleId, batteryPct}.

- Response: {searchId, case, directRoute, directMin, stations:\[… như trên + toDestMin\]}.

- case = enough: chỉ có directRoute, directMin, stations rỗng. needCharge: stations xếp theo travelMin + waitMin + chargeMin + toDestMin, mỗi phương án có route đủ hai chặng. fallback: nearestStation + missingKm để hiện cảnh báo đỏ.

- Lỗi: NO_ROUTE nếu không có đường giữa hai điểm.

searchId giữ kết quả trong Redis 10 phút để POST /trips dùng lại, không tính lại.

### Dẫn đường

| Endpoint                  | Request                                                                                                  | Response                                                                                                                           | Ghi chú                                                                                         |
|---------------------------|----------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| POST /trips               | {searchId, stationId?} (hoặc đủ tham số tìm nếu searchId hết hạn)                                        | {tripId, route, routeVersion, steps\[\], etas, phase}                                                                              | stationId null khi đủ pin                                                                       |
| POST /trips/{id}/position | {lat, lng, heading, speed, timestamp, routeVersion, batteryPct?}                                         | {etas:{toStation, wait, charge, toDest}, batteryPct, phase, rerouteNeeded, route?, routeVersion, stationSuggestion?, nearStation?} | batteryPct chỉ gửi khi người dùng sửa tay; nearStation = dữ liệu cổng khi vào bán kính gần trạm |
| PATCH /trips/{id}         | Một trong: {acceptStationId}, {declineStationId}, {batteryPct} (sửa tay / sau sạc), {status:"cancelled"} | Trip đầy đủ như POST /trips                                                                                                        | Ghi trip_events                                                                                 |

arrived do backend tự đặt khi vị trí vào bán kính đến nơi; response position trả phase = arrived để frontend dừng chỉ đường.

### WebSocket /ws

| Hướng           | Thông điệp           | Nội dung                                                                                         |
|-----------------|----------------------|--------------------------------------------------------------------------------------------------|
| Client → server | subscribe            | {bbox} (E1), {stationId} (E5, E6) hoặc {tripId} (E5)                                             |
| Client → server | unsubscribe          | Cùng dạng                                                                                        |
| Server → client | station.updated      | {stationId, color, availablePorts, byConnector?, ports?} — ports chỉ gửi cho kênh theo stationId |
| Server → client | prediction.refreshed | {runAt} — frontend tải lại availability nếu đang xem mốc T+k                                     |
| Server → client | trip.reroute         | Cùng dạng response position (có route hoặc stationSuggestion)                                    |

**Mã lỗi** ({code, message} + HTTP status): VALIDATION_ERROR 400, STATION_NOT_FOUND 404, TRIP_NOT_FOUND 404, NO_ROUTE 422, OUT_OF_RANGE 422, PREDICTION_UNAVAILABLE 503, RATE_LIMITED 429.

### API nội bộ (API key, không mở cho app)

| Endpoint                                       | Dùng cho                                       | Ghi chú                                                             |
|------------------------------------------------|------------------------------------------------|---------------------------------------------------------------------|
| POST /internal/port-status                     | Nguồn dữ liệu trạm đẩy trạng thái cổng (batch) | Ghi port_status + port_status_history + Redis, phát station.updated |
| POST /internal/predictions                     | Job mô hình ghi kết quả một lượt chạy          | Ghi predictions, cập nhật Redis, phát prediction.refreshed          |
| PUT /internal/stations, PUT /internal/vehicles | Đồng bộ dữ liệu tĩnh                           | Tăng stationsVersion / vehiclesVersion                              |
| PUT /internal/config/{key}                     | Chỉnh ngưỡng                                   | Không cần phát hành lại app                                         |

Nếu nguồn dữ liệu trạm không đẩy được, thay POST /internal/port-status bằng một job kéo dữ liệu định kỳ (ví dụ mỗi 30 giây).

## D2. Logic xử lý chính

### Tính màu trạm

từ số cổng trống (thật hoặc dự đoán) và ngưỡng trong app_config: red khi bằng 0, yellow khi dưới ngưỡng cao, green khi đạt ngưỡng cao, grey khi dữ liệu quá cũ hoặc không có dự đoán. Khi có vehicleId, chỉ đếm cổng hợp xe. Màu được tính lúc ghi (khi nhận trạng thái hoặc dự đoán mới) và lưu sẵn trong Redis, nên đọc availability không phải tính lại.

### Xếp hạng trạm (/search/stations, /search/route)

1.  Tính tầm đi còn lại: $reachableKm = batteryPct / 100 × battery\_kwh / consumption × 100$, trừ biên an toàn (ví dụ 10%).

2.  Lọc ứng viên bằng PostGIS: trạm đang mở, có cổng hợp xe, trong reachableKm theo đường chim bay; với tìm đường thì thêm điều kiện nằm trong hành lang quanh tuyến trực tiếp.

3.  Gọi routing engine (OSRM / GraphHopper / dịch vụ bản đồ) lấy travelMin thật, loại trạm vượt tầm pin.

4.  waitMin = dự đoán tại mốc gần nhất với thời điểm đến (T + travelMin, làm tròn về bước 5 phút, tối đa T+30).

5.  chargeMin = năng lượng cần nạp ÷ công suất hiệu dụng (nhỏ hơn giữa cổng và xe). Năng lượng cần nạp: tìm đường = đủ đến đích + biên an toàn; tìm trạm = sạc đến mức mặc định (ví dụ 80%).

6.  toDestMin từ routing engine (chỉ tìm đường); xếp theo totalMin, trả top limit.

### Phân loại tìm đường

enough nếu reachableKm ≥ quãng đường trực tiếp; needCharge nếu bước 3 còn ít nhất một trạm; ngược lại fallback.

### Ước tính pin khi đang đi

mỗi lần nhận vị trí, cộng quãng đường từ điểm trước vào distance_km; batteryPct = pin mốc − distance_since_mark × consumption / battery_kwh × 100. "Pin mốc" là pin nhập ban đầu, hoặc lần sửa tay / sau sạc gần nhất (ghi battery_corrected). Pin ước tính xuống dưới mức cần để đến trạm → kích hoạt đề xuất đổi trạm.

### Xử lý POST /trips/{id}/position

1.  Bỏ qua nếu timestamp cũ hơn lần gần nhất; ghi trip_positions.

2.  Khoảng cách tới trạm \< nearStationRadiusM → phase = at_station, kèm nearStation; tới đích \< arrivalRadiusM → phase = arrived, đóng trip.

3.  Tính ETA từng đoạn. Kiểm tra điều kiện đổi đường (lệch tuyến, ETA đổi nhiều, trạm hết cổng, pin không đủ) nhưng chỉ khi đã qua rerouteCooldownSec từ last_reroute_at.

4.  Cùng trạm → tính tuyến mới, tăng route_version. Đổi trạm → chạy lại xếp hạng từ vị trí hiện tại, bỏ trạm trong declined_station_ids, trả stationSuggestion.

### Job nền

| Job                        | Chu kỳ                                        | Việc làm                                                                   |
|----------------------------|-----------------------------------------------|----------------------------------------------------------------------------|
| Chạy mô hình dự đoán       | 5 phút                                        | Dự đoán T+5…T+30 cho mọi trạm × loại cổng, gọi POST /internal/predictions  |
| Theo dõi trạm bị ảnh hưởng | Khi có station.updated / prediction.refreshed | Tìm trip đang đi tới trạm chuyển sang đỏ, tính đề xuất và đẩy trip.reroute |
| Đánh dấu dữ liệu cũ        | 1 phút                                        | port_status quá hạn → unknown, trạm → grey                                 |
| Đóng trip bỏ dở            | 15 phút                                       | Trip không gửi vị trí quá 2 giờ → cancelled                                |

# E. Frontend (Đang triển khai)

Frontend gồm 6 màn hình (E1–E6) xoay quanh một bản đồ trạm sạc có dự đoán 30 phút tới, cùng phần kiến trúc module (E7) và dữ liệu lưu trên thiết bị (E8).

## Tổng quan

Người dùng bắt đầu ở bản đồ chính (E1), chọn **Tìm trạm** (E2) hoặc **Tìm đường** (E3), xem kết quả xếp hạng (E4), bấm **Bắt đầu đi** để vào chế độ dẫn đường (E5). Từ bất kỳ marker nào trên bản đồ hoặc trong bảng xếp hạng đều mở được chi tiết trạm (E6).

1.  E1 Màn hình chính → bấm **Tìm kiếm (mặc định và tìm trạm)**

2.  E2 hoặc E3 → điền form, bấm nút tìm

3.  E4 Kết quả → chọn phương án, bấm **Bắt đầu đi** (hoặc **Tắt** để quay về E1)

4.  E5 Đang đi → đến điểm đến thì tự dừng chỉ đường

5.  E6 Chi tiết trạm → mở từ E1, E4 hoặc E5, đóng để quay lại màn hình trước

## E1. Màn hình chính

E1 là một bản đồ toàn màn hình hiển thị mọi trạm sạc bằng marker đổi màu theo thời điểm được chọn trên thanh thời gian.

### Bản đồ và marker

- Mỗi trạm là một marker tô màu xanh / vàng / đỏ theo quy ước ở phần Tổng quan.

- Vị trí hiện tại của người dùng hiển thị bằng chấm riêng; nút "về vị trí của tôi" căn lại bản đồ.

- Khi zoom xa, các marker gần nhau được gộp thành cụm; cụm mang màu tốt nhất trong nhóm (có ít nhất một trạm xanh thì cụm màu xanh) và ghi số trạm còn chỗ.

### Thanh dịch chuyển thời gian

Thanh đặt dưới đáy bản đồ, gồm 7 mốc rời rạc: **T, T+5, T+10, T+15, T+20, T+25, T+30** (phút), với T là thời điểm hiện tại. Mốc đang chọn hiển thị kèm giờ tuyệt đối (ví dụ 14:35). Người dùng kéo hoặc bấm từng mốc; khi đổi mốc, màu marker đổi ngay với hiệu ứng chuyển màu mượt.

### Logic hiện màu (chưa chốt)

Khi đang xem mốc dự đoán (T+k), giao diện hiện nhãn "Dự đoán" ở thanh thời gian để phân biệt với dữ liệu thực; trạm chưa có dự đoán hiển thị marker xám.

### Tương tác

- Bấm vào marker → mở thẻ thông tin chi tiết trạm (tên, địa chỉ, khoảng cách, số cổng trống tại mốc đang xem, giờ mở cửa) và nút "Xem chi tiết" để sang E6.

- Hai nút nổi trên bản đồ: **Tìm trạm** (mở E2) và **Tìm đường** (mở E3).

## E2–E3. Form tìm kiếm (2 tab)

E2 và E3 gộp thành một form duy nhất dạng bảng trượt (bottom sheet) trên bản đồ, có hai tab ở đầu: **Tìm trạm** (E2) và **Tìm đường** (E3). Nút Tìm trạm / Tìm đường ở E1 mở cùng form này và chọn sẵn tab tương ứng. Người dùng đổi tab mà không mất dữ liệu đã nhập ở các trường chung.

### Các trường

| Trường        | Kiểu nhập                                        | Hiện ở tab    | Ghi chú                                                        |
|---------------|--------------------------------------------------|---------------|----------------------------------------------------------------|
| Điểm đi       | Ô tìm địa chỉ (gợi ý tự động) + chọn trên bản đồ | Cả hai        | Mặc định là vị trí hiện tại; có nút đặt lại về vị trí hiện tại |
| Điểm đến      | Ô tìm địa chỉ + chọn trên bản đồ                 | Chỉ Tìm đường | Có nút đảo chiều điểm đi ↔ điểm đến                            |
| Mẫu xe        | Danh sách thả xuống có tìm kiếm                  | Cả hai        | Quy định loại cổng tương thích và mức tiêu thụ điện            |
| Lượng pin còn | Thanh trượt 0–100% + ô nhập số                   | Cả hai        | Hiện thêm quãng đường ước tính còn đi được                     |
| Nút hành động | Nút chính                                        | Cả hai        | Tab Tìm trạm: **Tìm trạm**; tab Tìm đường: **Tìm đường đi**    |

Nút hành động bị vô hiệu hóa khi thiếu trường bắt buộc của tab đang mở (điểm đi, mẫu xe; thêm điểm đến ở tab Tìm đường). Kiểm tra tại chỗ: pin trong 0–100%, điểm đi khác điểm đến. Nếu không lấy được vị trí, form báo lỗi gần ô Điểm đi và yêu cầu nhập tay.

### Tab Tìm trạm (E2)

Bấm nút, giao diện hiện trạng thái đang tải rồi chuyển sang E4 chỉ hiển thị trạm, không có điểm đến.

### Tab Tìm đường (E3)

Sau khi bấm nút, kết quả được quyết định bởi việc pin hiện tại có đủ đi hết quãng đường hay không:

| Trường hợp                        | Điều kiện                                                             | Giao diện hiển thị                                                                             |
|-----------------------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| Đủ điện                           | Pin đủ đến điểm đến                                                   | Chỉ hiển thị tuyến đường và thời gian di chuyển; không đề xuất trạm sạc                        |
| Không đủ điện, có trạm cứu được   | Pin không đủ đến đích nhưng đủ đến ít nhất một trạm trên/gần lộ trình | Gợi ý danh sách trạm xếp hạng theo tổng thời gian (E4)                                         |
| Không đủ điện đến bất kỳ trạm nào | Pin không đủ đến cả trạm gần nhất                                     | Fallback: cảnh báo màu đỏ, hiển thị trạm gần nhất kèm khuyến nghị gọi cứu hộ hoặc sạc dự phòng |

## E4. Kết quả

E4 chia đôi màn hình: bản đồ phía trên hiển thị tuyến đường, bảng xếp hạng trạm phía phải (bảng trượt lên được). Chọn một dòng trong bảng thì bản đồ cập nhật tuyến tương ứng.

### Trên bản đồ

- Vẽ tuyến đường: đoạn từ điểm đi đến trạm và đoạn từ trạm đến điểm đến tô hai màu khác nhau.

- Nhãn thời gian gắn trên tuyến: thời gian di chuyển đến trạm, thời gian chờ ước tính (tại trạm), thời gian sạc, thời gian từ trạm đến đích.

- Trạm được chọn có hiệu ứng nổi bật: marker phóng to, có vầng sáng nhấp nháy (pulse) và nhãn "Đã chọn"; các trạm khác mờ đi.

- Hành trình đủ pin, không qua trạm nào: không có trạm được chọn, không có hiệu ứng, chỉ hiện tuyến và tổng thời gian.

### Bảng xếp hạng trạm

Xếp theo tổng thời gian tăng dần (đi đến trạm + chờ + sạc + đi từ trạm đến đích). Mỗi dòng gồm:

| Thành phần        | Nội dung                                                                                      |
|-------------------|-----------------------------------------------------------------------------------------------|
| Thứ hạng          | Số thứ tự, dòng đầu được đánh dấu "Nhanh nhất"                                                |
| Thông tin cơ bản  | Tên trạm, khoảng cách, chấm màu trạng thái, số cổng trống, loại cổng phù hợp                  |
| Tổng thời gian    | Con số nổi bật (phút)                                                                         |
| Biểu đồ thời gian | Thanh ngang xếp chồng theo thứ tự: di chuyển đến trạm → chờ ước tính → sạc → từ trạm đến đích |

Mỗi đoạn của biểu đồ có màu riêng, kèm chú giải và số phút khi di chuột/chạm vào. Chiều dài thanh tỉ lệ với cùng một thang đo để so sánh được giữa các trạm.

### Khác biệt giữa hai luồng

- Từ E3 (tìm đường): biểu đồ có đủ 4 đoạn, hiển thị tổng thời gian đến đích.

- Từ E2 (tìm trạm): biểu đồ chỉ có 3 đoạn (di chuyển đến trạm, chờ, sạc), không có thời gian từ trạm đến điểm đến; xếp hạng theo thời gian đến trạm + chờ + sạc.

### Nút hành động

**Bắt đầu đi** (vào E5 với trạm đang chọn) và **Tắt** (đóng kết quả, xoá tuyến khỏi bản đồ, quay về E1). Bấm tên trạm trong bảng để mở E6.

## E5. Màn hình đang di chuyển

E5 hoạt động như chế độ dẫn đường của Google Maps: bản đồ bám theo người dùng và tự cập nhật theo thời gian thực, chia thành ba giai đoạn.

### Giai đoạn 1 – Đang đi đến trạm sạc

- Hiển thị vị trí người dùng dạng mũi tên xoay theo hướng di chuyển, bản đồ tự căn giữa và xoay theo hướng đi; người dùng kéo bản đồ thì tạm dừng bám theo và hiện nút "Căn lại".

- Thanh thông tin trên cùng cập nhật liên tục: thời gian còn lại đến trạm, thời gian chờ ước tính, thời gian sạc, thời gian từ trạm đến đích, giờ đến dự kiến.

- Hướng dẫn rẽ (mũi tên + khoảng cách) hiển thị ở đầu màn hình.

### Tự tính lại lộ trình

Giao diện gửi vị trí định kỳ và cập nhật lại lộ trình khi vượt một trong các ngưỡng cấu hình được:

| Ngưỡng kích hoạt           | Ví dụ đề xuất                   |
|----------------------------|---------------------------------|
| Lệch khỏi tuyến đường      | \> D m trong t giây             |
| Thời gian dự kiến thay đổi | \> t phút so với lần tính trước |

Nếu trạm đổi thì hỏi xác nhận trước khi chuyển hướng. Đây là các ngưỡng đề xuất, cần bạn chốt giá trị.

### Giai đoạn 2 – Gần trạm sạc

Khi người dùng vào bán kính gần trạm (ví dụ 20m), một thẻ trạng thái trạm hiện lên phía dưới:

- Danh sách từng cổng: cổng trống (xanh), cổng đang sạc (cam, kèm số phút còn lại đến khi xong), cổng hỏng/bảo trì (xám).

- Thời gian hiển thị lúc này **chỉ còn thời gian từ trạm sạc đến điểm đến**; các mục thời gian di chuyển đến trạm và chờ được ẩn.

### Giai đoạn 3 – Đến điểm đến

Khi khoảng cách đến đích nhỏ hơn ngưỡng đến nơi (ví dụ 20 m), giao diện hiện thông báo "Bạn đã đến nơi", **ngừng chỉ đường** (dừng theo dõi vị trí liên tục và xoá tuyến), rồi quay về E1. Trong suốt quá trình, nút **Tắt** cho phép kết thúc sớm.

### Trường hợp ngoại lệ

Mất tín hiệu GPS hoặc mất mạng: giữ tuyến cuối cùng, hiện biểu tượng cảnh báo và thử kết nối lại tự động.

## E6. Chi tiết trạm

E6 cho thấy tình trạng trạm theo từng loại cổng sạc, gồm số liệu hiện tại và dự đoán cho các mốc tiếp theo. Mở từ E1 (thẻ trạm), E4 (bảng xếp hạng) hoặc E5.

### Phần đầu trang

Tên trạm, địa chỉ, khoảng cách từ vị trí người dùng, giờ mở cửa, chấm màu tổng quan của trạm và hai nút: **Chỉ đường đến đây** và **Đóng**.

**Mỗi loại cổng là một khối riêng** (ví dụ sạc nhanh DC, sạc thường AC; danh sách thật lấy từ dữ liệu trạm). Khối gồm:

| Thành phần          | Nội dung                                                                                       |
|---------------------|------------------------------------------------------------------------------------------------|
| Tiêu đề khối        | Tên loại cổng, công suất tối đa, nhãn "Phù hợp xe của bạn" nếu đúng mẫu xe đã nhập             |
| Trạng thái hiện tại | Chấm màu xanh/vàng/đỏ theo quy ước chung                                                       |
| Số cổng             | "Còn X / Tổng Y cổng trống", kèm số cổng đang sạc và số cổng hỏng                              |
| Dự đoán             | Dãy 6 ô tương ứng T+5, T+10, T+15, T+20, T+25, T+30; mỗi ô tô màu và ghi số cổng trống dự đoán |

Dãy dự đoán đặt ngay cạnh giá trị hiện tại (mốc T) để người dùng thấy xu hướng từ T đến T+30 trên một hàng; có thể chuyển sang dạng biểu đồ đường để xem số cổng trống thay đổi theo thời gian. Khi chọn một ô dự đoán, mốc đó được đánh dấu, ghi chú "Ước lượng từ mô hình, có thể sai lệch".

### Đồng bộ với E1

mốc thời gian đang chọn ở E1 được giữ khi vào E6 (ô tương ứng được làm nổi sẵn). Dữ liệu hiện tại tự làm mới định kỳ (ví dụ 30 giây) khi trang đang mở.

## E7. Kiến trúc module frontend

Frontend nên chia thành 4 lớp: màn hình (UI), module tính năng, dịch vụ dùng chung và lớp hạ tầng. Màn hình chỉ gọi module tính năng, không gọi API trực tiếp.

### Module tính năng

| Module     | Trách nhiệm                                                                                                                                   | Màn hình dùng  |
|------------|-----------------------------------------------------------------------------------------------------------------------------------------------|----------------|
| map        | Hiển thị bản đồ, marker trạm, gom cụm, vẽ tuyến đường và nhãn thời gian, hiệu ứng trạm được chọn                                              | E1, E4, E5     |
| timeline   | Thanh T…T+30, giữ mốc đang chọn, quyết định lấy dữ liệu thật hay dự đoán                                                                      | E1, E6         |
| station    | Danh sách trạm, trạng thái cổng hiện tại, dự đoán theo mốc, hiển thị màu xanh/vàng/đỏ do backend trả về, thẻ tóm tắt và trang chi tiết        | E1, E4, E5, E6 |
| search     | Form 2 tab Tìm trạm / Tìm đường, kiểm tra dữ liệu nhập, gửi yêu cầu tìm                                                                       | E2–E3          |
| routing    | Nhận kết quả đề xuất, xếp hạng, trường hợp đủ pin / thiếu pin / fallback, biểu đồ thời gian xếp chồng                                         | E4             |
| navigation | Theo dõi GPS, cập nhật ETA, phát hiện lệch tuyến và kích hoạt tính lại, chuyển giai đoạn (đến trạm → gần trạm → đến đích), kết thúc chỉ đường | E5             |
| vehicle    | Danh mục mẫu xe, loại cổng tương thích, ước tính quãng đường còn đi được từ % pin                                                             | E2–E3, E6      |

### Dịch vụ dùng chung

| Module     | Trách nhiệm                                                                                                        |
|------------|--------------------------------------------------------------------------------------------------------------------|
| location   | Lấy vị trí hiện tại, xin quyền, theo dõi liên tục khi đang đi, xử lý mất GPS                                       |
| geocoding  | Gợi ý địa chỉ khi gõ, đổi địa chỉ ↔ toạ độ                                                                         |
| realtime   | Kết nối WebSocket/SSE nhận cập nhật trạng thái trạm, tự kết nối lại                                                |
| api-client | Gọi REST, thử lại, chuẩn hóa lỗi, hủy request cũ khi đổi mốc thời gian                                             |
| storage    | Đọc/ghi dữ liệu lưu trên thiết bị (xem phần Dữ liệu cần lưu)                                                       |
| config     | Ngưỡng tính lại lộ trình, bán kính gần trạm, bán kính đến nơi, chu kỳ làm mới — lấy từ server, có giá trị mặc định |

### Lớp hạ tầng

quản lý state toàn cục (trạm, mốc thời gian, phiên dẫn đường), router giữa các màn hình, thư viện UI dùng chung (nút, bottom sheet, tab, toast, biểu đồ thanh ngang), logging lỗi.


## E8. Dữ liệu lưu trên thiết bị

Frontend chỉ cần lưu trên thiết bị những gì giúp mở app nhanh và không phải nhập lại; dữ liệu gốc (trạm, trạng thái, dự đoán, hành trình) nằm trên server.

| Dữ liệu                                                            | Mục đích                                             | Thời hạn                       |
|--------------------------------------------------------------------|------------------------------------------------------|--------------------------------|
| Mẫu xe đã chọn gần nhất                                            | Điền sẵn vào form E2–E3                              | Đến khi người dùng đổi         |
| % pin nhập gần nhất                                                | Gợi ý giá trị ban đầu (vẫn cho sửa)                  | 1 ngày                         |
| Tab form dùng gần nhất                                             | Mở đúng tab Tìm trạm / Tìm đường                     | Đến khi đổi                    |
| Lịch sử điểm đến (5–10 mục)                                        | Gợi ý nhanh khi gõ điểm đến                          | Không hết hạn, có nút xóa      |
| Danh sách trạm (thông tin tĩnh)                                    | Vẽ marker ngay khi mở app, trước khi có mạng         | Làm mới theo version từ server |
| Danh mục mẫu xe                                                    | Không phải tải lại mỗi lần mở form                   | Làm mới theo version           |
| Cấu hình ngưỡng (config)                                           | Dùng khi mất mạng                                    | Làm mới mỗi lần mở app         |
| Phiên dẫn đường đang chạy (tripId, tuyến, trạm đã chọn, giai đoạn) | Khôi phục E5 nếu app bị đóng hoặc tải lại giữa đường | Xóa khi đến nơi hoặc bấm Tắt   |

Không lưu trên thiết bị: trạng thái cổng thời gian thực và dự đoán (chỉ giữ trong bộ nhớ, cache ngắn ~30 giây) vì để lâu sẽ sai màu marker.

# F. Tích hợp, kiểm thử, demo (Đang triển khai)

## F1. Tích hợp

- Docker Compose gồm các service: PostGIS/Timescale, Redis, OSRM, backend, bộ mô phỏng, frontend (nginx).

- Script make seed, make train, make demo.

- Sinh TypeScript client từ OpenAPI (openapi-typescript). Dựng mock API ngay từ tuần đầu để frontend không phải chờ backend.

- CI bằng GitHub Actions chạy lint và test.

## F2. Kiểm thử phần mềm

- **Unit test (pytest)** cho tầm với, % pin khi tới, thời gian sạc, lớp Markov, xếp hạng, vòng đời cam kết, hysteresis của re-plan. Ca biên của Markov: $π_0 = 0$ thì $W = 0$; $r = 1$ thì $W ≤ Δ$.

- **Property test (Hypothesis):** $0 ≤ occ ≤ 1$; $W ≥ 0$; pin nhiều hơn thì tầm với không nhỏ hơn.

- **API test** bằng httpx AsyncClient.

- **E2E** luồng chính bằng Playwright.

- **Load test** bằng Locust, ví dụ 100 người lập hành trình đồng thời với p95 \< 1 giây.

## F3. Kiểm định mô hình

- Tốt hơn persistence ít nhất 5% theo từng horizon.

- Reliability diagram cho p_full.

- Stress test: Tết, mưa lớn, trạm đầy 100%, trạm mới chưa có lịch sử.

- Monotonicity: cao điểm phải cao hơn 3 giờ sáng.

- SHAP sanity check.

- Thời gian chờ so với ground truth từ bộ mô phỏng.
