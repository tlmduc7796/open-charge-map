# Mô hình sinh dữ liệu tổng hợp cho trạm sạc ô tô điện tại Việt Nam: nguồn dữ liệu, phương pháp và kiến trúc đề xuất cho bản demo

Phương án phù hợp nhất cho bản demo là một **bộ mô phỏng sự kiện rời rạc (DES, ví dụ SimPy) có tầng vật lý sạc**. Bộ mô phỏng gồm: (i) quá trình Poisson không đồng nhất để sinh lượt xe đến, với cường độ phụ thuộc thời gian, thời tiết và đặc trưng không gian; (ii) các phân phối tham số cho hành vi người dùng (SOC_start, SOC mục tiêu, thời gian lưu đỗ, độ kiên nhẫn), hiệu chỉnh trên các bộ dữ liệu công khai; (iii) đường cong sạc theo SOC cho từng mẫu xe, công suất tức thời = min(công suất cổng, giới hạn của xe, đường cong theo SOC). Các mô hình học sâu (GAN, VAE, diffusion) chưa cần cho demo, vì hiện chưa có bộ dữ liệu phiên sạc công khai nào của Việt Nam để huấn luyện. Chúng chỉ nên dùng ở giai đoạn sau, khi đã có log thật từ hệ thống.

## TL;DR

- **Không bộ dữ liệu công khai nào khớp trọn schema của bạn.** ACN-Data (Caltech/JPL) và ElaadNL có đủ 3–4 mốc thời gian (kết nối, kết thúc sạc, rút xe) nhưng chỉ có AC và không có SOC. Dữ liệu DC kèm SOC theo thời gian (909.135 phiên DCFC ở Tây Bắc Âu) và đường cong sạc Fastned cho biết SOC và độ suy giảm công suất. Dữ liệu Trung Quốc (Jiaxing: 441.077 giao dịch có thời tiết; UrbanEV Thâm Quyến: POI, thời tiết, giá) giúp hiệu chỉnh tác động thời gian, thời tiết và không gian. Vì vậy cần **ghép nhiều nguồn**: mỗi nguồn hiệu chỉnh một khối của mô hình.
- **Kiến trúc đề xuất** gồm 7 khối nối tiếp: cấu hình trạm → λ(t, môi trường, không gian) → chọn mẫu xe & SOC_start → hàng đợi (balking/reneging) & cấp cổng → đường cong sạc → SOC_end & thời điểm kết thúc sạc → thời gian lưu đỗ/rút xe. Mỗi bản ghi phải gắn cờ phân biệt biến *có thể quan sát* (các mốc thời gian, SOC, kWh) với biến *chỉ do mô phỏng sinh ra* (thời điểm đến, thời gian chờ, độ dài hàng đợi, balking/reneging).
- **Với Việt Nam**, cấu hình thực của V-Green khác danh sách công suất bạn đưa ra: AC 11 kW/cổng; DC 20, 60/80, 120/150 kW (2 cổng/trụ) và 250 kW (1 cổng/trụ, giới hạn SOC ở 80%). Từ 01/11/2025, phí sử dụng trạm sau khi sạc xong tính theo bậc trên toàn bộ trụ DC V-Green. Thông số pin và sạc của các mẫu VinFast (ví dụ VF 6: 59,6 kWh, AC 7,2 kW, DC 100 kW; trang đại lý ghi 10–70% mất 25 phút với bộ sạc 250 kW và khoảng 45 phút ở 60 kW) đủ để hiệu chỉnh đường cong sạc. Tuy nhiên, cơ cấu đội xe, hồ sơ giờ trong ngày và hệ số ngày lễ/Tết hiện vẫn là **giả định** và phải ghi rõ như vậy.

## Key Findings

1. **Dữ liệu AC có đủ các mốc thời gian, dữ liệu DC có SOC, nhưng hiếm bộ nào có cả hai.** ACN-Data ghi `connectionTime` (cắm sạc), `doneChargingTime` (thời điểm cuối cùng có dòng sạc khác 0) và `disconnectTime` (rút xe).\[1\]\[2\] ElaadNL tách riêng thời gian kết nối, thời gian sạc và thời gian nhàn rỗi (idle).\[3\] Ngược lại, SOC thực chỉ có trong dữ liệu DCFC thương mại, dữ liệu đo trong phòng thí nghiệm, hoặc là giá trị *ước tính* (bộ dữ liệu dân cư Na Uy).\[4\]\[5\]
2. **Phân phối hành vi đã có bằng chứng định lượng.** Ví dụ: phiên DCFC thường bắt đầu ở 10–60% SOC và kết thúc ở ≥80%.\[6\] Theo bài "Charging or Idling", phân tích hơn 300.000 phiên sạc AC và DC của Stadtwerke München (SWM) tại Munich năm 2020, thời gian kết nối ở trạm sạc nhanh trung bình 0,8 giờ (trung vị 0,6 giờ), với 15–20% là idle; với phiên AC, thời gian kết nối trung bình 5,9 giờ (trung vị 3,1 giờ), với 45–70% là idle. Ở Hà Lan, chỉ 15–25% thời gian kết nối là thời gian thực sự sạc. Từ các số này có thể suy ra tham số log-normal (xem mục Details, phần 3).
3. **Mô hình đường cong sạc hai giai đoạn (CC-CV) đã được chuẩn hóa trong EV2Gym.** Mô hình tăng SOC tuyến tính dưới ngưỡng τ, rồi tiến dần theo hàm mũ tới 100% ở pha điện áp không đổi (CV). Công suất luôn bị chặn bởi giới hạn của xe và của trụ.\[7\] Với DC, đường cong đo thực tế của Fastned (141 kiểu hành vi, công suất đỉnh 35–403 kW) là nguồn tốt nhất để lấy hình dạng suy giảm.\[8\]
4. **Hàng đợi:** M/M/c là mô hình phổ biến nhất trong tài liệu, nhưng không xử lý được λ(t) thay đổi theo giờ, thời gian sạc không theo phân phối mũ, và hành vi bỏ đi. Các nghiên cứu mới chuyển sang mô phỏng: lượt đến Poisson, balking và chọn trạm bằng mô hình logit đa thức (MNL) theo thời gian chờ kỳ vọng và quãng đường vòng, reneging theo độ kiên nhẫn.\[9\]\[10\] Ta dùng DES cho dữ liệu và dùng Erlang-C chỉ để kiểm tra chéo.
5. **Mô hình sinh bằng học máy:** copula (vine, CODINE), CopulaGAN (theo tổng quan arXiv 2409.15750, tỷ lệ khớp "xấp xỉ trên 90%" với dữ liệu bãi đỗ Caltech trong mô phỏng 48 giờ) và diffusion (SynthCharge đạt ΔMAE trong đánh giá TSTR là 1,29, so với 1,43 của CTVAE và 1,58 của CGAN). Các mô hình này hiệu quả khi *có* dữ liệu thật để học. Với demo tại Việt Nam, chúng thích hợp nhất cho việc mô phỏng phân phối đồng thời (giờ đến × thời gian lưu × năng lượng) học từ ElaadNL/ACN, rồi "gắn" thêm tầng vật lý SOC.
6. **Đặc trưng không gian:** phần lớn nghiên cứu đếm POI trong bán kính khoảng 500 m (OpenStreetMap), cộng thêm nhu cầu ở các trạm lân cận và khoảng cách tới trạm cạnh tranh gần nhất.\[11\]\[12\] Bằng chứng từ Thâm Quyến cho thấy mật độ trạm rất gần nhau làm *giảm* sản lượng trên mỗi trụ (hiệu ứng "giành khách").\[13\] Ở Albany, lưu lượng giao thông và mật độ xe điện quan trọng hơn POI: chỉ dùng POI thì R² giảm còn 0,43.\[14\]

## Details

### 1. Tổng quan bộ dữ liệu công khai và mức độ phù hợp với schema

| Bộ dữ liệu | Quy mô / thời gian | Trường chính | AC/DC | SOC | Các mốc thời gian | Link | Dùng để hiệu chỉnh |
|---|---|---|---|---|---|---|---|
| ACN-Data (Caltech, JPL, văn phòng) | Bài báo gốc: hơn 30.000 phiên; bản tĩnh 2018–2020 có 85.877 file chuỗi thời gian\[1\]\[15\] | connectionTime, doneChargingTime, disconnectTime, kWhDelivered, stationID, userID, thông tin người dùng nhập (kWh yêu cầu, giờ dự kiến rời đi, WhPerMile), chuỗi dòng điện/pilot\[1\]\[2\] | AC (Level 2, nơi làm việc) | Không | Kết nối ≈ bắt đầu sạc; có thời điểm kết thúc sạc; có thời điểm rút xe | https://ev.caltech.edu/dataset (API) | Thời gian lưu, idle, năng lượng, GMM giờ đến; hình dạng suy giảm AC |
| ElaadNL (Hà Lan) | Mẫu mở 10.000 phiên ngẫu nhiên năm 2019, trạm công cộng | Giờ đến, giờ rời, thời gian kết nối, thời gian sạc, công suất đỉnh, năng lượng; bảng Transactions đầy đủ có idle time | AC công cộng (≤23 kW)\[16\] | Không | Đến, kết thúc sạc (suy ra), rời | https://platform.elaad.io/download-data/ | Phân phối đồng thời giờ đến × thời gian lưu × kWh; idle |
| Palo Alto (ChargePoint) | 07/2011–12/2020\[17\]\[18\] | Thời điểm bắt đầu/kết thúc, tổng thời lượng, thời gian sạc, kWh, loại cổng, tọa độ | Chủ yếu AC L2 | Không | Kết nối/rút + thời gian sạc | https://data.paloalto.gov/datasets/194693 | Xu hướng dài hạn, giờ đến theo ngày trong tuần |
| Boulder (Colorado) | Từ 01/2018; một phân tích dùng 36.326 giao dịch (01/2018–11/2021)\[19\] | Trạm, ngày, giờ bắt đầu, thời gian sạc, kWh\[20\] | Chủ yếu AC | Không | Bắt đầu + thời lượng | https://open-data.bouldercolorado.gov (Electric Vehicle Charging Station Data) | Như Palo Alto; so sánh giữa các thành phố |
| Dundee (Scotland) | Nghiên cứu 91 ngày (03–06/2018): 40 trụ chậm (7 kW), 8 trụ nhanh, 9 trụ rapid; 8.870 phiên rapid\[21\] | Bắt đầu/kết thúc, kWh, công suất trụ, vị trí | AC + DC rapid (50 kW) | Không | Bắt đầu/kết thúc phiên | https://data.dundeecity.gov.uk/dataset/ev-charging-data | **Mức sử dụng DC**: 10,9 phiên/ngày/trụ rapid, so với 1,5 (chậm) và 1,9 (nhanh)\[21\] |
| Perth & Kinross (ChargePlace Scotland) | Khoảng 4 năm; trụ rapid 50 kW DC/43 kW AC và trụ fast 22 kW\[22\]\[23\] | Mã trụ, bắt đầu/kết thúc, kWh, địa điểm | AC + DC | Không | Bắt đầu/kết thúc | data.pkc.gov.uk; IEEE DataPort | Phân phối kWh phiên rapid |
| Hàn Quốc (Scientific Data 2024) | 72.856 phiên, 2.337 người dùng, 2.119 trụ, 30/09/2021–30/09/2022\[24\] | Mã người dùng/trụ đã ẩn danh, phân loại vị trí trụ, thời điểm bắt đầu/kết thúc\[24\] | AC/DC | Không | Bắt đầu/kết thúc | Bài Sci Data s41597-024-02942-9 | Hành vi theo loại vị trí (bối cảnh châu Á) |
| Jiaxing, Trung Quốc (Scientific Data 2025) | 441.077 giao dịch, 13 trạm, 12/2019–12/2021\[25\]\[26\] | **Order Creation Time**, Start Time, End Time, kWh, giá điện, phí dịch vụ, **lý do kết thúc**, thời tiết\[25\]\[26\]\[27\] | Trạm công cộng (chủ yếu DC) | Không | Tạo đơn (≈ kết nối), bắt đầu, kết thúc sạc | Bài Sci Data s41597-025-04982-1; bản sao trên Kaggle | Độ trễ từ tạo đơn đến bắt đầu sạc; tác động thời tiết; lý do dừng sạc |
| UrbanEV, Thâm Quyến (Scientific Data 2025) | Ban đầu 1.682 trạm/24.798 trụ, sau làm sạch còn 1.362 trạm/17.532 trụ; 01/09/2022–28/02/2023, theo giờ | Tỷ lệ chiếm dụng, thời lượng, sản lượng, giá, thời tiết, POI, ma trận kề/khoảng cách, 275 vùng giao thông\[28\]\[29\]\[30\]\[31\]\[32\] | Tổng hợp theo trạm/vùng | Không | Không (dữ liệu tổng hợp) | https://github.com/IntelligentSystemsLab/UrbanEV ; Dryad | **Hệ số giờ, thời tiết, POI, giá; kiểm định chiếm dụng theo giờ** |
| Dân cư Na Uy | Hơn 35.000 phiên, 267 người dùng, 12 địa điểm | Cắm/rút, kWh; **SoC lúc cắm, dung lượng pin, công suất là giá trị ước tính**\[33\] | AC tại nhà | Ước tính | Cắm/rút; thời gian sạc/idle ước tính | PMC11404051 | Phương pháp suy SOC khi dữ liệu không có SOC |
| DCFC Tây Bắc Âu (Nature Communications 2025) | 909.135 phiên, 612 trụ DCFC, 11/2021–07/2024\[6\] | Chuỗi thời gian SoC và công suất, công suất định mức đầu nối, thời lượng, kWh\[5\] | DC | **Có** | Bắt đầu/kết thúc | Bài s41467-025-65970-y (khả năng truy cập dữ liệu thô chưa xác nhận) | Phân phối SOC_start/SOC_end của DC |
| Đường cong Fastned | 252 phiên đo, 141 kiểu hành vi, công suất đỉnh 35–403 kW\[8\] | Công suất theo SoC do BMS báo cáo | DC | **Có** | Không áp dụng | Theo arXiv 2606.29994 | Hình dạng đường cong suy giảm theo mẫu xe |
| Bộ đo phòng thí nghiệm (Scientific Data 2025) | Các thử nghiệm AC/DC trên xe thương mại | start_soc_percent, end_soc_percent, AC/DC, loại đầu cắm, chuỗi thời gian độ phân giải cao\[34\] | AC + DC | **Có** | Không áp dụng | Bài s41597-025-05524-5 | Kiểm định mô hình CC-CV cho AC |

Ghi chú về chất lượng nguồn:
- Bộ DCFC 909.135 phiên có đồng tác giả từ ngành công nghiệp. Bài báo mô tả dữ liệu, nhưng tôi chưa xác minh được dữ liệu thô có tải công khai hay không. Nên coi đây là nguồn *thống kê đã công bố*, không phải nguồn để huấn luyện.
- UrbanEV là dữ liệu tổng hợp theo giờ, không ở mức phiên.\[29\] Bộ này dùng tốt để kiểm định chiếm dụng, nhưng không thay được dữ liệu phiên.
- Khung EV-Insights đã chuẩn hóa 7 bộ dữ liệu công khai với hơn 3 triệu phiên vào một data model có trường `plug_in_soc`, có thể dùng làm mẫu ETL.\[35\]

### 2. Phương pháp mô phỏng trạm sạc trong tài liệu

- **Hàng đợi giải tích.** M/M/c là cách tiếp cận phổ biến nhất: mỗi trạm là một hàng M/M/c, ghép thành mạng trạm. Các mô hình M/M/1/k có reneging (ví dụ IDEAS) dùng chuỗi Markov với tốc độ bỏ hàng μ_R, và phân biệt balking cưỡng bức (hàng đầy) với balking tự nguyện. Hạn chế đã được chính các tác giả thừa nhận: giả định phân phối mũ cho lượt đến, thời gian phục vụ và thời gian bỏ hàng là để mô hình giải được, nên không mô tả được hành vi có đuôi dài hoặc thay đổi theo thời gian.\[9\]\[10\]\[36\]
- **Mô phỏng hệ thống nhiều trạm.** Nghiên cứu về mạng trạm sạc nhanh (arXiv 2012.09349) sinh chuyến đi theo Poisson từ ma trận OD theo khung giờ. SOC đầu chuyến theo phân phối chuẩn cụt N(0,6; 0,2), ngưỡng quyết định sạc theo N(0,5; 0,1). Balking và chọn trạm được mô hình **cùng lúc** bằng MNL với các thuộc tính giá, thời gian chờ kỳ vọng và quãng đường vòng. Kết quả là lượng xe đến mỗi trạm trở thành **nội sinh**, phụ thuộc trạng thái của trạm đó và các trạm lân cận.\[10\] Đây chính là cơ chế mà các biến "khoảng cách trạm gần nhất" và "số trạm trong bán kính 3/5 km" của bạn cần.
- **Mô phỏng theo bước thời gian / Gym.** ACN-Sim (gắn với ACN-Data) và EV2Gym (bước 15 phút, mô hình xe từ dữ liệu bán hàng tại Hà Lan, hành vi lấy từ phân phối ElaadNL cho các bối cảnh public/workplace/residential) đều sinh lượt đến theo phân phối, rồi lấy thời điểm rời và năng lượng lúc đến **có điều kiện theo giờ và ngày đến**.\[7\]\[37\]\[38\]
- **Agent-based / dựa trên điều tra di chuyển.** emobpy (dùng điều tra MiD Đức), RAMP-mobility (28 nước châu Âu, độ phân giải 1 phút, có yếu tố mùa và nhiệt độ), SimBEV (MiD 2017), VencoPy và ev-flow (NHTS Mỹ) sinh chuỗi chuyến đi rồi suy ra nhu cầu sạc.\[39\]\[40\]\[41\]\[42\] Cách này phù hợp cho sạc tại nhà và nơi làm việc, nhưng kém phù hợp cho trạm công cộng tại Việt Nam vì Việt Nam chưa có điều tra di chuyển dành riêng cho ô tô điện.
- **Thống kê/Monte Carlo.** Có thể dùng KDE cho thời điểm đến và thời gian lưu, hỗn hợp Gaussian (GMM) cho cặp thời điểm kết nối–năng lượng (Lee và cộng sự trên ACN-Data), beta mixture cho số xe cắm/rút (ElaadNL), hoặc phân phối mũ cho khoảng cách giữa các lượt đến kết hợp GMM (SDG của Lahariya).\[23\]\[43\]\[44\]\[45\]

### 3. Phân phối thống kê cho từng biến (giá trị khởi tạo đề xuất)

Các tham số dưới đây được *suy ra từ nguồn* nếu có ghi chú, hoặc là *giả định khởi tạo cho demo*. Tất cả cần hiệu chỉnh lại theo mục (d).

| Biến | Phân phối đề xuất | Tham số khởi tạo | Cơ sở |
|---|---|---|---|
| Số lượt đến / cổng / ngày (λ0) | Poisson không đồng nhất (NHPP) | DC đô thị đông khách khoảng 6–11 lượt/cổng/ngày; AC khoảng 1,5–3 | Dundee: 10,9 phiên/ngày/trụ rapid, 1,5–1,9 với trụ chậm/nhanh\[21\] |
| Hồ sơ giờ trong ngày f_h | Hệ số nhân theo giờ, chuẩn hóa trung bình bằng 1 | Giả định cho DC đô thị VN: 0–5h: 0,2; 6–8h: 0,6; 9–10h: 0,9; 11–13h: 1,2; 14–16h: 0,9; 17–20h: 1,6; 21–23h: 0,7 | Giả định; phải học lại từ Jiaxing/UrbanEV (UrbanEV cho thấy cao điểm sau giờ tan làm) |
| SOC_start (DC) | Beta | Beta(2; 4), trung bình khoảng 0,33, phần lớn khối lượng trong 10–60% | Nature Comms: đa số phiên DCFC bắt đầu ở 10–60%\[6\] |
| SOC_start (AC) | Chuẩn cụt trên [0,05; 0,95] | N(0,5; 0,2) | Sun và cộng sự (trích trong arXiv 2012.09349): SOC trước khi sạc có trung bình 50–60%\[10\] |
| SOC_start (xe dịch vụ/taxi) | Beta | Beta(1,5; 5) | Giả định: xe dịch vụ chạy cạn pin hơn |
| SOC mục tiêu (DC) | Hỗn hợp | 45% đúng 0,80; 35% Beta(18; 3) (khoảng 0,86); 20% bằng 1,0. Trụ ≥250 kW: chặn ở 0,80 | Nature Comms: đa số kết thúc ở ≥80%;\[6\] chính sách V-Green giới hạn 80% với trụ ≥250 kW\[46\] |
| SOC mục tiêu (AC) | Hỗn hợp rời rạc | 1,0 (50%), 0,9 (30%), 0,8 (20%) | Giả định |
| Độ trễ cắm sạc → bắt đầu sạc | Log-normal | Trung vị khoảng 1 phút, σ = 0,6 | Giả định; hiệu chỉnh bằng khoảng "Order Creation → Start" của Jiaxing |
| Thời gian lưu dự kiến (AC, công cộng/trung tâm thương mại) | Log-normal | μ = ln(3,1 h) ≈ 1,13; σ ≈ 1,13 | Suy ra từ dữ liệu SWM Munich 2020 (hơn 300.000 phiên AC/DC): phiên AC trung bình 5,9 h, trung vị 3,1 h (exp(σ²/2) = 5,9/3,1) |
| Tổng thời gian kết nối (DC, để kiểm định) | Log-normal | μ = ln(0,6 h); σ ≈ 0,76 | Suy ra từ dữ liệu SWM Munich 2020: trung bình 0,8 h, trung vị 0,6 h |
| Idle sau sạc (DC) | Hỗn hợp: log-normal + đuôi mũ | 90%: log-normal trung vị 4 phút, σ = 0,9; 10%: mũ trung bình 20 phút | Munich: idle chiếm 15–20% thời gian kết nối ở trạm nhanh; V-Green miễn phí 10 phút đầu nên phần lớn idle sẽ dưới 10 phút (giả định hành vi)\[46\]\[47\] |
| Idle (AC) | Hệ quả của mô hình (thời gian lưu − thời gian sạc) | — | Hà Lan: chỉ 15–25% thời gian kết nối là sạc\[47\] |
| Độ kiên nhẫn khi xếp hàng (reneging) | Log-normal hoặc mũ | Trung vị 15 phút (DC), 30 phút (AC) | Giả định; IDEAS dùng tốc độ reneging μ_R theo phân phối mũ\[36\] |
| Balking | Logit theo thời gian chờ kỳ vọng W và thời gian đi tới trạm thay thế | P(balk) = 1/(1 + exp(−(β0 + β1·W − β2·T_alt))) | Cấu trúc MNL theo arXiv 2012.09349; hệ số β là giả định\[10\] |
| Năng lượng phiên (AC công cộng, để kiểm định) | Hệ quả của mô hình | Trung bình khoảng 8–11 kWh, độ lệch chuẩn khoảng 6,5–8,5 | Review dữ liệu mở: Boulder 8,42; Palo Alto 8,18; Dundee 9,16; Perth 11,01 kWh\[23\] |
| Thời lượng phiên DC (để kiểm định) | Hệ quả của mô hình | Thường 30–45 phút | NREL/OSTI "Time Matters": gần 16 triệu phiên L2/DC tại Mỹ giai đoạn 2017–2022; phiên DC "thường kéo dài 30–45 phút" (thời lượng điển hình, không phải trung vị) |

Gợi ý về phân phối đồng thời: thay vì lấy mẫu độc lập (giờ đến, thời gian lưu, năng lượng), hãy dùng **Gaussian copula** hoặc **vine copula** học từ ElaadNL/ACN theo từng loại vị trí, rồi ánh xạ "năng lượng" thành (SOC_start, SOC mục tiêu) thông qua dung lượng pin. Nghiên cứu so sánh copula trên chính ba biến này cho thấy copula tham số không bắt được cấu trúc đa đỉnh, còn CODINE (copula thần kinh) thì bắt được.\[48\] Cho demo, GMM có điều kiện theo (loại ngày, loại vị trí) là đủ.

### 4. Mô hình đường cong sạc và công thức công suất

**Công suất tức thời (phía lưới):**

P(t) = min( P_cổng , P_xe,max(chế độ) , P_xe,max(DC) · c_model(SOC(t)) )

- Với AC: P = min(P_cổng_AC, P_OBC, giới hạn theo số pha). Đường cong gần như phẳng tới ngưỡng τ_AC (khoảng 0,9–0,95), sau đó giảm theo mô hình hai giai đoạn của EV2Gym:
  - SOC_t = SOC_{t−1} + P_t·Δt/E nếu SOC_{t−1} < τ;
  - SOC_t = 1 + (SOC_{t−1} − 1)·exp(P_t·Δt / (E·(τ − 1))) nếu SOC_{t−1} ≥ τ.
  
  Trong đó P_t = η·I_t·V_t·√φ, có bị chặn bởi giới hạn của xe và trạm. Bài báo EV2Gym cho thấy mô hình này bám tốt đường cong Type 2 đo thực, nhưng hơi lệch với DC.\[7\]
- Với DC, dùng đường cong chuẩn hóa từng đoạn c(SOC) và hiệu chỉnh theo từng mẫu xe:
  - 0–5%: tăng dần từ 0,7 lên 1,0;
  - 5% → SOC_knee: bằng 1,0;
  - SOC_knee → 80%: giảm tuyến tính xuống r80;
  - 80 → 100%: giảm tuyến tính xuống r100.
  
  Giá trị mặc định đề xuất: pin LFP (phần lớn mẫu VinFast phổ thông) có SOC_knee = 0,60, r80 = 0,50, r100 = 0,10; pin NMC có SOC_knee = 0,50, r80 = 0,55, r100 = 0,10. Khi có đường cong Fastned của mẫu xe tương ứng thì thay bằng đường cong đó.
- **Động học SOC** (bước Δt = 1 phút): dSOC/dt = η·P(t)/E_usable, với η ≈ 0,90 cho AC và 0,93–0,95 cho DC (giả định). Năng lượng tính tiền là E_grid = ∫P dt. SOC_end = min(SOC mục tiêu, SOC tại thời điểm rút xe). Với trụ ≥250 kW của V-Green, SOC_end ≤ 0,80.
- **Thời gian sạc:** T_sạc = ∫ từ SOC_start đến SOC_end của E/(η·P(SOC)) dSOC. Lấy tích phân số trên lưới SOC 0,5%.
- **Kiểm tra hiệu chỉnh bằng công bố của VinFast** (thời gian sạc 10–70%):
  - VF 6 (59,6 kWh, DC 100 kW): với SOC_knee = 0,6 và r80 = 0,5, mô hình cho khoảng 22–24 phút. Trang đại lý vinfast-saigon.com.vn ghi 25 phút "với bộ sạc 250 kW (10-70%)", còn vinfastansuong.com ghi khoảng 45 phút ở 60 kW; vì vậy khi hiệu chỉnh cần ghép đúng công suất trụ với con số công bố.
  - VF 5 Plus (37,23 kWh, DC 50 kW): mô hình khoảng 27–28 phút, so với công bố 30–33 phút.\[49\]\[50\]
  - VF 3 (18,64 kWh): công bố 36 phút tương đương công suất trung bình khoảng 18–19 kW, nên đặt P_peak khoảng 22 kW.\[51\]\[52\] Đây là giá trị *suy ra*, vì VinFast không công bố công suất DC đỉnh của VF 3.

**Danh mục xe (bảng `vehicle_models`, giá trị khởi tạo):**

| Mẫu xe | Pin (kWh, khả dụng) | AC tối đa (kW) | DC tối đa (kW) | 10–70% (công bố) | Ghi chú |
|---|---|---|---|---|---|
| VinFast VF 3 | 18,64 | Không có bộ sạc AC trên xe (sạc "tại nhà" 3 kW là DC qua CCS2) | Chưa công bố (suy ra khoảng 22) | 36 phút | Không gán vào cổng Type 2\[51\]\[52\]\[53\]\[54\] |
| VinFast VF 5 Plus | 37,23 | 6,6\[55\]\[56\] | 50 | 30–33 phút | LFP\[49\]\[50\] |
| VinFast VF 6 | 59,6\[57\] | 7,2 | 100 | khoảng 25 phút (đại lý: với trụ 250 kW; khoảng 45 phút ở 60 kW) | |
| VinFast VF 7 | 59,6 (Eco) / 75,3 (Plus) | 7,2 | 110\[58\]\[59\] | ≤28 phút (mục tiêu)\[58\]\[60\]\[61\] | |
| VinFast VF 8 | 87,7 | 11 | Chưa công bố chính thức | ≤24 phút (mục tiêu)\[55\]\[62\] | Thế hệ mới năm 2026: 60,13 kWh\[63\]\[64\]\[65\] |
| VinFast VF 9 | 123\[66\] | 11 (3 pha) | Chưa công bố chính thức | khoảng 26 phút (mục tiêu)\[67\]\[68\]\[69\] | |
| VinFast VF e34 | 42 | khoảng 3,3 (theo trang sạc tại nhà) | 60 | khoảng 30 phút ở 60 kW\[70\]\[71\]\[72\] | |
| VinFast VF MPV 7 | 60,13 | n/a | 80 | 30 phút\[73\] | |
| BYD Atto 3 (VN) | 49,92 / 60,48 | 7 (wallbox kèm xe); EU 11 | 89–110 (EU)\[74\]\[75\]\[76\]\[77\] | — | |
| BYD Dolphin (VN) | 44,9\[78\] | n/a | n/a | — | |
| BYD Seal (VN) | 61,44 / 82,56 | n/a | khoảng 100 (EU, 82,5 kWh)\[79\]\[80\] | — | |
| MG4 (VN) | 51 (DEL) / 64 (LUX) | 6,6 / 11 | 88 / 140\[81\] | — | |
| Hyundai Ioniq 5 | 77,4–84 | 11 | 233–263\[82\]\[83\]\[84\] | — | Thông số EU |
| Kia EV6 | 74–80 khả dụng | 10,9 | 233–263\[85\]\[86\]\[87\] | — | Thông số EU/Mỹ |
| Tesla Model Y | 60 (RWD) / 74–79 | 11 | 175 / 250\[88\]\[89\]\[90\] | — | Không bán chính hãng tại VN; thông số EU |

Lưu ý mâu thuẫn: một moderator của VinFast nói VF 6–9 nhận AC 11 kW, trong khi FAQ chính thức ghi 7,2 kW cho VF 6/VF 7.\[54\]\[91\]\[92\] Tôi dùng số trong FAQ. Công suất DC đỉnh 150–250 kW cho VF 8/VF 9 trên các trang đại lý là không chính thức nên không đưa vào bảng.

### 5. Mô hình sinh dữ liệu bằng học máy và cách đánh giá

- **Copula:** Einolander & Lahdelma (2022) mô hình đồng thời giờ bắt đầu, năng lượng và thời lượng bằng copula đa biến. Một nghiên cứu năm 2026 so sánh vine copula, CODINE và GMMNet trên bộ ba (giờ đến, thời lượng, năng lượng).\[48\]\[93\]
- **GAN:** Theo tổng quan arXiv 2409.15750, CopulaGAN trên dữ liệu bãi đỗ Caltech (mô phỏng 48 giờ) có tỷ lệ khớp "xấp xỉ trên 90%" với dữ liệu thật. Có CWGAN gắn nhãn theo khu văn phòng, thương mại, dân cư. SDG của Lahariya sinh dữ liệu "không phân biệt được về mặt thống kê" so với dữ liệu thật.
- **Diffusion:** SynthCharge (DDPM có điều kiện) dẫn đầu trong đánh giá TSTR. DiffCharge sinh đường cong công suất sạc ở cấp pin và cấp trạm.\[94\]\[95\]
- **Transformer kết hợp Gibbs sampling** (Thượng Hải, 3.777 xe điện, 15 tháng): sinh chuỗi chuyến đi và sạc dưới ràng buộc. Code và dữ liệu tổng hợp được công bố tại https://github.com/zhilee2023/EV-drive-charge-data-gen. \[93\]
- **Thước đo đánh giá nên dùng:**
  - KS/Wasserstein cho từng phân phối biên;
  - sai khác ma trận tương quan và phụ thuộc copula;
  - TSTR (huấn luyện trên dữ liệu tổng hợp, kiểm tra trên dữ liệu thật);
  - điểm phân biệt của một bộ phân loại thật/giả;
  - Fréchet Power-Scenario Distance cho chuỗi công suất;
  - **kiểm tra ràng buộc vật lý** (kWh ≤ ΔSOC·E/η; P ≤ min(...); các mốc thời gian đúng thứ tự).

### 6. Ảnh hưởng của thời gian, môi trường và không gian lên nhu cầu

Mô hình cường độ đề xuất (Poisson log-linear, ước lượng được bằng GLM trên dữ liệu chiếm dụng/sản lượng theo giờ):

λ_s(t) = λ0_s · f_h(giờ | loại ngày, loại vị trí) · f_dow · f_lễ(t) · f_thời tiết(t) · f_giao thông(t) · exp(βᵀ·x_s)

trong đó x_s gồm:
- log mật độ dân số (ô 1 km);
- số POI trong bán kính 500 m theo nhóm (ăn uống, mua sắm, văn phòng, giáo dục, y tế, giao thông, giải trí);
- số trạm trong bán kính 3 km và 5 km;
- khoảng cách tới trạm gần nhất;
- thời gian đi tới trạm gần nhất theo khung giờ.

Bằng chứng định hướng dấu hệ số:
- POI trong 500 m (OSM, 11 nhóm như IJCAI 2016) cùng nhu cầu ở 5 trạm gần nhất dự báo được nhu cầu. Một nghiên cứu ở Hà Lan thấy bán kính 350 m cho R² tốt nhất. Nghiên cứu khai phá web cho thấy người dùng chịu đi bộ từ cơ sở giáo dục xa gấp đôi so với từ cửa hàng, nhà hàng, bến xe.\[11\]\[96\]\[97\]
- Palo Alto/Boulder (khám phá nhân quả): mức sử dụng chủ yếu do khoảng cách tới tiện ích, mật độ xe điện đăng ký và vị trí sát trục giao thông lớn.\[98\]
- Thâm Quyến: cạnh tranh ở cự ly rất gần có hệ số âm và có ý nghĩa thống kê. Vì vậy hệ số của "số trạm trong 3 km" nên âm (giả định khởi tạo β = −0,05 mỗi trạm). Khoảng cách tới trạm gần nhất cũng có hệ số âm nhẹ, tức trạm trong cụm đông vẫn được dùng nhiều hơn, nên tác động cạnh tranh không đơn điệu.\[13\]
- Albany: giao thông và mật độ xe điện chiếm ưu thế; chỉ dùng POI thì R² giảm còn 0,43. Hàm ý: không nên để POI chi phối λ.\[14\]
- UrbanEV và Jiaxing có sẵn thời tiết theo giờ/ngày (nhiệt độ, độ ẩm, lượng mưa), dùng để ước lượng f_thời tiết.\[26\]\[27\]\[29\]\[99\] Giá trị khởi tạo giả định: mưa >10 mm/h → ×0,85 với AC tại trung tâm thương mại, ×1,0 với DC.

Hệ số ngày lễ cho Việt Nam (giả định khởi tạo; cần dữ liệu thật để hiệu chỉnh):

| Thời kỳ | Trạm đô thị (trung tâm thương mại/chung cư) | Trạm cao tốc/quốc lộ |
|---|---|---|
| 3–5 ngày trước Tết Nguyên Đán | ×1,2 | ×2,0–3,0 |
| Mùng 1–3 Tết | ×0,4–0,5 | ×0,8 |
| Mùng 4–7 (quay lại thành phố) | ×0,8 | ×2,0–3,0 |
| Nghỉ 30/4–1/5, 2/9 (kỳ nghỉ dài) | ×0,8 | ×1,5–2,0 |
| Cuối tuần thường | ×1,1 (trung tâm thương mại), ×0,7 (văn phòng) | ×1,3 |

Cờ ngày lễ nên lấy theo âm lịch: Tết, Giỗ Tổ Hùng Vương 10/3 âm lịch, cùng các ngày lễ dương lịch 1/1, 30/4, 1/5, 2/9. Có thể dùng thư viện `holidays` của Python (mã quốc gia VN), nhưng cần kiểm tra lại các ngày nghỉ bù do Chính phủ công bố hằng năm.

### 7. Bối cảnh Việt Nam

- **Cấu hình V-Green (trang chính thức):**
  - DC 60/80 kW mỗi cổng, 2 cổng/trụ, đầu ra 150–1000 VDC, có tích hợp ổ cắm AC;\[46\]
  - DC 20 kW, 1 cổng (dạng tủ đứng hoặc treo tường);\[46\]
  - DC 120/150 kW mỗi cổng, 2 cổng/trụ;\[100\]
  - DC 250 kW, 1 cổng/trụ;\[101\]
  - AC 11 kW, 1 cổng/trụ.\[100\]
- **Mô hình hợp tác của VinFast:** trạm ở bãi đỗ xe có tối thiểu 5 trụ DC 30 kW và 5 trụ AC 11 kW. Trạm dừng nghỉ cao tốc có khoảng 10 trụ DC 60 kW mỗi bên, mỗi trụ 2 cổng, phục vụ đồng thời 20 xe.\[102\] Như vậy danh sách AC 7,4/11/22 kW và DC 60/120/250 kW của bạn dùng được làm "mẫu cấu hình", nhưng nên thêm các mức thực tế 11 kW AC và 20/30/80/150 kW DC.
- **Giá và phí (ảnh hưởng trực tiếp tới thời gian rút xe):**
  - giá sạc 3.858 đ/kWh, áp dụng từ 19/03/2024;\[46\]
  - phí sau khi sạc xong (theo thông báo V-Green, hiệu lực từ 00h ngày 01/11/2025, áp dụng cho toàn bộ trụ sạc DC V-Green trên toàn quốc, đã gồm VAT): miễn phí 10 phút đầu, 1.000 đ/phút từ phút 11–60, 2.000 đ/phút từ phút 61–120, 4.000 đ/phút từ phút 121 trở đi, tối đa 1.000.000 đ/lần; trước đó, từ 26/08/2025, thời gian miễn phí đã rút từ 30 xuống 10 phút;
  - phí này *không* áp dụng cho trụ AC 11 kW, nên idle ở trụ AC sẽ dài hơn nhiều;\[46\]
  - phí chiếm chỗ khi đỗ nhưng không cắm sạc: 200.000 đ/giờ, tối đa 1.500.000 đ/lần, chỉ áp dụng tại 3 trạm (đối diện Trường Đại học VinUni – Vinhomes Ocean Park, nhà để xe mặt đất B3 – Vinhomes Ocean Park, và sảnh chính Vincom Center Landmark 81).
  
  Do biểu phí bậc thang, phân phối idle của DC nên có mật độ dồn dưới 10 phút và các điểm gãy ở phút 60 và 120.
- **Dữ liệu và nghiên cứu tại Việt Nam:** tôi không tìm thấy bộ dữ liệu phiên sạc công khai nào của Việt Nam. Các nghiên cứu hiện có chủ yếu về ý định mua xe: khảo sát 516 người ở TP.HCM/Hà Nội; 1.337 phiếu ở 12 quận Hà Nội; báo cáo UNDP với 1.427 phản hồi tại 5 thành phố và 3 tỉnh.\[103\]\[104\] Ngoài ra có bài tối ưu vị trí trạm ở TP.HCM bằng MINLP, và bộ khảo sát giao thông UTM-Hanoi (Scientific Data 2024).\[105\]\[106\] Các nguồn này giúp xác định phân khúc người dùng, nhưng không cho phân phối phiên sạc.
- **Nguồn dữ liệu môi trường và không gian** (gợi ý, tôi chưa kiểm chứng chi tiết trong nghiên cứu này): POI và mạng đường từ OpenStreetMap (Geofabrik Vietnam); dân số dạng lưới từ WorldPop hoặc Tổng cục Thống kê; thời tiết theo giờ từ ERA5/Open-Meteo hoặc trạm Nội Bài/Tân Sơn Nhất; thời gian di chuyển theo khung giờ từ API định tuyến (OSRM trên OSM với hệ số ùn tắc theo giờ, hoặc API thương mại).

## Recommendations

### (b) Kiến trúc sinh dữ liệu end-to-end

**Khối 0 – Cấu hình trạm (sinh một lần).** Chọn loại vị trí: chung cư, trung tâm thương mại, văn phòng, bãi đỗ, cao tốc. Từ loại vị trí, sinh danh sách trụ và cổng theo các mẫu thực tế:
- trung tâm thương mại: 4–10 trụ AC 11 kW và 2–4 trụ DC 60 kW;
- cao tốc: 6–10 trụ DC 60/80 kW (2 cổng) và 0–2 trụ DC 250 kW (1 cổng);
- mỗi trụ có số cổng, chuẩn cổng (Type 2/CCS2) và P_cổng;
- P_trạm = tổng P_cổng (chỉ lưu làm thuộc tính, theo giả định của bạn là không phân bổ công suất).

Tọa độ được gán từ bản đồ thật hoặc lấy mẫu trong Hà Nội/TP.HCM. Từ đó tính đặc trưng không gian tĩnh: POI 500 m, dân số, số trạm trong 3/5 km, khoảng cách trạm gần nhất.

**Khối 1 – Lượt xe đến (NHPP).** Tính λ_s(t) theo công thức ở mục 6 trên lưới 5–15 phút. Sinh thời điểm đến bằng thuật toán thinning (Lewis–Shedler): sinh ứng viên với λ_max, rồi chấp nhận với xác suất λ(t)/λ_max. Thời điểm đến (`t_arrival`) là **biến mô phỏng**.

**Khối 2 – Xe và người dùng.**
- Lấy mẫu phân khúc người dùng (cá nhân, xe dịch vụ/taxi, khách đường dài), rồi lấy mẫu mẫu xe theo tỷ trọng của phân khúc. Tỷ trọng là giả định, ví dụ cá nhân: VF 3 20%, VF 5 20%, VF 6 12%, VF 7 8%, VF 8 10%, VF 9 5%, VF e34 10%, BYD 7%, khác 8%.
- Lấy SOC_start theo loại trụ dự định và phân khúc (bảng mục 3), SOC mục tiêu, thời gian lưu dự kiến (với AC) và độ kiên nhẫn.
- Lọc tính tương thích: xe không có bộ sạc AC trên xe (VF 3) chỉ được gán cổng DC.\[53\]\[54\]

**Khối 3 – Hàng đợi và cấp cổng (SimPy).**
- Mỗi cổng là một `simpy.Resource(capacity=1)`; dùng `FilterStore` để lọc theo chuẩn cổng và loại AC/DC.
- Khi xe đến: nếu có cổng tương thích còn trống thì cấp cổng có công suất hiệu dụng lớn nhất. Nếu không có, tính thời gian chờ kỳ vọng W (từ thời gian sạc còn lại của các xe đang sạc), rồi cho xe balk theo logit (chuyển sang trạm lân cận, dùng thời gian đi tới trạm thay thế).
- Nếu xe vào hàng: cho reneging khi thời gian chờ vượt độ kiên nhẫn.
- Ghi log `queue_len_on_arrival`, `wait_min`, `balked` và `reneged`. Tất cả là **biến mô phỏng**.

**Khối 4 – Kết nối và bắt đầu sạc.** t_connect = thời điểm được cấp cổng (+ thời gian đỗ và cắm, khoảng 1–2 phút). t_charge_start = t_connect + độ trễ xác thực (log-normal).

**Khối 5 – Công suất và đường cong sạc.** Tích phân SOC theo phút với P(t) = min(P_cổng, P_xe, P_xe·c(SOC)). Tính E_grid, P_avg và P_peak, và lưu chuỗi công suất theo phút vào bảng `session_power_ts` nếu cần.

**Khối 6 – SOC_end và thời điểm kết thúc sạc.**
- Với DC: sạc tới SOC mục tiêu (chặn ở 0,8 nếu trụ ≥250 kW), nên t_charge_end = t_start + T_sạc.
- Với AC: nếu t_start + T_sạc > t_connect + thời gian lưu dự kiến, người dùng rút xe trước khi đầy. Khi đó SOC_end < mục tiêu, t_charge_end = t_disconnect, và `end_reason = 'user_unplug'`.

**Khối 7 – Rút xe.**
- DC: t_disconnect = t_charge_end + idle (hỗn hợp có điểm gãy theo biểu phí V-Green).
- AC: t_disconnect = t_connect + thời gian lưu dự kiến.
- Giải phóng cổng; xe tiếp theo trong hàng được cấp cổng.

**Lựa chọn mô hình:** dùng mô hình tham số và DES làm lõi, vì minh bạch, dễ điều khiển kịch bản và giải thích được cho demo. Dùng copula/GMM cho bộ ba (giờ đến, thời gian lưu, năng lượng) học từ ElaadNL/ACN. Chỉ chuyển sang CTGAN, diffusion hay SynthCharge khi đã có ít nhất vài chục nghìn phiên thật của Việt Nam.

### (c) Schema dữ liệu đầu ra

**`stations`**: station_id, name, operator, lat, lon, city, district, location_type, n_posts, n_ports, total_power_kw, opening_hours, price_vnd_kwh, idle_fee_policy_id.

**`posts`** (trụ): post_id, station_id, current_type (AC/DC), rated_power_kw, n_ports, model, install_date.

**`ports`** (cổng): port_id, post_id, connector (TYPE2/CCS2), max_power_kw, soc_cap (ví dụ 0,8 với trụ ≥250 kW).

**`vehicle_models`**: model_id, brand, model, battery_kwh_usable, ac_onboard_kw (NULL nếu không có), dc_max_kw, chemistry, curve_id, ac_capable, dc_capable.

**`charging_curves`**: curve_id, soc_pct, p_norm (0–1).

**`sessions`** (mỗi dòng một lượt đến):

| Trường | Ý nghĩa | Loại |
|---|---|---|
| session_id, station_id, post_id, port_id | Định danh | Quan sát |
| vehicle_model_id, battery_kwh, user_segment | Xe và người dùng | Quan sát (segment là mô phỏng) |
| t_arrival | Thời điểm xe đến trạm | **Chỉ mô phỏng** |
| queue_len_on_arrival, wait_min | Độ dài hàng đợi và thời gian chờ | **Chỉ mô phỏng** |
| balked, reneged, diverted_to_station_id | Bỏ đi hoặc chuyển trạm | **Chỉ mô phỏng** |
| t_connect, t_charge_start, t_charge_end, t_disconnect | 4 mốc thời gian | Quan sát |
| soc_start, soc_target, soc_end | SOC | Quan sát (soc_target là mô phỏng) |
| energy_kwh, avg_power_kw, peak_power_kw | Năng lượng và công suất | Quan sát |
| charge_min, idle_min, connected_min | Các thời lượng dẫn xuất | Quan sát (dẫn xuất) |
| end_reason | target_reached / soc_cap / user_unplug | Quan sát |
| cost_energy_vnd, cost_idle_vnd | Chi phí | Quan sát |
| is_simulated_field_mask | Bitmask đánh dấu trường do mô phỏng sinh | Metadata |

**`queue_events`**: event_id, station_id, ts, event_type (arrive/join/balk/renege/connect/start/end/disconnect), session_id, queue_len_after, n_busy_ports. Toàn bộ bảng này là **chỉ mô phỏng**.

**`env_timeseries`** (theo giờ, theo trạm hoặc theo thành phố): ts, station_id, temp_c, rain_mm, humidity, is_weekend, is_holiday, holiday_name, tet_phase, is_peak_hour, traffic_index, travel_time_nearest_min.

**`spatial_static`**: station_id, pop_density_km2, poi_food_500m, poi_retail_500m, poi_office_500m, poi_edu_500m, poi_health_500m, poi_transport_500m, n_stations_3km, n_stations_5km, dist_nearest_station_km, dist_highway_km, road_class.

**`station_hourly`** (tổng hợp, dùng để kiểm định giống UrbanEV): station_id, ts, occupancy_rate, energy_kwh, n_sessions, mean_queue_len, mean_wait_min.

### (d) Hiệu chỉnh và kiểm định với dữ liệu công khai

1. **Hiệu chỉnh từng khối bằng nguồn tương ứng:**
   - ElaadNL/ACN → copula (giờ đến, thời gian lưu, kWh) và idle cho AC;
   - Dundee/Perth → số phiên/ngày/trụ rapid và kWh cho DC 50 kW;
   - Jiaxing → hồ sơ giờ của trạm công cộng châu Á, độ trễ tạo đơn → bắt đầu sạc, hệ số thời tiết, tỷ lệ lý do kết thúc;
   - UrbanEV → hệ số POI/giá/thời tiết bằng GLM Poisson/NegBin trên sản lượng theo giờ;\[32\]
   - Nature Comms DCFC → phân phối SOC_start/SOC_end; Fastned → c(SOC);
   - công bố 10–70% của VinFast → SOC_knee/r80 cho từng mẫu xe.
2. **Kiểm định phân phối biên và phân phối đồng thời:** KS, khoảng cách Wasserstein, sai khác ma trận tương quan Spearman; so hồ sơ chiếm dụng theo giờ (MAPE) với UrbanEV sau khi chuẩn hóa.
3. **Kiểm định hàng đợi:** chạy kịch bản dừng (λ hằng, thời gian phục vụ mũ) và so P(chờ), W_q với công thức Erlang-C của M/M/c. Kiểm tra định luật Little L = λ·W trên log mô phỏng.
4. **Kiểm định vật lý:** 100% bản ghi phải thỏa t_arrival ≤ t_connect ≤ t_start < t_end ≤ t_disconnect, E_grid·η ≈ (SOC_end − SOC_start)·E, P_peak ≤ min(P_cổng, P_xe).
5. **Kiểm định tiện ích (TSTR):** huấn luyện một mô hình dự báo chiếm dụng trên dữ liệu tổng hợp, kiểm tra trên Dundee/UrbanEV, rồi so với mô hình huấn luyện trên dữ liệu thật.
6. **Chuyển miền sang Việt Nam:** giữ cấu trúc mô hình, thay danh mục xe, cấu hình trạm và biểu phí Việt Nam, đặt hệ số giờ và ngày lễ làm tham số kịch bản. Khi có log OCPP thật của trạm, ước lượng lại λ và hồ sơ giờ bằng Bayes/MLE.

## Caveats

### (e) Giả định cần lưu ý khi áp dụng cho Việt Nam

- **Không có dữ liệu phiên sạc công khai của Việt Nam.** Cơ cấu đội xe, hồ sơ giờ, hệ số Tết/ngày lễ, hệ số thời tiết và tham số balking/reneging trong báo cáo là *giả định khởi tạo*. Không được trình bày chúng như số liệu quan sát.
- **Danh mục công suất:** mức AC 7,4 và 22 kW, và DC 120/250 kW đa cổng, không khớp hoàn toàn với V-Green (AC 11 kW; DC 250 kW chỉ 1 cổng).\[46\]\[101\] Nên để cấu hình là tham số.
- **Không phân bổ công suất** (theo giả định của bạn) sẽ làm thời gian sạc lạc quan ở các trụ DC 2 cổng nếu thực tế trụ chia công suất. Cần ghi rõ trong demo.
- **Khả năng sạc AC của VF 3** được suy từ trang phụ kiện và diễn đàn VinFast; công suất DC đỉnh của VF 3/VF 8/VF 9 không được công bố chính thức. Thông số của Hyundai, Kia, Tesla và một phần BYD lấy theo phiên bản EU/Mỹ.
- **Xe dịch vụ (taxi điện)** có thể chiếm tỷ trọng lớn ở trạm DC đô thị, với hành vi khác hẳn xe cá nhân (SOC thấp, sạc nhiều lần trong ngày). Nên mô hình thành một phân khúc riêng. Đây là giả định, chưa có số liệu.
- **Khí hậu nóng ẩm** có thể làm đường cong DC thực tế lệch so với dữ liệu châu Âu (Fastned, DCFC Tây Bắc Âu), do giới hạn nhiệt của pin. Mùa mưa và ngập cục bộ ảnh hưởng tới giao thông và nhu cầu.
- **Nhiều nghiên cứu được trích là preprint arXiv năm 2025–2026** (copula/CODINE, Fastned flexibility, ev-flow, ToU Thâm Quyến) chưa qua bình duyệt. Các con số từ trang đại lý xe và blog chỉ dùng tham khảo.
- **Biến thời gian chờ và hàng đợi** chỉ được coi là quan sát nếu hệ thống thật ghi được sự kiện đến hoặc xếp hàng (ví dụ camera, đặt chỗ qua app). Nếu không, phải giữ cờ "mô phỏng" trong mọi phân tích hạ nguồn.

## Sources

1. [ACN-Data: Analysis and Applications of an Open EV Charging Dataset](https://ev.caltech.edu/assets/pub/ACN_Data_Analysis_and_Applications.pdf)
2. [ACN-Data -- A Public EV Charging Dataset](https://ev.caltech.edu/dataset)
3. [USE CASES AND INTRODUCTORY ANALYSIS OF THE DATASET COLLECTED WITHIN THE LARGE](https://www.erachair.uniza.sk/wp-content/uploads/2018/11/Use_cases_and_introductory_analysis_of_the_dataset_collected_within_the_large_network_of_public_charging_stations.pdf)
4. [Electric vehicle charging dataset with 35,000 charging sessions from 12 residential locations in Norway - ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2352340924008461)
5. [Deep learning predicts real-world electric vehicle direct current charging profiles and durations](https://www.nature.com/articles/s41467-025-65970-y)
6. [Deep learning predicts real-world electric vehicle direct current charging profiles and durations - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12680626/)
7. <https://arxiv.org/html/2404.01849v1>
8. [Quantifying Realizable Flexibility Limits in Fast and Ultra-Fast EV Charging Using Real-World Data](https://arxiv.org/pdf/2606.29994)
9. [Stochastic modeling-based queueing frameworks for performance enhancement and economic optimization of hybrid electric vehicle charging networks - ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2590123026020943)
10. [Dynamic Modeling and Real-time Management of a System of EV Fast-charging Stations](https://arxiv.org/pdf/2012.09349)
11. [Demand Prediction and Placement Optimization for Electric ...](https://www.ijcai.org/Proceedings/16/Papers/442.pdf)
12. [Demand Prediction and Placement Optimization for Electric Vehicle Charging Stations](https://arxiv.org/html/1604.05472v2)
13. [The Effectiveness and Limits of Time-of-Use Pricing in Public EV Charging Networks](https://arxiv.org/pdf/2603.29223)
14. [Optimal Placement of Public Electric Vehicle Charging Stations Using Deep Reinforcement Learning](https://arxiv.org/pdf/2108.07772)
15. [GitHub - tongxin-li/ACN-Data-Static: This is a static version of ACN-Data (https://ev.caltech.edu/dataset), collected from three sites from 2018 to 2020. · GitHub](https://github.com/tongxin-li/ACN-Data-Static)
16. [Analyzing electric vehicle, load and photovoltaic generation uncertainty using publicly available datasets](https://arxiv.org/html/2409.01284v2)
17. [Electric Vehicle Charging Station Usage (July 2011 - Dec 2020) · Open Data · City of Palo Alto](https://data.paloalto.gov/datasets/194693/electric-vehicle-charging-station-usage-july-2011-dec-2020/)
18. [Electric Vehicle Charging Station Usage (July 2011 - Dec 2020) — OpenEnergyDataPortal](https://openenergyhub.ornl.gov/explore/dataset/electric-vehicle-charging-station-usage-july-2011-dec-2020/)
19. [Electric vehicle charging station distribution in four different cities...](https://www.researchgate.net/figure/Electric-vehicle-charging-station-distribution-in-four-different-cities-a-Palo-Alto-city_fig1_370637571)
20. [Electric Vehicle Charging Station Data](https://open-data.bouldercolorado.gov/maps/95992b3938be4622b07f0b05eba95d4c_0/explore)
21. [Multistep Electric Vehicle Charging Station Occupancy Prediction using Hybrid LSTM Neural Networks](https://arxiv.org/pdf/2106.04986)
22. [EV charger point usage - a Freedom of Information request to Perth and Kinross Council - WhatDoTheyKnow](https://www.whatdotheyknow.com/request/ev_charger_point_usage_6)
23. [A Review of Electric Vehicle Load Open Data and Models](https://www.mdpi.com/1996-1073/14/8/2233)
24. [A dataset for multi-faceted analysis of electric vehicle charging transactions](https://www.nature.com/articles/s41597-024-02942-9)
25. [A high-resolution electric vehicle charging transaction dataset with multidimensional features in China](https://www.nature.com/articles/s41597-025-04982-1)
26. [(PDF) A high-resolution electric vehicle charging transaction dataset with multidimensional features in China](https://www.researchgate.net/publication/390846683_A_high-resolution_electric_vehicle_charging_transaction_dataset_with_multidimensional_features_in_China)
27. [Climate-resilient electric vehicle charging infrastructure for sustainable cities: An interpretable causal-ensemble framework for preventive maintenance and low-carbon mobility](https://arxiv.org/pdf/2607.21444)
28. [GitHub - lizhanlian/UrbanEV: UrbanEV is an open benchmark dataset for electric vehicle (EV) charging demand in Shenzhen, China. · GitHub](https://github.com/lizhanlian/UrbanEV)
29. [Dryad](https://datadryad.org/dataset/doi:10.5061/dryad.np5hqc04z)
30. [GitHub - IntelligentSystemsLab/ST-EVCDP: A real-world dataset for EV-related research, e.g., spatiotemporal prediction and urban energy management. · GitHub](https://github.com/IntelligentSystemsLab/ST-EVCDP)
31. [Shenzhen’s EV Data Shows Why More Chargers May Not Fix the After-Work Charging Rush](https://www.torquenews.com/17998/shenzhens-ev-data-shows-why-more-chargers-may-not-fix-after-work-charging-rush)
32. [A Spatio-Temporal Attention Model for Short-Term Load Forecasting of Urban Electric-Vehicle Charging Stations and an Empirical Study of Spatial-Modeling Effectiveness](https://www.mdpi.com/1996-1073/19/14/3411)
33. [Electric vehicle charging dataset with 35,000 charging sessions from 12 residential locations in Norway](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11404051/)
34. [High-temporal-resolution dataset of uni-, bidirectional, and dynamic electric vehicle charging profiles](https://www.nature.com/articles/s41597-025-05524-5)
35. [EV-Insights: open source framework for electric vehicle charging data processing, analysis, and forecasting](https://link.springer.com/article/10.1186/s42162-025-00615-4)
36. [IDEAS: Information-Driven EV Admission in Charging Station Considering User Impatience to Improve QoS and Station Utilization](https://arxiv.org/html/2403.06223)
37. [Emission-Aware Reinforcement Learning for Sustainable Electric Vehicle Charging and Carbon Dioxide Reduction Under Varying Renewable Penetration](https://arxiv.org/html/2605.24543)
38. [ACN-Sim: An Open-Source Simulator for Data-Driven Electric ...](https://ev.caltech.edu/assets/pub/ACN_Sim_Open_Source_Simulator.pdf)
39. [energies Article Vehicle Energy Consumption in Python (VencoPy): Presenting](https://pdfs.semanticscholar.org/424e/b39c4c45eed922d99aaa87738b9eb7ed4a57.pdf)
40. [ev-flow: A Reproducible, NHTS-Grounded Generator of Synthetic Plug-in Electric Vehicle Charging Behavior for Eight U.S. Regions](https://arxiv.org/html/2606.19520)
41. [An open tool for creating battery-electric vehicle time series from empirical data, emobpy - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8196066/)
42. [GitHub - RAMP-project/RAMP-mobility: A novel application of the RAMP main engine for generating bottom-up stochastic electric vehicles load profiles. · GitHub](https://github.com/RAMP-project/RAMP-mobility)
43. [(PDF) Synthetic Data Generator for Electric Vehicle Charging Sessions: Modeling and Evaluation Using Real-World Data](https://www.researchgate.net/publication/343662878_Synthetic_Data_Generator_for_Electric_Vehicle_Charging_Sessions_Modeling_and_Evaluation_Using_Real-World_Data)
44. [FlexiGen: Stochastic Dataset Generator for Electric Vehicle Charging Energy Flexibility](https://arxiv.org/pdf/2411.07040)
45. [EV Charging Research at Caltech](https://ev.caltech.edu/research)
46. [Sản phẩm dịch vụ | V-Green](https://vgreen.net/vi/san-pham-dich-vu)
47. [Full article: Idle occupancy and dead piles: new challenges in public charging station promotion](https://www.tandfonline.com/doi/full/10.1080/19475683.2025.2472781)
48. [Capturing Multivariate Dependencies of EV Charging Events: From Parametric Copulas to Neural Density Estimation This work was partially supported by the following projects: V4Grid - The Visegrad group for Vehicle to X: Interreg Central Europe Programme, project No. CE0200803; LorAI - Low Resource Artificial Intelligence: Horizon Europe Programme, GA No. 101136646.](https://arxiv.org/html/2603.29554)
49. [Tổng quan VinFast VF5 Plus: Thông số, tính năng, giá bán chỉ từ 458 triệu đồng](https://vinfastauto.com/vn_vi/tong-quan-xe-o-to-dien-vinfast-vf-5-plus)
50. [Câu hỏi thường gặp về xe máy điện & ô tô VinFast](https://vinfastauto.com/vn_vi/cau-hoi-thuong-gap/cau-hoi-xe-o-to/san-pham/vf-5)
51. [VinFast VF 3: Thông số, Giá bán & Ưu đãi mới nhất](https://shop.vinfastauto.com/vn_vi/dat-coc-xe-dien-vf3.html)
52. [Thông số kỹ thuật VF 3, cập nhật mới nhất 2024](https://vinfastauto.com/vn_vi/thong-so-vf3)
53. [Sạc Tại Nhà 3KW](https://shop.vinfastauto.com/vn_vi/EEP69072176AB.html)
54. [Công suất sạc AC của xe VinFast là bao nhiêu ? - Hỏi](https://vinfast.vn/dien-dan/thao-luan/cong-suat-sac-ac-cua-xe-vinfast-la-bao-nhieu/)
55. [Thời gian sạc đầy pin xe ô tô điện Vinfast VFe34, VF5, VF8, VF9](https://evse.com.vn/thoi-gian-sac-day-pin-o-to-dien-vinfast)
56. [VinFast VF 5](https://en.wikipedia.org/wiki/VinFast_VF_5)
57. [Tìm hiểu công nghệ Pin xe ô tô điện VinFast, so sánh dung lượng pin của các dòng xe Vinfast - Vinfast Nam Từ Liêm](https://vinfastnamtuliem.vn/tim-hieu-cong-nghe-pin-xe-o-to-dien-vinfast-so-sanh-dung-luong-pin-cua-cac-dong-xe-vinfast/)
58. [Công suất sạc Pin tối đa trên VinFast VF 7 là bao nhiêu?](https://vinfastauto.com/vn_vi/node/11533)
59. [VinFast VF 7](https://en.wikipedia.org/wiki/VinFast_VF_7)
60. [Xe điện VinFast VF 7 chính hãng - Giá bán, Ưu đãi mới nhất](https://shop.vinfastauto.com/vn_en/dat-coc-xe-dien-vf7.html)
61. [VinFast VF 7 đi được bao nhiêu km? Thời gian mở bán dự kiến?](https://vinfastauto.com/vn_vi/vf-7-di-duoc-bao-nhieu-km)
62. [VinFast VF8 SUV điện hạng D của VinFast](https://vinfastvungtau.com.vn/vinfast-vf8.htm)
63. [VinFast VF 8 Eco Extended Range (2023-2026) price and specifications - EV Database](https://ev-database.org/car/1807/VinFast-VF-8-Eco-Extended-Range)
64. [Tôi muốn tìm hiểu về thông số kỹ thuật xe VF 8](https://vinfastauto.com/vn_vi/node/9080)
65. [VINFAST RA MẮT VF 8 THẾ HỆ MỚI - NÂNG CẤP TRẢI NGHIỆM TOÀN DIỆN CHO NGƯỜI DÙNG](https://vinfastauto.com/vn_vi/vinfast-ra-mat-vf-8-the-he-moi-nang-cap-trai-nghiem-toan-dien-cho-nguoi-dung)
66. [VinFast VF9 SUV điện hạng E cao cấp của VinFast](https://vinfastvungtau.com.vn/vinfast-vf9.htm)
67. [SPECIFICATION SHEET](https://static-cms-prod.vinfastauto.us/cms-vinfast-us/Specs/VF-9-Spec.pdf)
68. [Tổng quan VinFast VF 9 - mẫu SUV điện hạng sang của người Việt](https://vinfastauto.com/vn_vi/tong-quan-vinfast-vf-9)
69. [Công suất sạc Pin tối đa trên VinFast VF 9 là bao nhiêu?](https://vinfastauto.com/vn_vi/node/11572)
70. [Tìm hiểu pin xe ô tô điện VF e34: thông số, chính sách thuê](https://vinfastauto.com/vn_vi/pin-xe-o-to-dien-vf-e34)
71. [Thời gian sạc VF e34 đầy pin trong bao lâu?](https://vinfastauto.com/vn_vi/thoi-gian-sac-vf-e34-day-pin-trong-bao-lau)
72. [Thời gian sạc pin của các loại trụ sạc, sạc cầm tay cho VF e34](https://vinfastauto.com/vn_vi/thoi-gian-sac-pin-cac-loai-tru-sac-sac-cam-tay-vf-e34)
73. [VF MPV 7 - Thông số, hình ảnh, giá bán mới nhất](https://vinfastauto.com/vn_vi/dat-coc-xe-vf-mpv7)
74. [Bộ 3 xe điện BYD chốt giá tại Việt Nam: Từ 659 triệu, cao nhất 1,4 tỷ đồng](https://dantri.com.vn/o-to-xe-may/bo-3-xe-dien-byd-chot-gia-tai-viet-nam-tu-659-trieu-cao-nhat-14-ty-dong-20240718144416041.htm)
75. [BYD Atto 3: giá lăn bánh 8/2026, TSKT, đánh giá chi tiết - Báo VnExpress](https://vnexpress.net/oto-xe-may/v-car/dong-xe/byd-atto-3-266)
76. [BYD ATTO 3 (MY23-24) (2022-2025) price and specifications - EV Database](https://ev-database.org/car/1782/BYD-ATTO-3)
77. [BYD ATTO 3 (MY25) (2025-2026) price and specifications - EV Database](https://ev-database.org/car/3192/BYD-ATTO-3)
78. [Bộ 3 xe điện BYD chốt giá tại Việt Nam](https://chootocampha.com/news/251/40/bo-3-xe-dien-byd-chot-gia-tai-viet-nam)
79. [Bảng giá xe BYD 2026 mới nhất (10/2026)](https://oto.com.vn/bang-gia-xe-o-to-byd-moi-nhat)
80. [All electric vehicles in Europe - EV Database](https://ev-database.org/imp/)
81. [Thông số kỹ thuật xe MG4 EV: Liệu có đủ sức cạnh tranh VinFast VF 6 khi chốt giá từ 828 triệu đồng?](https://oto.com.vn/thong-so-ky-thuat/xe-mg4-ev-2024-tai-viet-nam-articleid-py1c5fh)
82. [Hyundai IONIQ 5 84 kWh RWD (MY24) (2024-2026) price and specifications - EV Database](https://ev-database.org/uk/car/2236/Hyundai-IONIQ-5-84-kWh-RWD)
83. [Hyundai IONIQ 5 Long Range 2WD (MY22) (2022-2024) price and specifications - EV Database](https://ev-database.org/uk/car/1662/Hyundai-IONIQ-5-Long-Range-2WD)
84. [Used Hyundai IONIQ 5 & Battery Heath (Real-world Data)](https://www.recurrentauto.com/guides/hyundai-ioniq-5)
85. [Kia EV6 Long Range 2WD (2021-2024) price and specifications - EV Database](https://ev-database.org/car/1481/Kia-EV6-Long-Range-2WD)
86. [Kia EV6 Long Range AWD (2024-2026) price and specifications - EV Database](https://ev-database.org/car/3029/Kia-EV6-Long-Range-AWD)
87. [2024 Kia EV6 Specifications](https://www.kiamedia.com/us/en/models/ev6/2024/specifications)
88. [Tesla Model Y Long Range AWD (Juniper) (2025) price and specifications - EV Database](https://ev-database.org/uk/car/3104/Tesla-Model-Y-Long-Range-AWD)
89. [Tesla Model Y Long Range RWD (Juniper - Tesla 4680) (2025-2026) price and specifications - EV Database](https://ev-database.org/car/3417/Tesla-Model-Y-Long-Range-RWD)
90. [Tesla Model Y RWD (Juniper) (2025) price and specifications - EV Database](https://ev-database.org/car/3103/Tesla-Model-Y-RWD)
91. [Câu hỏi thường gặp về xe máy điện & ô tô VinFast](https://vinfastauto.com/vn_vi/cau-hoi-thuong-gap/cau-hoi-xe-o-to/san-pham/vf-6)
92. [Câu hỏi thường gặp về xe máy điện & ô tô VinFast](https://vinfastauto.com/vn_vi/cau-hoi-thuong-gap/cau-hoi-xe-o-to/san-pham/vf-7)
93. [Synthetic data generation for joint electric vehicle driving and charging events via deep generative networks - ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0968090X25004851)
94. [SynthCharge: Synthetic Data Generator for Electric Vehicle Charging Sessions](https://doi.org/10.1145/3765611.3815511)
95. [Fr\\'{e}chet Power-Scenario Distance: A Metric for Evaluating Generative AI Models across Multiple Time-Scales in Smart Grids](https://arxiv.org/pdf/2505.08082)
96. [Predicting popularity of EV charging infrastructure from GIS ...](https://arxiv.org/pdf/1910.02498)
97. [Web Mining to Inform Locations of Charging Stations for Electric Vehicles](https://arxiv.org/pdf/2203.07081)
98. [Data-Driven Optimization of EV Charging Station Placement Using Causal Discovery](https://arxiv.org/html/2503.17055v1)
99. [(PDF) UrbanEV: An Open Benchmark Dataset for Urban Electric Vehicle Charging Demand Prediction](https://www.researchgate.net/publication/390285409_UrbanEV_An_Open_Benchmark_Dataset_for_Urban_Electric_Vehicle_Charging_Demand_Prediction)
100. [Nhượng quyền trạm sạc - Vinfast](https://vinfast-autohanoi.vn/tramsacvgreen/)
101. [Trạm Sạc VinFast - VINFAST BÌNH DƯƠNG](https://vinfastbinhduong.com/quy-hoach-tram-sac-vinfast/)
102. [Đăng ký hợp tác trạm sạc VinFast](https://vinfastauto.com/vn_vi/hop-tac-tram-sac-vinfast)
103. [Electric vehicle adoption in Vietnam: usefulness and pro-environmentalism in an emerging market](https://www.researchgate.net/publication/385841342_Electric_vehicle_adoption_in_Vietnam_usefulness_and_pro-environmentalism_in_an_emerging_market)
104. [report\_of\_ev\_target\_groups\_final.pdf](https://www.undp.org/sites/g/files/zskgke326/files/2024-10/report_of_ev_target_groups_final.pdf)
105. [Electric Vehicle Charging Stations Placement Optimization in Vietnam Using Mixed-Integer Nonlinear Programming Model](https://arxiv.org/pdf/2412.16025)
106. [An open dataset on individual perceptions of transport policies](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10803299/)
