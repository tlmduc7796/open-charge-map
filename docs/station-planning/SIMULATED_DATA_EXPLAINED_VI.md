# Giải thích dữ liệu mô phỏng của Planner

Tài liệu này mô tả **cách dữ liệu demo hiện tại được tạo**, lý do của từng quy tắc và các giá trị được đưa vào công thức. Các giá trị giả định chưa được hiệu chỉnh bằng lịch sử sạc thực tế; chúng phục vụ kiểm tra luồng tính toán và so sánh kịch bản.

## 1. Phạm vi và nguồn dữ liệu

| Thành phần | Giá trị hiện tại | Ý nghĩa |
|---|---|---|
| Snapshot | `hcmc-nine-wards-demo-v3` | Bộ file cố định mà Planner đọc |
| Ngày chuẩn bị | 13/10/2026 | Ngày tạo snapshot, không phải thời điểm đo nhu cầu |
| Phiên bản generator / kịch bản | `1.2` / `7` | Phiên bản ghi trong cấu hình snapshot |
| Seed | `20261013` | Cố định việc sinh phiên sạc, năng lượng và vận hành ngẫu nhiên |
| Phạm vi | 9 phường | Không đại diện toàn TP.HCM |
| Trạm hiện hữu trong demo | 37 | Fixture mô phỏng, không phải danh mục trạm đã xác minh |
| Ứng viên | 18 | 2 vị trí đại diện mỗi phường |
| Demand node | 27 | 3 điểm đại diện nhu cầu mỗi phường |
| Tuần mô phỏng | 07–13/07/2025, múi giờ UTC+7 | Lịch giả lập, không phải phát lại hoạt động thực tế |
| Bước thời gian | 30 phút | 48 khoảng/ngày, 336 khoảng/tuần |

Các nguồn và phần suy ra được phân biệt như sau:

| Dữ liệu | Căn cứ | Phần chưa được xác nhận |
|---|---|---|
| Ranh giới và dân số phường | Thuộc tính trong lớp địa giới nguồn | Ngày tham chiếu dân số và ngày hiệu lực pháp lý còn thiếu |
| POI và hạ tầng giao thông | Tọa độ, loại địa điểm từ bộ dữ liệu nguồn | Không có lưu lượng xe đo theo giờ; POI không tự chứng minh có nhu cầu sạc |
| Trạm hiện hữu | Bộ fixture 37 trạm được chọn sẵn | Không xác nhận tồn tại, công suất khả dụng hoặc hoạt động thực tế |
| Ứng viên | Dùng tọa độ POI/điểm giao thông trong phạm vi | Chưa xác nhận thửa đất, quyền triển khai, điện, lối vào và giấy phép |
| Demand node và nhu cầu | Quy tắc phân bổ dân số, POI và hệ số giả định | Không có giao dịch sạc thực tế để hiệu chỉnh |
| Thời gian tiếp cận | Khoảng cách địa lý và tốc độ giả định | Không phải thời gian đi theo mạng đường hoặc giao thông trực tiếp |
| Chi phí | Các mức đầu tư/vận hành giả định | Không phải báo giá theo từng địa điểm |

Nguồn cấu hình chính là [generation_config.json](../../data_platform/station_planning/demo_hcmc_v3/generation_config.json). Danh sách file đầu vào và dấu kiểm tra SHA-256 nằm trong [manifest.json](../../data_platform/station_planning/demo_hcmc_v3/manifest.json). `ref.kml` bị loại khỏi đầu vào; UrbanEVDataset không được dùng để tạo bộ dữ liệu Planner này.

## 2. Vì sao tạo các demand node ở những vị trí đó?

### 2.1. Quy tắc chọn tọa độ

Trong mỗi phường, generator lấy các POI nằm trong ranh giới rồi chọn 3 điểm:

1. Tìm một điểm đại diện nằm bên trong polygon phường bằng `representative_point()`; đây không nhất thiết là tâm hình học.
2. Chọn POI gần điểm đại diện nhất làm node đầu tiên.
3. Chọn node tiếp theo tại POI có **khoảng cách tới node đã chọn gần nhất lớn nhất**. Lặp lại tới khi đủ 3 node.

Công thức chọn node tiếp theo:

```text
p_next = argmax_p min_a d(p, a)

p: POI trong phường
a: các node đã chọn trong phường
d: khoảng cách địa lý giữa hai tọa độ
```

Mục đích là tạo vài điểm phân bố trên địa bàn để thử tính nhu cầu và khả năng tiếp cận. **Số 3 là cấu hình cho demo**, không phải số cụm tối ưu tìm được từ dữ liệu. Node nằm trên tọa độ POI nguồn, nhưng vị trí đó chưa được chứng minh là nơi phát sinh nhiều lượt sạc.

### 2.2. Phân bổ POI và dân số

Mỗi POI được gán vào node gần nhất. POI thông thường có trọng số 1. Nếu một nhóm có `m` bản ghi bị đánh dấu có khả năng trùng, mỗi bản ghi nhận trọng số `1/m`, để cả nhóm chỉ đóng góp tổng trọng số 1. Đây là cách giảm ảnh hưởng trùng dữ liệu, chưa phải xác minh các bản ghi thuộc cùng một địa điểm.

Với mỗi node `i` trong phường:

```text
W_i   = tổng trọng số POI được gán vào node i
s_i   = (1 - alpha) / n + alpha × W_i / sum(W)
P_i   = dân số phường × s_i

n     = 3 node/phường
alpha = 0,40
```

Như vậy, **60% dân số được chia đều**, còn **40% phân bổ theo tỷ trọng POI**. Tổng các `s_i` trong một phường bằng 1, nên không cộng trùng dân số. `P_i` là dân số đại diện được phân bổ, không phải số người thực sống trong một vùng quanh tọa độ node.

Lý do dùng thành phần chia đều là vẫn phân bổ nhu cầu cho các điểm có ít POI trong nguồn. Thành phần POI tạo khác biệt không gian. Tỷ lệ 60/40 là lựa chọn minh họa chưa được hiệu chỉnh; generator chưa dùng trọng số riêng theo sức hút sạc của từng loại POI.

### 2.3. Công thức lượng nhu cầu

Nhu cầu kỳ vọng của node `i` trong một khoảng 30 phút `t`:

```text
lambda(i,t) = P_i × v × e × (1 - h) × r × k × u(t) × a(hour(t)) / sum(a) / 2
```

| Ký hiệu | Giá trị | Ý nghĩa |
|---|---:|---|
| `P_i` | Dân số phân bổ theo công thức trên | Dân số đại diện cho node |
| `v` | 0,08 xe/người | Số xe giả định trên đầu người |
| `e` | 0,12 | Tỷ lệ xe điện giả định |
| `h` | 0,35 | Tỷ lệ có khả năng sạc tại nhà giả định |
| `1 - h` | 0,65 | Phần dùng để ước lượng nhu cầu sạc ngoài nhà |
| `r` | 0,25 lượt/xe điện/ngày | Tần suất sạc giả định |
| `k` | Thấp: 0,6; thông thường: 1; cao: 1,6 | Hệ số kịch bản nhu cầu |
| `u(t)` | Thứ Hai–Thứ Sáu: 1; Thứ Bảy–Chủ Nhật: 1,15 | Hệ số cuối tuần |
| `a(hour)` | Dãy trọng số dưới đây | Phân bố nhu cầu theo giờ |
| `sum(a)` | 24,49 | Chuẩn hóa trọng số giờ |
| Chia cho 2 | Hai khoảng 30 phút mỗi giờ | Giữ đúng tổng nhu cầu ngày |

Trọng số giờ, theo thứ tự 00 giờ đến 23 giờ:

```text
[0.20, 0.15, 0.12, 0.10, 0.12, 0.30, 0.70, 1.50,
 1.80, 1.50, 1.20, 1.30, 1.60, 1.20, 1.00, 1.20,
 1.50, 2.00, 2.20, 1.80, 1.30, 0.90, 0.50, 0.30]
```

Các giờ cao điểm và mức tăng cuối tuần chỉ tạo hình dạng chuỗi để thử nghiệm. Chúng chưa được rút ra từ lịch sử sạc của khu vực.

Tổng nhu cầu một ngày thường là `P_i × 0,00156 × k`. Tổng một tuần mẫu gồm 5 ngày thường và 2 ngày cuối tuần:

```text
Q_i = P_i × 0,00156 × (5 + 2 × 1,15) × k
    = P_i × 0,00156 × 7,3 × k
```

Ví dụ node `demand-hcm_2025_26737-01` ở phường Tân Định:

- Dân số phường trong nguồn: 48.524 người.
- Trọng số POI của 3 node: 209, 58, 34; tổng 301.
- `s_1 = 0,6/3 + 0,4 × 209/301 ≈ 0,477741`.
- `P_1 ≈ 23.181,898` người; nhu cầu thông thường khoảng **263,995 lượt/tuần**.
- Nhu cầu thấp/cao tương ứng khoảng **158,397 / 422,393 lượt/tuần**.

Tổng kỳ vọng của 27 node, cộng từ `expected_sessions` trong snapshot:

| Kịch bản | Tổng lượt kỳ vọng/tuần |
|---|---:|
| Thấp | 4.606,353 |
| Thông thường | 7.677,254 |
| Cao | 12.283,607 |

`expected_sessions` được làm tròn 6 chữ số thập phân ở từng khoảng 30 phút; cộng các dòng CSV có thể lệch rất nhỏ so với tính trực tiếp bằng công thức tuần.

### 2.4. Kỳ vọng và phiên được sinh ngẫu nhiên khác nhau

Generator sinh số phiên bằng `session_count ~ Poisson(lambda)`. Vì thế tổng phiên ngẫu nhiên có thể khác tổng kỳ vọng: ở mức thông thường, snapshot có **7.615 yêu cầu được sinh**, trong khi tổng kỳ vọng là khoảng **7.677,254 lượt**.

Planner và heatmap dùng **tổng `expected_sessions`**, không dùng số yêu cầu ngẫu nhiên để thay đổi nhu cầu giữa các lần bấm đánh giá. Ba kịch bản là mức giả định để phân tích độ nhạy, không phải khoảng tin cậy hay phân vị của mô hình dự báo.

Code tương ứng: [prepare_station_planning_demo.py](../../scripts/prepare_station_planning_demo.py), phần tạo `nodes` và `demand_rows`. Dữ liệu đối chiếu: [demand_nodes.csv](../../data_platform/station_planning/demo_hcmc_v3/demand_nodes.csv), [demand_intervals.csv](../../data_platform/station_planning/demo_hcmc_v3/demand_intervals.csv).

## 3. Quy tắc tạo các địa điểm ứng viên

Ứng viên được tạo **độc lập với demand node và điểm xếp hạng của Planner**. Generator dùng POI và các điểm hạ tầng giao thông trong pilot; chưa tìm vị trí tối ưu bằng demand prediction.

| Tham số | Giá trị | Mục đích trong demo |
|---|---:|---|
| Số ứng viên/phường | 2 | Giữ bộ so sánh nhỏ: 18 ứng viên cho 9 phường |
| Khoảng cách tối thiểu tới trạm hiện hữu | 150 m | Tránh lấy điểm quá sát fixture trạm hiện có |
| Khoảng cách giữa ứng viên | 250 m | Hạn chế các vị trí thử nghiệm bị tập trung sát nhau |
| Bán kính đếm điểm giao thông | 500 m | Tạo tín hiệu ngữ cảnh hạ tầng quanh ứng viên |
| Ngưỡng gắn nhãn giao thông cao | 20 điểm | Gán nhãn `high` khi có ít nhất 20 điểm giao thông trong bán kính |
| Loại địa điểm được đưa vào tập chọn | Bãi xe, trung tâm thương mại, siêu thị, khách sạn, khu du lịch, bến xe/trạm dừng | Các nhóm được cấu hình để dựng giả thuyết địa điểm |

Các giá trị 150 m, 250 m, 500 m và 20 điểm là **ngưỡng minh họa**, không phải quy chuẩn pháp lý hoặc ngưỡng tối ưu đã được kiểm chứng.

### 3.1. Lọc và chọn lần lượt

1. Chỉ giữ điểm thuộc nhóm loại địa điểm được phép và nằm trong ranh giới pilot.
2. Tính khoảng cách tới trạm hiện hữu gần nhất; bỏ điểm có khoảng cách dưới 150 m.
3. Duyệt các phường theo thứ tự mã phường. Mỗi phường chọn hai vị trí:
   - Vị trí thứ nhất: ưu tiên khoảng cách tới trạm gần nhất lớn nhất, nhằm đại diện cho khoảng trống trạm hiện có.
   - Vị trí thứ hai: ưu tiên số điểm giao thông trong bán kính 500 m lớn nhất; nếu bằng nhau thì ưu tiên xa trạm hiện hữu hơn.
4. Trong danh sách đã sắp xếp, lấy điểm đầu tiên cách **tất cả ứng viên đã chọn**, kể cả ở phường khác, ít nhất 250 m.
5. Nếu các tiêu chí bằng nhau, dùng mã `feature_id` để giữ thứ tự xác định. Nếu không đủ điểm thỏa điều kiện, generator báo lỗi thay vì tự tạo tọa độ mới.

Biểu diễn quy tắc:

```text
g(p)    = min_s d(p, s)                          # trạm hiện hữu s
c500(p) = số điểm giao thông có d(p, q) <= 500 m

Tập hợp lệ: loại địa điểm phù hợp, trong pilot, g(p) >= 150 m
Ứng viên thứ nhất: sắp theo g(p) giảm dần, rồi feature_id tăng dần
Ứng viên thứ hai: sắp theo c500(p) giảm dần, g(p) giảm dần, rồi feature_id tăng dần
Điều kiện lấy điểm: d(p, c) >= 250 m với mọi ứng viên c đã chọn
```

Khoảng cách `d` dùng công thức Haversine với bán kính Trái Đất `6.371.008,8 m`. Đây là khoảng cách địa lý, không phải chiều dài đường đi.

Nhãn giao thông cao chỉ nói rằng có nhiều **điểm hạ tầng** trong nguồn. Nó không phải lưu lượng xe đo được và không tự cộng điểm giao thông vào bộ xếp hạng hiện tại. Generator dùng cách chọn lần lượt; thứ tự phường và các vị trí đã chọn có thể ảnh hưởng kết quả, chưa có bài toán tối ưu đồng thời tất cả vị trí.

### 3.2. Vì sao phần lớn ứng viên là khách sạn?

Theo nhãn loại địa điểm trong snapshot, có **14 khách sạn, 3 bãi xe và 1 siêu thị**. Kết quả phản ánh tập POI đầu vào, các nhóm được phép và quy tắc khoảng cách/ngữ cảnh. Chưa có cơ sở kết luận khách sạn là nhóm phù hợp nhất để xây trạm. Một số tên POI có thể chưa thống nhất với nhãn loại địa điểm; cần kiểm tra nguồn trước khi dùng thực tế.

Mọi ứng viên vẫn là giả thuyết địa điểm: `eligibility = conditional`. Các trường đất, lối vào, nguồn điện, giấy phép và tương thích đầu nối chưa có bằng chứng xác minh.

Code: [prepare_station_planning_demo.py](../../scripts/prepare_station_planning_demo.py), phần `pool_by_ward` và `candidates`. Kết quả: [candidate_sites.csv](../../data_platform/station_planning/demo_hcmc_v3/candidate_sites.csv).

## 4. Thời gian tiếp cận và độ phủ

Ma trận tiếp cận nối mọi demand node với mọi trạm hiện hữu và ứng viên, kể cả khác phường: `27 × (37 + 18) × 3 = 4.455` dòng cho ba tốc độ giả định.

```text
d_proxy_km = d_geographic_m × 1,3 / 1000
t_minutes = d_proxy_km / speed_kmh × 60 + 2
```

| Tham số | Giá trị |
|---|---:|
| Hệ số tăng khoảng cách | 1,3 |
| Thời gian tiếp cận cố định | 2 phút |
| Tốc độ nhanh / thông thường / chậm | 25 / 20 / 12 km/h |
| Profile Planner đang dùng | `normal`: 20 km/h |
| Ngưỡng mặc định | 15 phút; người dùng có thể đổi, ví dụ 5 phút |

Ví dụ: khoảng cách địa lý 1 km tương ứng `1 × 1,3 / 20 × 60 + 2 = 5,9 phút` ở profile thông thường. Hệ số 1,3 mô phỏng đường đi vòng; 2 phút mô phỏng phần tiếp cận cố định. Chúng chưa được hiệu chỉnh bằng thời gian đi thực tế, không xét đường một chiều, cầu, ùn tắc hoặc khả năng vào địa điểm.

Với ngưỡng `T`:

```text
E(T) = các node có thời gian tới ít nhất một trạm hiện hữu <= T
C_j(T) = các node có thời gian tới ứng viên j <= T
D = tổng nhu cầu kỳ vọng của toàn bộ node có dữ liệu

Nhu cầu tiếp cận được của ứng viên j = sum(Q_i, i thuộc C_j)
Nhu cầu được phủ thêm bởi j = sum(Q_i, i thuộc C_j nhưng không thuộc E)
Độ phủ tăng thêm (%) = nhu cầu được phủ thêm / D × 100
Nhu cầu ngoài ngưỡng (%) = sum(Q_i, i không thuộc E) / D × 100
```

Tỷ lệ được tính theo **lượng nhu cầu**, không theo số node. Ở kịch bản thông thường và ngưỡng 5 phút, snapshot có khoảng **1.223,829 lượt/tuần ngoài ngưỡng**, tương ứng **15,941%**. Ở ngưỡng 15 phút, fixture phủ hết nhu cầu nên độ phủ tăng thêm của các ứng viên bằng 0; điều đó không chứng minh toàn địa bàn thực tế đã được phục vụ đủ.

Ma trận này kiểm tra khả năng tiếp cận theo giả định, chưa tính trạm đầy, đóng cửa, hỏng cổng hoặc tương thích xe. Code: [rules.py](../../data_platform/station_planning/rules.py); dữ liệu: [access_matrix.csv](../../data_platform/station_planning/demo_hcmc_v3/access_matrix.csv).

## 5. Tạo ứng viên khác với xếp hạng ứng viên

Generator tạo sẵn 18 ứng viên. Khi bấm đánh giá, Planner chỉ xếp hạng tập ứng viên người dùng đang chọn; mặc định là ba mã `cand-hcm_2025_26911-02`, `cand-hcm_2025_26929-01`, `cand-hcm_2025_27073-01`.

Các trọng số kỹ thuật cấu hình sẵn:

| Tiêu chí | Trọng số | Trạng thái trong snapshot hiện tại |
|---|---:|---|
| Nhu cầu sạc tiếp cận được | 30% | Tính từ nhu cầu mô phỏng |
| Nhu cầu được phủ thêm | 25% | Tính từ nhu cầu và ma trận tiếp cận |
| Điều kiện mặt bằng và nguồn điện | 20% | Chưa đủ bằng chứng để chấm |
| Phù hợp với khu vực/mạng lưới | 15% | Chưa đủ bằng chứng để chấm |
| Khoảng trống trạm hiện có | 10% | Tỷ lệ nhu cầu trong vùng tiếp cận ứng viên chưa được trạm hiện hữu phủ |

Điểm nhu cầu được chuẩn hóa trong tập ứng viên đang đánh giá:

```text
S_demand(j) = 100 × (D_j - D_min) / (D_max - D_min)
Nếu D_max = D_min, điểm thành phần này là 50.
```

`D_j` là nhu cầu tiếp cận được của ứng viên, không phải doanh số hoặc số lượt chắc chắn sẽ ghé trạm đó. Điểm nhu cầu có thể thay đổi khi đổi tập ứng viên.

Điểm độ phủ tăng thêm chính là tỷ lệ ở mục 4. Điểm khoảng trống là `100 × nhu cầu chưa được phủ trong C_j / tổng nhu cầu trong C_j`; nếu mẫu số bằng 0 thì thành phần này chưa xác định.

Điểm tổng loại các thành phần chưa có dữ liệu khỏi cả tử số và mẫu số:

```text
Score(j) = sum(w_l × S_l(j)) / sum(w_l), với l là các thành phần đã có điểm
```

Ở snapshot hiện tại, ba thành phần có dữ liệu đầy đủ có tổng trọng số `30 + 25 + 10 = 65`. Ví dụ điểm thành phần `100, 0, 0` cho điểm tổng `30 × 100 / 65 ≈ 46,154`, không phải 30 hoặc 100.

Ngưỡng tỷ trọng bằng chứng tối thiểu là **0,6**. Công thức tổng quát là `sum(w_l × evidence_fraction_l) / 100` cho các thành phần đã có điểm; đây không phải xác suất thành công. Engine chỉ xếp hạng nhóm có thành phần và mức bằng chứng tương thích, đạt ngưỡng này. Trong fixture hiện tại tỷ trọng là 0,65. Thành phần chưa có dữ liệu không được tự gán 0; điều kiện vật lý chưa xác minh không được coi là đã đạt.

Chi phí không nằm trong điểm tổng hiện tại. Cấu hình **DC 4 cổng × 80 kW = 320 kW** là cấu hình người dùng chọn để thử, chưa phải công suất tối ưu do mô hình tìm ra. Mục tiêu sử dụng công suất 0,8 có trong package nhưng chưa được dùng để tối ưu quy mô trạm trong demo này.

Code: [recommendation_engine.py](../../backend/app/planning/recommendation_engine.py); bộ tham số: [technical_constraints_package.json](../../data_platform/station_planning/demo_hcmc_v3/technical_constraints_package.json).

## 6. Chi phí mô phỏng

Chi phí đầu tư ban đầu được tạo theo công thức:

```text
CAPEX = (số cổng × chi phí thiết bị/cổng + chi phí mặt bằng + chi phí đấu nối) × f
```

| Khoản mục | Giá trị cơ sở |
|---|---:|
| Số cổng tham chiếu | 4 |
| Thiết bị mỗi cổng | 250.000.000 đồng |
| Chuẩn bị/lắp đặt mặt bằng | 100.000.000 đồng/trạm |
| Đấu nối | 80.000.000 đồng/trạm |
| Tổng đầu tư | **1.180.000.000 đồng/trạm** |
| Hệ số chi phí thấp / cơ sở / cao `f` | 0,8 / 1 / 1,25 |
| Tổng tương ứng | 944.000.000 / 1.180.000.000 / 1.475.000.000 đồng |

Cả 18 ứng viên dùng cùng giả định nên chi phí cơ sở bằng nhau. Planner hiện đọc `base_cost` đã tính từ CSV khi cấu hình khớp **DC 4 × 80 kW**. Đổi loại sạc, số cổng hoặc công suất sẽ trả chi phí chưa xác định; API chưa tự nhân lại chi phí theo cấu hình mới.

File cũng có chi phí thuê 120 triệu/năm, vận hành cố định 60 triệu/năm và bảo trì bằng 3% vốn thiết bị, tức 30 triệu/năm ở mức cơ sở. Tổng là **210 triệu đồng/năm, chưa gồm điện**. Các khoản hằng năm chưa được cộng vào chi phí đầu tư đang hiển thị.

Ngân sách 10 tỷ đồng trong package là tham chiếu cho tập nhiều trạm. Planner hiện chỉ kiểm tra ngân sách **mỗi địa điểm** nếu người dùng nhập giới hạn riêng; chưa chọn danh mục trạm theo tổng ngân sách. Package còn có giá bán giả định 6.500 đồng/kWh, tỷ lệ chiết khấu 10% và giới hạn hoàn vốn 7 năm; demo Planner chưa tính doanh thu, lợi nhuận, NPV hay hoàn vốn từ chúng. Ba mức chi phí độc lập với ba mức nhu cầu.

Nguồn: [candidate_cost_assumptions.csv](../../data_platform/station_planning/demo_hcmc_v3/candidate_cost_assumptions.csv), [finance_package.json](../../data_platform/station_planning/demo_hcmc_v3/finance_package.json). Cách API chọn chi phí: [repository.py](../../backend/app/planning/repository.py), hàm `_candidate_cost`.

## 7. Phần mô phỏng phiên sạc và vận hành

Phần này tạo thêm dữ liệu vận hành để kiểm tra hệ thống; nó không thay thế tổng nhu cầu kỳ vọng mà Planner đang sử dụng.

| Tham số | Giá trị giả định |
|---|---:|
| Năng lượng mỗi yêu cầu | Lấy mẫu phân phối chuẩn, trung bình 26 kWh, độ lệch chuẩn 6 kWh |
| Giới hạn năng lượng | Chặn trong khoảng 8–38 kWh; không phải phân phối chuẩn cắt cụt được lấy mẫu lại |
| Công suất sạc mỗi cổng | 80 kW cố định |
| Xác suất toàn trạm ngừng phục vụ mỗi khoảng khi đang mở cửa | 3% |
| Xác suất hỏng mỗi cổng trong nhánh còn hoạt động | 4% |
| Giới hạn chờ | 60 phút; yêu cầu bị bỏ khi thời gian chờ vượt ngưỡng |
| Hiệu suất điện giả định | 0,93 |

Yêu cầu được gán ngẫu nhiên cho trạm **cùng phường**, với xác suất tỷ lệ theo số cổng. Quy tắc này khác ma trận tiếp cận có các cặp khác phường; không phải hành vi chọn trạm theo tuyến đường của người lái. Mỗi cổng phục vụ tối đa một yêu cầu trong một khoảng 30 phút; thời lượng sạc là `năng lượng / 80 × 60` phút. Mô hình chưa mô phỏng đường cong giảm công suất theo pin.

Chi phí điện trong dữ liệu vận hành dùng `điện lấy từ lưới = điện giao cho xe / 0,93`, rồi nhân giá theo khung giờ của bảng giá tham chiếu lịch sử. Cấp điện áp `< 6 kV` là giả định; không xác nhận hợp đồng điện thực tế của trạm. Một tuần mô phỏng không được tự nhân thành dự báo tài chính năm.

## 8. Đọc heatmap và kết quả đúng phạm vi

- Demand node được giữ trong dữ liệu để tính toán, nhưng giao diện chỉ vẽ vùng màu làm mượt; không hiển thị chấm demand.
- Vàng → đỏ thể hiện mức tập trung nhu cầu tương đối. Vùng màu không phải mật độ dân cư đã đo, ranh giới phục vụ hoặc bằng chứng có nhu cầu cao tại mọi tọa độ được tô.
- Goong dùng lớp heatmap theo trọng số nhu cầu; OSM dự phòng dùng canvas. Cường độ/vùng chồng màu còn phụ thuộc cách làm mượt và mức zoom. Không đọc màu như một giá trị lượt sạc chính xác cho từng tọa độ.
- Thang tham chiếu giữ theo bộ dữ liệu đầy đủ khi đổi kịch bản hoặc lọc vùng xa trạm. Đổi ngưỡng tiếp cận không tự đổi lượng nhu cầu; bộ lọc chỉ giữ các node có thời gian đến trạm hiện hữu gần nhất lớn hơn ngưỡng.
- Cần đánh giá lại sau khi đổi ngưỡng để cập nhật độ phủ và thứ hạng. Ẩn node khỏi bản đồ không xóa chúng khỏi phép tính.
- Thứ hạng là so sánh trong tập địa điểm và kịch bản hiện tại. Chưa có demand prediction từ dữ liệu thực, tối ưu vị trí toàn cục, tối ưu danh mục đầu tư hoặc xác nhận khả thi xây dựng.

## 9. Đối chiếu và tái lập

| File | Vai trò |
|---|---|
| [generation_config.json](../../data_platform/station_planning/demo_hcmc_v3/generation_config.json) | Các giá trị đã dùng để tạo snapshot |
| [station_planning_demo.json](../../config/station_planning_demo.json) | Cấu hình đầu vào cho lần tạo lại |
| [prepare_station_planning_demo.py](../../scripts/prepare_station_planning_demo.py) | Quy tắc sinh dữ liệu |
| [rules.py](../../data_platform/station_planning/rules.py) | Khoảng cách, thời gian tiếp cận và điều kiện demo |
| [validation_report.json](../../data_platform/station_planning/demo_hcmc_v3/validation_report.json) | Kết quả kiểm tra cấu trúc, số lượng, khoảng cách và bảo toàn dữ liệu |
| [repository.py](../../backend/app/planning/repository.py) | Đọc file, cộng nhu cầu tuần và ánh xạ đầu vào Planner |
| [demandHeatmap.ts](../../frontend/src/planning/demandHeatmap.ts) | Giá trị heatmap, tỷ lệ ngoài ngưỡng và bộ lọc |

Có thể kiểm tra bộ dữ liệu hiện có từ thư mục gốc repo:

```powershell
python scripts/validate_station_planning_demo.py
python scripts/validate_station_planning_contract.py
```

Kiểm tra đạt chỉ xác nhận dữ liệu nhất quán với các quy tắc demo; không xác nhận nhu cầu, giá thành hay khả thi ngoài thực tế. Khi chủ động tạo lại bằng `prepare_station_planning_demo.py`, cần giữ cấu hình, nguồn và phiên bản dependency tương ứng để đối chiếu snapshot; lệnh tạo lại ghi các file đầu ra.

Các lý do và ngưỡng trong tài liệu này là giải thích mục đích của cấu hình hiện hành. Chúng không phải kết quả tối ưu hoặc hệ số đã học từ dữ liệu thực. Để sử dụng cho quy hoạch thực tế, cần thay hoặc hiệu chỉnh các giả định bằng dữ liệu và xác minh chuyên môn phù hợp.
