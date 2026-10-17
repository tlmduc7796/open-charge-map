# Mô phỏng tải trạm trên bản đồ Planner

Phiên bản mô hình: `ward-relief-v3`. Đầu vào cao điểm: `peak-load-demo-v1`. Dữ liệu: `hcmc-nine-wards-demo-v3`.

## Mục đích và cách dùng

Màu của trạm hiện hữu thể hiện áp lực nhu cầu tại một khung 30 phút cao điểm giả lập. Chọn mức nhu cầu, chọn ứng viên rồi bấm **Đánh giá địa điểm**. **Sau bổ sung** giả sử tất cả ứng viên được xếp hạng cùng được mở với cấu hình cổng đang đánh giá và có điều phối giảm tải sang trạm mới. Nút **Trước bổ sung** cho phép đối chiếu cùng lượng khách, cùng khung giờ và cùng phạm vi tiếp cận.

Chọn ứng viên trong danh sách chỉ hiện marker, chưa thêm năng lực phục vụ. Ứng viên bị loại hoặc chưa có thứ hạng không được tính thành trạm mới. Thay đổi đầu vào xóa kết quả đánh giá cũ và đưa mạng về hiện trạng; cần đánh giá lại để mô phỏng bổ sung. Ẩn marker trạm hiện hữu hoặc lọc vùng heatmap chỉ thay đổi hình ảnh, không loại nhu cầu hay công suất khỏi phép tính.

Có thể đọc toàn bộ phép tính theo chuỗi: **nhu cầu kỳ vọng tại các node → phân bổ về trạm hiện hữu → so với năng lực phục vụ → chuyển một phần khách sang trạm mới cùng phường → tính lại tải và màu**. Mô hình không gán sẵn màu đỏ cho trạm gần vùng nóng rồi đổi sang xanh sau khi bấm đánh giá; màu được suy ra từ lượng nhu cầu và năng lực sau từng bước.

## Dữ liệu sử dụng

- `demand_intervals.csv`: số phiên **kỳ vọng** của 27 node, mỗi 30 phút, theo ba kịch bản. Với từng kịch bản, lấy khung có tổng nhu cầu của cả khu vực lớn nhất; nếu bằng nhau lấy thời điểm sớm nhất. Lấy giá trị của mọi node **tại cùng khung đó**, không ghép các cực đại ở những thời điểm khác nhau.
- `existing_sites.csv`: tọa độ, mã phường (`unit_id`), số cổng và công suất tổng của 37 trạm.
- `candidate_sites.csv`: tọa độ và mã phường ứng viên; số cổng và công suất lấy từ request đã đánh giá. Tên phường lấy từ `pilot_units.geojson`, hiển thị trong danh sách và popup, tìm kiếm được theo tên phường.
- `generation_config.json`, `access_model.json`, `technical_constraints_package.json`: tham số gốc đã kiểm tra hash theo manifest. Snapshot, CSV và hàm xếp hạng không bị sửa để tạo ra kết quả mong muốn.

Mô phỏng tải đọc **số phiên kỳ vọng đã có trong CSV**, không tự sinh thêm khách từ màu heatmap, số cổng hoặc điểm xếp hạng. Dữ liệu này là một tuần giả lập; không lấy số xe đang sạc trực tiếp, số phiên thực tế trong database hoặc dữ liệu dự báo thời gian thực.

## Ký hiệu và nguồn tham số

Trong các công thức dưới đây, `i` là node nhu cầu, `j` là trạm hiện hữu và `k` là trạm mới:

| Ký hiệu | Ý nghĩa | Đơn vị |
|---|---|---|
| `q_i` | Nhu cầu kỳ vọng tại node `i` trong khung được chọn | lượt/30 phút |
| `q_ij` | Phần nhu cầu của node `i` được phân bổ cho trạm `j` | lượt/30 phút |
| `Q_j = tổng_i(q_ij)` | Tổng nhu cầu đang giao cho trạm `j` | lượt/30 phút |
| `n_j`, `P_j` | Số cổng và công suất **tổng trạm** | cổng, kW |
| `C_j` | Năng lực phục vụ tương đương của trạm trong một khung | lượt/30 phút |
| `t_ij` | Thời gian di chuyển từ node tới trạm, chưa cộng thời gian vào trạm | phút |
| `u_j = Q_j / C_j` | Tỷ lệ nhu cầu trên năng lực; nhân 100 để hiển thị phần trăm | tỷ lệ |
| `α = 0,8` | Mục tiêu tải sau điều phối và giới hạn nhận tải của trạm mới | tỷ lệ |

Các file cấu hình trong bảng sau đều thuộc `data_platform/station_planning/demo_hcmc_v3/`:

| Tham số | Giá trị hiện tại | Nguồn và cách sử dụng |
|---|---|---|
| Độ dài khung `Δ` | 30 phút | `generation_config.json#/calendar/interval_minutes` |
| Điện năng trung bình `E` | 26 kWh/phiên | `generation_config.json#/demand/energy_per_session_mean_kwh`; dùng giá trị trung bình, không bốc ngẫu nhiên điện năng từng xe |
| Hiệu suất `η` | 0,93 | `generation_config.json#/operations/grid_delivery_efficiency` |
| Hệ số vòng đường | 1,3 | `access_model.json#/circuity_factor`; nhân khoảng cách cung lớn để ước lượng đường đi |
| Tốc độ | 20 km/h | `access_model.json#/speed_kmh_by_profile/normal`; mô phỏng này dùng profile nền `normal`, không đổi tốc độ khi đổi mức nhu cầu |
| Thời gian vào trạm | 2 phút | `access_model.json#/fixed_access_minutes`; chỉ cộng khi kiểm tra ngưỡng tiếp cận |
| Ngưỡng nhóm trạm gần | 2 phút di chuyển | Quy tắc demo được đặt trong `repository.py::_load_simulation_inputs` theo yêu cầu ưu tiên trạm gần; không phải số đo hành vi |
| Thời gian tiếp cận tối đa | Mặc định 15 phút | Giá trị hiện tại trên form, truyền qua `technical.coverage_minutes`; người dùng có thể đổi |
| Thời gian phục vụ tối thiểu | 30 phút | Backend đặt bằng độ dài khung; phù hợp giả định `operations.charging_model` của fixture |
| Mục tiêu tải `α` | 80% | `technical_constraints_package.json#/capacity_target/maximum_utilization`; mục tiêu minh họa, chưa hiệu chỉnh từ vận hành thực tế |
| Cấu hình trạm mới | Mặc định 4 cổng × 80 kW/cổng | Cấu hình người dùng gửi để đánh giá; `P_k = số_cổng × kW_mỗi_cổng` |
| Hệ số làm trơn khoảng cách | 0,5 phút | Hằng số trong `stationLoad.ts::assignDemand`, tránh trọng số vô hạn khi trùng tọa độ |
| Số mũ suy giảm theo thời gian | 2 | Quy tắc demo trong trọng số `1 / (t + 0,5)^2`; ưu tiên trạm gần, chưa khớp theo dữ liệu lựa chọn của tài xế |
| Ngưỡng quá tải cao | Trên 125% | Quy ước phân màu trong `stationLoad.ts::loadLevel`; không phải một ngưỡng an toàn điện |

**Cơ sở của mô hình:** quan hệ điện năng/công suất cho thời gian sạc, tỷ lệ nhu cầu/năng lực và phép cộng–trừ bảo toàn nhu cầu là các phép tính có ý nghĩa vật lý hoặc số học. Cách chia khách theo trọng số, nhóm gần 2 phút, giới hạn cùng phường, mục tiêu 80% và các mức màu là **quy tắc thiết kế cho demo**. Việc một giá trị có sẵn trong cấu hình không biến nó thành thông số đã được đo hoặc kiểm định thực nghiệm. Phần mô phỏng này chưa phải mô hình hàng đợi hay một công thức dự báo hành vi đã được hiệu chỉnh theo paper.

## Chọn nhu cầu cao điểm như thế nào?

Với từng kịch bản `s`, backend đọc toàn bộ các khung của tuần và tính:

`D_s(t) = tổng_i q_i,s(t)`.

Chọn `t*_s` có `D_s(t)` lớn nhất; nếu nhiều khung bằng nhau thì lấy khung sớm nhất. Đầu vào mô phỏng là `q_i = q_i,s(t*_s)` của cả 27 node tại đúng khung đó. Không lấy nhu cầu cả tuần chia đều cho số khung và không ghép cực đại riêng của từng node.

Trên snapshot hiện tại, cả ba kịch bản cùng chọn **18:00–18:30 ngày 12/07/2025, giờ Việt Nam**:

| Kịch bản | Tổng nhu cầu kỳ vọng của 27 node trong khung |
|---|---|
| Thấp (`low`) | 32,593878 lượt |
| Thông thường (`base`) | 54,323134 lượt |
| Cao (`high`) | 86,917011 lượt |

Đây là thời điểm trong lịch giả lập của bộ dữ liệu, không phải số liệu ngày đang chạy demo. Mỗi kịch bản vẫn tìm cao điểm độc lập; không mặc định lúc nào cũng là 18:00. Kịch bản Thấp/Cao được sinh với hệ số 0,6/1,6 so với nền trong cấu hình sinh dữ liệu; mô phỏng tải đọc trực tiếp các dòng CSV đã làm tròn nên tổng có thể lệch rất nhỏ so với phép nhân lại.

## Quy tắc phân bổ

Khoảng cách cung lớn Haversine với bán kính Trái Đất 6.371,0088 km:

`t_di_chuyển = khoảng_cách_km × 1,3 / 20 × 60`.

Đây là ước lượng hình học với tốc độ cố định, không phải thời gian đi đường do Goong trả về. Bản đồ nền không biến phép tính này thành định tuyến theo đường thật; sông, cầu, đường một chiều và ùn tắc chưa được xét riêng. Với ngưỡng trên form là `T`, điều kiện tiếp nhận là `t_di_chuyển + 2 ≤ T`, áp dụng từ **node gốc tới từng trạm**, không đo từ trạm cũ tới trạm mới.

Nhóm **gần** gồm các trạm cách node tối đa **2 phút di chuyển**. Khoản **2 phút vào trạm** của access proxy cũ được cộng riêng khi kiểm tra ngưỡng tiếp cận trên form; không cộng nó vào mốc 2 phút di chuyển. Ví dụ: đi 1,5 phút và vào trạm 2 phút có tổng thời gian tiếp cận 3,5 phút.

1. Chỉ xét trạm có công suất/số cổng hợp lệ và tổng thời gian tiếp cận không vượt ngưỡng trên form.
2. Nếu có trạm trong 2 phút di chuyển, chia nhu cầu cho nhóm này; nếu không, chia cho các trạm trong ngưỡng tiếp cận.
3. Trọng số của trạm `j`: `w_j = C_j / (t_j + 0,5)^2`. `0,5 phút` là hệ số làm trơn mới cho demo, tránh chia cho 0 tại node trùng tọa độ; chưa được hiệu chỉnh bằng hành vi tài xế.
4. Nhu cầu node tới trạm `j`: `q_ij = q_i × w_j / tổng(w)`. Mỗi node được chia đúng một lần. Không có trạm tiếp nhận thì nhu cầu được ghi là **chưa phân bổ**; không âm thầm bỏ nó.

Trọng số thực tế là `w_ij` vì mỗi node có khoảng cách tới trạm khác nhau. Sau khi chia từng node, cộng `Q_j = tổng_i q_ij` để ra tải đầu vào của trạm. Điều kiện cùng phường **chưa áp dụng ở bước hiện trạng**; một node có thể đang được phục vụ bởi trạm bên kia ranh giới nếu thỏa điều kiện khoảng cách.

Ví dụ sau **chỉ minh họa công thức**, không phải một dòng dữ liệu đo được: một node có 4 lượt kỳ vọng, có hai trạm đều nằm trong nhóm gần và thỏa ngưỡng tiếp cận:

| Trạm | Năng lực `C` | Di chuyển `t` | Trọng số `C / (t + 0,5)^2` | Nhu cầu nhận | Mức tải |
|---|---|---|---|---|---|
| A | 1 lượt/khung | 0,5 phút | `1 / 1^2 = 1` | `4 × 1 / 2 = 2` lượt | 200% |
| B | 4 lượt/khung | 1,5 phút | `4 / 2^2 = 1` | `4 × 1 / 2 = 2` lượt | 50% |

Hai trạm nhận tổng cộng đúng 4 lượt. Trạm A vẫn bị tính 200% dù B còn dư năng lực: hiện trạng mô tả một cách phân bổ có ưu tiên khoảng cách, chưa chủ động điều phối lại giữa các trạm cũ. **Không cắt nhu cầu của A xuống 1 lượt** vì làm vậy sẽ khiến phần áp lực biến mất khỏi mô phỏng.

Đây là mô hình phân bổ hiện trạng theo khoảng cách và năng lực, không phải dự báo lựa chọn trạm. Quy tắc ưu tiên nhóm gần có bước chuyển tại 2 phút. Không điều phối giữa các trạm hiện hữu trong bước hiện trạng, nên vẫn có thể xảy ra mất cân đối cục bộ dù tổng công suất toàn vùng còn dư. Không mô phỏng lan truyền hàng đợi; phần vượt năng lực được giữ lại để nhìn thấy áp lực cục bộ.

## Năng lực và màu tải

Với trạm có `n_j` cổng và công suất tổng `P_j`, mô hình giả sử chia đều công suất:

`P_mỗi_cổng = P_j / n_j`.

Ví dụ, `existing_sites.csv` ghi 4 cổng và 320 kW thì công suất dùng để tính mỗi cổng là 80 kW. Với ứng viên mới, form nhập trực tiếp kW/cổng; mô hình nhân số cổng để ra công suất tổng trước khi dùng cùng công thức.

`thời_gian_phục_vụ = max(30, 26 / (P_mỗi_cổng × 0,93) × 60)` phút.

`C_j = số_cổng × 30 / thời_gian_phục_vụ` phiên mỗi khung.

`mức_tải = nhu_cầu_được_phân_bổ / C_j`.

- 26 kWh/phiên và hiệu suất 0,93 lấy từ cấu hình sinh dữ liệu.
- Mức sàn 30 phút phù hợp giả định fixture: mỗi cổng nhận tối đa một yêu cầu trong một slot 30 phút. Không suy ra khả năng sạc nối tiếp nhanh hơn từ phép chia điện năng đơn thuần.
- 80% là ngưỡng vận hành thoải mái trong technical package. **Vượt năng lực phục vụ của mô hình** chỉ bắt đầu khi lớn hơn 100%; đây không phải phép đo quá tải điện thực tế.

Ví dụ năng lực:

| Cấu hình | Thời gian từ điện năng/công suất | Thời gian dùng trong mô hình | Năng lực `C` |
|---|---|---|---|
| 1 cổng × 80 kW | `26 / (80 × 0,93) × 60 ≈ 20,97` phút | `max(30; 20,97) = 30` phút | 1 lượt/30 phút |
| 4 cổng × 80 kW | 20,97 phút/cổng | 30 phút/cổng | 4 lượt/30 phút |
| 1 cổng × 7 kW, ví dụ đối chiếu công thức | Khoảng 239,63 phút | 239,63 phút | Khoảng 0,1252 lượt/30 phút |

Dòng 7 kW cho thấy công suất thấp làm năng lực tương đương giảm. Đây không phải mô phỏng một phiên sạc dài qua nhiều khung; mô hình chỉ quy đổi về tốc độ phục vụ trung bình trong một khung tĩnh.

Ví dụ trạm có `C = 4` và `Q = 5` thì `u = 5 / 4 = 125%`, phần vượt năng lực là `5 - 4 = 1` lượt/khung. **125% không có nghĩa 125% số cổng thực tế đang cắm xe**; nó có nghĩa nhu cầu được giao bằng 1,25 lần năng lực của mô hình. Tương tự, 627% biểu thị áp lực nhu cầu gấp khoảng 6,27 lần năng lực, không phải occupancy thực đo vượt 100%. Các số lẻ là kỳ vọng thống kê, không phải một số xe nguyên đã đếm được.

| Màu trạm hiện hữu | Mức tải | Ý nghĩa |
|---|---|---|
| Xanh lá | ≤ 80% | Trong khả năng phục vụ |
| Hổ phách | > 80% đến 100% | Gần đầy tải |
| Đỏ | > 100% đến 125% | Quá tải |
| Đỏ sẫm | > 125% | Quá tải cao |
| Xám | Chưa xác định | Thiếu số cổng/công suất; không coi là 0% tải |

Marker trạm hiện hữu quá tải lớn hơn nhẹ để dễ thấy. Ứng viên giữ màu xanh biển/tím cho trạng thái chọn/xếp hạng; popup hiển thị mức tải giả định của trạm mới sau bổ sung.

## Sau bổ sung và giá trị so sánh

**Điểm xếp hạng không được dùng để nhân giảm tải.** Tạo phương án điều phối sang trạm mới, giữ nguyên tổng nhu cầu và nguồn gốc node:

1. Mở các ứng viên có thứ hạng, dùng cấu hình cổng của request. Giới hạn nhận thêm tại mỗi trạm mới là **80% năng lực** để giữ dự phòng.
2. Xét nhu cầu chưa phân bổ trước, sau đó xét trạm hiện hữu chịu tải cao hơn trước. Trạm hiện hữu chỉ chuyển phần trên mục tiêu **80% năng lực**; không rút hết khách khỏi trạm đang hoạt động bình thường.
3. Với nhu cầu đang thuộc trạm cũ, chỉ xét ứng viên có **cùng `unit_id` với trạm cũ**, đồng thời thỏa ngưỡng tổng thời gian tiếp cận trên form tính từ node nhu cầu gốc. Không áp trần 2 phút trong bước giảm tải này; mốc 2 phút chỉ dùng để mô phỏng ưu tiên trạm gần trong hiện trạng. Mã phường lấy từ trường dữ liệu gốc, không đoán theo tên hoặc chuỗi ID.
4. Khi node nhu cầu khác phường với trạm cũ (do vùng phục vụ qua ranh giới), điều kiện cùng phường vẫn so giữa **trạm cũ và trạm mới**. Với nhu cầu trước đó chưa phân bổ, xét phường của node gốc; phần này là tăng độ phủ, không ghi thành giảm tải trạm cũ. Thiếu mã phường thì không chuyển tải. Ưu tiên đường di chuyển ngắn; dùng thứ hạng ứng viên để phá hòa khi thời gian bằng nhau, sau đó dùng ID để tái lập.
5. Mỗi lần chuyển lấy giá trị nhỏ nhất của: phần nhu cầu node còn có thể chuyển, phần tải trạm cũ cần giảm, và khả năng tiếp nhận còn lại của ứng viên. Trừ đúng lượng ấy ở trạm cũ và cộng sang trạm mới.
6. Phần chưa chuyển được vẫn thuộc trạm cũ. Nhu cầu chưa được tiếp nhận vẫn được báo là chưa phân bổ. Không xóa nhu cầu, không tăng số cổng ngầm để đổi màu.

### Công thức mỗi lần chuyển tải

Với một phần nhu cầu gốc của node `i` đang thuộc trạm cũ `j` và ứng viên nhận `k`:

- `F_ij`: phần nhu cầu trong luồng `i → j` chưa chuyển đi.
- `R_j = max(0; Q_j,trước - α × C_j)`: lượng cần nhường để hướng trạm cũ về 80%; giá trị còn lại giảm sau mỗi lần chuyển.
- `B_k = max(0; α × C_k - Q_k,hiện_tại)`: khả năng nhận thêm của trạm mới mà vẫn giữ mức tối đa 80%.
- Nếu cùng phường và thỏa ngưỡng tiếp cận: `x_ijk = min(F_ij; R_j; B_k)`.
- Cập nhật `Q_j := Q_j - x_ijk`, `Q_k := Q_k + x_ijk`, đồng thời trừ `x_ijk` khỏi `F_ij` và `R_j` còn lại.

Với nhu cầu chưa phân bổ, không có trạm cũ để trừ tải: xét cùng phường với node, lấy `x_ik = min(F_i; B_k)`, rồi giảm lượng chưa phân bổ đúng bằng `x_ik`.

Thứ tự xử lý dùng mức tải **trước điều phối** để ưu tiên trạm cũ, không sắp xếp lại sau mỗi lần chuyển. Trong cùng mức ưu tiên, chọn thời gian di chuyển ngắn trước, tiếp đến thứ hạng ứng viên và ID để kết quả có thể tái lập. Mô hình chỉ chuyển từ trạm cũ/nhu cầu chưa phân bổ tới trạm mới; không chuyển giữa các trạm cũ hoặc giữa hai trạm mới.

Giới hạn 80% cũng có nghĩa một trạm cũ đang 90% có thể nhường một phần để về mục tiêu 80%, dù chưa được đếm là quá tải. Nếu nhu cầu chưa phân bổ dùng hết khả năng nhận của ứng viên trước, phần tải ở trạm cũ có thể không giảm.

Đây là thuật toán tham lam dựng **phương án điều phối giả định**, không bảo đảm tối ưu toàn cục hay dự báo tài xế tự chuyển trạm. Nó cần giả định có thể hướng dẫn người dùng tới trạm mới. Ứng viên ngoài ngưỡng tiếp cận hoặc công suất nhỏ có thể giúp ít hoặc không giúp; không ép tất cả trạm chuyển xanh sau đánh giá. Do chỉ chuyển vào phần năng lực còn trống của trạm mới, tổng nhu cầu vượt công suất của phương án này không được tăng so với hiện trạng.

Bảng mô phỏng hiển thị số trạm hiện hữu quá tải trước/sau. Đồng thời tính `tổng max(nhu_cầu_trạm - C_j, 0)` trên **toàn mạng, kể cả trạm mới** để không che việc chuyển quá tải từ trạm cũ sang ứng viên. Đây là nhu cầu vượt năng lực theo phân bổ tĩnh, chưa phải số khách bị từ chối thực tế. Popup có tải phần trăm và tên phường; báo cáo tải xuống có kết quả từng trạm, nhu cầu chưa phân bổ, luồng chuyển tải thực sự được chấp nhận (phường chung, node gốc, trạm cũ, ứng viên nhận, thời gian di chuyển, số phiên) và toàn bộ đầu vào để tái lập.

### Cách tính các chỉ số trên giao diện và báo cáo

| Chỉ số | Công thức/cách đếm | Cách đọc |
|---|---|---|
| Tổng nhu cầu `D` | `tổng_i q_i` | Giữ nguyên trước/sau trên cùng kịch bản và khung |
| Nhu cầu chưa phân bổ `U` | Tổng phần nhu cầu chưa giao được cho trạm có năng lực hợp lệ | Tách riêng khỏi phần vượt công suất tại trạm |
| Số trạm hiện hữu quá tải | Đếm trạm **hiện hữu** có `Q_j / C_j > 1` | Trạm mới không nằm trong số đếm này |
| Vượt công suất toàn mạng `E_mạng` | `tổng_trạm_có_C max(Q - C; 0)`, gồm cả trạm mới | Không lấy dư công suất ở nơi khác bù trừ để che quá tải cục bộ |
| Lượng tải chuyển | Tổng các `x` được chấp nhận | Gồm chuyển từ trạm cũ và tiếp nhận nhu cầu chưa phân bổ; cần xem nguồn từng luồng |

Hai đại lượng **chưa phân bổ** và **vượt công suất** khác nhau: `E_mạng = 0` vẫn có thể đi cùng `U > 0` nếu có nhu cầu ngoài vùng phục vụ. Khi đọc kết quả phải xem cả hai trong báo cáo. Trạm thiếu số cổng/công suất có `C` và tải là chưa xác định, không được đếm thành một trạm 0% tải; nhu cầu không giao được cho các trạm còn lại đi vào `U`.

Điều kiện bảo toàn tại mỗi phương án:

`tổng_trạm Q + U = D`.

Sau một lần chuyển `x`, bên gửi giảm `x` và bên nhận tăng `x`; vì vậy tổng không thay đổi. `E_mạng` không tăng trong phương án này vì không thêm tải vào trạm cũ và trạm mới nhận tối đa 80%. Tuy nhiên, giảm `E_mạng` chưa chắc giảm ngay **số trạm quá tải**: trạm từ 627% xuống 307% vẫn lớn hơn 100%.

Mô hình tính bằng số thực; phân loại dùng dung sai `10^-9` quanh các ngưỡng để tránh sai số máy tính. Giao diện làm tròn phần trăm về số nguyên và nhu cầu vượt năng lực về một chữ số thập phân; báo cáo bảng thường giữ bốn chữ số. Ví dụ `0,3010` lượt/khung hiện thành `0,3`; phép tính nội bộ không làm tròn theo con số trên màn hình.

## Ví dụ kiểm tra trên snapshot hiện tại

Ngưỡng tiếp cận 15 phút, mỗi trạm mới 4 cổng DC × 80 kW. Ba ứng viên mặc định là `cand-hcm_2025_26911-02`, `cand-hcm_2025_26929-01`, `cand-hcm_2025_27073-01`:

| Bộ ứng viên giả sử mở | Kịch bản | Trạm hiện hữu quá tải trước → sau | Nhu cầu vượt năng lực toàn mạng trước → sau |
|---|---|---|---|
| Ba điểm mặc định | Thông thường | 1 → 1 | 2,9183 → 2,9183 lượt/30 phút |
| Ba điểm mặc định | Cao | 3 → 3 | 5,5702 → 5,5702 lượt/30 phút |
| Vị trí ứng viên A – Thạnh Mỹ Tây | Cao | 3 → 3 | 5,5702 → 2,3702 lượt/30 phút |
| Hai ứng viên phường Thạnh Mỹ Tây | Cao | 3 → 2 | 5,5702 → 0,3010 lượt/30 phút |
| Cả 18 ứng viên | Cao | 3 → 0 | 5,5702 → 0 lượt/30 phút |

Ba trạm hiện hữu bị quá tải trong kịch bản Cao thuộc các phường: `EVC-565` ở **Thạnh Mỹ Tây**, `EVC-178` ở **Xuân Hòa**, `EVC-568` ở **Tân Định**. Ba ứng viên mặc định nằm ở các phường khác nên không nhận chuyển tải của ba trạm này trong mô hình v3.

Hai ứng viên Thạnh Mỹ Tây là `cand-hcm_2025_26956-01` (**Vị trí ứng viên A – Thạnh Mỹ Tây**) và `cand-hcm_2025_26956-02` (**Vị trí ứng viên B – Thạnh Mỹ Tây**). Cùng mở hai điểm này giúp tải của `EVC-565` giảm từ khoảng **627% xuống 80%**, còn hai trạm quá tải ở phường khác vẫn giữ tải cũ. Chỉ mở ứng viên A thì EVC-565 còn khoảng **307%** vì một trạm mới nhận tối đa 3,2 phiên/30 phút theo ngưỡng 80%.

### Tính từng bước cho EVC-565

Đây là số từ snapshot và phép phân bổ của mô hình, với kịch bản Cao, giới hạn tiếp cận 15 phút:

1. `EVC-565` có **1 cổng, tổng 80 kW**, nên `C_cũ = 1` lượt/30 phút. Sau khi cộng phân bổ từ các node, `Q_cũ ≈ 6,269229` lượt/khung; tải là `6,269229 / 1 × 100 ≈ 626,92%`, hiển thị **627%**.
2. Mục tiêu tại trạm cũ là `0,8 × 1 = 0,8` lượt. Phần có thể nhường là `R = 6,269229 - 0,8 = 5,469229` lượt.
3. Mỗi ứng viên có 4 cổng × 80 kW, `C_mới = 4`. Giới hạn nhận là `0,8 × 4 = 3,2` lượt/khung.
4. Các luồng được chuyển trong ví dụ này xuất phát từ node `demand-hcm_2025_26956-02`, có `F = 6,164919` lượt ban đầu đang phân bổ cho EVC-565. Ứng viên A cách node khoảng **3,16 phút di chuyển + 2 phút vào trạm = 5,16 phút**; ứng viên B khoảng **5,31 + 2 = 7,31 phút**. Cả hai cùng phường với EVC-565 và dưới 15 phút, nên đều đủ điều kiện dù cách node hơn 2 phút di chuyển.
5. Ứng viên A gần hơn nên nhận trước `min(6,164919; 5,469229; 3,2) = 3,2` lượt. Luồng từ node còn `2,964919`, phần trạm cũ cần nhường còn `2,269229`; ứng viên B nhận tiếp `min(2,964919; 2,269229; 3,2) = 2,269229` lượt.

| Trạm | Nhu cầu trước | Nhận/nhường | Nhu cầu sau | Năng lực `C` | Tải sau |
|---|---|---|---|---|---|
| EVC-565 | 6,269229 | Nhường 5,469229 | 0,8 | 1 | 80%, xanh lá |
| Vị trí ứng viên A – Thạnh Mỹ Tây, giả sử mở | Chưa có trong mạng | Nhận 3,2 | 3,2 | 4 | 80%; marker vẫn giữ màu trạng thái ứng viên |
| Vị trí ứng viên B – Thạnh Mỹ Tây, giả sử mở | Chưa có trong mạng | Nhận 2,269229 | 2,269229 | 4 | Khoảng 56,73%; marker vẫn giữ màu trạng thái ứng viên |

Kiểm tra tổng: `0,8 + 3,2 + 2,269229 = 6,269229` lượt/khung. Không tạo thêm hoặc xóa khách để đổi màu.

Riêng phần vượt năng lực của EVC-565 giảm `6,269229 - 1 = 5,269229` lượt. Lượng **chuyển** lớn hơn lượng **vượt công suất được loại bỏ** 0,2 lượt vì mục tiêu là 80%, còn ngưỡng hết quá tải là 100%. Toàn mạng còn `5,570197 - 5,269229 ≈ 0,300968` lượt vượt năng lực tại hai trạm ở phường khác, nên giao diện hiện **3 → 2 trạm quá tải**, **5,6 → 0,3 lượt/30 phút**.

Có thể demo bằng cách bỏ chọn tất cả, tìm **Thạnh Mỹ Tây**, chọn hai kết quả, đặt nhu cầu **Cao**, giữ cấu hình 4 cổng × 80 kW và bấm đánh giá. Mở cả 18 điểm chỉ là kịch bản kiểm tra đủ năng lực, không phải khuyến nghị đầu tư cả 18 trạm.

Tổng nhu cầu được bảo toàn ở cả hai phía; công suất và dữ liệu đầu vào không được sửa để làm các ví dụ đạt mục tiêu.

## Giới hạn

- Tất cả kết quả tải là giả lập. Heatmap vẫn thể hiện nhu cầu gốc; bổ sung trạm không làm biến mất nhu cầu sạc của khu vực.
- Giả sử các cổng hoạt động, mở cửa và cung cấp công suất giả định ở khung cao điểm. Không đọc trạng thái occupancy của demo tài xế hay lịch sử kinh doanh.
- Không mô phỏng giờ mở cửa riêng, lỗi cổng, giới hạn đấu nối, tương thích đầu sạc, suy giảm công suất theo SOC, hay lượng xe đang chờ từ khung trước. Thiếu công suất không được tự điền để làm trạm trông ít tải.
- Mở tất cả ứng viên có thứ hạng là một phương án minh họa; chưa phải tối ưu danh mục theo ngân sách tổng. Xếp hạng và điều kiện vật lý cần xác minh vẫn giữ nguyên trong báo cáo.
- Các số lẻ là giá trị kỳ vọng, không phải số xe đo được. Không suy ra SLA chờ, doanh thu, hiệu quả đầu tư hoặc số cổng tối ưu từ màu tải này.

## Đối chiếu với mã nguồn và kiểm thử

| Phần tính toán | Nơi triển khai |
|---|---|
| Đọc cấu hình, chọn cùng một khung cao điểm cho từng kịch bản | [repository.py](../../backend/app/planning/repository.py), `_load_simulation_inputs` |
| Khoảng cách và thời gian di chuyển | [stationLoad.ts](../../frontend/src/planning/stationLoad.ts), `driveMinutes` |
| Năng lực, phân bổ hiện trạng, phân màu và tổng hợp chỉ số | [stationLoad.ts](../../frontend/src/planning/stationLoad.ts), `capacity`, `assignDemand`, `loadLevel`, `summarize` |
| Điều kiện cùng phường và các lần chuyển tải | [stationLoad.ts](../../frontend/src/planning/stationLoad.ts), `relieveLoad` |
| Hiển thị thời điểm, so sánh trước/sau, các số đã làm tròn | [StationLoadPanel.tsx](../../frontend/src/planning/StationLoadPanel.tsx) |
| Xuất kết quả từng trạm, luồng chuyển và đầu vào | [plannerReport.ts](../../frontend/src/planning/plannerReport.ts), `buildPlannerReport` |

[Kiểm thử tải trạm](../../frontend/src/planning/stationLoad.test.ts) kiểm tra bảo toàn nhu cầu, giới hạn nhận tải, ảnh hưởng số cổng/công suất, ngưỡng tiếp cận, cùng/khác phường, mã phường thiếu, node qua ranh giới và các mốc phân màu. [Kiểm thử tích hợp](../../backend/tests/test_planning_integration.py) đối chiếu đầu vào cao điểm với CSV gốc. Khi đổi quy tắc, cần cập nhật cả tài liệu, mã tính và các ví dụ số; không chỉ đổi màu hiển thị.
