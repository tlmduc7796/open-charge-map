# Schema dữ liệu phiên sạc mô phỏng (Simulator Session Schema)

Tài liệu này định nghĩa schema đầu ra của module data-simulator (branch `feat/data-simulator`). Thiết kế mô phỏng nằm ở [simulator.md](simulator.md). Quy ước chung theo [SMART_EV_JOURNEY_DATA_CONTRACT_MVP.md](SMART_EV_JOURNEY_DATA_CONTRACT_MVP.md) §2.

## 1. Phạm vi và nguyên tắc

- **Chỉ lưu dữ liệu đo được ở trạm thật.** Trạm thật ghi nhận được lúc cắm, lúc bắt đầu và kết thúc sạc, lúc rút xe, kWh và công suất. Xe đến, hàng đợi, thời gian chờ, xe bỏ đi không thu thập được nên **không có trong schema**. Simulator vẫn mô phỏng hàng đợi bên trong để quyết định xe nào được cấp cổng lúc nào (mục 6).
- **Nguồn đầu vào của simulator:**
  - `data/static/stations.geojson`: chỉ đọc `station_id`, `total_ports`, `connectors[]`. Bỏ qua `access` và `amenities` (demo coi mọi trạm là public, có bãi đỗ).
  - `data/static/vehicles.json`: `vehicle_id`, `usable_battery_kwh`, `max_ac_power_kw`, `max_dc_power_kw`, `ac_connectors`, `dc_connectors`, `charging_efficiency`.
- **Đầu vào cho tốc độ xe đến** (xem mục 9): thời gian (giờ, thứ trong tuần), thời tiết (3 loại: nắng, nhiều mây, mưa) và hệ số POI cố định của từng trạm. Đây chỉ là đầu vào của simulator, **không xuất hiện** trong `sessions`. Không dùng `data/demo/queue_assumptions.json`.
- **Ngoài phạm vi** (theo scope guard của dự án): giá, phí idle, chi phí. Thời tiết và POI chỉ được dùng cho mô hình xe đến của simulator, không dùng cho recommender hay chấm điểm.
- Mọi bản ghi là dữ liệu tổng hợp: `data_source = "synthetic"`, `is_synthetic = true`. Không trộn vào dữ liệu huấn luyện UrbanEV và không ghi vào `data/static/`.

## 2. Quy ước

| Mục | Quy ước |
|---|---|
| Thời gian | ISO-8601 có múi giờ `+07:00` (Asia/Ho_Chi_Minh) |
| Thời lượng | phút (`*_min`) |
| Công suất | kW (`*_kw`) |
| Năng lượng | kWh (`*_kwh`) |
| SOC | số thực trong `[0, 1]` |
| Định dạng file | CSV UTF-8, dòng đầu là tên cột; thời gian rỗng ghi là ô trống |

## 3. Bảng `ports`: danh sách cổng

Suy ra từ `connectors[]` của `stations.geojson` (dữ liệu chưa có id từng cổng). Mỗi connector có `count = n` sinh `n` dòng, đặt `port_id = <station_id>_P<k>` với `k` tăng dần trong trạm.

| Trường | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `port_id` | string | Id cổng | `ST_EVO_DEUTSCHES_HAUS_P1` |
| `station_id` | string | Trạm chứa cổng | `ST_EVO_DEUTSCHES_HAUS` |
| `connector` | enum `Type2`, `CCS2` | Chuẩn đầu cắm | `Type2` |
| `current` | enum `AC`, `DC` | Loại dòng điện | `AC` |
| `max_power_kw` | float > 0 | **Công suất định mức của cổng** | `22` |

Với 3 trạm hiện có: Audi 4 cổng (2 CCS2 DC 180 kW, 2 Type2 AC 11 kW), Deutsches Haus 4 cổng (Type2 AC 22 kW), Lavida 1 cổng (CCS2 DC 160 kW).

## 4. Bảng `sessions`: một dòng cho mỗi phiên sạc

Chỉ gồm các phiên sạc thật sự diễn ra. Xe bỏ đi vì hàng đợi (balk, renege) không tạo dòng nào.

### 4.1. Định danh

| Trường | Kiểu | Nullable | Ý nghĩa |
|---|---|---|---|
| `session_id` | string | không | Id duy nhất, ví dụ `SES_000001` |
| `station_id` | string | không | Trạm nơi sạc |
| `port_id` | string | không | Cổng được cấp (khóa ngoại tới `ports`) |
| `vehicle_id` | string | không | Mẫu xe (khóa ngoại tới `vehicles.json`) |

### 4.2. Bốn mốc thời gian

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `t_connect` | datetime | Lúc xe cắm vào cổng |
| `t_charge_start` | datetime | Lúc dòng điện bắt đầu chảy (sau độ trễ xác thực) |
| `t_charge_end` | datetime | Lúc dừng sạc: đủ mục tiêu hoặc người dùng rút sớm |
| `t_disconnect` | datetime | Lúc rút xe, cổng được giải phóng |

Không trường nào nullable. Thứ tự bắt buộc: `t_connect ≤ t_charge_start < t_charge_end ≤ t_disconnect`.

### 4.3. SOC

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `soc_start` | float `[0,1]` | Mức pin lúc bắt đầu sạc |
| `soc_end` | float `[0,1]` | Mức pin lúc dừng sạc. Luôn `> soc_start` |

### 4.4. Năng lượng và công suất

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `energy_kwh` | float > 0 | Tổng điện trạm cấp cho xe trong phiên (phía lưới) |
| `avg_power_kw` | float > 0 | Công suất trung bình = `energy_kwh / charge_min × 60` |
| `max_power_kw` | float > 0 | **Công suất tức thời lớn nhất của phiên** |
| `min_power_kw` | float > 0 | **Công suất tức thời nhỏ nhất của phiên** (chỉ xét lúc có dòng sạc P > 0 trong `[t_charge_start, t_charge_end]`) |

Lưu ý tên: `sessions.max_power_kw` là công suất lớn nhất đạt được trong phiên, khác `ports.max_power_kw` là công suất định mức của cổng. `max_power_kw` của phiên không vượt cổng và không vượt giới hạn của xe.

Khi simulator dùng công suất cố định (bản đơn giản, chưa có đường cong sạc), `min_power_kw = avg_power_kw = max_power_kw`. Ba giá trị chỉ khác nhau sau khi thêm đường cong sạc.

### 4.5. Thời lượng dẫn xuất

Tính từ các mốc ở 4.2, lưu sẵn để phân tích và để validator kiểm tra nhất quán.

| Trường | Công thức | Ý nghĩa |
|---|---|---|
| `charge_min` | `t_charge_end − t_charge_start` | Thời gian thật sự sạc |
| `idle_min` | `t_disconnect − t_charge_end` | Xe đã dừng sạc nhưng chưa rút, cổng bị chiếm |
| `connected_min` | `t_disconnect − t_connect` | Tổng thời gian cổng bị chiếm |

### 4.6. Kết cục

| `end_reason` | Khi nào |
|---|---|
| `target_reached` | Sạc tới mức mục tiêu của người dùng |
| `user_unplug` | Người dùng rút xe trước khi đạt mục tiêu (chủ yếu AC) |

### 4.7. Nguồn gốc dữ liệu

| Trường | Giá trị |
|---|---|
| `data_source` | `synthetic` |
| `is_synthetic` | `true` |
| `synthetic_fields` | Danh sách tên trường do mô phỏng sinh ra (tách bằng `;`). Mọi trường của bảng này đều là mô phỏng, nên liệt kê toàn bộ trừ các khóa định danh |

## 5. Không thuộc schema

| Trường / bảng | Lý do loại |
|---|---|
| `t_arrival`, `queue_len_on_arrival`, `wait_min` | Không đo được ở trạm thật |
| `balked`, `reneged`, `diverted_to_station_id` | Xe bỏ đi không để lại dấu vết ở trạm |
| `soc_target` | Người dùng không khai báo mức mục tiêu ở trạm thật (simulator vẫn dùng nội bộ để quyết định khi nào dừng sạc) |
| Bảng `queue_events` | Toàn bộ là biến chỉ có khi mô phỏng |
| `post_id`, `battery_kwh`, `user_segment` | Dữ liệu không có trụ; pin lấy từ `vehicles.json` qua `vehicle_id` |
| `cost_energy_vnd`, `cost_idle_vnd`, giá, phí idle | Ngoài phạm vi (scope guard) |
| Thời tiết, POI | Chỉ là đầu vào của mô hình xe đến (mục 9), không lưu trong `sessions` |
| `is_simulated_field_mask` | Thay bằng `synthetic_fields` đúng quy ước của repo |
| `soc_cap` trong `end_reason` | Không trạm nào có trụ ≥ 250 kW |

## 6. Dữ liệu debug (ngoài schema)

Để kiểm thử simulator, simulator ghi thêm các file riêng vào `data/simulated/debug/`: `arrivals.csv` (lượt đến, xem mục 9) và `queue_log.csv` (mỗi lượt đến một dòng: `arrival_id`, `station_id`, `t_arrival`, `queue_len_on_arrival`, `wait_min`, `outcome` = `served` hoặc `reneged`, `port_id`). Các file này **không thuộc schema**, chỉ dùng cho kiểm thử, và không được dùng cho phân tích hay huấn luyện.

## 7. Bất biến cho validator

Mọi dòng trong `sessions` phải thỏa:

1. `t_connect ≤ t_charge_start < t_charge_end ≤ t_disconnect`.
2. `0 ≤ soc_start < soc_end ≤ 1`.
3. `min_power_kw ≤ avg_power_kw ≤ max_power_kw ≤ min(ports.max_power_kw, giới hạn xe)`; giới hạn xe là `max_ac_power_kw` với cổng AC, `max_dc_power_kw` với cổng DC.
4. `energy_kwh × charging_efficiency ≈ (soc_end − soc_start) × usable_battery_kwh` (sai số nhỏ).
5. `charge_min`, `idle_min`, `connected_min` khớp với các mốc thời gian; `connected_min = charge_min + idle_min + (t_charge_start − t_connect)`.
6. Tương thích: cổng AC chỉ dùng cho xe có `ac_connectors` chứa `connector` đó; tương tự với DC.
7. Không có hai phiên chồng lấp thời gian `[t_connect, t_disconnect]` trên cùng một `port_id`.
8. Số cổng bận tại mọi thời điểm không vượt số cổng của trạm.

## 8. Định dạng đầu ra

- `data/simulated/ports.csv`, `data/simulated/sessions.csv`.
- Không ghi đè `data/runtime/` và `data/demo/`.
- Cùng một seed phải cho cùng một kết quả (tái lập được).

## 9. Mô hình xe đến (đầu vào của simulator)

Xe đến theo quá trình Poisson không đồng nhất (thuật toán thinning), tính **theo trạm**, không gắn nhãn AC hay DC (việc chọn cổng thuộc bước hàng đợi). Tốc độ đến (xe/giờ) của trạm `s` tại thời điểm `t`:

`λ_s(t) = λ0_s × f_giờ[h(t)] × f_thứ[d(t)] × f_tt[w(t)] × g(POI_s)`

Code: `simulator/arrivals.py`, `simulator/weather.py`. Tham số: `config/simulator.json`. Đầu ra (ngoài schema): `data/simulated/debug/arrivals.csv` với các cột `arrival_id`, `station_id`, `t_arrival`, `vehicle_id`, `soc_start`, `soc_target`, `patience_min`.

| Thành phần | Ý nghĩa | Nguồn |
|---|---|---|
| `λ0_s` | `Σ (số cổng loại c × r_c) ÷ 24`, c ∈ {AC, DC}: một tốc độ chung cho trạm, bằng số cổng × trung bình có trọng số của `r_DC` (18) và `r_AC` (4,5) xe/cổng/ngày | Giả định. Cao hơn khoảng Dundee (DC 6–11, AC 1,5–3) để có hàng đợi dày giờ cao điểm |
| `f_giờ[h]` | 24 hệ số theo từng giờ, chuẩn hóa trung bình = 1. Đỉnh chính 11–13h (12h ≈ 2,65), đỉnh phụ 17–19h | Giả định |
| `f_thứ[d]` | 7 hệ số Thứ 2–Chủ nhật, chuẩn hóa trung bình = 1 (thứ 6 và thứ 7 cao, Chủ nhật thấp) | Giả định |
| `f_tt[w]` | Thời tiết 3 loại theo giờ: nắng, nhiều mây, mưa. Mưa nếu lượng mưa ≥ 0,5 mm/giờ; nắng nếu ban ngày và mây < 40%; còn lại nhiều mây. Hệ số của trạm là trung bình có trọng số (số cổng × `r_c`) của hệ số AC (nắng 1,05; mây 1,00; mưa 0,85) và DC (1,00; 1,00; 0,95) | Dữ liệu thời tiết thật từ API Open-Meteo (một lần, lưu `data/simulated/inputs/weather_hcmc.json`); hệ số là giả định |
| `g(POI_s)` | Hệ số POI **cố định** cho từng trạm, trong [0,7; 1,5]: Deutsches Haus 1,2; Audi 1,1; Lavida 0,9 | Giả định theo vị trí, không gọi API |

Không có hệ số ngày lễ. Mọi hệ số là giả định, đặt trong `config/simulator.json`, không viết cứng trong code; chỉ có 3 trạm nên không thể ước lượng hệ số từ dữ liệu. Trạm bắt đầu trống lúc 00:00 ngày đầu (không có ngày khởi động).

**Thuộc tính mỗi lượt đến** (dùng chung cho mọi xe, không phân AC/DC, không phụ thuộc loại xe hay giờ):

| Trường | Phân phối |
|---|---|
| `vehicle_id` | Chọn theo trọng số (VF5 0,55; VF7 0,35) trong các xe có đầu cắm khớp với trạm; xe GBT không khớp nên không xuất hiện |
| `soc_start` | Beta(2; 3), trung bình 0,4; chặn trong [0,05; 0,8] và thấp hơn `soc_target` ít nhất 0,1 |
| `soc_target` | Rời rạc: 0,8 (40%), 0,9 (25%), 1,0 (35%) |
| `patience_min` | Log-normal, trung vị 20,9 phút, σ = 0,6 (trung bình 25 phút; 90% trong khoảng 8–56 phút) |

**Mức tải giờ trưa.** Với thời gian chiếm cổng giả định DC ≈ 40 phút, AC ≈ 150 phút, hệ số tải ρ = λ ÷ Σ(số cổng × μ) trung bình trong 11–13h (trời nhiều mây): Lavida ≈ 1,06; Audi ≈ 1,28; Deutsches Haus ≈ 1,32. ρ > 1 nên hàng đợi hình thành quanh giờ trưa.

## 10. Mô phỏng phiên sạc (hàng đợi, cấp cổng, rút xe)

Code: `simulator/sessions.py` (SimPy), chạy bằng `python -m simulator.sessions`; kiểm tra bằng `python scripts/validate_simulator.py` (báo cáo `data/validation/simulator_validation_report.md`). Đầu ra: `data/simulated/sessions.csv`, `ports.csv`.

Mỗi lượt đến:

1. **Chọn cổng.** Tìm cổng rảnh mà đầu cắm khớp xe (`ac_connectors` với cổng AC, `dc_connectors` với cổng DC). Nếu nhiều cổng rảnh: ưu tiên **DC trước AC** (`port_preference`), rồi cổng cho công suất sạc cao nhất.
2. **Hết cổng thì xếp hàng.** Hàng FIFO theo trạm; chờ tối đa `patience_min`, hết kiên nhẫn thì **bỏ đi và không tạo phiên**. Khi một cổng được trả, xe đứng đầu hàng mà dùng được cổng đó được cấp ngay.
3. **Mốc thời gian.** `t_connect` = lúc được cấp cổng + trễ cắm (log-normal trung vị 1,5 phút); `t_charge_start` = `t_connect` + trễ xác thực (trung vị 1 phút).
4. **Sạc với công suất cố định** `P = min(công suất cổng, công suất xe)`: `charge_min = Δsoc × pin ÷ (P × hiệu suất 0,9) × 60`. Chưa có đường cong sạc, nên `min_power_kw = avg_power_kw = max_power_kw = P`.
5. **Rút xe phụ thuộc thời điểm sạc xong** (dùng chung AC và DC, đều là giả định):

   | Việc | Quy tắc |
   |---|---|
   | Rút sớm (`user_unplug`) | Xác suất theo giờ **dự kiến** sạc xong: 0,35 nếu 22:00–06:00, 0,10 các giờ còn lại. Nếu rút sớm: dừng ở `u` × thời gian sạc dự kiến với `u` ~ Uniform(0,5; 0,95), `soc_end < soc_target`, `idle_min = 0` |
   | Idle sau khi sạc đủ (`target_reached`) | Log-normal theo giờ sạc xong: 06:00–22:00 trung vị 8 phút (σ = 0,9); 22:00–06:00 trung vị 180 phút (σ = 0,7), tức xe để qua đêm |

6. Trả cổng lúc `t_disconnect`.

Trạm bắt đầu trống lúc 00:00 ngày đầu. Seed riêng cho từng trạm, tách khỏi seed xe đến nên thêm bước này không đổi dữ liệu xe đến. Không có balking riêng, chỉ bỏ đi khi hết kiên nhẫn.

**Kết quả chạy hiện tại** (60 ngày, xem báo cáo kiểm định): xe bỏ đi nhiều nhất lúc 11–13h (khoảng 30–43%) và có 48% xe phải xếp hàng lúc 12h; thời gian chiếm cổng trung bình DC khoảng 44 phút, AC khoảng 258 phút. Phiên AC rất dài vì xe chỉ nhận 6,6–7,2 kW.

## 11. Điểm mở

- Đường cong sạc đầy đủ theo SOC hay giữ công suất cố định cho MVP (xem data contract §15).
- Đường cong sạc theo SOC (hiện công suất cố định, nên DC lạc quan ở 80–100%) và hệ số giờ/xác suất rút sớm/idle ở mục 10 đều là giả định.
- Giá trị `r_c`, `f_giờ`, `f_thứ`, hệ số thời tiết, `g_poi`, `soc_start`, `soc_target` và `patience_min` đều là giả định cần hiệu chỉnh khi có dữ liệu thật.
- Tham số balking và reneging (chỉ ảnh hưởng nội bộ, đều là giả định).
