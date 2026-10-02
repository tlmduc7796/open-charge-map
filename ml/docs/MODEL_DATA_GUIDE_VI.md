# Bản đồ dữ liệu và mô hình: từ dữ liệu trạm đến dự báo thời gian chờ

Tài liệu này trả lời bằng ngôn ngữ sản phẩm bốn câu hỏi:

1. Mỗi mô hình cần dữ liệu gì, lấy từ đâu và cần lưu như thế nào?
2. Mỗi mô hình tạo ra kết quả gì?
3. Kết quả của mô hình nào được dùng ở đâu, đặc biệt là khi chạy mô phỏng hàng đợi (DES)?
4. Phải so sánh và chia train/validation/test thế nào để không tự đánh lừa mình?

Nó không có ý nói mọi mô hình dưới đây đều phải được làm. Lộ trình hợp lý là làm mô hình đơn giản, chứng minh nó tốt hơn cách đoán đơn giản, rồi mới tăng độ phức tạp nếu dữ liệu thật cho thấy điều đó đáng giá.

## 1. Bức tranh lớn: mỗi thành phần trả lời một câu hỏi khác nhau

Người dùng mở app không thật sự quan tâm tên mô hình. Họ hỏi: “Nếu tôi tới trạm này thì có cổng phù hợp không, chờ bao lâu, và tôi có nên chọn trạm này không?”

Để trả lời, hệ thống có thể đi theo hai nhánh dữ liệu:

```text
Nhánh dữ liệu tổng quát của trạm
  lịch sử trạm đông/vắng
  -> XGBoost hoặc LSTM dự báo độ đông ở thời điểm người dùng tới
  -> Markov hoặc Erlang-C ước lượng rủi ro phải chờ khi thiếu chi tiết từng cổng

Nhánh dữ liệu chi tiết từng cổng
  cổng nào đang bận, xe nào đang cắm, xe nào đang xếp hàng
  -> provider báo thời gian nhả cổng, hoặc RDM dự báo thời gian còn lại
  -> DES xếp lịch theo thứ tự hàng đợi và connector tương thích
  -> thời điểm người dùng có thể bắt đầu sạc

Sau đó
  route + mức pin + khả năng đi tiếp + giá + sở thích người dùng
  -> xếp hạng các trạm và giải thích vì sao chọn trạm đó
```

Hai nhánh này không thay thế nhau:

- Nếu chỉ biết “trạm có 3/4 cổng đang bận”, nhánh tổng quát vẫn hữu ích.
- Nếu biết chi tiết từng cổng và từng session, DES cho câu trả lời sát thực tế hơn.
- Nếu dữ liệu chi tiết bị cũ hoặc thiếu, không được dùng DES để tạo ra một ETA có vẻ chính xác nhưng thực chất là bịa. Khi đó phải quay về ước lượng tổng quát hoặc nói rõ chưa đủ dữ liệu.

## 2. Trạng thái hiện tại của repository

Hiện đã có Queue Lab: người demo tự tạo cổng, connector, xe trong hàng đợi và thời lượng. DES xếp xe đúng connector và đúng thứ tự; Monte Carlo có thể thử duration cố định hoặc một khoảng duration giả lập. Đây là demo đúng về **logic hàng đợi** và **cách biểu diễn bất định**.

Tuy nhiên, duration trong Queue Lab hiện chưa đến từ model hay telemetry trạm thật.

Nhánh occupancy cũng đã có pipeline XGBoost và benchmark exploratory trên UrbanEV. Kết quả này chỉ cho thấy XGBoost có học được một phần quan hệ phi tuyến trên dữ liệu Shenzhen; nó không phải model đã được train/deploy cho trạm Việt Nam. Backend hiện giữ fallback an toàn là dùng occupancy mới nhất thay vì tự nhận có dự báo ML production.

Các trạng thái quan trọng:

| Thành phần | Trạng thái hiện tại | Không nên nói quá |
|---|---|---|
| XGBoost occupancy | Có pipeline/benchmark source-domain | Không phải model phục vụ trạm Việt Nam |
| LSTM occupancy | Có hướng thử nghiệm, đang tắt | Chưa có kết quả đủ điều kiện deploy |
| Markov | Có thiết kế/toán chuyển đổi trạng thái | Chưa có transition model đã train/calibrate |
| Erlang-C | Có thể dùng cho aggregate wait | Không biết từng xe, từng cổng hay thứ tự queue |
| RDM | Có contract và training gate | Chưa có artifact đã train |
| DES / Queue Lab | Đã hoạt động với input mô phỏng | Chưa phải OCPP/operator feed thật |

## 3. Dữ liệu nền cần chuẩn bị trước khi nói tới model

Đừng nhét tất cả vào một bảng khổng lồ. Nên giữ các nhóm dữ liệu riêng, có khóa liên kết và timestamp rõ ràng. Một số dữ liệu là public/operational; một số là dữ liệu người dùng và phải có consent, retention policy, phân quyền truy cập.

### 3.1. Danh mục trạm và cổng sạc

Nguồn tốt nhất: operator, CPO, roaming provider hoặc dữ liệu OCPP đã được đối soát. Đây là dữ liệu tương đối ổn định, nhưng phải version hóa vì trạm có thể thay cổng hoặc đổi tình trạng khai thác.

Mỗi trạm nên có:

- Mã trạm, tên, tọa độ, địa chỉ, đơn vị vận hành/host, múi giờ.
- Giờ hoạt động, quy tắc vào bãi xe, yêu cầu đặt chỗ hay thanh toán, mức giá nếu có.
- Tổng số cổng, trạng thái khai thác của từng cổng: hoạt động, bảo trì, offline, bị khóa.
- Loại connector từng cổng hỗ trợ: CCS2, CHAdeMO, Type 2…; không được chỉ lưu một connector chung cho cả trạm nếu thực tế các cổng khác nhau.
- Công suất tối đa, giới hạn chia sẻ công suất, khả năng sạc AC/DC và các ràng buộc vật lý liên quan.

Danh mục này là đầu vào cho compatibility, route recommendation và DES. Nó không cần “train”, nhưng sai connector là toàn bộ forecast sau đó có thể sai.

### 3.2. Lịch sử occupancy tổng quát của trạm

Đây là dữ liệu cho XGBoost/LSTM occupancy và Markov aggregate. Một quan sát cứ mỗi 5 phút là điểm khởi đầu hợp lý nếu provider chỉ cung cấp snapshot định kỳ; không cần cố tạo dữ liệu từng giây nếu nguồn không có thật.

Mỗi quan sát nên ghi:

- Thời điểm trạm thực sự được quan sát, có timezone.
- Thời điểm backend nhận dữ liệu. Hai thời điểm này khác nhau khi network chậm.
- Mã trạm và, tốt hơn nữa, số cổng khả dụng theo từng loại connector.
- Số cổng bận, rảnh, offline/faulted; tỷ lệ bận chỉ là số phụ trợ, không thay số đếm thực.
- Nguồn dữ liệu, mã event/snapshot, version schema và chất lượng dữ liệu.
- Các context chỉ thêm khi API có thể cung cấp đúng dữ liệu đó lúc chạy thật: thứ trong tuần, giờ trong ngày, ngày lễ của khu vực triển khai, thời tiết địa phương, giá, traffic…

Ví dụ một dòng dễ hiểu: “Lúc 18:05 tại trạm A, trong 4 cổng CCS2 đang vận hành có 3 cổng bận, 1 cổng rảnh, 0 cổng lỗi; snapshot do operator gửi lúc 18:05:10.”

### 3.3. Lịch sử session chi tiết của từng xe tại từng cổng

Đây là dữ liệu cho RDM và cũng là nền để xác minh DES. Cần tách dữ liệu này khỏi bảng occupancy tổng quát vì đây là dữ liệu nhạy cảm hơn và có hạt dữ liệu nhỏ hơn.

Mỗi session tối thiểu cần có:

- Một mã session ngẫu nhiên/đã pseudonymize; không dùng biển số hay định danh người dùng làm feature mặc định.
- Trạm nào, cổng nào, connector nào.
- Lúc xe cắm vào cổng.
- Lúc xe ngừng thực sự dùng điện, nếu có.
- Lúc xe **rút khỏi cổng**. Đây là mốc quan trọng nhất cho bài toán chờ.
- Tổng điện đã cấp; nếu có thì chuỗi công suất/dòng điện theo thời gian.

Dữ liệu tốt hơn có thể gồm:

- Mức pin bắt đầu và mức pin mục tiêu, nếu người dùng đồng ý chia sẻ.
- Loại xe hoặc nhóm xe, nhưng nên kiểm tra tính đầy đủ và quyền sử dụng trước khi dùng.
- Công suất hiện tại, năng lượng đã giao đến thời điểm quan sát, thời gian đã cắm.
- Lý do kết thúc, lỗi, session bị ngắt, thao tác stop từ app.

Điểm hay bị nhầm: xe ngừng hút điện không đồng nghĩa cổng đã rảnh. Người dùng có thể sạc đầy nhưng vẫn đỗ xe cắm dây. Với DES, label đúng là thời điểm xe **rút ra**, vì đó là lúc xe sau thật sự dùng được cổng.

### 3.4. Sự kiện queue và sự kiện phục vụ thực tế

Nếu muốn DES đúng trong môi trường live, cần quan sát được queue thật; không thể suy ra queue theo ý định của người dùng trên app.

Nên lưu:

- Xe hoặc token queue đã xác nhận có mặt tại trạm, thời điểm vào queue, thứ tự queue.
- Connector xe cần dùng và, nếu người dùng khai báo, nhu cầu năng lượng/thời lượng mong muốn.
- Thời điểm xe thực sự được cấp cổng, cổng nào, sau đó bắt đầu session lúc nào.
- Xe hủy, bỏ queue, không tới, connector không tương thích hoặc cổng lỗi.

Ý định “tôi đang đi tới trạm” chỉ là planned arrival. Nó có thể dùng để ước lượng áp lực tương lai, nhưng không được tính như một xe đã đứng trong confirmed queue.

### 3.5. Dữ liệu từ người dùng app cho recommendation

Đây chủ yếu giúp trả lời “trạm nào phù hợp với chuyến đi này”, không phải dữ liệu bắt buộc để RDM hoạt động.

Khi được người dùng cho phép, app/xe có thể gửi:

- Vị trí hiện tại, điểm đến hoặc route đang đi.
- Mức pin còn lại, quãng đường ước tính còn đi được, mức pin dự phòng mong muốn.
- Loại connector xe dùng được và công suất sạc tối đa mà xe nhận được.
- Mức pin/điện lượng người dùng muốn nạp hoặc muốn sạc trong bao lâu.
- Thời điểm dự kiến tới mỗi trạm, do route engine tính.
- Sở thích: “cần đi gấp”, “ưu tiên ít rủi ro”, “có thể chờ”, “ưu tiên rẻ”, “chỉ muốn trạm nằm trên đường”.

Mức pin và quãng đường còn đi được hoàn toàn có thể do xe tự tính rồi gửi sang, nếu người dùng cho phép. Backend không nên tự suy đoán quá mức khi xe đã có range estimate tốt hơn.

### 3.6. Ground truth để đánh giá

Không có ground truth thì không thể biết model tốt hay chỉ nghe có vẻ hợp lý. Cần lưu riêng các kết quả thực tế:

- Tại thời điểm dự báo, hệ thống đã nói gì và dùng model/source nào.
- Người dùng hoặc session thật sự bắt đầu sạc lúc nào.
- Họ chờ bao lâu từ lúc tới trạm đến lúc có cổng.
- Cổng thực sự nhả lúc nào.
- Có telemetry nào bị stale/mất/sai thứ tự hay không.

Những dòng này là “đáp án thật” để benchmark XGBoost, RDM, Markov và DES sau này.

## 4. Quy tắc chung để chia train, validation và test

### 4.1. Không chia ngẫu nhiên theo từng dòng

Dữ liệu có thời gian. Nếu lấy ngẫu nhiên một dòng tháng 10 vào train và một dòng tháng 9 vào test, model có thể học từ tương lai để dự báo quá khứ. Kết quả đẹp nhưng không giống môi trường production.

Cách mặc định:

```text
Quá khứ xa hơn       -> train
Khoảng sau train      -> validation
Khoảng mới hơn nữa    -> test chưa động tới
```

Ví dụ có thể là: train tháng 1–6, validation tháng 7, test tháng 8. Mốc tháng chỉ là ví dụ; phải chọn theo độ dài dữ liệu thực có.

Validation dùng để chọn feature, hyperparameter và quyết định có thử model phức tạp hơn không. Test là bài kiểm tra cuối cùng; không được liên tục xem test rồi chỉnh model tới khi điểm đẹp. Nếu đã dùng test để quyết định, phải mở một test window mới hoặc dùng rolling-origin backtest.

### 4.2. “Một xe phải nằm trong cùng một tập” áp dụng mạnh nhất cho RDM

Một session có thể sinh ra rất nhiều dòng telemetry: phút 1, phút 2, phút 3… của cùng một xe. Nếu phút 1–20 vào train còn phút 21–30 vào test, model gần như đã thấy chính xe đó; điểm test sẽ giả tạo.

Quy tắc bắt buộc cho RDM/session model:

> Toàn bộ ảnh chụp của cùng một session phải cùng train, hoặc cùng validation, hoặc cùng test.

Thực hiện theo thời gian: xếp session theo thời điểm rút cổng, chọn các session kết thúc trong giai đoạn train/validation/test tương ứng, rồi gán toàn bộ telemetry của session đó vào đúng tập. Session bắc qua ranh giới có thể được gán theo thời điểm rút cổng hoặc loại khỏi tập đánh giá, miễn chính sách được ghi rõ và không trộn session.

Với occupancy, đơn vị thường là snapshot của trạm chứ không phải xe. Khi đó cần tôn trọng thứ tự thời gian của cả chuỗi trạm. Có thể thêm một thử nghiệm khó hơn: giữ hẳn một số trạm chưa từng thấy làm test để biết model có tổng quát sang trạm mới hay không. Nhưng test chính để deploy vẫn là dự báo tương lai trên các trạm sẽ vận hành.

### 4.3. Chỉ dùng những gì đã biết tại lúc dự báo

Nếu dự báo tại 18:00 thì model chỉ được thấy dữ liệu tồn tại trước hoặc đúng 18:00. Không được dùng:

- Thời điểm xe rút cổng thật sự, vì đó chính là đáp án cần đoán.
- Tổng năng lượng cuối session nếu tại 18:00 chưa biết nó sẽ nạp bao nhiêu.
- Occupancy của 18:05 để dự báo 18:05.
- Một feature weather/calendar không có cách cung cấp khi API chạy thật.

Đây là lỗi leakage, nguy hiểm hơn lỗi code thông thường vì model vẫn chạy và nhìn có vẻ rất chính xác.

## 5. XGBoost occupancy: dự báo trạm sẽ đông đến đâu

### Nó giải quyết gì?

XGBoost occupancy trả lời: “Khi người dùng đến trạm sau 5, 10, 15… phút, khả năng bao nhiêu cổng sẽ đang bận?” Nó không biết chính xác xe nào đang cắm ở port nào.

XGBoost là nhiều cây quyết định ghép lại. Mỗi cây tìm những quy tắc nhỏ trong dữ liệu, cây sau sửa lỗi của cây trước. Vì vậy nó học được quan hệ phi tuyến kiểu: “trạm này chỉ đặc biệt đông vào tối thứ sáu sau mưa”, nhưng vẫn dễ bắt đầu hơn LSTM khi dữ liệu chủ yếu là bảng.

### Train cần dữ liệu gì?

Mức tối thiểu:

- Lịch sử occupancy có nhịp đều của từng trạm: ví dụ một snapshot mỗi 5 phút.
- Số cổng hoạt động và số cổng bận/rảnh tại mỗi snapshot.
- Mã trạm để model biết trạm nào là trạm nào, hoặc profile lịch sử riêng cho trạm.
- Timestamp và timezone.

Từ đó tạo feature dễ hiểu:

- Trạm đang bận thế nào trong 5, 10, 15… 60 phút gần nhất.
- Giờ trong ngày, thứ trong tuần.
- Mức đông điển hình của chính trạm đó ở khung giờ tương tự, nhưng profile này phải tính từ train data, không dùng test/future.
- Nếu deployment có thật: ngày lễ địa phương, thời tiết địa phương, giá hoặc traffic. Không có ở production thì không đưa vào train.

Target là occupancy thật tại những mốc tương lai. Ví dụ snapshot lúc 18:00 dự báo số/tỷ lệ cổng bận tại 18:05, 18:10… 19:00. Có thể train một model cho mỗi mốc hoặc một model nhiều đầu ra; code hiện theo hướng nhiều horizon.

### Output là gì?

Một output tốt có dạng:

> Khi xe đến sau 15 phút, trạm này dự báo 3 trong 4 cổng tương thích đang bận; độ bất định/quality: medium.

Nó có thể trả tỷ lệ bận, số cổng bận dự kiến và/hoặc xác suất trạm full. Cần ép output vào giới hạn vật lý: không thể âm, không thể nhiều cổng bận hơn số cổng đang hoạt động.

### So sánh với gì?

Không so XGBoost với “không có gì”. So với:

1. Persistence: cứ đoán 15 phút nữa tình trạng y như hiện tại.
2. Daily-naive: cùng giờ hôm qua sẽ như hôm nay.
3. Weekly-naive: cùng giờ/thứ tuần trước sẽ như hôm nay.
4. Sau này mới so với LSTM trên cùng feature, cùng split và cùng horizon.

Đo MAE, median absolute error và RMSE theo từng horizon; đồng thời xem từng trạm, từng loại connector và các giờ đông. Nếu model nói xác suất full, thêm Brier score/reliability để xem xác suất có đáng tin không.

### Dữ liệu nào phù hợp?

UrbanEV phù hợp để thử pipeline occupancy vì nó có chuỗi busy/idle theo trạm ở nhịp 5 phút. Nó không đủ cho RDM hay DES thực tế vì không có session ID, queue order, port lifecycle hay mốc xe rút cổng. Dữ liệu operator/OCPP ở Việt Nam mới là dữ liệu để quyết định deploy.

## 6. LSTM occupancy: chỉ khi chuỗi dữ liệu dày và sạch

### Nó giải quyết gì khác XGBoost?

LSTM cũng có thể dự báo trạm sẽ đông thế nào, nhưng thay vì nhìn các cột “5 phút trước, 10 phút trước…”, nó đọc cả một chuỗi có thứ tự. Về mặt ý tưởng, nó có thể nhận ra pattern kéo dài như một đợt tăng dần trước giờ tan tầm, rồi dự báo nhiều mốc tương lai cùng lúc.

LSTM không tự động tốt hơn XGBoost. Nó tốn dữ liệu, khó debug và dễ overfit hơn. Nếu XGBoost không vượt baseline rõ ràng thì việc nhảy sang LSTM thường không sửa được gốc vấn đề là thiếu dữ liệu/domain mismatch.

### Train cần dữ liệu gì?

Nó dùng gần như cùng domain occupancy với XGBoost, nhưng yêu cầu chặt hơn về chuỗi:

- Snapshot đều theo một cadence đã chọn, ví dụ 5 phút một lần.
- Chuỗi liên tục đủ dài qua nhiều ngày/tuần và qua các trạng thái đông/vắng khác nhau.
- Timestamp được chuẩn hóa timezone; event đến muộn phải được xử lý trước khi tạo chuỗi.
- Khoảng thiếu ngắn cần được đánh dấu rõ; outage dài không được lấp giả thành trạm rảnh.
- Có đủ trạm và đủ lịch sử đại diện cho các loại trạm. Một vài tuần ở một trạm ít biến động thường không đủ lý do dùng LSTM.

Input tại mỗi mốc có thể là occupancy, số cổng tương thích rảnh/bận, trạng thái offline, giờ/ngày, calendar và context đã được duyệt. Toàn bộ chuỗi trước thời điểm dự báo là input; output là occupancy ở các mốc 5–60 phút sau.

Nói “dày” không có một con số ma thuật. Nếu nguồn chỉ gửi đúng 5 phút một snapshot thì resample thành 5 phút; không nên bịa dữ liệu 1 phút. Với telemetry 1 phút hoặc dày hơn, có thể downsample về 1/5 phút để ổn định và giảm noise. Điều quan trọng là đều, đúng thứ tự và có đủ lịch sử, không phải cứ càng nhiều hàng càng tốt.

### Output và benchmark

Output giống XGBoost: occupancy hoặc xác suất full ở các mốc tới. Vì output giống nhau nên so sánh công bằng được:

- Cùng train/validation/test theo thời gian.
- Cùng input contract có thể cung cấp khi live.
- Cùng baseline persistence/daily/weekly/XGBoost.
- Cùng metric, cộng thêm latency và độ phức tạp vận hành.

Chỉ giữ LSTM nếu nó cải thiện nhất quán trên test tương lai và không làm serving quá chậm/khó tái tạo.

## 7. RDM: model dự báo cổng đang bị chiếm còn bao lâu sẽ nhả

### RDM là mục tiêu dự báo, không phải tên thuật toán

RDM là viết tắt của Residual/Remaining Duration Model. Nó trả lời một câu khác occupancy:

> Chiếc xe đang cắm ở cổng này, tại thời điểm này, còn bao lâu thì rút xe và nhường cổng?

RDM có thể dùng XGBoost, LSTM, survival model hoặc mô hình quantile. Vì vậy câu đúng không phải “RDM hay XGBoost/LSTM”, mà là “dùng XGBoost hay LSTM để xây RDM?”.

Khởi đầu hợp lý là RDM bằng XGBoost/quantile model, vì feature session thường là bảng và dữ liệu telemetry có thể chưa đủ dày. LSTM-RDM chỉ nên thử khi có chuỗi công suất/năng lượng dày, dài, sạch và có lý do chứng minh các điểm trước đó trong session giúp dự báo tốt hơn feature tổng hợp.

### Label đúng để train là gì?

Tại một thời điểm trong khi xe đang cắm, label là số phút còn lại đến khi xe **rút khỏi cổng**.

Không dùng thời điểm dòng điện về 0 nếu xe vẫn cắm chiếm cổng. Trong bối cảnh queue, xe sau chỉ phục vụ được sau khi connector vật lý rảnh.

### Train RDM cần dữ liệu gì?

Mỗi hàng train là một ảnh chụp của một session đang chạy. Ví dụ tại phút thứ 12 của session, model chỉ được thấy thông tin tồn tại ở phút 12; đáp án là xe rút cổng sau đó bao nhiêu phút.

Tối thiểu:

- Mã session, mã trạm, mã cổng, loại connector.
- Thời điểm cắm, thời điểm quan sát và thời điểm rút cổng thực tế.
- Xe đã cắm được bao lâu tại thời điểm quan sát.
- Năng lượng đã cấp đến thời điểm quan sát, nếu có.

Tốt hơn rất nhiều nếu có:

- Công suất/dòng điện hiện tại và vài giá trị ngay trước đó.
- Chuỗi công suất hoặc năng lượng tích lũy theo thời gian.
- Công suất danh định của cổng, loại connector, trạng thái fault.
- Mức pin hiện tại và mục tiêu, loại xe, requested energy/departure nếu người dùng chia sẻ hợp lệ.
- Thời gian, ngày, trạm; các feature này có thể giúp nhưng không được để chúng thay session telemetry.

Không được dùng những thông tin chỉ biết sau khi session kết thúc: tổng điện cuối session, thời điểm rút thật, hoặc điện được cấp ở các phút sau thời điểm snapshot.

### RDM bằng XGBoost và RDM bằng LSTM khác nhau thế nào?

RDM-XGBoost biến “diễn biến gần đây” thành vài cột tóm tắt: xe đã cắm 12 phút, đã nhận 9 kWh, công suất hiện tại 60 kW, công suất trung bình 5 phút gần nhất 58 kW. Nó là lựa chọn đầu tiên tốt khi telemetry không đều hoặc hạn chế.

RDM-LSTM đưa nguyên một chuỗi có thứ tự vào model: công suất phút 1, 2, 3… đến phút 12; năng lượng tích lũy tương ứng; trạng thái/công suất cổng. Nó có thể học dạng đường cong sạc, nhưng cần:

- Time series đủ dày, thường chọn cadence nhất quán 1–5 phút tùy nguồn.
- Nhiều session hoàn chỉnh, đủ loại xe/cổng/giai đoạn sạc.
- Xử lý rõ session ngắn, đo thiếu, thay đổi công suất và event đến trễ.
- So sánh công bằng với RDM-XGBoost trước khi giữ nó.

### Output nên là gì?

Đừng chỉ trả “còn 17 phút”. Output tốt là một phân phối hoặc ít nhất ba mốc:

- Kịch bản nhanh: cổng có thể nhả sau khoảng 10 phút.
- Kịch bản thường gặp: khoảng 17 phút.
- Kịch bản chậm: có thể tới khoảng 29 phút.

Các mốc này thường gọi là P10/P50/P90. Chúng không phải “độ chính xác 10/50/90%”; chúng mô tả các khả năng thời gian nhả cổng. Monte Carlo DES sẽ lấy mẫu từ distribution đó.

### Benchmark RDM với gì?

So candidate RDM với:

1. Trung vị thời gian còn lại theo trạm + loại connector + giai đoạn session.
2. Trung vị đơn giản theo loại connector/công suất nếu trạm ít dữ liệu.
3. Nếu provider có báo thời gian nhả cổng, xem đó là external reference mạnh và đối chiếu cả hai với thời điểm rút thật.
4. XGBoost-RDM so với LSTM-RDM, nếu đã đủ data gate cho LSTM.

Đo sai lệch phút trung bình/median; bóc theo xe đã cắm được bao lâu, connector, power band, trạm và giờ cao điểm. Với P10/P50/P90, phải đo calibration: nếu nói P90 thì đa số xấp xỉ 90% session thật phải nhả trước mốc đó. Sau cùng, đo tác động thật: đưa RDM vào DES có giảm sai lệch thời điểm người dùng bắt đầu sạc không?

## 8. ACN-Data: dùng để học gì, không dùng để khẳng định gì

ACN-Data là dữ liệu session sạc công khai từ mạng sạc thích ứng ở Mỹ, không phải dữ liệu trạm Việt Nam. Theo tài liệu chính thức, một session có các mốc xe cắm, ngừng hút điện, rút xe; năng lượng được cấp; định danh station/session; và endpoint time-series có dòng điện đo được/pilot signal theo timestamp. Một số session còn có thông tin người dùng khai báo như năng lượng yêu cầu hoặc thời điểm muốn rời đi. Xem [ACN-Data dataset](https://ev.caltech.edu/dataset.html).

ACN-Data đặc biệt phù hợp cho **thử pipeline RDM**, vì có hai thứ UrbanEV không có:

- Session ID để nhóm toàn bộ điểm telemetry của một xe.
- Thời điểm rút xe để tạo ground truth “còn bao lâu đến khi nhả cổng”.

Nếu lấy endpoint có time series, nó còn có current/pilot signal để thử feature công suất hoặc LSTM-RDM. Cần inspect export cụ thể trước khi train; không được giả định mọi site/session đều có đầy đủ SoC, loại xe, connector hay queue state.

ACN-Data không phù hợp để nói “model này sẽ chính xác ở Việt Nam”, bởi hành vi workplace tại Caltech/JPL, chính sách parking, loại xe, charger, giá và giờ làm khác thị trường mục tiêu. Nó cũng không tự cung cấp queue vật lý cho public charging, nên không đủ để chứng minh whole-DES wait time production. Vai trò đúng: dựng ETL, kiểm tra split theo session, thử baseline/RDM, và chứng minh pipeline kỹ thuật trước khi có operator data.

## 9. Markov: khi chỉ có trạng thái tổng quát, không có từng session

### Nó cần dữ liệu gì?

Markov dùng chuỗi snapshot occupancy đều theo thời gian. Ví dụ, với các cổng connector tương thích, trạng thái ở mỗi 5 phút có thể là “0 cổng rảnh”, “1 cổng rảnh”, “2 cổng rảnh”… Nó **không** nhìn một chiếc xe cụ thể, không biết xe đó cắm từ lúc nào và không tính được xe đó còn bao lâu sẽ rút.

Từ dữ liệu lịch sử, nó học/ước lượng các chuyển trạng thái. Ví dụ: trong các buổi tối thứ sáu trước đây, khi trạm này đang không còn cổng CCS2 rảnh, sau 5 phút có bao nhiêu lần xuất hiện ít nhất một cổng CCS2 rảnh? Đây là tần suất của những trạng thái tương tự trong quá khứ, không phải lịch của chiếc xe hiện đang cắm.

- Nếu hiện không còn cổng rảnh, 5 phút sau có xác suất bao nhiêu để có một cổng rảnh?
- Nếu hiện có một cổng rảnh, 5 phút sau xác suất hết chỗ là bao nhiêu?

Có thể tính transition bằng tần suất lịch sử hoặc dùng một model phụ có điều kiện theo giờ, ngày, trạm, connector và context. Nếu có connector-aware port state thì Markov nên chạy trên số cổng **tương thích** rảnh/bận, không phải tổng số cổng bất kỳ.

### Output là gì?

Markov có thể trả:

- Xác suất sạc ngay.
- Xác suất có ít nhất một cổng tương thích trong 5/10/15 phút.
- Một distribution của thời điểm “cổng phù hợp đầu tiên rảnh”.

Nó không thể nói chắc “xe ở port A sẽ rút lúc 18:17”, bởi nó không biết xe nào đang ở port A, xe đó đã cắm bao lâu, công suất đang sạc là bao nhiêu, hay xe ấy có rút ngay sau khi sạc xong không. Markov chỉ có thể nói: “với trạng thái full như bây giờ và các tình huống tương tự trong lịch sử, xác suất có một cổng CCS2 rảnh trong 10 phút là 40%.”

Xe đang cắm và xe xếp hàng trước requester chính là lý do Markov không phải công cụ đúng khi có telemetry chi tiết. Nếu quan sát được thứ tự queue và từng cổng/session, DES phải được dùng: provider hoặc RDM cho biết từng cổng nhả lúc nào, DES xếp từng xe trước requester vào connector tương thích. Nếu chỉ biết có `n` xe queue mà không biết họ là ai, cần sạc bao lâu hay dùng connector nào, có thể đưa queue length vào Markov/Erlang-C như một tín hiệu aggregate, nhưng output vẫn chỉ là xác suất/ước lượng trung bình, không phải lịch thật của queue.

### Markov khác Erlang-C thế nào?

Erlang-C là công thức hàng đợi cổ điển, không phải model ML cần học từng transition. Nó nhận các giả định tổng quát như số cổng đang phục vụ, tốc độ xe đến và thời lượng phục vụ trung bình, rồi ước lượng xác suất phải chờ và thời gian chờ trung bình. Nó hữu ích khi dữ liệu ít, nhưng thường dựa vào giả định arrival/service đơn giản và có xu hướng nhìn hệ thống ở mức aggregate/steady state.

Markov nhìn lịch sử chuyển trạng thái thực tế của chính trạm: từ full sang có chỗ, từ có chỗ sang full, theo nhịp 5 phút. Nó có thể mô tả xác suất theo trạng thái hiện tại tốt hơn Erlang-C nếu chuỗi dữ liệu đủ tốt. Đổi lại, nó vẫn không có chi tiết xe/port/queue như DES.

```text
Erlang-C: số cổng + lượng xe đến + thời lượng trung bình
          -> xác suất chờ và thời gian chờ aggregate

Markov:   lịch sử trạng thái bận/rảnh chuyển đổi qua thời gian
          -> xác suất có cổng rảnh trong các phút tới

DES:      từng port + từng session + confirmed queue
          -> lịch cấp cổng cụ thể và thời điểm bắt đầu sạc
```

Markov cần benchmark bằng Brier score cho “có sạc ngay không”, reliability/calibration của các xác suất và calibration của distribution thời điểm cổng đầu tiên rảnh. Nó không nên được train chỉ để tạo ra một probability mình đã muốn có từ trước.

## 10. DES: máy tính hàng đợi, không phải model ML

DES là Discrete-Event Simulation. Nó không train trên dataset. Nó chạy logic thời gian khi có đủ input đáng tin: cổng nào rảnh, cổng nào đang bận, mỗi cổng nhả khi nào, ai đang xếp hàng, xe nào dùng connector nào.

### DES cần những dữ liệu nào khi chạy live?

#### A. Thông tin cố định của trạm

- Cổng nào tồn tại, cổng nào đang vận hành.
- Connector mà từng cổng hỗ trợ.
- Công suất/ràng buộc kỹ thuật nếu chúng ảnh hưởng khả năng phục vụ.
- Operator/host/source để biết mức độ tin cậy của data và chính sách queue/reservation.

#### B. Telemetry mới của từng cổng

- Port đang available, charging, faulted/offline hay reserved.
- Mã session nếu cổng đang charging.
- Thời điểm snapshot được quan sát và độ mới của dữ liệu.
- Event ID/sequence/timestamp để xử lý event trùng, đến muộn hoặc sai thứ tự.
- Nếu provider biết: thời điểm hoặc số phút còn lại tới khi cổng được nhả.
- Nếu provider không biết: elapsed time, năng lượng đã cấp, current power, các signal khác để RDM dự báo.

#### C. Confirmed queue

- Thứ tự xe đã được xác nhận có mặt.
- Connector xe cần.
- Nhu cầu sạc/thời lượng mà xe khai báo nếu có.
- Hủy queue, bỏ queue, timeout, reservation nếu operator có chính sách đó.

#### D. Xe đang hỏi forecast

- Connector tương thích của xe.
- Khi nào xe có mặt ở trạm; thường là ETA từ route engine.
- Nhu cầu sạc để ước lượng charging duration sau khi xe được cấp cổng.

Nếu một cổng đang bận nhưng không có provider duration và RDM chưa được duyệt, DES không có quyền giả một con số chính xác. Nó phải trả không đủ dữ liệu cho precise DES, hoặc app dùng aggregate wait với caveat rõ ràng.

### Output RDM/ML đi vào DES như thế nào?

Ưu tiên duration cho mỗi cổng đang charging:

1. Provider/operator báo thời điểm nhả cổng mới và hợp lệ: dùng trực tiếp.
2. Provider không báo nhưng RDM đã được benchmark/calibrate/release: dùng distribution RDM.
3. Không có cả hai: không chạy precise DES cho snapshot đó.

Duration cho người trong confirmed queue:

1. Người dùng/operator khai báo duration hoặc energy target đáng tin: dùng như input.
2. Nếu thiếu, chỉ sau này mới dùng một **queue-duration model**. Đây có thể dùng XGBoost/LSTM giống RDM về kiến trúc, nhưng target khác: dự báo tổng thời gian chiếm cổng của xe trước khi nó bắt đầu sạc. Không nên âm thầm dùng average global ở DES production.
3. Khi chưa có dự báo đáng tin: DES cần fail closed hoặc hiển thị rằng forecast không đầy đủ.

### Thuật toán DES làm gì?

Theo lời thường:

1. Bỏ các cổng offline/faulted và cổng không tương thích.
2. Đặt cổng rảnh là “rảnh ngay”, cổng đang sạc là “rảnh khi xe hiện tại nhả”.
3. Lấy xe confirmed queue theo đúng thứ tự, cấp xe đầu queue vào cổng tương thích rảnh sớm nhất.
4. Khi xe đó sạc xong, cập nhật lúc cổng ấy rảnh cho xe tiếp theo.
5. Đến lượt requester, chọn cổng tương thích rảnh sớm nhất; khoảng từ ETA đến mốc đó là wait time.

Với tất cả duration cố định, output là một timeline deterministic. Với RDM/provider/queue duration có distribution, Monte Carlo lấy sample duration, chạy DES hàng nghìn lần và trả P10/P50/P90 wait, xác suất sạc ngay và xác suất chờ quá ngưỡng người dùng chọn.

### DES phải so với gì?

Khi có telemetry/queue thật, lưu forecast tại lúc ra quyết định rồi so với actual:

- Sai lệch thời điểm cổng nhả.
- Sai lệch thời điểm user bắt đầu sạc.
- Sai lệch wait time.
- Coverage: actual wait có nằm trong interval P10–P90 đúng tần suất mong đợi không?
- So DES với aggregate Erlang-C/Markov, theo trạm và theo chất lượng telemetry.

Chỉ khi DES đủ fresh và liên tục tốt hơn aggregate estimate mới nên dùng nó để ghi đè wait time trong ranking production.

## 11. Recommendation cuối cùng: dự báo vật lý và sở thích là hai việc khác nhau

Forecast trả lời điều có thể xảy ra ở trạm. Sở thích người dùng quyết định trạm nào hợp hơn. “Cần gấp” không được làm model bịa số phút nhỏ hơn; nó chỉ thay đổi cách xếp hạng giữa các trạm.

Ví dụ một recommendation có thể cân nhắc:

- Xe có đi được đến trạm với mức pin dự phòng an toàn không?
- Connector có tương thích không?
- Trạm có nằm trên route hoặc detour có chấp nhận được không?
- ETA đến trạm là bao lâu?
- Khi tới, khả năng sạc ngay là bao nhiêu?
- P50/P90 wait là bao nhiêu? Trạm rủi ro cao có thể không hợp người “cần đi gấp”.
- Xe cần nạp bao nhiêu điện, cổng có đủ công suất không, ước lượng sạc bao lâu?
- Giá, giờ mở cửa, access restriction, reliability, preference rẻ/nhanh.
- Chất lượng forecast: dữ liệu mới hay cũ, provider duration hay RDM, có queue thật hay chỉ aggregate estimate?

Ví dụ hành vi ranking:

| Kiểu người dùng | Hệ thống ưu tiên |
|---|---|
| Cần đi gấp | ETA + P90 wait thấp + xác suất có cổng cao + charging power phù hợp |
| Có thể chờ nhưng muốn rẻ | Giá/đường vòng thấp; vẫn cảnh báo rủi ro wait |
| Không muốn rủi ro | Trạm có P50 và P90 gần nhau, telemetry mới, forecast confidence cao |
| Chỉ sạc để đến điểm đích | Năng lượng tối thiểu đủ an toàn và trạm trên route |
| Muốn nạp nhiều để đi xa | Cổng công suất cao và dự báo thời gian rời trạm tổng cộng thấp |

Output cuối không nên chỉ là một “trạm tốt nhất” bí ẩn. Với mỗi trạm, app nên giải thích:

```text
Bạn đến sau: 12 phút
Khả năng cắm sạc ngay: 35%
Thời gian chờ P50/P90: 10 / 26 phút
Thời gian cần sạc dự kiến: 24 phút
Tổng thời gian đến lúc rời trạm P50/P90: 46 / 62 phút
Lý do: trên route, CCS2 tương thích, telemetry mới 20 giây,
      wait từ DES/RDM hoặc aggregate fallback
Caveat: chưa quan sát xe có thể tới trạm sau snapshot
```

## 12. Lộ trình nên làm, không bị lẫn mô hình

1. Giữ Queue Lab + Monte Carlo như demo logic; tiếp tục gắn nhãn duration mô phỏng.
2. Chốt data contract operator/OCPP: port lifecycle, connector, event ordering, freshness, session start/end/disconnect, queue events.
3. Dùng ACN-Data để dựng thử ETL và RDM benchmark: session grouping, split đúng, label nhả cổng, XGBoost-RDM trước.
4. Không release RDM chỉ vì nó chạy. So với median baseline và calibrate quantile trên test future.
5. Khi operator data thật có, lặp lại RDM trên domain mục tiêu; ACN chỉ là bài tập/pipeline validation.
6. Khi RDM được duyệt, thay duration synthetic trong Monte Carlo DES bằng distribution RDM ở những cổng provider không báo thời gian nhả.
7. Song song, nếu mục tiêu recommendation aggregate cần occupancy, thu occupancy Việt Nam rồi rerun XGBoost với temporal holdout. Chỉ thử LSTM khi XGBoost/baseline và data volume cho thấy có lý do.
8. Chỉ làm Markov khi có use case aggregate-only rõ ràng: nhiều trạm không cung cấp session/port detail nhưng có occupancy đều theo thời gian.
9. Backtest tất cả forecast với actual start time/wait time; sau đó mới cho DES thay aggregate wait trong ranking production.

Kết luận ngắn: **XGBoost/LSTM/Markov dự đoán hoặc ước lượng điều chưa biết; RDM dự đoán thời điểm nhả của một session; DES ghép các duration, cổng và queue thành lịch; recommendation ghép forecast đó với đường đi và nhu cầu của người dùng.**
