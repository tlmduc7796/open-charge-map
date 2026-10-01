# Luồng ưu tiên hiện tại: Queue Lab → Monte Carlo DES → ACN/RDM

## Đọc tài liệu này khi nào?

Đây là thứ tự công việc hiện tại cho team frontend, backend và ML. Nó không thay thế các contract trong `DES_RDM_INTEGRATION.md`; nó chốt **cái gì làm ngay bây giờ**, cái gì để sau, và vì sao.

Việc tiếp theo **không phải train thêm occupancy model, LSTM hay Markov**. Việc tiếp theo là hoàn thiện demo Queue Lab bằng DES deterministic ở frontend.

## Quyết định hiện tại về occupancy benchmark

Benchmark UrbanEV vừa chạy cho kết quả `GO_NEXT_EXPLORATORY_CHECK`. Residual XGBoost thắng persistence ở cả 12 horizon trên validation. MAE validation cải thiện khoảng 4.15% đến 14.01%; trên test exploratory, mức cải thiện chỉ khoảng 0.91% đến 1.31%. Daily-naive và weekly-naive thua persistence rõ rệt; calibration ECE của residual XGBoost cũng tốt hơn persistence ở tất cả horizon.

Điều này cho thấy XGBoost học được residual so với occupancy hiện tại trong UrbanEV. Tuy nhiên nó **không** là bằng chứng để deploy: UrbanEV là source domain Shenzhen, lợi ích test khoảng 1% là nhỏ, và test window đã được xem khi ra quyết định nên không còn là final holdout độc lập.

Một chi tiết cần nói đúng: tất cả horizon đều chọn `alpha = 1.0` và threshold gần 0. Nghĩa là residual-magnitude gate thực tế không loại dự báo nào. Kết quả tốt đến từ residual XGBoost L1, không phải từ cơ chế gate, và gate không phải confidence/uncertainty.

Kết luận hành động: giữ XGBoost như một kết quả exploratory; không deploy từ benchmark này và không train LSTM lúc này. Nếu quay lại occupancy ML, ưu tiên là rolling-origin backtest mới để kiểm tra lợi ích khoảng 1% có lặp lại hay không.

## Bước 1 — Queue Lab deterministic DES

Mục tiêu của Queue Lab là cho người xem nhìn được nguyên nhân của wait time, không phải chỉ nhìn một số phút được backend trả về.

Luồng demo là:

```text
Port state + thời gian đến lúc port được nhả + confirmed queue
→ DES
→ thời điểm xe requester bắt đầu sạc và thời gian chờ
```

### Input mà frontend cần cho phép nhập

Mỗi port cần có:

- `port_id`: định danh port trong simulator.
- `connector_types`: các connector port hỗ trợ.
- `state`: `available`, `charging`, hoặc `offline`.
- Khi `charging`: `session_id` và `reported_remaining_port_release_min`.

`reported_remaining_port_release_min` có nghĩa là còn bao lâu tới khi xe **rút khỏi port**. Nó không nhất thiết bằng thời điểm xe đã sạc xong, vì xe có thể đã `doneChargingTime` nhưng vẫn chiếm port đến `disconnectTime`.

Confirmed queue cần có:

- `queue_position`: thứ tự thực tế tại trạm.
- `compatible_connector_types`: connector xe đó cần.
- `expected_charge_duration_min`: thời gian xe đó chiếm port sau khi được cắm.

Requester cần gửi connector xe dùng được và `evaluation_at`. Planned arrival trong app không được đưa thẳng vào confirmed queue: đó mới là ý định đi tới trạm và chỉ được aggregate wait dùng theo xác suất.

### DES phải làm gì?

DES bỏ qua port offline. Port available tạo một slot rảnh ngay tại `evaluation_at`; port charging tạo slot rảnh tại `observed_at + reported_remaining_port_release_min`. Sau đó DES xếp từng xe trong confirmed queue vào port **compatible** rảnh sớm nhất. Cuối cùng nó làm điều tương tự cho requester.

Frontend gửi snapshot qua `PUT /realtime/stations/{station_id}/telemetry`, rồi gọi `POST /realtime/stations/{station_id}/simulate-wait`. Kết quả cần hiển thị tối thiểu là:

- `predicted_charge_start_at`: thời điểm requester có thể bắt đầu sạc.
- `estimated_wait_min`: số phút từ `evaluation_at` đến thời điểm đó.
- `duration_sources`: số phút đến từ provider hay từ duration được nhập cho queue.
- `flags`: caveat và lỗi compatibility.

Timeline nên biểu diễn mỗi port là một lane: phần đang bận, xe queue được xếp vào lane nào, và đoạn requester được bắt đầu. Đây là bằng chứng trực quan của output, không phải animation trang trí.

### Preset bắt buộc: kết quả wait 28 phút

Để preset có kết quả **28 phút** với hai port đang bận 8 và 20 phút, cần nói rõ connector. Cấu hình đơn giản là:

```text
Port A: CCS2, charging, được nhả sau 8 phút
Port B: Type2, charging, được nhả sau 20 phút
Queue #1: cần CCS2, sạc 20 phút
Requester: cần CCS2
```

DES sẽ cho Queue #1 vào Port A từ phút 8 đến phút 28; requester cũng chỉ dùng được CCS2 nên bắt đầu ở phút 28. Do đó `estimated_wait_min = 28`.

Chi tiết connector là bắt buộc. Nếu cả A và B đều là CCS2 và requester dùng được cả hai, requester sẽ lấy Port B ở phút 20, nên wait đúng theo DES sẽ là 20 phút chứ không phải 28. Đây là một test tốt để chứng minh simulator thật sự tôn trọng compatibility thay vì chỉ cộng duration theo hàng đợi.

Ngoài kết quả số, UI phải giữ các caveat sau:

- `CONFIRMED_QUEUE_ONLY`: chỉ queue quan sát/xác nhận được dùng.
- `UNOBSERVED_ARRIVALS_EXCLUDED`: simulator không thấy xe sẽ tới sau snapshot.
- `SNAPSHOT_ADVANCED_WITHOUT_NEW_TELEMETRY`: user tính tại thời điểm mới hơn snapshot.
- Nếu không có port compatible, wait là `null` kèm flag unsupported; không hiển thị 0 phút.

Trong phase này, snapshot phải có `data_source: "simulated"`. Queue Lab là demo deterministic, chưa phải station feed thật và chưa được tự động ghi đè wait trong journey recommendation.

## Bước 2 — Monte Carlo DES, vẫn chưa cần ML

Sau deterministic Queue Lab, bổ sung một mode Monte Carlo. Khác biệt duy nhất là duration không còn là một số cố định; nó là một distribution synthetic có tham số do demo chọn. Mỗi run lấy mẫu duration cho từng port/session và queue vehicle, chạy lại cùng thuật toán DES, rồi ghi nhận wait của requester.

Chạy ví dụ 1,000 lần với seed cố định để cùng input luôn tái tạo cùng kết quả. Output cần dễ đọc:

- `P10`, `P50`, `P90` của wait time: lần lượt là mốc 10%, median và 90% của các simulation runs.
- `P(wait > N)`: xác suất wait dài hơn ngưỡng N phút do user chọn.
- số run, seed và mô tả distribution đã dùng.

Ví dụ cách đọc: nếu P10/P50/P90 là 12/28/45 phút, 50% run có wait không quá 28 phút, còn 10% trường hợp xấu nhất bắt đầu từ khoảng 45 phút trở lên. Đây là uncertainty từ giả định synthetic, không phải confidence của model ML.

Yêu cầu kiểm thử quan trọng: khi tất cả distribution đều là duration cố định, Monte Carlo phải trả cùng kết quả deterministic. Với preset ở trên, P10 = P50 = P90 = 28 và xác suất `wait > 28` bằng 0. Nếu không đạt tính chất này, implementation Monte Carlo sai hoặc timeline deterministic sai.

Monte Carlo nên là một endpoint/service riêng hoặc một mode có contract rõ; không được lẫn sample random vào `simulate-wait` deterministic hiện có. Frontend cần hiện rõ mode đang xem: `Deterministic` hay `Monte Carlo (synthetic)`.

## Bước 3 — ACN-Data và RDM

Chỉ sau khi Queue Lab deterministic và Monte Carlo demo hoàn chỉnh mới chuyển sang ACN-Data. Mục tiêu ở bước này là thay duration synthetic bằng một distribution học từ session thật, không phải quay lại train occupancy/LSTM.

Target phải là:

```text
remaining_port_release_min = disconnectTime - observation_timestamp
```

Mốc đúng là `disconnectTime`, vì đây là lúc port thực sự có thể phục vụ xe sau. Không dùng thời điểm charging current về 0 nếu xe vẫn cắm chiếm port.

Dataset session phải có ít nhất session ID, port ID, timestamp quan sát, session elapsed time, delivered energy, current power, connector và eventual `disconnectTime`. Các row của cùng một session không được đi vào cả train và test.

Model RDM/quantile sau này nên tạo ra phân phối hoặc quantile cho `remaining_port_release_min`, ví dụ P10/P50/P90. Monte Carlo DES sẽ sample từ phân phối đó thay vì duration synthetic. Provider-reported port-release duration vẫn được ưu tiên; RDM chỉ là fallback khi provider không có dữ liệu và model đã qua benchmark, calibration, monitoring và rollback review.

## Markov để sau cùng, với vai trò khác

Markov chưa làm ở giai đoạn này. Nó không cạnh tranh với DES và không thay RDM. Nó là fallback xác suất cho trường hợp chỉ có aggregate occupancy nhưng không có telemetry từng port/session. Khi có per-port state, remaining port-release duration và confirmed queue, DES là công cụ phù hợp hơn.

Khi ACN/RDM đã có nền session data, team mới quyết định có cần Markov để mô tả uncertainty của aggregate wait hay không. Nếu làm, nó cần transition/calibration backtest riêng; không suy ngược transition từ một occupancy ratio mong muốn.

## Checklist trước khi chuyển bước

Queue Lab deterministic hoàn thành khi frontend tạo được snapshot, DES trả output đúng, timeline giải thích được kết quả, preset 28 phút chạy ổn định, và caveat/connector incompatibility hiển thị đúng.

Monte Carlo hoàn thành khi seed tái tạo được kết quả, output có P10/P50/P90 và `P(wait > N)`, còn input duration cố định luôn khớp deterministic DES.

Chỉ khi hai điều trên hoàn thành mới bắt đầu thủ tục ACN-Data, dataset contract và RDM. Điều này giữ roadmap bám sát bài toán wait time thật: đầu tiên minh hoạ logic chính xác, sau đó minh hoạ uncertainty, cuối cùng mới dùng ML để thay thế synthetic duration bằng một dự báo có ground truth.

## Tài liệu liên quan

- `DES_RDM_INTEGRATION.md`: contract runtime hiện có, nguồn dữ liệu và guardrail DES/RDM.
- `README.md`: pipeline occupancy/source-domain benchmark và data gates.
- `MARKOV_PHASE_PLAN.md`: thiết kế Markov khi sau này cần fallback aggregate uncertainty.
- `TRANSFER_LEARNING_URBANEV_TO_VIETNAM.md`: ranh giới giữa UrbanEV source experiment và dữ liệu Việt Nam/production.
