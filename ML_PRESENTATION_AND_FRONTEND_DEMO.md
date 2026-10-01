# Smart EV Journey: câu chuyện ML, kết quả hệ thống và đề xuất demo realtime

## 1. Bài toán chúng ta đang giải quyết

Smart EV Journey không chỉ trả lời “trạm nào ở gần?”. Khi người lái xe điện cần sạc giữa hành trình, lựa chọn hợp lý phải trả lời đồng thời bốn câu hỏi:

1. Xe có đi được đến trạm mà vẫn còn mức pin dự phòng an toàn không?
2. Trạm có đầu sạc phù hợp với xe không, và xe thực tế sạc được ở công suất nào?
3. Khi xe đến nơi, khả năng trạm bận và thời gian phải chờ là bao lâu?
4. Sau khi cân bằng chờ đợi, đi vòng, thời gian sạc và rủi ro pin, trạm nào đáng đi nhất?

Vì vậy kết quả cuối cùng không phải chỉ là một dự báo ML. Nó là một recommendation có giải thích: trạm nào được chọn, xe sẽ đến với bao nhiêu pin, phải chờ bao lâu, sạc bao lâu, vì sao trạm khác bị xếp dưới hoặc bị loại.

## 2. Hiện hệ thống đã làm được gì

Hệ thống đã có dữ liệu trạm, thông số xe, route, trạng thái runtime, event demo và luồng backend/frontend hoàn chỉnh. Người dùng có thể chọn xe, mức pin, điểm đi và điểm đến; backend trả về danh sách trạm được xếp hạng và frontend hiển thị chúng trên bản đồ.

Ở tầng domain, hệ thống đã xử lý các phần bắt buộc trước khi dùng ML:

- Loại trạm không công khai hoặc đang offline.
- Kiểm tra đầu sạc AC/DC có tương thích với xe hay không.
- Tính công suất sạc thực tế theo giới hạn thấp hơn giữa trạm và xe.
- Tính năng lượng tiêu hao để đi đến trạm và loại xe không còn đủ SoC dự phòng.
- Tính điện năng cần nạp, thời gian sạc, thời gian đi vòng và điểm tổng hợp.

Phần này quan trọng vì ML không được phép “cứu” một lựa chọn vật lý không khả thi. Một trạm không có connector phù hợp hoặc xe không đủ pin để tới trạm phải bị loại trước khi ranking.

## 3. Phần ML thực chất đang ở đâu?

Hiện tại pipeline ML đã sẵn sàng, nhưng chưa có occupancy model nào được train, đánh giá và release để phục vụ production. Đây là điểm cần nói rõ khi present.

Dataset UrbanEV hiện được dùng để kiểm chứng pipeline: 50 trạm, hơn 2.6 triệu quan sát, theo chu kỳ 5 phút. Nó là dữ liệu lịch sử từ Shenzhen, Trung Quốc, nên không được dùng để khẳng định hiệu quả dự báo cho TP.HCM hay Việt Nam.

Quy trình hiện có là:

1. Chuẩn hoá raw data về một schema chung: timestamp, station ID, số cổng, số cổng bận, occupancy ratio và temporal split.
2. Tách train/validation/test theo thời gian, không trộn ngẫu nhiên. Việc này tránh để model nhìn tương lai khi học quá khứ.
3. Tạo 12 giá trị occupancy gần nhất, tương ứng 60 phút lịch sử, làm input.
4. Tạo ba target: occupancy sau 5, 10 và 15 phút.
5. Train ba XGBoost models riêng cho ba horizon và so sánh với baseline persistence.
6. Chỉ khi artifact, feature contract và metadata đều hợp lệ thì backend mới load model. Nếu thiếu hoặc sai, backend tự quay về fallback an toàn.

Fallback hiện tại là persistence: trạng thái occupancy gần nhất được dùng như dự báo. Điều này không phải lỗi của demo; đó là cơ chế bảo vệ để hệ thống không đưa một model chưa được duyệt vào recommendation.

Khi có model release, model occupancy sẽ trả về tỷ lệ cổng bận dự báo tại thời điểm xe đến trạm. Ví dụ, nếu trạm có 4 cổng operational và dự báo occupancy là 0.75, backend hiểu là khoảng 3 cổng sẽ bận. Kết quả đó là một input cho phần ước lượng thời gian chờ, không phải kết luận recommendation cuối cùng.

## 4. Các hướng model khác đang có và ý nghĩa của chúng

XGBoost baseline là bước đầu vì nó chỉ cần lịch sử occupancy, là loại input backend có thể tái tạo được. Các hướng nâng cao đã được chuẩn bị trong code nhưng chưa được bật vì thiếu data domain hoặc chưa đủ điều kiện serving.

Hybrid LSTM hiện là hướng học chuỗi occupancy và dự báo đồng thời nhiều horizon. File vẫn mang tên `train_lstm_markov.py` theo roadmap cũ, nhưng code hiện tại chưa sinh các Markov transition head; Markov vẫn là module xác suất riêng. Hướng này hiện là experimental: cần dữ liệu Việt Nam, context theo vùng deploy và kiểm định calibration trước khi đưa vào API.

Transformer là hướng mở rộng khi có dữ liệu đa nguồn và dài hạn: occupancy, thời tiết, traffic, đặc tính trạm, POI và lịch. Nó có thể học ảnh hưởng giữa nhiều trạm và nhiều tín hiệu hơn, nhưng hiện chưa có enriched dataset đã được duyệt. Code tồn tại để định nghĩa đường scale, không phải để claim model đang chạy.

Foundation model như Chronos hoặc TimesFM mới ở mức research gate. Chưa có provider/version/license/adapter được pin, vì vậy không nên nói hệ thống đã fine-tune foundation model.

Residual Duration Model, gọi tắt là RDM, là một model khác hoàn toàn với occupancy. Nó không dự báo “trạm đông bao nhiêu”; nó dự báo “một xe đang sạc ở cổng này còn bao nhiêu phút nữa mới xong”. RDM cần session telemetry thật, như thời gian sạc đã trôi qua, kWh đã nạp, công suất hiện tại, SoC, mục tiêu SoC, loại xe và connector. Chưa có dữ liệu session đúng chuẩn cũng như ground truth session end time, nên RDM hiện chưa được train.

## 5. Hệ thống ước lượng thời gian chờ như thế nào?

Khi chưa biết chi tiết trạng thái từng cổng, hệ thống dùng cách aggregate. Nó kết hợp occupancy forecast, số cổng hoạt động, số xe đang queue, session duration trung bình và arrival rate để tạo ước lượng wait theo Erlang-C.

Phần này có hai nguồn arrival:

- Arrival rate nền của trạm, đang dùng dữ liệu demo synthetic.
- Planned arrival do người dùng xác nhận “đang đi tới trạm”. Planned arrival chỉ đóng góp theo xác suất, không được xem như xe đã đứng trong queue.

Kết quả trả về gồm estimated wait, xác suất phải chờ, các thành phần tính toán và flags. Nếu trạm offline hoặc hệ thống quá tải, wait được cap để ranking vẫn ổn định và UI có thể nói rõ tình trạng overload/offline.

Đây là cách phù hợp khi hệ thống chỉ biết tình trạng tổng hợp của trạm. Tuy nhiên nó không thể trả lời chính xác cổng nào sẽ rảnh lúc nào, vì nó không biết session đang sạc còn bao lâu.

## 6. Ví dụ luồng hoạt động với VinFast VF 7 Eco

Giả sử một người lái VinFast VF 7 Eco từ Nguyễn Hữu Thọ – Phước Kiển đến Phú Nhuận. Xe đang còn 55% pin và người lái muốn sạc lên 80%. Xe dùng được cả CCS2 lẫn Type2; quan trọng nhất, xe sạc DC tối đa 100 kW và phải luôn còn ít nhất 10% pin dự phòng.

Kết quả hệ thống chọn **EV ONE Lavida Quận 7**. Lý do rất đơn giản: xe tới được, sạc nhanh được, và tại thời điểm đó không phải chờ.

Hệ thống kiểm tra theo đúng thứ tự này:

1. **Xe có tới được Lavida không?** Có. Trạm cách khoảng 3.25 km, mất khoảng 4 phút để tới. Xe chỉ tiêu hao khoảng 0.38 kWh, nên khi đến vẫn còn khoảng 54% pin — cao hơn nhiều so với ngưỡng an toàn 10%.
2. **Xe có sạc được ở đó không?** Có. Lavida có cổng CCS2, đúng connector của VF 7. Trạm ghi 160 kW, nhưng xe chỉ nhận tối đa 100 kW, nên hệ thống dùng **100 kW** để tính; không lấy 160 kW để làm kết quả đẹp hơn thực tế.
3. **Xe cần sạc trong bao lâu?** Từ khoảng 54% lên 80%, xe cần thêm khoảng 15.3 kWh. Với công suất thực tế 100 kW và hiệu suất 90%, thời gian sạc ước lượng là khoảng **10 phút**.
4. **Có phải đợi không?** Ở normal demo, Lavida có một cổng đang trống và không có xe xếp hàng. Dự báo fallback cũng không thấy occupancy tăng, nên wait ước lượng là **0 phút**.

Vì thế Lavida đứng hạng 1. Điểm 0.9443 chỉ là cách backend biểu diễn kết quả; khi present không cần đọc số này. Chỉ cần nói: “Lavida thắng vì xe đến được an toàn, có CCS2, sạc khoảng 10 phút và không cần chờ.”

So sánh với **EV ONE Deutsches Haus** sẽ làm lý do rõ hơn. Xe vẫn có thể tới trạm này, nhưng trạm chỉ có Type2. VF 7 dùng được Type2, song đó là sạc AC và xe chỉ nhận khoảng 7.2 kW, nên cùng lượng điện cần nạp sẽ mất khoảng **150 phút**, thay vì 10 phút ở Lavida. Thêm vào đó, tại thời điểm demo Deutsches Haus đã bận 3 trong 4 cổng và có xe chờ; wait estimate bị cap ở 120 phút. Vì vậy dù đường qua Deutsches Haus ít đi vòng hơn, nó vẫn là lựa chọn tệ hơn nhiều.

Thông điệp của ví dụ là: hệ thống không chọn trạm gần nhất. Nó chọn trạm giúp người lái hoàn thành hành trình tốt nhất sau khi xét khả năng tới nơi, connector, công suất sạc, hàng đợi và thời gian đi vòng. Trạm Audi nội bộ không xuất hiện trong kết quả vì không công khai; đây là ví dụ về một điều kiện bị loại ngay từ đầu, không cần đem đi tính điểm.

### Nếu nhìn từ bên trong, từng model/khối trả ra gì?

Khi present, có thể nói “hệ thống không chỉ trả một câu là chọn Lavida”. Mỗi khối trả một mảnh thông tin, rồi backend ghép chúng thành câu trả lời cuối cùng.

**1. Khối route và mức pin trả về:**

```text
route_distance_to_station_m = 3,249 m
route_duration_to_station_s = 240 s
trip_energy_kwh = 0.384 kWh
arrival_soc = 0.5436  (tức 54.36%)
reachable = true
```

Ý nghĩa: xe đi tới Lavida mất khoảng 4 phút và hết chưa đến nửa kWh. `arrival_soc` là lượng pin còn lại khi xe chạm trạm, không phải pin hiện tại. `reachable = true` có nghĩa là 54.36% vẫn lớn hơn reserve 10%, nên đây mới là candidate được phép đi tiếp vào bước ranking.

**2. Khối compatibility trả về:**

```text
matched_connectors = ["CCS2"]
effective_power_kw = 100
compatible = true
```

Ý nghĩa: connector của xe và của Lavida khớp ở CCS2. `effective_power_kw` là công suất xe thực sự có thể dùng, luôn lấy mức thấp hơn giữa khả năng trạm và khả năng xe. Vì trạm có 160 kW nhưng VF 7 nhận tối đa 100 kW, kết quả phải là 100 kW. Con số này đi thẳng vào phép tính thời gian sạc.

**3. Khối occupancy forecast trả về:**

```text
predicted_occupancy_ratio = 0.0
predicted_occupied_ports = 0.0
operational_ports = 1
prediction_source = "persistence"
```

Ý nghĩa: tại ETA của VF 7, hệ thống dự kiến Lavida có 0 trên 1 cổng bận. `ratio = 0.0` nghĩa là 0%, không phải độ tin cậy 0%. `prediction_source = persistence` nói rõ đây là fallback lấy trạng thái occupancy gần nhất, bởi chưa có occupancy model release. Khi XGBoost được release, hai số occupancy này sẽ vẫn có cùng ý nghĩa, chỉ khác nguồn là `model`.

**4. Khối aggregate wait trả về:**

```text
current_queue_length = 0
avg_session_duration_min = 30
estimated_wait_min = 0
```

Ý nghĩa: snapshot hiện không có xe xếp hàng, và mô hình queue đang dùng giả định một session trung bình 30 phút. Nhưng vì dự báo còn một cổng trống tại lúc xe đến, `estimated_wait_min` là 0: người lái có thể cắm sạc ngay. Đây là estimate tổng quát, không biết cụ thể xe nào đang cắm ở cổng nào.

**5. Khối charging estimate trả về:**

```text
arrival_soc = 54.36%
target_soc = 80%
energy_to_add_kwh = 15.28 kWh
estimated_charge_min = 10.19 phút
```

Ý nghĩa: `energy_to_add_kwh` là lượng điện phải đưa vào pin, không phải năng lượng dùng để đi tới trạm. `estimated_charge_min` là thời gian từ lúc bắt đầu cắm sạc đến khi đạt 80%; nó chưa gồm thời gian chờ hoặc thời gian di chuyển.

**6. Khối recommendation trả về:**

```text
rank = 1
final_score = 0.9443
estimated_wait_min = 0
estimated_charge_min = 10.19
detour_min = 3.28
```

Ý nghĩa: `rank = 1` là thông tin người dùng cần nhất. `final_score` chỉ là điểm nội bộ để backend sắp thứ tự, được tạo từ wait, detour, charging time và mức an toàn SoC theo preference của scenario; không nên xem nó là phần trăm “độ tốt” hay “độ chính xác”. Ba con số còn lại là lý do có thể giải thích được cho hạng 1: không chờ, sạc khoảng 10 phút và đi vòng thêm khoảng 3 phút.

Để demo DES, cùng Lavida có thể nhận một snapshot mới: cổng duy nhất đang bận, phiên hiện tại còn 8 phút và đã có một xe queue được xác nhận sẽ sạc 20 phút. DES trả về:

```text
method = "discrete_event_simulation"
estimated_wait_min = 28
predicted_charge_start_at = 18:32
duration_sources = ["PROVIDER_REPORTED_DURATION", "QUEUE_DURATION_ESTIMATE"]
```

Ý nghĩa: 8 phút đầu chờ xe đang sạc xong, 20 phút tiếp theo dành cho xe đứng trước trong queue, nên VF 7 bắt đầu sạc sau 28 phút. `duration_sources` cho frontend và người dùng biết 8 phút đầu là số do provider báo, còn 20 phút là thời lượng dự kiến của xe đang xếp hàng. Đây là kết quả chính xác hơn aggregate wait **chỉ vì** snapshot có dữ liệu từng cổng và queue thật.

Với LSTM/Markov và RDM, phần output nên được giải thích như sau nhưng phải gắn nhãn **minh hoạ tương lai, chưa phải model đang chạy**:

- LSTM/Markov có thể trả `probability_wait_zero = 0.70`, nghĩa là xác suất xe tới và cắm được ngay là 70%, chứ không phải hệ thống chắc chắn 70% chính xác. Nó cũng có thể trả phân phối: xác suất phải đợi 5, 10, 15 phút.
- RDM có thể nhận các feature của một session như đã sạc 12 phút, đã nạp 9 kWh và công suất hiện tại 60 kW; output ví dụ `remaining_charge_min = 8`. Nghĩa là phiên đang sạc được dự đoán còn 8 phút. Số này chỉ được đưa vào DES khi provider chưa báo duration và RDM đã qua review/calibration.

## 7. DES và RDM thay đổi demo realtime ra sao?

Điểm thú vị nhất để demo không phải là cố nói “ML đã biết chính xác tương lai”. Điểm thú vị là cho người xem thấy hệ thống chọn đúng mức độ chắc chắn tương ứng với dữ liệu hiện có.

Khi chỉ có status tổng hợp, hệ thống dùng aggregate wait. Khi có một snapshot realtime đầy đủ — từng cổng available/charging/offline, connector từng cổng, session đang chạy còn bao lâu và queue đã được xác nhận — hệ thống có thể chạy Discrete-Event Simulation, gọi là DES.

DES làm việc rất trực quan: nó tạo một mốc “cổng rảnh lúc nào” cho từng cổng. Cổng available rảnh ngay. Cổng charging rảnh sau remaining duration do provider báo hoặc, trong tương lai, do RDM dự đoán. Sau đó DES xếp từng xe trong confirmed queue vào cổng tương thích rảnh sớm nhất. Cuối cùng nó tìm cổng tương thích rảnh sớm nhất cho xe của người dùng.

Ví dụ realtime giả lập cho Lavida: lúc 18:04, cổng CCS2 duy nhất đang sạc và provider báo còn 8 phút. Có một xe thực sự đang đứng queue, cần CCS2 và dự kiến sạc 20 phút. VF 7 của người dùng đến lúc 18:04. Cổng sẽ rảnh lúc 18:12, xe queue dùng cổng tới 18:32, do đó VF 7 có thể bắt đầu sạc lúc 18:32 và phải chờ 28 phút.

Đây là ví dụ rất tốt khi present: ở normal aggregate demo, Lavida từng được tính wait là 0. Nhưng snapshot realtime mới cho biết chi tiết mà aggregate status không thấy, nên DES trả 28 phút. Hai con số không “mâu thuẫn”; chúng trả lời với mức thông tin khác nhau.

RDM chỉ xuất hiện khi provider không báo remaining duration của một session. Khi đó RDM, nếu đã được train và approve, sẽ dự báo phần thời gian còn lại; DES dùng kết quả đó để xếp lịch. Provider duration luôn được ưu tiên hơn RDM. Nếu không có provider duration và cũng chưa có RDM approved, hệ thống phải fail closed, không được bịa ra thời gian chính xác.

## 8. Đề xuất demo frontend: Realtime Queue Lab

Đề xuất là giữ nguyên journey demo hiện tại và thêm một phần mở rộng dưới station details của trạm đang chọn, có thể gọi là **Realtime Queue Lab**.

Người dùng bắt đầu như hiện tại: chọn xe, SoC, origin/destination và chạy recommendation. Sau khi click một trạm, họ có thể bật Queue Lab để xem cùng lúc hai kết quả:

- Aggregate estimate: kết quả hiện tại từ occupancy forecast/persistence và Erlang-C.
- DES realtime estimate: kết quả từ snapshot theo từng cổng, chỉ xuất hiện khi snapshot hợp lệ đã được đưa vào simulator.

Không nên để DES tự động ghi đè wait trong recommendation ngay từ demo đầu tiên. Nên đặt hai kết quả cạnh nhau để người xem hiểu cái gì đã thay đổi và vì sao. Đây cũng là cách an toàn để team quan sát chênh lệch giữa aggregate và DES trước khi đưa DES vào ranking thật.

Phần Queue Lab chỉ cần dễ nhìn, không cần thiết kế cầu kỳ:

- Hiển thị từng cổng dưới dạng một hàng: connector, trạng thái, thời điểm sẽ rảnh. Available màu xanh, charging màu vàng, offline màu xám.
- Hiển thị confirmed queue theo thứ tự, connector và thời lượng sạc kỳ vọng.
- Hiển thị xe requester: connector cần dùng, ETA, predicted start time và estimated wait.
- Có một block giải thích ngắn: “Port 01 rảnh sau 8 phút → Q-01 dùng thêm 20 phút → xe của bạn bắt đầu sau 28 phút.”
- Luôn hiện snapshot timestamp, data source và flags để người xem biết đây là realtime thật hay simulation.

Frontend chỉ cần gọi các API đã có:

- `PUT /realtime/stations/{station_id}/telemetry` để lưu snapshot simulator.
- `GET /realtime/stations/{station_id}/telemetry` để load snapshot.
- `POST /realtime/stations/{station_id}/simulate-wait` với `evaluation_at` và `compatible_connector_types` để chạy DES.
- `POST /journey/recommend` vẫn là luồng ranking hiện tại.
- `POST /demo/reset` để xoá event, planned arrival và telemetry in-memory sau mỗi lượt demo.

Khi build frontend, cần hiện rõ các caveat từ backend. `CONFIRMED_QUEUE_ONLY` nghĩa là chỉ xe được xác nhận có mặt mới được đưa vào DES queue. `UNOBSERVED_ARRIVALS_EXCLUDED` nghĩa là DES không đoán những xe chưa xuất hiện sau snapshot. Snapshot cũ cũng phải được đánh dấu stale. Các flags này là một phần của sản phẩm chứ không phải chi tiết debug.

## 9. Một lượt present nên kể như thế nào

Mở đầu bằng bài toán: “Không phải cứ chọn trạm gần nhất. Chúng ta cần biết xe tới được không, có sạc được không, chờ bao lâu và tổng thời gian có hợp lý không.”

Sau đó chạy VF 7 Eco normal journey. Chỉ ra Lavida được chọn vì CCS2 phù hợp, xe đến vẫn còn 54.36% pin, chỉ cần nạp khoảng 15.28 kWh và sạc khoảng 10 phút. So sánh với Deutsches Haus để chứng minh hệ thống nhìn cả connector/power, queue và detour chứ không chỉ nhìn bản đồ.

Tiếp theo chuyển sang một scenario low-SOC hoặc xe GB/T để chứng minh hard constraints: nếu không tới được hoặc không có connector, candidate bị loại trước khi score. Đây là phần cho thấy recommendation đáng tin vì nó không ưu tiên “điểm số đẹp” hơn điều kiện vật lý.

Sau đó mở Realtime Queue Lab ở Lavida, bơm snapshot giả lập: một cổng còn 8 phút, một xe queue 20 phút. Cho người xem thấy aggregate đang nói 0 phút còn DES nói 28 phút; giải thích vì aggregate chỉ có dữ liệu tổng hợp, DES có trạng thái từng cổng và queue vật lý.

Kết thúc bằng một event outage: khi Lavida offline, trạm bị loại và ranking đổi sang Deutsches Haus. Nhấn mạnh đây là khả năng hệ thống đã chạy được ngay cả khi ML model chưa release.

## 10. Những điều phải nói đúng và roadmap

Không nên claim hệ thống đã dự báo occupancy chính xác cho TP.HCM, đã train LSTM/Transformer/Foundation Model, đã có RDM, hoặc đang dùng realtime station feed thật. Hiện các phần đó là pipeline, experiment path hoặc simulator contract.

Roadmap hợp lý là:

1. Hoàn thiện Realtime Queue Lab để demo được DES với telemetry simulated một cách minh bạch.
2. Tích hợp telemetry từ operator/OCPP: port state, session lifecycle, connector, timestamp, duplicate/out-of-order handling và freshness SLA.
3. Thu thập occupancy history Việt Nam theo dạng append-only; benchmark XGBoost với persistence trên temporal test set; chỉ release sau khi metrics, calibration và capacity checks được duyệt.
4. Thu thập completed session data để train RDM. Label phải là thời gian thực còn lại tới lúc session kết thúc, và toàn bộ row của một session không được nằm ở cả train lẫn test.
5. So sánh DES và aggregate estimate với thời điểm xe thực sự bắt đầu sạc. Chỉ sau khi đánh giá theo từng trạm, freshness và fallback policy rõ ràng mới đưa DES vào ranking tự động.

Tóm lại, ý tưởng trung tâm của hệ thống là: dùng ML để dự báo phần không nhìn thấy được, dùng dữ liệu realtime khi có để mô phỏng chính xác hơn, và luôn giữ safety rule cùng mức độ bất định hiển thị rõ cho người dùng.

---

### Nguồn code chính để team đối chiếu

- Pipeline và training contract: `ml/README.md`, `ml/src/build_feature_dataset.py`, `ml/src/train_occupancy.py`.
- DES/RDM contract: `ml/DES_RDM_INTEGRATION.md`, `backend/app/domain/realtime.py`.
- Logic recommendation: `backend/app/domain/recommendation.py`, `backend/app/domain/services.py`, `backend/app/domain/wait_estimation.py`.
- Frontend hiện có: `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`.
