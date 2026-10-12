# Định hướng ML cho bài toán đề xuất trạm sạc

> **Kết luận ngắn:** Nghiên cứu về quy hoạch trạm sạc đã dùng ML để ước lượng nhu cầu tại địa điểm mới, rồi đưa nhu cầu đó vào thuật toán coverage/location/size optimization. Vì vậy ML có chỗ đứng thực tế trong bài toán của nhóm. Tuy nhiên, nhánh station recommendation hiện mới có tài liệu thiết kế, chưa có model demand đã huấn luyện trên dữ liệu TP.HCM. Mục tiêu hiện tại là chốt pipeline và contract; chỉ làm training demo synthetic nếu cần chứng minh luồng kỹ thuật, không quảng bá nó thành dự báo thị trường.

## 1. Cần hiểu đúng “hệ thống có ML”

Station recommendation là một hệ thống gồm nhiều khối, không phải một model AI tự chọn vị trí:

```text
Nguồn dữ liệu không gian + giao dịch sạc
              ↓
ML / statistical demand estimation
Ước lượng nhu cầu ở candidate mới theo vùng và thời gian
              ↓
Location / capacity optimization
Chọn vị trí, quy mô và trade-off theo mục tiêu/ràng buộc
              ↓
Kết quả giải thích được + nguồn + độ bất định
```

- **ML trả lời:** ở candidate/vùng này, nhu cầu sạc có thể ở mức nào theo thời gian, dựa trên dữ liệu quan sát và các biến liên quan?
- **Optimization trả lời:** với nhu cầu đó, candidate set, ngân sách, coverage, capacity và policy đã cho, chọn tổ hợp vị trí/quy mô nào?
- **GIS/rule engine trả lời:** điểm có nằm trong study area, gần trạm nào, tiếp cận ra sao, dữ liệu/grid/site readiness đang pass, fail hay unknown?

Operations Research (MCLP, knapsack/set cover, MILP, heuristic) không tự động đồng nghĩa với ML/AI. Ngược lại, dùng ML dự đoán nhu cầu cũng chưa đủ để chứng minh vị trí được chọn khả thi hoặc sinh lợi.

## 2. Nghiên cứu liên quan và bài học rút ra

### 2.1 Bài 442 — ML dự đoán nhu cầu tại candidate mới rồi tối ưu địa điểm

Gopalakrishnan và cộng sự dùng supervised multi-view learning: Multiple Dependent Regression dựa trên CCA kết hợp riêng từng view dữ liệu để dự đoán demand. Các view gồm historical energy usage ở trạm hiện hữu, số lượng/loại POI gần trạm và traffic tại các junction lân cận. Thí nghiệm dùng 252 điểm sạc công cộng ở North East England; đánh giá leave-one-station-out và so sánh với các baseline regression/CCA.

Sau dự báo, bài dùng mixed packing-and-covering dưới ngân sách, giải bằng IPAC kết hợp knapsack và set cover; queueing model chuyển ngưỡng chờ thành số charging slots/cost. Điểm quan trọng cho nhóm là **có tiền lệ trực tiếp cho chuỗi ML demand → optimization vị trí/quy mô**, chứ không phải mọi phần đều dùng ML. Bài cũng nêu hạn chế: khi đơn giản hóa, họ bỏ qua phần demand overlap giữa các vùng tiếp cận candidate; đây là lời nhắc rằng hệ thống mới phải tính marginal coverage để tránh cộng trùng lợi ích.

Nguồn: [IJCAI 2016 paper 442](https://www.ijcai.org/Proceedings/16/Papers/442.pdf), [abstract chính thức của IJCAI](https://www.ijcai.org/Abstract/16/442).

### 2.2 Demand-supply coupling — dự báo và quyết định vị trí ảnh hưởng lẫn nhau

Song và Hu (2023) dùng gradient boosting với 15 feature để dự báo nhu cầu, sau đó giải location problem có xét việc mở trạm mới làm thay đổi phân bổ nhu cầu và utilization ở cả trạm mới lẫn trạm cũ. Case study dùng sáu năm charging-event data ở Kansas City. Bài này cảnh báo không nên chỉ xếp từng candidate độc lập theo demand: khi thêm một trạm, demand có thể dịch chuyển giữa các site.

Nguồn: [bản ghi nghiên cứu của Penn State và DOI](https://pure.psu.edu/en/publications/learning-based-demand-supply-coupled-charging-station-location-pr/).

### 2.3 Cold start/new city — transfer learning là hướng nghiên cứu, không phải mặc định demo

SPAP đề xuất học demand ở city nguồn rồi chuyển sang city đích bằng attention-based spatial-temporal domain adaptation, đồng thời lặp giữa dự báo và cập nhật charger plan. Thí nghiệm dùng dữ liệu ba thành phố Trung Quốc. Chính bài cũng nhấn mạnh domain shift: quy mô, hạ tầng, mức phát triển EV và chính sách khác nhau có thể khiến transfer âm.

Ý nghĩa với TP.HCM: có thể nghiên cứu transfer learning nếu đối tác có data ở nhiều city và feature semantics tương thích; không nên lấy model nước khác rồi gọi output là demand TP.HCM nếu chưa kiểm tra domain shift/hiệu chỉnh.

Nguồn: [SPAP preprint và paper text](https://arxiv.org/abs/2110.09452).

### 2.4 Nghiên cứu gần đây về station mới

Zheng và cộng sự (2026) dự đoán demand vài ngày tới cho candidate trạm mới bằng CNN, dùng transaction history trung bình của các trạm trong bán kính 3 km cùng thuộc tính trạm, thời tiết và ngày nghỉ. Nghiên cứu dùng dữ liệu của 274 trạm tại Nanjing trong khoảng 242 ngày và so sánh CNN với LSTM, XGBoost, ST-GCN, Informer. Đây là ví dụ gần trực tiếp với cold-start station, nhưng kết quả gắn với một operator, một city và horizon ngắn; không thể suy ra cùng độ chính xác ở HCMC.

Nguồn: [Energies 2026, Demand Prediction of New Electric Vehicle Charging Stations](https://www.mdpi.com/1996-1073/19/2/378).

### 2.5 Dự báo + ràng buộc lưới + tối ưu dưới bất định

Wang và cộng sự (iScience, 2025) trình bày framework dự báo demand theo không gian-thời gian rồi dùng stochastic location/sizing optimization có xét grid constraints và uncertainty. Case study ở Austin, Texas; đây là ví dụ cho việc giữ uncertainty và lưới điện bên cạnh demand model, thay vì chọn site theo một giá trị điểm duy nhất.

Nguồn: [iScience 2025, DOI 10.1016/j.isci.2025.113368](https://doi.org/10.1016/j.isci.2025.113368).

## 3. Kết luận cho đề án HCMC

1. **Có cơ sở để đưa demand ML vào kiến trúc mục tiêu.** Bài 442 và các nghiên cứu sau dùng mô hình học để dự đoán demand ở nơi chưa có giao dịch, sau đó mới tối ưu vị trí/quy mô.
2. **Không cần tuyên bố ML đã hoạt động ở demo hiện tại.** Repo station recommendation hiện mới có schema/tài liệu, chưa có demand model của bài toán này và chưa có nhãn demand HCMC đủ để train/validate.
3. **ML phải dự đoán đại lượng có định nghĩa.** Nên bắt đầu với expected charging sessions/ngày và/hoặc energy kWh/ngày theo candidate/grid cell; nếu cần thiết kế số cổng peak-hour thì cần dữ liệu theo thời gian đủ chi tiết. “Nhu cầu” không đồng nghĩa với “thiếu hụt”; unmet demand phải tính tiếp từ demand, supply, reachability và capacity.
4. **Không train target bằng POI/traffic tự chế.** POI, traffic, dân cư, fleet, home charging là feature/proxy; cần label từ sessions, kWh, charging events hoặc một target được định nghĩa rõ. Nếu chỉ dùng proxy score thì gọi nó là proxy/scenario, không gọi là model đã forecast demand thật.
5. **Xử lý bias từ vị trí trạm hiện có.** Transaction chỉ quan sát ở nơi đã có trạm và bị giới hạn bởi số cổng, giá, uptime, accessibility và cách nhà vận hành phủ mạng. Vùng không có giao dịch không đồng nghĩa demand bằng 0.
6. **Model là đầu vào, không phải quyết định cuối.** Engine xếp hạng/tối ưu còn cần hard constraints, marginal coverage, cost/budget khi có, power/grid feasibility và policy package.

## 4. Pipeline ML mục tiêu

### 4.1 Đầu vào và đơn vị dự báo

Chia study area/pilot TP.HCM thành demand cells hoặc candidate-site records có version geometry. Mỗi record theo thời gian cần có:

- `target`: sessions/transactions, kWh hoặc peak-hour demand; lưu rõ đơn vị và khoảng thời gian.
- `spatial features`: POI mix/dwell proxy, population/buildings, road accessibility/traffic, fleet/depot, nearby station supply, home charging nếu có.
- `temporal features`: giờ/ngày/mùa/ngày nghỉ, thời gian hiệu lực của policy/tariff nếu dùng.
- `supply context`: số cổng, loại/công suất, uptime, giá và thời điểm trạm hoạt động.
- `provenance`: nguồn, thời gian, boundary/data version, `observed/proxy/synthetic/scenario/unknown`, quyền dùng và chất lượng.

Model result tối thiểu: candidate/cell, horizon, expected demand, unit, model/data version, uncertainty interval hoặc low/base/high scenarios, flags/provenance. Khi chưa có căn cứ tính khoảng tin cậy, không gọi sensitivity scenario là xác suất.

### 4.2 Baseline và model ladder

Thứ tự nên thử theo độ phức tạp tăng dần:

1. **Rule/scenario baseline:** transparent demand profiles do team cấu hình; cần để demo hệ thống dù chưa có model.
2. **Simple statistical baseline:** historical average/neighbor-site analogue hoặc regression đơn giản; đo được model có hơn baseline không.
3. **Gradient-boosted trees:** XGBoost/LightGBM/CatBoost trên tabular multi-source features nếu có đủ labeled examples. Đây là model candidate hợp lý đầu tiên để thử, không cam kết chắc chắn sẽ thắng.
4. **Spatio-temporal/transfer models:** CNN/GNN/ST-GCN/transfer learning chỉ khi có đủ chuỗi thời gian, network graph, nhiều vùng/city và bằng chứng baseline không đáp ứng.

Không nên bắt đầu bằng fine-tune LLM, GNN hoặc LSTM chỉ để có nhãn “AI”. Vấn đề chính của bài này là target, data coverage, spatial transfer và demand/supply feedback; kiến trúc phức tạp không bù được thiếu ground truth.

### 4.3 Huấn luyện và đánh giá

- Tách train/validation/test theo thời gian; thêm spatial/corridor holdout để kiểm tra khả năng dự báo cho khu/site chưa thấy.
- So với naive/neighbor baseline và báo metric phù hợp target như MAE/RMSE/WAPE hoặc Poisson deviance cho count; không chỉ báo một accuracy tổng.
- Báo kết quả theo vùng, loại site và mức coverage dữ liệu; tránh random split làm site/time lân cận lọt cả train lẫn test.
- Kiểm tra predicted demand không vượt giới hạn vật lý do số cổng/công suất/giờ mở cửa nếu target là served transactions.
- Lưu feature schema, training data snapshot, model version, hyperparameters, split protocol, metrics và data source trong model card.
- Nếu transfer city, đánh giá cross-city holdout và domain shift; không tự coi calibration từ nơi khác là đúng cho TP.HCM.

## 5. Đường làm thực tế theo trạng thái dữ liệu

### Hiện tại — tài liệu và baseline

- Giữ demand model là một component trong M2, tách với site optimizer.
- Chốt demand dataset contract cùng M1: spatial unit, timestamp, target, source labels và missingness.
- Engine M2B chạy được khi nhận demand matrix từ baseline scenario, không bị phụ thuộc vào model ML.
- Không báo accuracy hoặc “demand forecast của HCMC” nếu chưa có validation data.

### Demo cuộc thi — nếu cần chứng minh ML end-to-end

- Tạo synthetic cell/session data bằng generator có công thức và seed cố định.
- Chạy pipeline thật: build dataset → feature validation → train simple model (ví dụ gradient boosting) → spatial/time holdout → compare với baseline → predict demand surface → đưa vào site optimizer.
- Trên mọi chart/slide ghi **synthetic ML pipeline demonstration**; metric chỉ đánh giá model học lại generator, không chứng minh độ chính xác ngoài đời.
- Có thể dùng một model artifact demo để chứng minh train/serve/version workflow; tuyệt đối không trộn artifact synthetic với observed production data.

### Khi doanh nghiệp cấp data

- Thay generator bằng aggregated transactions/sessions/energy có quyền sử dụng.
- Xác định target và geography cùng data owner; nối POI/traffic/fleet/population theo ngày hiệu lực.
- Backtest temporal và spatial, đánh giá sai số/calibration, phân tích bias supply-censored.
- Chỉ bật forecast model trong recommendation run khi model/data version vượt gate chất lượng do team và domain owner thống nhất.

## 6. Gắn vào M1–M5 hiện tại

Giữ nguyên 5 module cấp cao; bổ sung hai nhánh con trong **M2** để có người phụ trách rõ mà không phải đổi toàn bộ kế hoạch:

| Nhánh | Trách nhiệm | Artifact bàn giao |
|---|---|---|
| M1 — Data & GIS | Dữ liệu, candidate, spatial/time contract, sample/provenance | Demand training table + input feature contract |
| M2A — Demand ML | Dataset builder, baseline, training/evaluation/inference pipeline; synthetic-only demo nếu được chọn | Versioned demand surface + model card/metrics/flags |
| M2B — Site recommendation engine | Hard constraints, coverage, ranking/portfolio, capacity interface | Candidate score/selection + explanation |
| M3 — Backend/DB | API/service/repository; gọi M2A result và M2B engine theo data contract | API response với model/data/algorithm provenance |
| M4 — Frontend Planner | Hiển thị demand map, recommendations, uncertainty/flags | UI giải thích được output và trạng thái dữ liệu |
| M5 — Integration/demo | Gắn end-to-end, scenario/seed, acceptance và presenter notes | Demo tái lập + giới hạn được công bố |

M2A/M2B có thể làm song song trên payload nội bộ ở mục “M2A → M2B” trong [hợp đồng chung](modules/SHARED_CONTRACT_VI.md): M2A trả candidate/cell, target + unit, time window, value, status/provenance, model/data version và uncertainty nếu có; M2B nhận contract này và vẫn chạy baseline nếu model chưa có. M5 ráp cuối. Xem thêm [brief engine M2B](modules/M2_RECOMMENDATION_ENGINE_VI.md).

## 7. Nội dung có thể trình bày với giám khảo

> “Các nghiên cứu về quy hoạch trạm đã kết hợp machine learning để ước lượng nhu cầu ở các candidate mới từ giao dịch trạm lân cận, POI và giao thông, sau đó đưa kết quả sang tối ưu coverage, ngân sách và quy mô. Nhóm thiết kế theo cùng nguyên tắc tách demand model và optimization. Với demo hiện tại, model pipeline có thể được kiểm tra bằng dữ liệu synthetic có gắn nhãn; nhóm không tuyên bố độ chính xác demand tại TP.HCM. Khi có dữ liệu operator, pipeline được huấn luyện/đánh giá lại theo spatial và temporal holdout trước khi dùng cho quyết định.”

Nếu demo chưa chạy model synthetic, thay câu “model pipeline có thể được kiểm tra” bằng “pipeline được thiết kế và là bước phát triển tiếp theo”; không nói “hệ thống dùng ML để dự báo” như tính năng đã hoạt động.

## 8. Câu hỏi còn mở trước khi train thật

1. Doanh nghiệp có thể cấp target nào: session count, kWh, occupancy, requests bị từ chối, hay nhiều target?
2. Có charging events aggregate ở vùng/city khác để cold-start/transfer không?
3. Candidate là parcel/site host thật hay cell/corridor node? Resolution bao nhiêu và ai duyệt?
4. Đầu ra phục vụ dự báo theo vài ngày/giờ hay tăng trưởng hạ tầng nhiều năm? Hai horizon có target/model khác nhau.
5. Có quyền dùng traffic, OD, fleet, EV ownership, home charging và POI không; thời điểm cập nhật nào?
6. Chọn service/coverage objective hay investor utilization/revenue khi đưa forecast vào optimizer?

## Tài liệu liên quan

- [Kế hoạch triển khai tổng thể](IMPLEMENTATION_PLAN_VI.md)
- [Bài báo 442: review của nhóm](PAPER_442_REVIEW_VI.md)
- [Kế hoạch dữ liệu](DATA_PLAN_VI.md)
- [Hợp đồng chung v0.1](modules/SHARED_CONTRACT_VI.md)
- [Brief engine M2 hiện tại](modules/M2_RECOMMENDATION_ENGINE_VI.md)
