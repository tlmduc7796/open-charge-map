# Tổng hợp Machine Learning của Open Charge Map

## Phạm vi, cách đọc và kết luận ngắn

Tài liệu này tổng hợp toàn bộ phần Machine Learning (ML) hiện có trong thư mục `ml`: mã thực thi, notebook, cấu hình, manifest dữ liệu, báo cáo kết quả và toàn bộ tài liệu thiết kế trong `ml/docs`. Mục tiêu là mô tả hệ thống theo dòng dữ liệu và quyết định kỹ thuật, thay vì giải thích theo danh sách tệp.

Kết luận quan trọng nhất là: **repository chưa có mô hình ML nào được phát hành cho vận hành hoặc được dùng để tự động quyết định trạm/đường đi cho người dùng thật.** Phần ML đã tạo được một hạ tầng có kiểm soát leakage, provenance và các thử nghiệm offline; Queue Lab/DES hiện phục vụ demo và kiểm thử nội bộ. Dữ liệu vận hành Việt Nam theo từng cổng và từng phiên sạc vẫn là điều kiện còn thiếu để đi tới production.

Có ba nhóm công việc cần phân biệt rõ trong toàn bộ lịch sử phát triển:

1. **Benchmark nguồn UrbanEV:** dữ liệu lịch sử 5 phút ở Shenzhen, Trung Quốc, dùng để kiểm chứng pipeline dự báo độ bận của trạm. Đây là benchmark nguồn, không phải dữ liệu Việt Nam.
2. **Sân thử dữ liệu tổng hợp Gold:** hành vi sạc của ACN-Data Caltech (Mỹ) được giảm dữ liệu nhận diện, học thành prior bằng CTGAN, rồi gắn vào topology cổng đã được xác nhận ở Việt Nam và bị ràng buộc vật lý. Nó kiểm tra luồng dữ liệu, training contract và replay hàng đợi, chứ không chứng minh hành vi người dùng Việt Nam.
3. **Đường đi production trong tương lai:** dữ liệu OCPP/nhà vận hành Việt Nam được chuẩn hóa thành các bảng canonical; chỉ sau backtest, calibration, review riêng tư, monitoring và rollback mới được cân nhắc phục vụ.

Những kết quả dưới đây không được trộn lẫn giữa ba nhóm này. Cụ thể, việc XGBoost cải thiện nhỏ trên UrbanEV không mâu thuẫn với việc persistence thắng trên Gold: đó là hai dataset, hai quy luật dữ liệu và hai experiment khác nhau.

## 1. Bài toán sản phẩm và kiến trúc logic

Người dùng không cần biết tên model; câu hỏi thực tế là: *khi tôi đến một trạm, có cổng phù hợp không, tôi phải chờ bao lâu, và trạm nào hợp nhất với chuyến đi của tôi?* Repository tách câu hỏi này thành các phần có nhãn và dữ liệu riêng, để tránh lấy một mô hình rồi gán vai trò không đúng cho nó.

```text
Lịch sử độ bận tổng quát của trạm                 Trạng thái chi tiết từng cổng/phiên
  (bao nhiêu cổng bận/rảnh theo thời gian)          (cổng nào bận, xe nào đang cắm, queue nào xác nhận)
                 |                                                    |
                 v                                                    v
    dự báo occupancy hoặc baseline                    provider báo thời gian nhả cổng
    (persistence / XGBoost / LSTM)                    hoặc RDM dự báo thời lượng còn lại
                 |                                                    |
                 v                                                    v
  Markov hoặc Erlang-C khi chỉ có tổng quát       DES xếp cổng theo connector và thứ tự queue
                 \                                                   /
                  \                                                 /
                   +------ xác suất/chờ/khả năng sạc ngay --------+
                                          |
                                          v
       ETA tuyến đường + connector + pin/range + giá + sở thích + cờ độ tin cậy
                                          |
                                          v
                              xếp hạng và giải thích trạm
```

Hai nhánh không thay thế nhau. Khi chỉ có snapshot “3/4 cổng đang bận”, dự báo occupancy và mô hình xác suất aggregate là hợp lý. Khi có trạng thái mới của từng cổng, các session đang sạc, thời điểm nhả cổng và hàng đợi thực sự, mô phỏng sự kiện rời rạc (DES) tạo lịch cấp cổng cụ thể hơn. DES không được phép tự bịa một thời lượng trung bình nếu thiếu thông tin đó; khi telemetry thiếu hoặc stale, hệ thống phải quay về ước lượng aggregate hoặc nói rõ chưa đủ dữ liệu.

### Khái niệm cốt lõi

- **Occupancy** là tỷ lệ/số cổng đang bị chiếm ở cấp trạm vào một thời điểm. Nó không biết xe nào nằm ở cổng nào.
- **RDM (Remaining/Residual Duration Model)** trả lời câu khác: xe đang chiếm một cổng sẽ còn bao lâu mới *rút dây và nhả cổng vật lý*. Nhãn đúng là thời gian từ lúc quan sát đến `disconnect_at`, không phải lúc dòng điện về 0 hay lúc xe đã đầy.
- **Markov** là lớp xác suất chuyển trạng thái aggregate: ví dụ, nếu tất cả cổng CCS2 đang đầy, 5 phút sau xác suất có ít nhất một cổng rảnh là bao nhiêu. Nó không thể lập lịch một xe cụ thể.
- **DES** là thuật toán lịch hàng đợi, không phải model ML. Nó đặt thời điểm rảnh cho từng cổng, lần lượt cấp cổng tương thích cho hàng đợi đã xác nhận và cho người đang hỏi.
- **P10/P50/P90** là ba mốc phân vị: tình huống sớm, điển hình và muộn của thời lượng/wait. Chúng mô tả bất định, không phải ba mức “độ chính xác”.

## 2. Dữ liệu và provenance

### 2.1. UrbanEV: nguồn lịch sử để kiểm chứng pipeline occupancy

UrbanEV là archive bất biến đã được fingerprint: SHA-256 `9d3f0a…27881a79`, 647,305,188 bytes, ZIP integrity PASS. Nó chứa chuỗi cấp trạm 5 phút từ **01-09-2022 đến 28-02-2023**. Tiền xử lý chọn 50 trạm đại diện theo tier dung lượng, tạo 2,606,400 quan sát. Với từng snapshot, chỉ giữ số cổng bận/rảnh để suy ra dung lượng cố định của trạm và tỷ lệ bận trong khoảng [0, 1]. Không đưa giá, thời tiết, POI, queue hay các dữ liệu tương lai vào dataset cơ sở.

Chia thời gian đã được đóng băng:

| Tập | Khoảng thời gian | Số hàng | Tỷ lệ bận trung bình |
| --- | --- | ---: | ---: |
| Train | 01-09-2022 – 15-01-2023 | 1,972,800 | 0.2723 |
| Validation | 16-01-2023 – 31-01-2023 | 230,400 | 0.2279 |
| Test | 01-02-2023 – 28-02-2023 | 403,200 | 0.2517 |

Preprocess kiểm tra không có occupancy âm/vượt dung lượng, timestamp hợp lệ, và `train` kết thúc trước `validation`, còn validation kết thúc trước test. Dữ liệu này có đủ chuỗi occupancy để thử XGBoost, LSTM hoặc Markov aggregate, nhưng **không có session ID, thứ tự queue, lifecycle per-port hay thời điểm xe rút**. Vì vậy nó không thể tạo RDM trung thực, không thể kiểm chứng DES theo từng xe, và không tạo bằng chứng về độ chính xác tại Việt Nam.

### 2.2. ACN-Data: nguồn hành vi/session để dựng pipeline RDM và CTGAN

ACN-Data Caltech là nguồn công khai ở Mỹ. Các session summary tải về nằm ngoài Git, token chỉ được đọc từ biến môi trường hoặc `.env` bị ignore, và manifest lưu hash/timestamp thay vì bí mật. Tài liệu handoff ghi nhận 31,424 session Caltech 2018–2021: 15,297 (2018), 10,617 (2019), 2,472 (2020), và 3,038 (2021). Time series dòng điện đã chỉ được thử trên lát nhỏ; chưa có mirror đầy đủ cho hơn 31 nghìn session vì endpoint phải tải theo từng session.

ACN có mốc cắm, kết thúc sạc, rút xe và điện năng; vì vậy nó hữu ích để kiểm tra ETL/session split/RDM. Dù vậy hành vi workplace của Caltech/JPL, chính sách bãi đỗ, xe, giá và nhu cầu khác Việt Nam. Nó chỉ là dữ liệu nguồn cho pipeline và prior tổng hợp, không phải ground truth production Việt Nam.

### 2.3. Gold synthetic: hành vi nguồn + topology Việt Nam + ràng buộc vật lý

Để có sân thử end-to-end trước khi nhận dữ liệu nhà vận hành, pipeline tạo Gold dataset theo chuỗi:

```text
ACN raw session summaries 2018–2021
  -> bảng hành vi đã giảm thông tin nhận diện
  -> CTGAN học phân phối hành vi nguồn
  -> lấy mẫu hành vi mới
  -> phân bổ vào port của trạm Việt Nam có topology provider_reported
  -> ép ràng buộc vật lý và replay 5 phút
  -> sessions, telemetry, occupancy cho train/evaluation offline
```

Bảng đầu vào CTGAN cố ý bỏ user ID, session ID gốc, station/port ID gốc và timestamp rút xe. Nó chỉ giữ giờ/ngày đến, thời gian đỗ, thời gian sạc, điện năng đã giao/yêu cầu và thời lượng có thể ở lại. CTGAN học **prior hành vi nguồn** chứ không được dùng để gán danh tính hay vị trí thực. Trainer mã nguồn dùng `CTGANSynthesizer`; tham số CLI mặc định là 300 epoch, nhưng handoff ghi rõ scenario Gold hiện tại đã chọn **30 epoch** vì fidelity check trên held-out 2021 tốt hơn run 200 epoch theo sai lệch tổng hợp. Không có report fidelity chi tiết được track trong checkout, nên không có số liệu fidelity nào được suy diễn thêm ở đây.

Generator chỉ nhận trạm có `matched_station_id` và topology kỹ thuật được đánh dấu `provider_reported`; các connector `synthetic` hoặc `unknown` bị loại. Scenario hiện được tài liệu ghi là TP.HCM từ 01-01 đến 01-04-2026, seed `20261004`, giả định 1.5 session/port/ngày, 16 trạm và 211 cổng. Con số session/port/ngày là giả định scenario, không phải demand đã học từ Việt Nam.

Các kiểm tra vật lý gồm: một cổng không phục vụ hai xe cùng lúc, năng lượng không vượt công suất cổng × thời lượng sạc × hiệu suất giả định 0.92, queue quá 120 phút bị bỏ, occupancy không vượt dung lượng. Mọi bảng được gắn `is_synthetic=true`, source và quality flag synthetic, manifest hash, rồi chia theo thời gian 60/20/20.

| Sản phẩm Gold | Ý nghĩa | Dùng cho |
| --- | --- | --- |
| Danh mục trạm/cổng | inventory, connector và công suất đã chọn | ràng buộc topology, DES |
| Sessions | vòng đời từ đến, cắm, xong sạc đến rút dây | nhãn RDM và replay |
| Telemetry 5 phút | năng lượng/công suất replay theo từng session | feature RDM, không phải meter thật |
| Occupancy 5 phút | số/tỷ lệ cổng bận của mỗi trạm | benchmark occupancy |

Telemetry Gold là piecewise-constant replay từ sessions, không phải dòng/công suất do cổng thật đo. Vì vậy mô hình train từ nó chỉ cho biết contract có chạy được; không được diễn giải thành accuracy người dùng thật.

### 2.4. Dữ liệu bổ sung: calendar, weather và simulator

Các calendar 5 phút cho Germany và Vietnam đã được tạo cùng phạm vi ngày; calendar Việt Nam có weekend, holiday, Tết, mùa mưa phía Nam và mùa du lịch. Weather lịch sử lấy từ Open-Meteo rồi nội suy từ giờ xuống 5 phút; artifact hiện lưu tọa độ Paderborn, Đức. Các feature temporal/context chỉ là candidate: temporal cần nguồn calendar đúng deployment region tại inference, còn weather cần nguồn station-local realtime cùng policy freshness/missingness. Do đó chúng chưa được sử dụng trong một release production.

Có một điểm cần đánh dấu: tài liệu UrbanEV mô tả source domain là Shenzhen, trong khi collector weather và một artifact calendar được chuẩn bị theo Germany/Paderborn. Repository không ghi một experiment kết quả nào xác nhận đã ghép chúng để train. Vì profile temporal/context bị khóa, bản tổng hợp này **không coi weather/calendar Germany là feature hợp lệ của UrbanEV hay Việt Nam**; đây là dữ liệu chuẩn bị/candidate cần audit địa lý trước khi dùng.

`ml/data/sessions.csv` là 4,020 session synthetic của simulator (tháng 8–9/2026), có explicit `is_synthetic=true`. Nó được dùng trong các thí nghiệm seed/replay nội bộ, không phải dữ liệu quan sát.

## 3. Lớp chuẩn hóa dữ liệu và chống leakage

Thay vì tạo extractor riêng cho từng model, repository chuẩn hóa mỗi nguồn thành bốn sản phẩm canonical. Adapter là nơi hiểu tên cột nhà cung cấp; model chỉ đọc schema đã chuẩn hóa.

| Sản phẩm canonical | Một hàng là gì | Timing semantics | Các phần dùng nó |
| --- | --- | --- | --- |
| Occupancy history | snapshot của trạm | `observed_at` là lúc trạng thái đúng; `received_at` là lúc backend nhận | XGBoost/LSTM/Markov aggregate |
| Sessions | một lần xe cắm | `disconnect_at` là nhả cổng vật lý; `done_charging_at` không thay thế nó | RDM, audit/replay |
| Session telemetry | một quan sát trong session | năng lượng/công suất chỉ được phép là điều đã biết ở thời điểm quan sát | RDM |
| Port status | một snapshot/sự kiện của một cổng | connector, state, event sequence và freshness | Markov connector-aware, DES future |

Mỗi dòng có source, schema version, quality/backfill flag và timestamp UTC; raw export được giữ append-only bên ngoài Git, còn sản phẩm được kèm manifest hash/provenance. Adapter chấp nhận một số tên ACN/OCPP/vendor thông dụng nhưng không được biến raw column thành model feature chỉ vì tên cột thuận tiện.

Ba hàng rào chống leakage được thực hiện xuyên suốt:

1. **Chia theo thời gian.** Train ở quá khứ, validation tiếp theo để chọn thiết kế, test ở đoạn sau để chấm một lần. Nếu test đã bị xem khi ra quyết định, nó phải mang nhãn exploratory; một test window mới hoặc rolling-origin mới mới đủ làm final holdout.
2. **Không tách session qua nhiều tập.** Mọi snapshot của một xe/session RDM nhận cùng split dựa trên `disconnect_at`; session censored không trở thành nhãn.
3. **Không dùng tương lai.** Không đưa disconnect, done-charging, final energy, SOC khi rời, idle duration hoặc lý do kết thúc vào feature RDM. Với occupancy, lag và target phải cùng split; các hàng đụng ranh giới bị bỏ thay vì mượn nhãn tương lai.

Điều này là quan trọng hơn việc chọn model: nếu kiểm tra leakage sai, model vẫn chạy và có điểm đẹp nhưng không thể tái lập lúc live.

## 4. Nhánh dự báo occupancy

### 4.1. Biểu diễn và feature

Đầu vào cốt lõi là 12 snapshot occupancy trước đó, tương đương một giờ lịch sử ở cadence 5 phút. Với mỗi origin, hệ thống tạo 12 target trực tiếp: +5, +10, …, +60 phút. Direct multi-horizon tránh việc forecast +60 phải phụ thuộc vào chính dự báo +55 trước đó.

Có bốn profile feature:

| Profile | Nội dung | Trạng thái inference |
| --- | --- | --- |
| Baseline | 12 lag occupancy | reproducible với lịch sử occupancy hợp lệ |
| Seasonal | 12 lag + prior theo trạm/weekday-vs-weekend/slot 5 phút của thời điểm cần dự báo | có thể đóng gói cùng model nếu có station ID và timestamp |
| Temporal | baseline + calendar | bị khóa vì backend chưa có calendar deployment-region phù hợp |
| Context | temporal + weather | bị khóa vì chưa có weather station-local realtime được validation |

Seasonal prior được fit **chỉ từ train**. Nó ước lượng mức bận điển hình của chính trạm tại khung 5 phút tương ứng, có smoothing về trung bình của trạm khi bucket ít dữ liệu. Khi dự báo +30 phút, feature seasonal phải là bucket của thời điểm +30, không phải giờ ở origin. Exact profile này được persist để train, validation, test và inference dùng một quy tắc duy nhất.

### 4.2. Baseline và XGBoost

Baseline quan trọng nhất là **persistence**: giữ trạng thái quan sát gần nhất. Ngoài ra benchmark so với “cùng giờ hôm qua” và “cùng giờ/tuần trước”. XGBoost gồm nhiều cây quyết định tuần tự sửa sai số; từ các lag, nó học quan hệ phi tuyến mà không cần recurrent network.

Trainer hiện hỗ trợ hai cách:

- Dự báo trực tiếp occupancy cho mỗi horizon; hoặc
- Học **residual so với persistence**, tức chỉ học mức phải cộng/trừ vào trạng thái mới nhất. Đây là cách hợp lý khi persistence vốn rất mạnh ở forecast ngắn.

Thiết lập XGBoost source benchmark: objective tuyệt đối L1 (`reg:absoluteerror`), 500 trees, depth 8, learning rate 0.05, subsample 0.8, column subsample 0.8, seed 42, 12 lag. Trainer artifact-format dùng square error với cùng số tree/depth/rate; artifact UrbanEV luôn được meta gắn `exploratory_source_domain_only` và backend có chủ ý từ chối serving nó.

Benchmark còn thử gate theo độ lớn residual, chọn alpha/threshold trên validation. Đây không phải confidence hay uncertainty. Ở run UrbanEV đã ghi nhận, tất cả horizon chọn alpha=1 và threshold gần 0; gate thực tế không loại dự báo nào, lợi ích là từ residual XGBoost L1.

### 4.3. Kết quả occupancy UrbanEV

Kết quả benchmark UrbanEV được chốt là `GO_NEXT_EXPLORATORY_CHECK`: residual XGBoost tốt hơn persistence ở toàn bộ 12 horizon trên validation, cải thiện MAE khoảng **4.15%–14.01%**. Trên test exploratory, cải thiện chỉ **0.91%–1.31%**. Daily/weekly-naive thua persistence rõ rệt; ECE calibration của residual XGBoost tốt hơn persistence tại các horizon đã báo cáo.

Đây là tín hiệu rằng XGBoost học được một phần biến động trên source domain, nhưng không phải lý do để deploy hoặc nhảy sang LSTM: lợi ích test nhỏ, test đã được xem để ra quyết định, và Trung Quốc không phải Việt Nam. Quyết định hiện tại là nếu quay lại nhánh này thì chạy rolling-origin backtest mới để xem lợi ích khoảng 1% có lặp lại hay không.

### 4.4. Benchmark Gold occupancy: kết quả trái chiều nhưng nhất quán về ý nghĩa

Trên Gold Q1/2026, hai XGBoost thử nghiệm thua persistence ở cả 12 horizon:

| Candidate | Validation mean MAE | Kết luận |
| --- | ---: | --- |
| Persistence | 0.049078 | baseline tốt nhất |
| XGBoost 12 lag | 0.070331 | thua persistence |
| XGBoost 12 lag + seasonal prior | 0.071334 | cũng thua persistence |

Ví dụ tại +5 phút: 0.016286 (persistence), 0.024643 (lag XGBoost), 0.025824 (seasonal); tại +60 phút: 0.078358, 0.109355, 0.109020. Benchmark thống nhất khác cũng so sánh Markov/XGBoost/LSTM trên 248,464 hàng train, 82,752 validation và 82,736 test exploratory. Để tái lập trên máy cá nhân, XGBoost của benchmark này bị giới hạn 50,000 hàng cho mỗi horizon (220 tree, depth 6, learning rate 0.05, subsample/column subsample 0.8); ngân sách giới hạn đó không phải result công bố production. MAE validation ở +5/+15/+30/+45/+60 lần lượt:

| Horizon | Persistence | Markov | XGBoost | LSTM |
| ---: | ---: | ---: | ---: | ---: |
| 5 phút | 0.0163 | 0.0246 | 0.0250 | 0.0939 |
| 15 phút | 0.0296 | 0.0446 | 0.0444 | 0.1029 |
| 30 phút | 0.0475 | 0.0706 | 0.0691 | 0.1119 |
| 45 phút | 0.0634 | 0.0928 | 0.0906 | 0.1234 |
| 60 phút | 0.0784 | 0.1124 | 0.1095 | 0.1320 |

Daily và weekly naive khoảng 0.24–0.26 MAE nên không có mặt trong bảng rút gọn. Kết quả không chứng minh XGBoost/LSTM “vô dụng”; nó cho biết Gold simulator hiện có state persistence rất mạnh, còn arrivals còn lại chủ yếu ngẫu nhiên và ba tháng synthetic chưa cung cấp tín hiệu đủ giàu. Quyết định đúng là dừng tăng độ phức tạp, dùng persistence cho demo occupancy, và ưu tiên telemetry thật.

### 4.5. LSTM, Transformer và foundation model: có code nhưng chưa được kích hoạt

**Hybrid LSTM occupancy (Phase 05A)** đã được hiện thực để nghiên cứu. Nó đọc 12 occupancy lag theo đúng thứ tự thời gian bằng LSTM hidden size 32; một nhánh context đọc các feature lịch mục tiêu và seasonal prior ở từng horizon; hai nhánh ghép lại qua dense 64→32, dropout 0.2 rồi sigmoid tạo 12 occupancy ratio. Loss là SmoothL1 regression, Adam mặc định learning rate 0.001, batch 512, 20 epoch, seed 42. Nó không phải binary classifier/BCE và **không tạo Markov transition head**. Schema hiện tắt profile này; chưa có experiment được chấp nhận cho serving.

Benchmark Gold có một LSTM nhỏ, intentionally bounded để laptop tái lập: 16 hidden units, L1 loss, Adam 0.002, 4 epoch, tối đa 40,000 train rows. Những số LSTM trong bảng Gold thuộc benchmark giới hạn này, không phải release hybrid LSTM Phase 05A.

**Transformer** là skeleton multi-horizon: projection width 64, hai encoder layer với 4 heads, context branch, MSE/AdamW 0.001 trong 20 vòng. Nó cần sequence occupancy + weather/traffic và context calendar/POI đã được schema duyệt; profile đang disabled và enriched dataset chưa tồn tại.

**Foundation model** chỉ có cổng kế hoạch cho Chronos hoặc TimesFM. Chưa có provider adapter/package/license/version được pin, chưa có GPU budget/dataset protocol được duyệt, nên `--execute` cố ý fail. Đây không phải model đã fine-tune.

## 5. Markov: fallback xác suất, không phải RDM hay DES

Với port status đầy đủ, pipeline có thể gom theo trạm + loại connector + timestamp thành số cổng compatible available/busy/unavailable và cờ full. Bảng transition học trên train tần suất từ số cổng rảnh hiện tại sang số cổng rảnh kế tiếp tại cadence hợp lệ; gap không bị giả làm transition. Validation đo Brier score cho sự kiện “bước kế tiếp có cổng rảnh”, test chỉ mở bằng opt-in và được gắn exploratory.

Lớp toán học tách riêng nhận xác suất busy→free và free→busy theo từng bước 5 phút, lan truyền xác suất busy, rồi suy ra xác suất sạc ngay, xác suất lần đầu xuất hiện cổng rảnh, expected wait trong horizon và xác suất vẫn bận. Re-occupation không ảnh hưởng sau khi người dùng đã thấy cổng rảnh lần đầu.

Hiện Markov **chưa có transition model đã train/calibrate để dùng sản phẩm**. Nó bị deferred; chỉ phù hợp nếu không có lifecycle/session/queue per-port. Khi DES có input mới và đủ, DES luôn ưu tiên hơn Markov; không được suy ngược transition từ một probability mong muốn.

## 6. Nhánh RDM: dự báo thời gian nhả cổng

### 6.1. Tạo dataset RDM

Một hàng supervised là ảnh chụp khi xe vẫn còn cắm. Feature cơ bản là: xe đã cắm bao lâu, năng lượng đã giao đến lúc đó, current power, station, port và connector. Label là `disconnect_at - observed_at` tính bằng phút và phải dương. Toàn bộ telemetry của session được gán cùng split theo disconnect; các observation trước khi cắm/sau khi rút và session censored bị loại.

Profile **live-safe** bổ sung công suất danh định cổng từ inventory, giờ/thứ local (mặc định Asia/Ho_Chi_Minh) và cờ đang rút điện. Nó vẫn cấm disconnect, done-charging, final energy và idle duration làm feature. Đây là profile duy nhất có thể được train lại cho candidate production sau khi nhận telemetry nhà vận hành thật.

### 6.2. Quantile XGBoost RDM

Ba XGBoost quantile riêng tạo P10/P50/P90. Preprocess numeric dùng median imputation; categorical (station/port/connector) dùng most-frequent imputation và one-hot với unknown ignored. Mỗi model dùng objective `reg:quantileerror`, 350 trees, depth 6, learning rate 0.04, subsample 0.8, column subsample 0.8, seed 42. P50 được chấm MAE, median absolute error, RMSE; các phân vị được chấm coverage và quantile crossing.

Validation là nơi lựa chọn; test mặc định bị khóa. Artifact luôn `experimental_not_serving_ready`; nếu có provider-reported remaining duration mới/hợp lệ thì provider thắng, RDM chỉ là fallback sau calibration/replay/monitoring/rollback review.

### 6.3. Kết quả RDM Gold và thí nghiệm hai nhóm feature

Gold RDM quantile đã chạy để chứng minh contract: 499,279 observation train và 168,749 validation. P50 validation có MAE **186.42 phút**, median absolute error **137.01 phút**, coverage P10/P50/P90 **11.1% / 50.6% / 87.7%**, crossing **0.43%**. Test chưa mở tại run đó. Những số này không đại diện accuracy thực, vì telemetry replay synthetic.

Thí nghiệm độc lập theo nhiều simulator seed kiểm tra giá trị thông tin của hai profile. 4 seed train có 3,712 session/76,400 snapshot; 2 seed validation có 1,864/40,960; 2 seed test có 1,821/42,679. Tách bằng seed bảo đảm cả “thế giới” mô phỏng của validation/test chưa từng đi vào train.

| Profile | MAE validation | MAE test | Median AE test | Coverage P10–P90 test |
| --- | ---: | ---: | ---: | ---: |
| Live-safe/basic | 76.5 phút | 99.4 phút | 51.8 phút | 69.9% |
| Enhanced simulator-only | 63.5 phút | 86.0 phút | 36.7 phút | 69.1% |

Enhanced thêm SOC khi đến, SOC hiện tại suy từ meter, công suất xe tối đa, dung lượng pin và nhóm xe. Nó giảm test MAE khoảng **13.4 phút**, cho thấy các thuộc tính này chứa signal trong simulator; nhưng coverage khoảng 70% thấp hơn trực giác khoảng 80% của interval 10–90%, MAE còn cao, và những feature đó cần consent/quyền provider ngoài đời. Vì vậy enhanced chỉ trả lời “nên xin thêm dữ liệu gì”, không phải candidate serving.

## 7. DES, Queue Lab và replay RDM

Hiện thứ tự delivery được chốt là **Queue Lab deterministic → Monte Carlo DES → ACN/RDM**, không phải train thêm occupancy, LSTM hay Markov ngay lập tức.

### 7.1. Queue Lab deterministic

Queue Lab nhận port state (`available`, `charging`, `offline`), connector của từng port, remaining time đến physical port release cho cổng đang charging, confirmed queue theo thứ tự và connector/duration, rồi connector của requester. Nó bỏ port offline, đặt port rảnh tại evaluation time và port bận tại lúc nó nhả, sau đó lần lượt cấp port compatible rảnh sớm nhất cho queue và requester. Planned arrival trong app không được tự coi là confirmed queue.

Preset kiểm thử 28 phút là một ví dụ kiểm tra logic connector: Port A CCS2 bận 8 phút; Port B Type2 bận 20 phút; queue #1 cần CCS2/sạc 20 phút; requester cần CCS2. Queue nhận A từ phút 8–28, nên requester đợi 28 phút. Nếu cả hai port cùng CCS2, đáp án phải là 20 chứ không phải 28.

Queue Lab gắn rõ `data_source: simulated` và các caveat: chỉ queue đã xác nhận, không nhìn thấy xe sẽ tới sau snapshot, snapshot có thể cũ, và nếu không có port compatible thì trả wait null thay vì 0 phút. Nó chưa tự ghi đè ETA trong recommendation live.

### 7.2. Monte Carlo DES

Mode Monte Carlo dùng cùng thuật toán nhưng sample duration nhiều lần (ví dụ 1,000 run, seed cố định) để trả P10/P50/P90 wait và P(wait > N). Khi mọi duration cố định, output bắt buộc trùng deterministic DES; đây là invariant test. Ở giai đoạn hiện tại, distribution Monte Carlo là synthetic assumption, không phải confidence của ML.

### 7.3. Replay/evaluation đã chạy

Benchmark simulator seed `20261006` tạo 935 session và chấm 360 snapshot có session active ở năm ETA. Khả năng dự báo “có cổng”:

| ETA | Persistence, toàn trạm | XGBoost, toàn trạm | RDM, chỉ snapshot hiện tại |
| ---: | ---: | ---: | ---: |
| 5 phút | 95.8% | 70.8% | 98.6% |
| 15 phút | 87.5% | 76.4% | 87.5% |
| 30 phút | 83.3% | 75.0% | 83.3% |
| 45 phút | 70.8% | 65.3% | 84.7% |
| 60 phút | 70.8% | 63.9% | 84.7% |

RDM hữu ích hơn ở ETA xa trong **bài snapshot** vì nó biết các xe đang bận có thể nhả; nó không tính xe mới sẽ đến sau snapshot, nên không thể so như full-station future demand. RDM release MAE là 117.6 phút và interval coverage 73.6%, còn quá yếu cho người dùng thật. Lý do được ghi nhận là distribution duration Gold/replay khác simulator benchmark: pipeline không leak nhưng transfer giữa các miền synthetic đã yếu.

Replay Queue Lab seed `20261007` sau đó thêm một xe queue đã xác nhận, duration cố định 30 phút, và requester sau xe đó. Có 46 scenario, P50 wait MAE **64.9 phút**, coverage P10–P90 **84.8%**, median actual wait **0 phút**. Median 0 không có nghĩa model tốt: nhiều scenario vẫn còn port khác rảnh. Kết luận là luồng RDM → Queue Lab đã vận hành đúng theo connector/queue và biểu diễn interval, nhưng duration prediction chưa đủ để gọi là ETA thật.

## 8. Thứ tự phát triển và quyết định chuyển hướng

1. **Xây nền occupancy source-domain.** Archive UrbanEV được nhận dạng/hash, preprocess thành chuỗi trạm 5 phút với split thời gian và kiểm tra invariant.
2. **Xây contract feature/training.** Tạo 12 lag, 12 direct horizon, feature profiles và artifact metadata để training/inference có thể tái lập; temporal/context bị từ chối nếu API không thể tái tạo feature.
3. **Thử benchmark UrbanEV.** Residual XGBoost có tín hiệu nhỏ hơn persistence nhưng chỉ trên Shenzhen/test exploratory. Không promote vì domain mismatch và test không còn pristine.
4. **Dựng Gold synthetic có provenance.** Vì chưa có telemetry/session Việt Nam, ACN được privacy-minimize → CTGAN → topology Việt Nam ràng buộc vật lý. Mục đích là test kỹ thuật, không tạo “Vietnam ground truth”. CTGAN 30 epoch được chọn cho scenario Gold vì fidelity held-out 2021 tốt hơn run 200 epoch theo sai lệch tổng hợp; đây là lựa chọn experiment, không phải claim hành vi Việt Nam.
5. **Chạy Gold occupancy/RDM.** Persistence thắng các occupancy candidate; RDM chứng minh dataset split/artifact chạy nhưng sai số/cali chưa đủ. Điều này loại bỏ lý do chạy LSTM/Transformer chỉ để tìm model phức tạp hơn.
6. **Tập trung Queue Lab/DES.** Logic physical connector/queue được làm rõ trước, deterministic rồi Monte Carlo, sau đó mới dùng RDM để thay synthetic duration nếu có ground truth và calibration.
7. **Giữ các hướng mở nhưng khóa gate.** Markov là aggregate fallback; LSTM/Transformer/foundation cần dữ liệu/context/schema đã duyệt; RDM live-safe cần provider export thật.

## 9. Đánh giá, giới hạn và các vấn đề đã được xử lý

### Những giới hạn/risks đã được nhận diện

- **Domain mismatch:** Shenzhen, Caltech và simulator không phải hành vi Việt Nam. Hệ thống ghi rõ source/synthetic labels thay vì claim transfer tự động.
- **Persistence rất mạnh:** trạng thái vừa quan sát có quán tính lớn ở horizon ngắn. Kết quả model phức tạp thua baseline là lý do dừng, không phải lỗi cần che bằng tuning.
- **RDM label dễ sai ngữ nghĩa:** `done_charging_at` không phải `disconnect_at`; pipeline dùng mốc rút dây để trả lời wait thật.
- **Leakage theo session:** nhiều telemetry row của cùng xe không được phép rơi vào train và test khác nhau.
- **Telemetry synthetic thiếu realism:** Gold telemetry chỉ replay, làm RDM shift distribution khi đem sang simulator mới.
- **DES có thể tạo false precision:** thiếu duration/session/queue thì precise DES bị fail-closed; provider duration ưu tiên hơn ML.
- **Feature có thể không tồn tại lúc inference:** calendar/weather/traffic không được train-deploy nếu API chưa phục vụ cùng semantics.
- **Quyền riêng tư:** raw operator data, GPS, SoC, vehicle attributes và user intent cần consent, retention, access control; CTGAN behavior table cố loại định danh nguồn.

### Cách repository xử lý

- Dataset manifest/hash, schema version, source/quality flags và raw policy.
- Validation cadence, duplicate, timezone UTC, capacity/physical bounds, connector-aware state và event freshness.
- Test access opt-in với nhãn exploratory; test đã dùng để ra quyết định không bị mô tả thành final holdout.
- So baseline persistence/daily/weekly/median provider trước khi chọn ML.
- Quantile crossing/coverage, Brier/reliability, per-horizon MAE/RMSE và replay thành user-visible start/wait time.
- Artifact có metadata/release status; backend không tự nạp artifact exploratory.

## 10. Pipeline hiện tại đang được sử dụng và trạng thái từng thành phần

Pipeline hiệu lực hiện tại không phải một chuỗi “model A → model B”. Nó là cơ chế an toàn theo độ chi tiết dữ liệu:

```text
1. Queue Lab demo: duration do người demo/cảnh quan synthetic cung cấp
   -> DES deterministic hoặc Monte Carlo
   -> wait/start time + caveat; không phục vụ live ranking

2. Nếu chỉ có occupancy history hợp lệ:
   -> persistence là baseline demo hiện được chọn trên Gold
   -> XGBoost UrbanEV chỉ là benchmark source-domain, không serving

3. Khi có data nhà vận hành thật:
   raw append-only -> canonical sessions/telemetry/port status
   -> time/session-safe datasets -> validation/backtest/calibration/replay
   -> provider duration ưu tiên; RDM live-safe chỉ là fallback đã được duyệt
   -> DES chỉ dùng khi snapshot fresh, chi tiết và confirmed queue đủ
```

| Thành phần | Trạng thái cuối cùng hiện tại |
| --- | --- |
| Persistence occupancy | baseline/demo an toàn trên Gold; không phải live ML release |
| UrbanEV residual XGBoost | exploratory source-domain result; không deploy |
| Gold lag/seasonal XGBoost | đã benchmark và thua persistence; không promote |
| Hybrid LSTM | code/protocol có sẵn nhưng schema disabled, chưa được chọn |
| Transformer / Chronos / TimesFM | research/gated, chưa có training run hợp lệ |
| Markov | thiết kế + trainer aggregate, chưa có artifact calibrate để product use |
| Quantile RDM | artifacts/experiments offline synthetic; chưa serving |
| Queue Lab DES | logic demo/replay hoạt động với input mô phỏng, có caveat |
| Monte Carlo DES | mode uncertainty từ duration synthetic; chưa phải model confidence |

## 11. Điều kiện để tiến tới production và các việc còn dang dở

Trước khi đổi bất kỳ thành phần nào thành serving, cần:

1. Nhận dữ liệu OCPP/operator Việt Nam append-only: occupancy/port snapshots, fault/offline, lifecycle session, `disconnect_at`, telemetry công suất/năng lượng, inventory port và event ordering/freshness. Queue thật phải tách khỏi planned arrival.
2. Chuẩn hóa vào contracts hiện có, audit timezone, missingness, late/out-of-order events, connector/capacity semantics, privacy/retention và provenance.
3. Đóng băng temporal/rolling-origin protocol với test window Việt Nam mới. Occupancy so với persistence/daily/weekly theo trạm, connector và peak period; RDM so với station-connector median và provider duration.
4. Calibrate: occupancy probability/reliability, RDM P10/P50/P90 coverage/crossing, Markov Brier/reliability, DES predicted vs actual release/start/wait time.
5. Chỉ promote model thắng rõ ràng, ổn định và có artifact metadata, runtime feature-serving, monitoring/canary/feature flag và rollback. Nếu telemetry stale hoặc duration không đủ, fallback phải rõ ràng là aggregate estimate hoặc “không đủ dữ liệu”.

Với transfer UrbanEV → Vietnam, quy trình đúng là train/benchmark Vietnam-only, China-only zero-shot, và China-initialized rồi Vietnam-adapted trên cùng split Vietnam; seasonal profile phải fit lại từ Vietnam train. Không gọi việc retrain XGBoost là “fine-tuning” theo nghĩa LLM, và không chuyển RDM từ UrbanEV vì UrbanEV không có session label.

## 12. Dấu vết thực thi chính (để kiểm chứng, không phải cách đọc tài liệu)

Các executable tạo nên pipeline là: acquisition/preprocess UrbanEV; adapter/canonical dataset builders; feature contract/XGBoost trainer/benchmark; ACN adapter/CTGAN/Gold generator; RDM dataset builder/quantile trainer/profile experiment; Markov state/transition tools; và benchmark replay Queue Lab. Notebook chỉ là front end review mỏng: chúng gọi các command này, không chứa pipeline độc lập. `01` audit inputs/schema, `02` build/audit XGBoost features, `03` chỉ xem LSTM/Markov plan, và `04` chỉ in các gate Transformer/foundation.

Các report/artifact lớn và raw session data được Git-ignore theo thiết kế. Vì vậy, số liệu nêu trong tài liệu này đến từ các Markdown handoff/roadmap đã lưu và các manifest/report tracked; nơi artifact/report run không tồn tại trong checkout, tài liệu không suy diễn thêm số liệu hay trạng thái train.

---

**Kết luận cuối:** phần ML đã làm tốt việc biến một vấn đề dễ bị “hứa quá” thành các câu hỏi đo được: dự báo độ bận, dự báo thời điểm nhả cổng, và lập lịch queue. Cấu trúc hiện tại bảo vệ ranh giới giữa benchmark nguồn, dữ liệu synthetic và vận hành thật. Điểm chưa hoàn thành không phải thiếu một model phức tạp hơn, mà là thiếu telemetry/session/queue Việt Nam có lineage và ground truth để kiểm chứng các model đó.
