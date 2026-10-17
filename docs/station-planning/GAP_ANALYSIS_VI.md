# Phân tích khoảng trống trạm sạc (9 phường)

Tài liệu tổng hợp cho tab **Khoảng trống** của Planner: dữ liệu lấy từ đâu, thật hay mô phỏng, ba chế độ xem trên bản đồ (lưu lượng tuyến đường, giá nhà, điểm dự đoán) và cách tính điểm. Triển khai [kế hoạch khoảng trống trạm sạc](../../KeHoachPlannerNew/ke-hoach-khoang-trong-tram-sac.md); API `/api/v1/planning/gap/*`.

Đây là bước **sàng lọc khối đất để đi khảo sát**, không dự đoán doanh thu và không thay engine `technical_opportunity` của tab Planner.

## 1. Tóm tắt trong một bảng

| Dữ liệu | Thật hay mô phỏng? | Nguồn | Dùng ở đâu |
|---|---|---|---|
| Mạng đường (tên, cấp, số làn, hình học) | **Thật** | OpenStreetMap (ODbL) | Cắt khối đất; vẽ tuyến đường; cấp đường là đầu vào của lưu lượng mô phỏng |
| POI (điểm đến) | **Thật** (dữ liệu đã thu thập) | `context_poi.geojson` + 3 nhóm giao thông trong `context_transport.geojson` | Thành phần POI của nhu cầu D |
| Hạ tầng giao thông (đèn tín hiệu, trạm buýt, ga MRT, bến xe) | **Thật** (dữ liệu đã thu thập) | `context_transport.geojson` | Đầu vào của lưu lượng mô phỏng |
| **Lưu lượng xe** | **Mô phỏng** (`synthetic`) | Công thức trong `scripts/prepare_gap_analysis_demo.py`, tham số ở `config/gap_analysis_demo.json` | Chế độ *Lưu lượng tuyến đường*; thành phần Flow của nhu cầu D |
| **Giá nhà (giá thuê)** | **Mô phỏng** (`synthetic`) | Cùng script | Chế độ *Giá nhà*; chia điểm ở Bước 4 |
| Trạm của mình và trạm đối thủ | **Mô phỏng** | Cùng script (+ 1 trạm đặt tay) | Nguồn cung `Cung`; khoảng cách trạm gần nhất |
| Pháp lý | **Chưa xác minh** | Không thu thập, không mô phỏng | Nhãn `unknown` cho mọi ứng viên |
| Dữ liệu giao thông thật (vận tốc theo đoạn đường) | Thật, **chưa dùng** | `data_platform/new/traffic_flow_hcm/` | Chưa nối vào tính năng |
| Giá bất động sản theo phường (giá bán, giá thuê) | Thật nhưng thưa, **chưa dùng** | `data_platform/new/ward_price_estimates.*` | Chưa nối vào tính năng |

Quy tắc đọc: **chỉ mạng đường, POI và hạ tầng giao thông là dữ liệu thu thập**. Mọi con số lưu lượng và giá trên bản đồ là số mô phỏng, nên thứ hạng ứng viên chỉ minh họa cách làm, không phản ánh thị trường thật. Giao diện luôn gắn nhãn nguồn dữ liệu phía trên bản đồ.

## 2. Ba chế độ xem trên bản đồ

Nút chọn chế độ nằm trên thanh công cụ của bản đồ. Ứng viên (số 1–5) và trạm luôn hiện ở cả ba chế độ.

| Chế độ | Bản đồ vẽ gì | Giá trị và màu | Chú giải |
|---|---|---|---|
| **Lưu lượng tuyến đường** | Từng tuyến đường là một đường màu, đường đông xe vẽ đè lên trên; các khối chỉ còn là nền mờ | Xe/giờ cao điểm (mô phỏng) của **từng đường**. Màu liên tục xanh lá → vàng → cam → đỏ → đỏ đậm (`#2eab4f`, `#f4c20d`, `#ee7b19`, `#d7261e`, `#7b0d0d`), kéo từ đường ít xe nhất tới đường nhiều xe nhất trong 9 phường. Nét dày theo cấp đường và theo mức zoom | Thanh gradient kèm số xe/giờ thấp nhất và cao nhất |
| **Giá nhà** | Mỗi khối đất tô một màu | Giá thuê mô phỏng, nghìn đồng/m²/tháng. Thang vàng nhạt → nâu đậm (`#fff7bc` … `#993404`), tuyến tính giữa giá thấp nhất và cao nhất của mọi khối. Khối bị loại **không** bị xám ở chế độ này | Thanh gradient kèm giá thấp nhất và cao nhất |
| **Điểm dự đoán** (mặc định) | Mỗi khối đất tô một màu | Điểm xếp hạng sau bước giá thuê (mục 5, Bước 4). Cùng thang vàng → nâu, kéo trên các khối **đủ điều kiện**; khối bị loại tô xám | Thanh gradient kèm điểm thấp nhất và cao nhất |

Ghi chú khi rê chuột: trên đường (chế độ lưu lượng) hiện tên đường, cấp, số làn, số xe/giờ và mức đông (*Thông thoáng*, *Khá đông*, *Đông*, *Rất đông, dễ kẹt*, chia theo vị trí trong thang: dưới 20%, 20–45%, 45–70%, trên 70%). Trên khối hiện mã khối, đường bao quanh, diện tích, Gap, D, Cung và hạng. Viền nét đứt teal là khối gần trạm của mình; viền đen đậm là cụm của ứng viên đang chọn.

Hai chế độ sau tô màu theo khối; chế độ đầu theo tuyến. Mức "đông" là **tương đối** trong 9 phường, không phải ngưỡng kẹt xe thật.

## 3. Nguồn dữ liệu lưu lượng

### 3.1 Dữ liệu đầu vào thật

- **Mạng đường OpenStreetMap** (`raw_data/osm_roads/hcm_nine_wards_roads.geojson`, 9.854 đoạn, thu bằng `scripts/collect_osm_roads.py`, hash trong `collection_manifest.json`). Lấy `motorway`, `trunk`, `primary`, `secondary`, `tertiary`, `unclassified`, các `_link`, cộng đường `residential` có tên. Hẻm (tên bắt đầu Hẻm, Ngõ, Ngách, Kiệt) và đường chưa đặt tên bị bỏ, nên còn 5.095 đường được tính lưu lượng. © những người đóng góp OpenStreetMap, giấy phép ODbL: dữ liệu dẫn xuất phải giữ ghi nguồn này.
- **Hạ tầng giao thông** trong `context_transport.geojson`, với trọng số: nhà ga MRT 3,0; bến xe và trạm dừng 2,0; đèn tín hiệu 1,0; trạm xe buýt 0,6; mỗi đỉnh của đường 0,15. Cộng theo từng ô lưới 300 m (hoặc theo từng khối), rồi đổi sang thứ hạng phần trăm.
- **Tâm thành phố** là mốc giả định (Chợ Bến Thành, 10,7725 / 106,698) cho khoảng cách xuyên tâm.

### 3.2 Lưu lượng là số mô phỏng, không phải số xe đo được

Không có nguồn đếm xe theo đoạn đường nào trong repo. Lưu lượng mô phỏng, đơn vị **xe/giờ cao điểm**, nằm trong 250–4250. Ba mô hình cùng một họ công thức, khác nhau ở đơn vị tính:

| Mô hình | Tính cho | Thành phần và trọng số | File |
|---|---|---|---|
| **Theo tuyến** (chế độ *Lưu lượng tuyến đường*) | Từng đường (5.095) | Gần trung tâm 35% · cấp đường và số làn 40% · hạ tầng giao thông quanh đường 15% · nhiễu mượt 10% | `route_roads.csv` |
| **Theo khối** (cho nhu cầu D, mặc định) | Từng khối đất (488) | Gần trung tâm 40% · cấp đường × chiều dài đường bao quanh 35% · hạ tầng giao thông trong khối 15% · nhiễu 10% | `route_blocks.csv` |
| **Theo lưới 300 m** (để so sánh) | Từng ô vuông (291) | Gần trung tâm 45% · hạ tầng giao thông 35% · nhiễu 20% | `grid_cells.csv` |

Cách tính chung:

1. `radial = exp(−khoảng cách tới tâm / 3500 m)`.
2. `capacity` (năng lực đường): ở mô hình **tuyến** là điểm cấp đường chia 6 (cao tốc 6, trục chính 5, đường chính 4, liên khu vực 3, khu vực 2, nội khu 1), cộng 0,03 cho mỗi làn trên 2 (nếu OSM có số làn, tối đa 1); ở mô hình **khối** là tổng (chiều dài đường × điểm cấp) của các đường nằm trong 15 m quanh khối, đổi sang thứ hạng phần trăm.
3. `infrastructure`: thứ hạng phần trăm của hạ tầng giao thông (xem 3.1); với tuyến, lấy ô lưới chứa điểm giữa đường.
4. Nhiễu mượt: tổng các sóng sin·cos theo tọa độ. Tuyến dùng tần số cao hơn (0,002–0,007 rad/m) để cùng một trục đường đổi màu theo đoạn.
5. `latent` = tổng có trọng số, chuẩn hóa min–max về 0–1.
6. `flow = 250 + 4000 × latent^1,3 × jitter`, `jitter = exp(N(0; 0,12))`, cắt về 250–4250 và làm tròn chục.

Hệ quả cần nhớ: lưu lượng tuyến cao hơn ở đường chính, trục chính và gần trung tâm (trung bình: đường chính ≈ 2.250, trục chính ≈ 2.200, liên khu vực ≈ 1.680, khu vực ≈ 1.410, nội khu ≈ 730 xe/giờ). Lưu lượng khối và lưu lượng tuyến **tương quan nhưng không bằng nhau** vì tính riêng; ứng viên dùng lưu lượng khối.

Mỗi dòng dữ liệu đều có cột `flow_status = synthetic`; manifest ghi `data_labels.flow` và `data_labels.road_flow` bắt đầu bằng `synthetic`.

### 3.3 Dữ liệu giao thông thật đã có nhưng chưa dùng

`data_platform/new/traffic_flow_hcm/`: lịch sử **điều kiện lưu thông** theo đoạn đường (Kaggle *Traffic Flow data in Ho Chi Minh City*, CC0, mirror Transport Data Commons). 5.390 đoạn đường trong 9 phường, 7.509 quan sát vận tốc, từ 7/2020 tới 4/2021, lấy mẫu không đều.

- Nguồn **không có số xe**: mọi bản ghi có `vehicle_count = null`. Chỉ có vận tốc; tỷ lệ so với `max_velocity` mới là chỉ báo tắc nghẽn.
- `observation_count = 0` nghĩa là không có quan sát, không phải lưu lượng bằng 0.
- Ranh giới phường là snapshot 2025, dữ liệu 2020–2021 nên chỉ là chuẩn hóa không gian.
- README của bộ này cấm dùng làm "lưu lượng xe" hoặc nhãn nhu cầu sạc. Nếu muốn vẽ màu kẹt xe theo dữ liệu thật thì cần một lớp **điều kiện lưu thông** riêng, tách khỏi lưu lượng mô phỏng.

## 4. Nguồn dữ liệu giá nhà

### 4.1 Giá thuê mô phỏng (đang hiển thị)

Giá thuê mỗi khối, đơn vị **nghìn đồng/m²/tháng**, nằm trong 100–1100 (trung vị khối ≈ 480):

```
giá = (100 + 650 × exp(−khoảng cách tới tâm / 2800 m) + 120 × thứ hạng POI) × exp(N(0; 0,15))
```

cắt về 100–1100 và làm tròn 5 nghìn. `thứ hạng POI` là thứ hạng phần trăm của điểm POI có trọng số của khối trong 9 phường. Tức là giá cao ở gần trung tâm và nơi nhiều điểm đến. Không dùng tin rao thật; cột `rent_status = synthetic`; manifest ghi `data_labels.rent` bắt đầu bằng `synthetic`.

### 4.2 Giá bất động sản theo phường (có sẵn, chưa dùng)

`data_platform/new/ward_price_estimates.{csv,json,geojson}` (`hcmc-nine-wards-price-supplement-20261017-v1`): một giá bán (đồng/m²) và một giá thuê (đồng/m²/tháng) cho từng phường, là **trung vị mẫu tin rao đã chọn lọc** (batdongsan.com.vn), mỗi giá chỉ dựa trên 1–2 tin.

| Phường | Giá bán (triệu đ/m²) | Giá thuê (nghìn đ/m²/tháng) |
|---|---|---|
| Tân Định | 197 | 489 |
| Sài Gòn | 241 (mượn từ Bến Thành, 0 mẫu) | 733 |
| Bến Thành | 241 | 200 |
| Bình Quới | 55 | 92 |
| Bình Thạnh | 120 | 150 |
| Thạnh Mỹ Tây | 106 | 210 |
| Tân Sơn Hòa | 139 | 185 |
| Phú Nhuận | 121 | 333 |
| Xuân Hòa | 656 | 833 |

Mọi dòng có `quality_status = low_evidence_demo_reference_not_market_valuation`, `reliability = low_sparse_sample`, không hiệu chỉnh thời gian, không phải báo giá hay giao dịch xác minh. Giá thuê Bến Thành (200) thấp hơn Tân Định (489) và Sài Gòn (733) cho thấy mẫu quá thưa để so sánh phường. Trường `source_ref` trỏ tới `raw_data/property_prices/…`, thư mục này chưa có trong repo nên không kiểm tra lại được mẫu gốc.

Nếu muốn thay giá mô phỏng bằng giá thật: chỉ có độ phân giải **phường** (9 giá), không thay được giá từng khối; cách hợp lý là dùng làm mốc hiệu chỉnh hoặc hiển thị song song, và gắn nhãn độ tin cậy thấp.

## 5. Cách tính điểm (tab Khoảng trống / Điểm dự đoán)

Điểm là **thứ hạng ưu tiên khảo sát**, không phải dự báo doanh thu hay xác suất thành công. Tên "điểm dự đoán" trên giao diện chỉ để chỉ chế độ xem điểm này.

Mọi tính toán chạy trên từng **khối đất** (mặc định) hoặc ô lưới, chỉ cần một điểm đại diện cho mỗi đơn vị. Tham số mặc định: `w₁ = 0,5`, `λ = 1000 m`, chuẩn hóa min–max, `rent_mode = divide`, `ε = 0,1`, ngưỡng ăn nhu cầu 500 m, `min_demand = 0,1`, 5 ứng viên cách nhau tối thiểu 1 km.

1. **Nhu cầu D.** `D = w₁·Flow + w₂·POI`, `w₂ = 1 − w₁`; `Flow` là lưu lượng khối và `POI` là điểm POI có trọng số, mỗi cái chuẩn hóa 0–1 trên toàn 9 phường (min–max hoặc thứ hạng phần trăm). Điểm POI = tổng trọng số loại POI × trọng số chống trùng (`poi_model_weights.csv`); loại POI có trọng số riêng trong config (trung tâm thương mại 5, bãi xe 4, siêu thị 3, khu du lịch 3, khách sạn 2,5 … nhà thờ, chùa 0,1, nhà vệ sinh 0).
2. **Nguồn cung.** `Cung = Σ nₖ · exp(−dₖ / λ)` trên **mọi** trạm (của mình và đối thủ); `nₖ` là số cổng (hoặc kW chia 60 kW), `dₖ` là đường chim bay từ điểm đại diện tới trạm.
3. **Gap.** `Gap = D / (1 + Cung)`: nhu cầu cao, ít trạm quanh thì Gap cao.
4. **Giá thuê.** `rent_mode = divide`: `Điểm = Gap / (Rent~ + ε)`, với `Rent~` là giá thuê chuẩn hóa 0–1 trên mọi khối. Giá thấp thì điểm cao. Chế độ `filter` loại khối có giá vượt ngưỡng; `none` giữ `Điểm = Gap`. Khối thiếu giá bỏ qua bước này và gắn nhãn, không coi là 0.
5. **Loại và gắn cờ.** `D < min_demand` thì loại (`demand_below_floor`). Khoảng cách tới trạm **của mình** gần nhất nhỏ hơn ngưỡng thì gắn cờ "có thể lấy khách của trạm cũ" (hoặc loại, nếu `own_mode = exclude`).
6. **Chọn ứng viên.** Xếp khối đủ điều kiện theo `Điểm` giảm dần, lấy lần lượt khối cách mọi ứng viên đã chọn ≥ 1 km cho đủ 5; khối liền kề được gộp vào cụm của ứng viên.
7. **Độ ổn định.** Chạy lại với 9 bộ tham số (`w₁` ± 0,2 × `λ` nhân 0,5 / 1 / 1,5) và đếm số bộ vẫn chọn vùng đó: từ 2/3 trở lên là *Ổn định*, ngược lại *Nhạy với giả định*.

**Ví dụ (ứng viên 1 với tham số mặc định, khối B0348 · Tân Sơn Hòa):** `Flow = 0,502`, `POI = 0,286` ⇒ `D = 0,5·0,502 + 0,5·0,286 = 0,394`; `Cung = 1,346` ⇒ `Gap = 0,394 / 2,346 = 0,168`; giá thuê 265 nghìn ⇒ `Rent~ = 0,151` ⇒ `Điểm = 0,168 / (0,151 + 0,1) = 0,669`.

**Điểm này tô màu thế nào:** chế độ *Điểm dự đoán* tô `Điểm` của từng khối trên thang vàng → nâu (cao nhất = nâu đậm), khối bị loại tô xám. Chế độ *Giá nhà* chỉ tô giá thuê thô và **không** phải điểm; giá chỉ ảnh hưởng điểm qua phép chia ở Bước 4, nên khối rẻ (màu nhạt ở tab Giá nhà) có xu hướng điểm cao.

Khác kế hoạch gốc: thêm `min_demand` để loại khối gần như không có nhu cầu (nếu không, công thức thuần xếp các khối trống hoàn toàn lên đầu). Đặt `min_demand = 0` để chạy công thức thuần.

## 6. Ứng viên và thông số xung quanh

Giao diện luôn hiển thị đúng **5 ứng viên** ở panel bên trái (không còn thiết lập; API vẫn nhận `top_n` 1–30). Mỗi thẻ có:

- **Điểm lưu lượng:** `flow_norm × 100` (vị trí của khối trong 9 phường, 0–100), kèm xe/giờ.
- **Giá thuê:** nghìn đồng/m²/tháng của khối.
- **Đối thủ gần nhất:** khoảng cách và mã trạm.

Bấm một ứng viên để mở chi tiết: nhu cầu D, nguồn cung (của mình và đối thủ), Gap, điểm; đường bao quanh; các trạm đóng góp nhiều nhất vào `Cung`; độ ổn định; danh sách việc pháp lý chưa kiểm tra; và mục **lưu lượng, giá bất động sản xung quanh** (`nearby`) tính trong bán kính **800 m**:

| Thông số | Ý nghĩa |
|---|---|
| Lưu lượng tại khối, trung bình quanh, cao nhất quanh (kèm tên đường của khối đó) | xe/giờ cao điểm, mô phỏng |
| Vị trí lưu lượng | "cao hơn x% khối trong 9 phường" |
| Giá thuê tại khối, trung bình quanh, thấp nhất – cao nhất quanh | nghìn đ/m²/tháng, mô phỏng |
| Vị trí giá | "đắt hơn x% khối trong 9 phường" |

Điều kiện đất (chủ mặt bằng, diện tích sử dụng, lối vào) và điện lưới không được xét; pháp lý của mọi ứng viên là `unknown`.

## 7. Cách chia khu vực

Mặc định mỗi ô là **một khối đất nằm giữa các tuyến đường thực tế** (`division = route`); lưới vuông 300 m (`grid`) vẫn gọi được qua API, chỉ để so sánh.

1. Mỗi đường (lọc như mục 3.1) nở ra bằng nửa bề rộng mặt đường theo cấp (đường chính 9 m, liên khu vực 7 m, khu vực 6 m, nội khu 4 m, trục chính và cao tốc 10 m).
2. Phần đất còn lại của từng phường sau khi trừ các dải đường là các **khối**. Khối nhỏ hơn 1.500 m² bị bỏ.
3. Khối vượt 30 ha (vùng trống lớn mà mạng đường không bao kín, 47 mảnh ở Bình Quới, Thạnh Mỹ Tây, Bình Thạnh, Tân Sơn Hòa) được cắt đôi liên tiếp theo cạnh dài cho tới ≤ 30 ha, đánh dấu `subdivided`; ranh giới cắt không phải đường thật.

| | Khối đường (`route`) | Lưới vuông (`grid`) |
|---|---|---|
| Ô | Đa giác theo đường bao thực tế, mã `B0001…` | Hình vuông 300 × 300 m, mã `G0001…` |
| Số ô | 488 (47 mảnh chia nhỏ), 0,15–30 ha, trung vị ≈ 1,9 ha | 291 |
| POI | POI nằm trong khối; POI trên lòng đường gán cho khối gần nhất trong 60 m | POI nằm trong ô |

## 8. Trạm mô phỏng

16 trạm, 84 cổng, 5,3 MW, tạo bởi `scripts/prepare_gap_analysis_demo.py` theo `station_simulation` trong config; **không phải trạm thật** và độc lập với 37 trạm `EVC-*` của tab Planner. Trên giao diện chỉ có hai loại: *Trạm của mình* (`OWNED`, teal) và *Trạm đối thủ* (`OTHER_NETWORK`, cam); tên Đối thủ A/B/C chỉ hiện trong chi tiết trạm.

| Loại | Trạm | Cổng | Công suất |
|---|---|---|---|
| Trạm của mình | 5 | 22 | 1,4 MW |
| Trạm đối thủ | 11 (A 5, B 3, C 3) | 62 | 3,9 MW |

Vị trí chọn từ POI có sẵn (trung tâm thương mại, siêu thị, bãi xe, khách sạn, bến xe, trạm xăng, bệnh viện, đại học, khu du lịch), cách nhau ≥ 300 m, ưu tiên nơi nhu cầu cao (đối thủ mạnh hơn: số mũ 1,2–1,5 so với 1,0). `station_simulation.manual_stations` đặt trạm ở tọa độ cố định mà không dùng số ngẫu nhiên nên không đổi trạm khác: hiện có `CMP-A-05` tại 10,82273, 106,73518 (Bình Quới), 6 cổng DC 120 kW, loại điểm `other`. Bấm vào trạm trên bản đồ để xem địa điểm và bảng thông số từng nhóm cổng.

## 9. API, mã nguồn và cách tạo lại

- `GET /api/v1/planning/gap/snapshot?division=route|grid`: ô phân tích (với `route` có `polygon`, `area_m2`, `road_names`…), POI, lưu lượng, giá thuê, **`roads`** (từng tuyến: tên, cấp, số làn, `flow_vph` mô phỏng, điểm `[lat, lon]`), trạm kèm nhóm cổng, tổng hợp theo mạng. Khoảng 1,7 MB.
- `POST /api/v1/planning/gap/run`: tham số snake_case như mục 5; trả điểm từng ô, ứng viên (kèm `nearby`) và cảnh báo.
- Mã: `backend/app/planning/gap_analysis.py` (logic thuần), `gap_service.py` (đọc snapshot, kiểm hash), `gap_api_models.py`; frontend `frontend/src/planning/gap/` (`GapView`, `GapGoongMap` Goong, `GapLeafletMap` dự phòng OSM, `gapFormat`, `gapGeo`). Bản đồ cần `VITE_GOONG_MAPTILES_KEY` trong `frontend/.env.local`; không có khóa thì dùng Leaflet + OpenStreetMap.
- Snapshot nằm ở `data_platform/station_planning/gap_v1/` (`grid_cells.csv`, `route_blocks.csv`, `route_roads.csv`, `gap_stations.csv`, `gap_station_ports.csv`, `manifest.json` có hash từng file).

```powershell
python scripts/prepare_gap_analysis_demo.py     # cần shapely (scripts/requirements-station-planning.txt, hoặc --dependency-dir)
python scripts/collect_osm_roads.py             # chỉ khi muốn làm mới mạng đường (cần mạng)
pytest backend/tests/test_gap_analysis.py backend/tests/test_gap_api.py tests/test_gap_analysis_demo.py
pnpm --dir frontend exec vitest run src/planning/gap
```

Mỗi nhóm dữ liệu dùng một luồng số ngẫu nhiên riêng (khối: seed + 1, lưu lượng tuyến: seed + 2), nên thêm hoặc đổi một nhóm không làm đổi các file khác. Đổi seed hoặc tham số mô phỏng: sửa `config/gap_analysis_demo.json`, đổi `snapshot_id` và `output_directory`, cập nhật `GAP_SNAPSHOT_ID` trong `gap_service.py`. Backend và frontend chỉ đọc file đã sinh, không cần shapely lúc chạy.

## 10. Giới hạn đã biết

- Lưu lượng, giá thuê và trạm đều là mô phỏng. Thứ hạng không phản ánh thị trường thật; chỉ POI, mạng đường và hạ tầng giao thông là dữ liệu thu thập.
- Màu "đông, kẹt" của tuyến là mức tương đối trong số mô phỏng; không có dữ liệu đếm xe hay tốc độ thực tế trên bản đồ.
- Phép chia cho giá thuê thưởng khối **rẻ**: với dữ liệu hiện tại có ứng viên có POI gần 0 (ví dụ khu ga sân bay, khối ven rạch) vẫn lọt top 5 nhờ giá thấp và lưu lượng vừa. `min_demand` chỉ chặn `D < 0,1`. Nên xem `D` và POI trong chi tiết ứng viên trước khi tin thứ hạng.
- `Cung` tính bằng số cổng còn `D` trong 0–1, nên khối có nhiều trạm quanh đó gần như luôn có Gap thấp; đổi `λ` hoặc `supply_basis` để xem độ nhạy. Công thức chưa xét diện tích khối và không phân biệt đối thủ đã chứng minh nhu cầu với đối thủ làm cung dư.
- Khoảng cách là đường chim bay từ điểm đại diện, chưa dùng thời gian lái xe.
- Khối đường chính xác bằng độ đầy đủ của OpenStreetMap: hẻm bị bỏ nên một khối có thể chứa nhiều dãy nhà; sông, kênh, công viên không chặn khối nên khối kề nước có thể gồm cả mặt nước. Mảnh `subdivided` không có đường bao thật ở cạnh cắt. Ranh giới phường cũng cắt khối.
- Giá bất động sản và giao thông thật (mục 3.3, 4.2) đang nằm ngoài tính năng; việc nối vào cần quyết định riêng về độ phân giải (phường so với khối) và nhãn độ tin cậy.
