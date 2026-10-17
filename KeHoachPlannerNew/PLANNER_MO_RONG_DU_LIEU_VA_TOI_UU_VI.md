# Planner mở rộng: dữ liệu nhu cầu, mạng trạm và tính khả thi đầu tư

> **Trạng thái:** Đề xuất kỹ thuật và kế hoạch triển khai; **không phải** mô tả một tính năng đã hoàn thành.
>
> **Mục tiêu:** Chuyển Station Planner từ công cụ sàng lọc demo dựa trên snapshot thành công cụ giúp doanh nghiệp trả lời có căn cứ: *nên khảo sát vị trí nào trước, vì sao, còn thiếu bằng chứng gì, và không nên xây ở đâu.*
>
> **Cách tính điểm:** thống nhất với [kế hoạch tìm khoảng trống trạm sạc](ke-hoach-khoang-trong-tram-sac.md): $D_i$ (Flow + POI) → $\text{Cung}_i$ → $\text{Gap}_i = D_i/(1+\text{Cung}_i)$ → điều chỉnh giá thuê → cờ ăn nhu cầu của mình (mục 4.5). Các phần còn lại của tài liệu (nhãn, trạng thái cổng, gate pháp lý) là dữ liệu và bằng chứng đi kèm kết quả, không phải số hạng thêm vào công thức.
>
> **Đọc cùng:** [Đề án Smart EV Journey](DE_AN_SMART_EV_JOURNEY.md), [tài liệu kỹ thuật tổng thể](TAI_LIEU_KY_THUAT_VA_LO_TRINH_PHAT_TRIEN_VI.md), [nhóm tính năng và roadmap](FEATURE_GROUPS_AND_ROADMAP_VI.md).

---

## Mục lục

0. [Tóm tắt phản hồi của ban giám khảo](#0-tóm-tắt-phản-hồi-của-ban-giám-khảo)
1. [Điểm xuất phát thực tế của repo](#1-điểm-xuất-phát-thực-tế-của-repo)
2. [Nguyên tắc thiết kế](#2-nguyên-tắc-thiết-kế)
3. [Ngôn ngữ chung và mô hình thông tin](#3-ngôn-ngữ-chung-và-mô-hình-thông-tin)
4. [Lớp dữ liệu nhu cầu: dân cư, điểm đến và luồng xe](#4-lớp-dữ-liệu-nhu-cầu-dân-cư-điểm-đến-và-luồng-xe)
5. [Nhãn mạng trạm: của doanh nghiệp, liên kết và mạng khác](#5-nhãn-mạng-trạm-của-doanh-nghiệp-liên-kết-và-mạng-khác)
6. [Trạng thái chi tiết từng vị trí/cổng sạc](#6-trạng-thái-chi-tiết-từng-vị-trícổng-sạc)
7. [Điều kiện pháp lý và dữ liệu cạnh tranh](#7-điều-kiện-pháp-lý-và-dữ-liệu-cạnh-tranh)
8. [Cách Planner ra quyết định sau khi mở rộng](#8-cách-planner-ra-quyết-định-sau-khi-mở-rộng)
9. [Kiến trúc dữ liệu, API và giao diện cần xây](#9-kiến-trúc-dữ-liệu-api-và-giao-diện-cần-xây)
10. [Hướng phát triển mô hình dự báo nhu cầu](#10-hướng-phát-triển-mô-hình-dự-báo-nhu-cầu)
11. [Lộ trình thực hiện và tiêu chí hoàn thành](#11-lộ-trình-thực-hiện-và-tiêu-chí-hoàn-thành)
12. [Kiểm thử, đo hiệu quả và quản trị dữ liệu](#12-kiểm-thử-đo-hiệu-quả-và-quản-trị-dữ-liệu)
13. [Cách trình bày lại với ban giám khảo](#13-cách-trình-bày-lại-với-ban-giám-khảo)
14. [Nguồn tham khảo](#14-nguồn-tham-khảo)

---

## 0. Tóm tắt phản hồi của ban giám khảo

Các góp ý có thể hiểu thành bốn yêu cầu lớn, không phải chỉ là thêm vài lớp marker lên bản đồ.

| Góp ý | Câu hỏi kinh doanh phía sau | Năng lực cần có | Kết quả người dùng nên thấy |
|---|---|---|---|
| Thêm cường độ dân cư và dòng người/xe đi qua đường | Khu vực này có **nhu cầu sạc thật** hay chỉ đông người? | Tách dữ liệu cư dân, điểm đến, luồng xe và nhu cầu sạc; theo không gian lẫn thời gian | Bản đồ nhu cầu có giải thích nguồn và khung giờ, không chỉ heatmap chung chung |
| Nhãn trạm của mình và trạm đối thủ | Vị trí mới có bổ sung thị trường hay chỉ tự cạnh tranh với mạng hiện có? | Phân loại mạng trạm theo từng doanh nghiệp, có nguồn xác minh | Bản đồ phân biệt “Mạng của bạn”, “Mạng liên kết”, “Mạng khác”, “Chưa xác minh” |
| Xem trạng thái chi tiết các cổng | Nguồn cung sạc thực tế còn bao nhiêu và đáng tin đến đâu? | Dữ liệu theo từng vị trí sạc/cổng, thời điểm cập nhật, tình trạng lỗi và dữ liệu cũ | Danh sách cổng tương thích: sẵn sàng/đang sạc/lỗi/không rõ, thay vì một số đếm mơ hồ |
| Thêm trạm đối thủ và thông tin đặt trạm | Điểm này có đáng khảo sát và có vướng pháp lý không? | Hồ sơ pháp lý, giá thuê tham khảo (tùy chọn) và nguồn cung cạnh tranh | Mỗi vị trí có lý do ưu tiên, rủi ro, bằng chứng thiếu và việc khảo sát tiếp theo |

### Một câu trả lời mới cho ban giám khảo

> Planner không chọn điểm xây trạm bằng một “điểm AI” duy nhất. Hệ thống tách rõ **nhu cầu có thể phục vụ**, **nguồn cung hiện có**, và **khả năng xây/vận hành**; mỗi kết luận đều nêu nguồn dữ liệu, độ mới và phần cần khảo sát ngoài thực địa.

---

## 1. Điểm xuất phát thực tế của repo

Đây là ranh giới cần nói rõ trước khi phát triển tiếp.

| Thành phần | Hiện có | Điều chưa nên tuyên bố |
|---|---|---|
| Planner | Snapshot 9 phường, 18 vị trí ứng viên, 27 điểm nhu cầu, engine `technical_opportunity` để sàng lọc kỹ thuật | Chưa là hệ thống phê duyệt đầu tư hoặc tối ưu danh mục đầu tư thật |
| Dân số, POI và giao thông | Có dữ liệu dân số theo phường và POI/bối cảnh giao thông | Chưa có số xe đi qua theo đoạn đường/khung giờ; `traffic_intensity` hiện là proxy/kịch bản |
| Trạm hiện hữu | Có 37 trạm fixture dùng cho demo Planner | Chưa có nguồn xác minh trạm thật, quan hệ chủ sở hữu/mạng, hay dữ liệu đối thủ đầy đủ |
| Trạng thái cổng | Backend đã có bảng trạng thái cổng, lịch sử và API ingest; luồng driver có thể suy ra số cổng từ occupancy tổng | Planner chưa nhận telemetry thật; không thể khẳng định “cổng số 2 đang sạc” khi nguồn chỉ báo tổng số cổng bận |
| Pháp lý, giấy phép | Candidate có các điều kiện dạng `unknown`/`conditional` và thông tin scenario | Chưa có xác nhận của cơ quan có thẩm quyền về quy hoạch, giấy phép, PCCC hay điều kiện kinh doanh. Đất và điện lưới nằm ngoài phạm vi Planner |

Các giới hạn này đã được ghi trong [README bộ dữ liệu Planner](../../data_platform/station_planning/README.md) và [README dữ liệu POI/giao thông](../../raw_data/official_poi_transport/README.md). Việc mở rộng phải giữ nguyên tính trung thực này: **proxy là proxy, mô phỏng là mô phỏng, dữ liệu đo được là dữ liệu đo được.**

---

## 2. Nguyên tắc thiết kế

1. **Không đánh đồng nơi đông người với nhu cầu sạc cao.** Dân cư, người đến ban ngày, xe đi qua và phiên sạc là bốn tín hiệu khác nhau.
2. **Không biến thiếu dữ liệu thành điểm 0 hoặc điểm đạt.** Trường chưa khảo sát phải là `chưa xác minh`; kết quả cần chỉ rõ điều đó.
3. **Phân biệt dữ liệu hiện tại, lịch sử và dự báo.** Ví dụ: “cổng đang sẵn sàng”, “thường đông lúc 18:00”, “dự báo đầy sau 20 phút” là ba phát biểu khác nhau.
4. **Nhãn “của mình/đối thủ” phụ thuộc doanh nghiệp đang xem.** Một trạm có thể là trạm đối tác của doanh nghiệp A nhưng là mạng khác với doanh nghiệp B.
5. **Không công bố trạng thái đối thủ như sự thật nếu nguồn không được cấp quyền.** Mỗi trạng thái phải có nguồn, thời điểm cập nhật và nhãn độ mới.
6. **Điểm số chỉ để ưu tiên khảo sát.** Điều kiện pháp lý (quy hoạch, giấy phép, PCCC, điều kiện kinh doanh) phải được kiểm tra trước khi coi là có thể xây. Điều kiện đất và điện lưới nằm ngoài phạm vi Planner.
7. **Dùng dữ liệu tổng hợp, không theo dõi hành trình cá nhân.** Planner cần số lượng xe/người theo ô và khung giờ, không cần GPS thô hoặc danh tính tài xế.
8. **Mỗi lần chạy phải tái lập được.** Lưu phiên bản dữ liệu, cấu hình trọng số, thời điểm chạy và bằng chứng đi kèm kết quả.

---

## 3. Ngôn ngữ chung và mô hình thông tin

### 3.1. Bốn tín hiệu nhu cầu không được gộp lẫn

| Tín hiệu | Nghĩa dễ hiểu | Ví dụ câu hỏi trả lời được | Không thể suy ra trực tiếp |
|---|---|---|---|
| **Dân cư cư trú** | Có bao nhiêu người sinh sống quanh đây | Khu chung cư có thể cần sạc qua đêm không? | Bao nhiêu xe điện sẽ sạc hôm nay |
| **Người đến ban ngày/điểm đến** | Người tới làm việc, học, mua sắm, khám bệnh, du lịch… | Có xe đỗ đủ lâu để sạc ban ngày không? | Lượng xe đi qua đường kế bên |
| **Lưu lượng xe đi qua** | Số xe trên từng đoạn đường theo khung giờ | Vị trí có được nhìn thấy, dễ ghé vào và có luồng xe phù hợp không? | Số người đi bộ hoặc số phiên sạc |
| **Nhu cầu sạc EV** | Số phiên sạc, kWh, thời gian chờ hoặc số lượt không được phục vụ | Khu nào thật sự thiếu khả năng sạc? | Chỉ từ dân số/POI mà khẳng định được |

Ví dụ: một phố đi bộ rất đông không nhất thiết có nhu cầu sạc ô tô cao; một đường xe đông nhưng khó rẽ vào hoặc không có chỗ đỗ có thể là vị trí xấu. Vì thế Planner phải lưu các tín hiệu riêng trước khi tính kết luận.

### 3.2. Phân cấp đúng của trạm sạc

```text
Địa điểm / trạm (Station location)
  └── Vị trí sạc vật lý (EVSE: một chỗ mà một xe có thể dùng)
        └── Đầu cắm (Connector: CCS2, Type 2, ...)
```

Một vị trí sạc có thể có nhiều đầu cắm nhưng không đồng nghĩa hai xe có thể sạc cùng lúc. Vì vậy:

- **Số vị trí sạc có thể phục vụ xe** mới là số chỗ sạc; không được cộng mọi đầu cắm thành “số cổng trống”.
- Cần biết xe nào tương thích với đầu cắm nào trước khi nói còn chỗ.
- Mỗi thay đổi trạng thái phải gắn với đúng cấp mà nguồn dữ liệu cung cấp: cả trạm, vị trí sạc, hay đầu cắm.

### 3.3. Nhãn độ tin cậy tối thiểu

Mọi trường quan trọng trên bản đồ hoặc trong báo cáo cần mang một trong các nhãn sau:

| Nhãn | Nghĩa | Ví dụ |
|---|---|---|
| `measured` | Đo/nhận trực tiếp từ nguồn vận hành | Event cổng đang sạc từ CPO |
| `official` | Công bố bởi cơ quan/nguồn chính thức | Dân số công bố theo địa bàn |
| `verified` | Đã kiểm tra thủ công, có người và bằng chứng | Văn bản xác nhận của cơ quan có thẩm quyền |
| `estimated` | Ước lượng từ mô hình/dữ liệu hợp lệ | Phân bố dân số theo ô nhỏ |
| `proxy` | Tín hiệu thay thế, chưa phải giá trị cần đo | Loại đường dùng thay cho lượng xe qua đường |
| `synthetic` | Dữ liệu mô phỏng phục vụ demo/test | Demand node hiện tại |
| `unknown` | Chưa có đủ thông tin | Chưa xác minh tình trạng giấy phép |

Mỗi bản ghi cần có ít nhất: `source_name`, `source_url hoặc mã hợp đồng`, `observed_at/published_at`, `ingested_at`, `last_verified_at`, `confidence` và người/hệ thống nhập.

---

## 4. Lớp dữ liệu nhu cầu: dân cư, điểm đến và luồng xe

### 4.1. Câu hỏi Planner phải trả lời

Planner không nên hỏi chung “khu này đông không?”. Nó phải trả lời lần lượt:

1. **Ai có thể cần sạc?** Cư dân, nhân viên, khách mua sắm, taxi/fleet, người đi liên tỉnh…
2. **Họ xuất hiện ở đâu và lúc nào?** Ban đêm ở chung cư, buổi sáng ở văn phòng, cuối tuần ở trung tâm thương mại, giờ cao điểm trên trục đường.
3. **Họ có thể tiếp cận vị trí này không?** Thời gian lái xe, lối vào/ra, quay đầu, bãi đỗ, giờ mở cửa.
4. **Họ đã có nơi sạc đủ tốt chưa?** Số vị trí sạc tương thích, độ tin cậy, giá/giờ hoạt động và khoảng cách.
5. **Bằng chứng thật là gì?** Số phiên/kWh/đơn bị bỏ hàng chờ từ trạm hoặc fleet, không chỉ là heatmap.

### 4.2. Mô hình dữ liệu theo ô không gian và thời gian

Không nên chỉ chấm theo phường. Một phường có thể vừa có chung cư dày đặc, vừa có khu công nghiệp hoặc đường vành đai. Nên chia vùng pilot thành các ô lưới thống nhất, chẳng hạn ô lục giác 250–500 m tùy mật độ khu vực, rồi tổng hợp theo khung giờ.

```text
demand_cell
  cell_id, polygon, resolution_m
  time_window_start, time_window_end, weekday_type
  resident_population
  daytime_activity_index
  vehicle_flow_count_or_proxy
  EV_propensity_estimate
  home_charging_deficit_estimate
  observed_sessions, observed_kwh, abandoned_requests
  source_quality, confidence, snapshot_version
```

**Tối thiểu cho công thức khoảng trống (mục 4.5):** mỗi ô cần `flow` (đo được hoặc proxy, kèm nhãn), `poi` (tổng hợp từ POI trong ô), `cung` (tính từ danh sách trạm) và `rent` nếu có. Các trường còn lại là lớp hiển thị, đối chiếu và nhãn kiểm chứng, chưa đi vào điểm.

**Lưu ý:** các trường `observed_sessions`, `observed_kwh` và `abandoned_requests` chỉ có khi đã có đối tác chia sẻ dữ liệu. Chúng là nhãn để kiểm chứng. Không được tự sinh ra rồi gọi là nhu cầu thị trường.

### 4.3. Dữ liệu cần thu và cách sử dụng

| Lớp dữ liệu | Trường tối thiểu | Nguồn khởi đầu phù hợp | Tần suất | Cách dùng | Giới hạn phải hiển thị |
|---|---|---|---|---|---|
| Dân cư | số dân, ngày tham chiếu, ranh giới/ô lưới | Tổng cục Thống kê; dữ liệu quy hoạch/công bố địa phương | Khi có công bố mới | Nền nhu cầu cư trú | Dữ liệu theo phường không cho biết chính xác từng tòa nhà |
| Phân bố dân cư ước lượng | số dân ước lượng/ô, độ phân giải, năm dữ liệu | WorldPop/GHSL hoặc nguồn có license phù hợp | Theo bản phát hành | Làm lớp chi tiết giữa các vùng thống kê | Là ước lượng, không phải số đo thực địa |
| Điểm đến và lưu trú | loại POI, giờ hoạt động, sức chứa/bãi đỗ nếu có | Bản đồ số TP.HCM, đối tác bất động sản, khảo sát | Định kỳ + khi khảo sát | Ước lượng hoạt động ban ngày và thời gian dừng | POI không chứng minh có nhu cầu sạc |
| Lưu lượng xe | đoạn đường, số xe, loại xe nếu có, khung giờ, phương pháp đếm | Cảm biến/camera/cơ quan giao thông; nhà cung cấp traffic theo hợp đồng | Giờ hoặc gần thời gian thực | Đo luồng xe và khả năng tiếp cận | Tốc độ ùn tắc/probe không tự động bằng tổng số xe |
| Di chuyển tổng hợp | số lượt đi giữa vùng, thời gian, phương pháp khử định danh | Fleet, nhà mạng hoặc ứng dụng di chuyển có thỏa thuận | Theo kỳ được phép | Nhìn dòng đi lại liên vùng | Chỉ nhận số liệu tổng hợp; không nhận hành trình cá nhân |
| Sạc thực tế | phiên sạc, kWh, thời gian chờ, lỗi, bỏ hàng chờ | CPO, fleet, điểm sạc của khách hàng | Liên tục/định kỳ | Đo nhu cầu và hiệu quả phục vụ thật | Cần kiểm tra quyền chia sẻ và độ đầy đủ |

Nguồn chính thức có thể dùng làm lớp dân số nền là [hệ thống dữ liệu không gian kinh tế–xã hội của Tổng cục Thống kê](https://giskinhtexahoi.gso.gov.vn/introduceNew/). Dữ liệu theo ô nhỏ như WorldPop chỉ nên được hiển thị là **ước lượng phân bố**, không phải con số dân cư xác nhận từng ô.

### 4.4. Lưu lượng “người hay đi qua đường” phải được định nghĩa đúng

Trước khi đi tìm dữ liệu, cần chốt mục tiêu là loại nào:

| Cần biết gì? | Dữ liệu đúng | Không nên thay bằng |
|---|---|---|
| Xe có thể ghé trạm | Số xe theo đoạn đường/khung giờ; luồng xe rẽ/tiếp cận | Số người đi bộ |
| Khách có thể ở lại đủ lâu | Bãi đỗ, loại điểm đến, thời gian lưu trú, giờ hoạt động | Chỉ số ùn tắc |
| Nhu cầu xe điện | Phiên sạc thật, dữ liệu fleet/EV có thỏa thuận, mô hình đã kiểm chứng | Tổng dân số hoặc tổng số xe |
| Khả năng hiển thị/dễ vào | Mặt tiền, hướng đường, lối vào/ra, khoảng quay đầu | Khoảng cách thẳng trên bản đồ |

Ở giai đoạn demo có thể dùng loại đường, nút giao, bãi đỗ và POI làm **proxy tiếp cận**. Nhưng chỉ khi có dữ liệu đếm xe theo giờ hoặc nguồn traffic đã được cấp quyền mới được ghi là “lưu lượng xe”. Repo hiện ghi rõ chưa có loại dữ liệu này; cần giữ đúng nhãn đó.

### 4.5. Cách tính điểm: công thức sàng lọc khoảng trống

Ở giai đoạn đầu, Planner dùng **score có giải thích**, không gọi là mô hình AI và không cần bài toán tối ưu. Công thức thống nhất với [kế hoạch tìm khoảng trống trạm sạc](ke-hoach-khoang-trong-tram-sac.md); mục tiêu là **sàng lọc danh sách địa điểm đi khảo sát**, không dự đoán doanh thu hay lợi nhuận.

Đơn vị tính là **ô lưới** $i$ (mục 4.2). Năm bước chạy lần lượt trên toàn vùng pilot:

**Bước 1 — Nhu cầu tiềm năng của ô $i$.** Chuẩn hóa từng chỉ số về thang 0–1 (min-max hoặc thứ hạng phần trăm), rồi cộng có trọng số:

$$D_i = w_1 \cdot \widetilde{\text{Flow}}_i + w_2 \cdot \widetilde{\text{POI}}_i, \qquad w_1 + w_2 = 1$$

| Đầu vào | Lấy từ | Ghi chú bắt buộc |
|---|---|---|
| $\text{Flow}_i$ | Lưu lượng xe theo ô; nếu chưa có thì cấp đường/mật độ đường làm proxy (mục 4.4) | Ghi rõ nhãn `measured` hay `proxy`; proxy không được gọi là số xe |
| $\text{POI}_i$ | POI trong ô: siêu thị, văn phòng, khách sạn, bãi đỗ... (nhóm chung cư/khu dân cư nếu kịch bản là sạc qua đêm) | POI không chứng minh có nhu cầu sạc |

- Bắt đầu với $w_1 = w_2 = 0{,}5$. Làm sạc nhanh dọc đường: tăng $w_1$. Làm sạc ở điểm đến (trung tâm thương mại, văn phòng): tăng $w_2$.
- Dân số cư trú, hoạt động ban ngày chi tiết và nhu cầu sạc quan sát được (mục 4.2) là **lớp hiển thị và đối chiếu**, chưa là số hạng của $D_i$. Chỉ đưa vào công thức khi đã có bằng chứng chúng cải thiện thứ hạng (mục 10).

**Bước 2 — Nguồn cung đã có quanh ô $i$.** Mỗi trạm đóng góp giảm dần theo khoảng cách:

$$\text{Cung}_i = \sum_{k} n_k \cdot e^{-d_{ik}/\lambda}$$

- $n_k$: số cổng (vị trí sạc) của trạm $k$, **gồm cả trạm của mình và đối thủ**.
- $d_{ik}$: khoảng cách từ ô $i$ đến trạm $k$.
- $\lambda$: bán kính ảnh hưởng, ví dụ 1 km trong nội đô, vài km ở vùng thưa.

**Bước 3 — Điểm khoảng trống.**

$$\text{Gap}_i = \frac{D_i}{1 + \text{Cung}_i}$$

Ô có nhu cầu cao mà nguồn cung quanh đó thấp sẽ có điểm cao.

**Bước 4 — Điều chỉnh theo chi phí đất (tùy chọn).** Chọn một trong hai cách:

- **Lọc:** loại các ô có giá thuê vượt ngưỡng chấp nhận.
- **Chia:** chuẩn hóa $\widetilde{\text{Rent}}_i$ về thang 0–1, rồi

$$\text{Điểm}_i = \frac{\text{Gap}_i}{\widetilde{\text{Rent}}_i + \varepsilon}$$

với $\varepsilon$ là hằng số nhỏ (ví dụ 0,1) để không chia cho 0. Nếu không dùng bước này thì $\text{Điểm}_i = \text{Gap}_i$.

**Bước 5 — Cờ ăn nhu cầu của chính mình.**

$$d_i^{\text{own}} = \min_{k \in J_{\text{own}}} d_{ik}$$

Nếu $d_i^{\text{own}}$ nhỏ hơn một ngưỡng (ví dụ 500 m đến 1 km) thì gắn cờ hoặc loại ô đó, vì trạm mới ở đó dễ lấy khách của trạm cũ.

**Quy tắc để công thức không đánh lừa người đọc**

- **Thiếu dữ liệu không phải điểm 0.** Ô chưa có giá thuê không được coi là $\widetilde{\text{Rent}}_i = 0$ (sẽ đẩy điểm lên cao nhất): bỏ qua Bước 4 cho ô đó và gắn nhãn `thiếu giá thuê`. Trạm chưa xác minh vẫn được cộng vào $\text{Cung}_i$ và gắn cờ `chưa xác minh`, không giả định là không tồn tại.
- **Lưu tham số mỗi lần chạy:** $w_1, w_2, \lambda$, ngưỡng giá thuê, ngưỡng $d^{\text{own}}$, $\varepsilon$, cách chuẩn hóa (và giá trị min/max dùng), phiên bản dữ liệu.
- **Sensitivity:** chạy lại với vài bộ $(w_1, w_2)$ và $\lambda$ (ví dụ $w_1 \in \{0{,}3;\,0{,}5;\,0{,}7\}$) và xem thứ hạng top 10–20 có đổi mạnh không; ô chỉ lọt top ở một bộ tham số cần được ghi là nhạy với giả định.
- Người dùng chọn kịch bản (**khu chung cư**, **trục liên tỉnh**, **trung tâm thương mại**), mỗi kịch bản là một bộ tham số có tên.

### 4.6. Kết quả trên giao diện

Người dùng bật/tắt độc lập các lớp:

- Cư dân cư trú.
- Hoạt động ban ngày/điểm đến.
- Lưu lượng xe: đo được hoặc proxy, với nhãn khác màu.
- Nguồn cung sạc hiện có theo thời gian lái xe.
- Nhu cầu chưa được phục vụ và vị trí ứng viên.

Khi bấm một ô hoặc một candidate, hệ thống hiển thị câu giải thích như:

> Nhu cầu tiềm năng cao vào 17:00–21:00 vì khu căn hộ đông và có bãi đỗ; lớp lưu lượng xe hiện là proxy từ loại đường/POI, chưa có bộ đếm xe. Vùng 10 phút lái xe chỉ còn 3 vị trí sạc CCS2 đã xác minh.

Đó là cách giúp người xem hiểu **vì sao** điểm cao và **điều gì chưa đủ chắc chắn**.

---

## 5. Nhãn mạng trạm: của doanh nghiệp, liên kết và mạng khác

### 5.1. Không dùng một cột `is_competitor`

`is_competitor = true` là thiết kế sai trong sản phẩm nhiều doanh nghiệp. Một trạm có thể:

- do doanh nghiệp A sở hữu;
- do doanh nghiệp B vận hành;
- là mạng roaming/liên kết mà A muốn điều hướng khách tới;
- là mạng khác từ góc nhìn của A, nhưng lại là mạng của chính B.

Do đó phải tách **đơn vị vận hành trạm** khỏi **mối quan hệ thương mại với doanh nghiệp đang đăng nhập**.

```text
organization
  └── station_network_relationship
        organization_id
        station_id hoặc operator_id
        relationship = OWNED | OPERATED | PARTNER | OTHER_NETWORK | UNVERIFIED
        evidence_source, verified_at, verified_by, confidence
```

### 5.2. Nhãn trên giao diện

| Bối cảnh | Nhãn khuyến nghị | Vì sao |
|---|---|---|
| Màn hình tài xế | Tên/thương hiệu nhà vận hành | Trung lập, không tạo cảm giác hệ thống thiên vị |
| Planner của một doanh nghiệp | **Mạng của bạn**, **Mạng liên kết**, **Mạng khác**, **Chưa xác minh** | Hữu ích cho phân tích đầu tư và độ phủ |
| Báo cáo nội bộ | Có thể diễn giải “đối thủ” nếu có bằng chứng và đúng phạm vi tổ chức | Tránh phân loại suy diễn hoặc công khai không cần thiết |

Nhãn không được suy luận chỉ từ tên, logo hoặc vị trí gần nhau. Nó cần nguồn và ngày xác minh. Khi không chắc, hiển thị `Chưa xác minh`.

### 5.3. Cạnh tranh được tính trong nguồn cung, tự cạnh tranh được tính bằng cờ riêng

Công thức khoảng trống (mục 4.5) xử lý hai việc khác nhau bằng hai cơ chế riêng:

| Câu hỏi | Cách tính | Vị trí trong công thức |
|---|---|---|
| Quanh ô này đã có bao nhiêu nguồn cung sạc, kể cả đối thủ? | Mọi trạm (của mình, liên kết, mạng khác, chưa xác minh) đều cộng vào $\text{Cung}_i = \sum_k n_k e^{-d_{ik}/\lambda}$; trạm xa thì đóng góp ít | Bước 2, làm giảm $\text{Gap}_i$ |
| Xây trạm mới ở đây có lấy khách của trạm mình đã có không? | Khoảng cách tới trạm gần nhất của mình $d_i^{\text{own}}$ so với ngưỡng, gắn cờ hoặc loại | Bước 5, không đi vào điểm |

Hệ quả:

- Nhãn quan hệ mạng (mục 5.1) quyết định trạm nào thuộc $J_{\text{own}}$ ở Bước 5. Trạm chưa có bằng chứng quan hệ **không** được đưa vào $J_{\text{own}}$; nó vẫn nằm trong $\text{Cung}_i$.
- Trạm đối thủ chỉ làm giảm điểm qua $\text{Cung}_i$, theo khoảng cách và số cổng; không có hệ số phạt riêng cho “đối thủ”.
- Một trạm cạnh tranh gần đó có thể là tín hiệu cung đã đủ, cũng có thể là dấu hiệu khu vực có cầu. Công thức không tách hai trường hợp này, nên báo cáo từng ứng viên phải liệt kê các trạm đóng góp lớn nhất vào $\text{Cung}_i$ để người khảo sát tự đánh giá.
- Bản đầu dùng $n_k$ là số cổng và $d_{ik}$ là khoảng cách địa lý. Nếu có dữ liệu thì tinh chỉnh sau (giai đoạn P3): chỉ đếm vị trí sạc tương thích, hiệu chỉnh theo công suất/giờ mở cửa/độ tin cậy, và dùng thời gian lái xe thay cho khoảng cách thẳng.

### 5.4. Dữ liệu tĩnh tối thiểu cho mọi trạm

```text
station
  station_id, operator_id, operator_name, brand_name
  latitude, longitude, address, public_access, opening_hours
  station_lifecycle: planned | active | temporarily_closed | retired
  source_type, source_ref, last_verified_at

station_network_relationship
  organization_id, station_id hoặc operator_id, relationship
  evidence_source, verified_at, verified_by, confidence
```

Thông tin giá, phí đỗ xe và chương trình đối tác chỉ lưu/hiển thị nếu nguồn cho phép sử dụng. Mỗi đối tác có thể có quyền xem khác nhau.

---

## 6. Trạng thái chi tiết từng vị trí/cổng sạc

### 6.1. Trạng thái cần hiển thị

Người dùng không cần nhìn payload kỹ thuật, nhưng cần biết cổng nào có thể dùng được và dữ liệu có đáng tin không.

| Trạng thái hiển thị | Ý nghĩa cho người dùng | Có tính là chỗ trống? |
|---|---|---|
| Sẵn sàng | Có thể bắt đầu phiên sạc | Có, nếu tương thích |
| Đang chuẩn bị/đang sạc/đang hoàn tất | Có xe hoặc phiên sạc đang diễn ra | Không |
| Đã đặt chỗ | Tạm dành cho xe khác | Không |
| Bị chặn | Chỗ đỗ/cổng không thể tiếp cận dù thiết bị không lỗi | Không |
| Tạm ngưng | Nhà vận hành khóa tạm thời | Không |
| Lỗi | Thiết bị báo lỗi | Không |
| Offline | Thiết bị/hệ thống mất kết nối theo quy tắc đối tác | Không |
| Không rõ/dữ liệu cũ | Không đủ bằng chứng để nói còn chỗ | Không |
| Sắp mở/đã gỡ bỏ | Trạng thái vòng đời, không phải trạng thái sạc tức thời | Không |

Các chuẩn như [OCPP](https://openchargealliance.org/protocols/ocpp-protocols/) và [OCPI](https://evroaming.org/ocpi/) có các trạng thái khác nhau. Hệ thống nên lưu **mã gốc** của đối tác và map sang nhóm hiển thị ở trên, thay vì làm mất chi tiết gốc.

### 6.2. Luật trung thực quan trọng nhất

Nếu nguồn chỉ nói “trạm có 2/6 cổng bận”, hệ thống chỉ được nói:

> Trạm đang có 4/6 vị trí không bận theo dữ liệu tổng, cập nhật lúc 14:10.

Hệ thống **không được bịa** “cổng A2 đang sạc” và “cổng B1 trống”. Chỉ khi nhận event theo từng EVSE/cổng mới được hiển thị cụ thể.

### 6.3. Dữ liệu tĩnh và dữ liệu động

```text
evse
  evse_id, station_id, physical_reference, parking_bay
  reservation_supported, capability, active

connector
  connector_id, evse_id, standard, format, power_type
  max_voltage, max_amperage, max_power_kw, active

port_status_event
  source_event_id, station_id, evse_id, connector_id
  raw_status, normalized_status
  event_occurred_at, received_at
  source_protocol, source_partner, source_priority
  payload_reference, confidence

port_status_current
  evse_id hoặc connector_id, normalized_status, status_since
  last_observed_at, stale_after, freshness_state, source_event_id
```

`event_occurred_at` và `received_at` phải lưu riêng. Một event có thể xảy ra lúc 09:00 nhưng hệ thống chỉ nhận lúc 09:08; nếu gộp hai thời điểm, mô hình và màn hình sẽ hiểu sai độ mới dữ liệu.

### 6.4. Nguồn dữ liệu và độ ưu tiên

```text
Trạm do doanh nghiệp vận hành
  → adapter OCPP hoặc API của hệ quản trị trạm
  → lưu event thô → chuẩn hóa → trạng thái hiện tại

Mạng liên kết/roaming
  → adapter OCPI hoặc API đã được cấp quyền
  → cùng pipeline, nhưng giữ tên nguồn và điều khoản dữ liệu

Mạng khác
  → catalog tĩnh được cấp quyền/xác minh thủ công trước
  → chỉ thêm trạng thái động khi có feed hợp lệ
```

OCPP không tự cho phép đọc dữ liệu của mọi mạng trạm; OCPI cũng cần quan hệ tích hợp/quyền truy cập. Đây là điều kiện đối tác, không giải quyết bằng code một mình.

Thứ tự ưu tiên khi hai nguồn mâu thuẫn có thể là: telemetry trực tiếp của nhà vận hành → feed liên kết có hợp đồng → nguồn được cấp quyền → xác minh thủ công → crowdsourced. Quy tắc này phải cấu hình được và lưu trong audit log.

### 6.5. Pipeline event cần có

```text
Nhà vận hành / đối tác
        │ event hoặc bản snapshot
        ▼
Adapter từng nguồn
        │ kiểm schema, xác thực, gắn nguồn
        ▼
Kho event thô bất biến
        │ chống trùng, sắp theo thời điểm, map trạng thái
        ▼
Lịch sử trạng thái + bảng trạng thái hiện tại
        │ kiểm dữ liệu cũ / chất lượng dữ liệu
        ▼
Driver Journey, Planner, dashboard vận hành, dữ liệu train
```

Yêu cầu kỹ thuật bắt buộc:

- Event có `source_event_id` hoặc hash để không ghi trùng khi gửi lại.
- Có hàng đợi/retry và khả năng replay event khi adapter lỗi.
- Không ghi đè lịch sử; bảng “hiện tại” là dữ liệu dẫn xuất từ event lịch sử.
- Mỗi đối tác có ngưỡng “dữ liệu cũ” riêng theo SLA.
- Có dashboard: tỷ lệ event trễ, tỷ lệ cổng `unknown`, thời gian mất kết nối, lỗi map trạng thái.

### 6.6. Ví dụ hiển thị dễ hiểu

```text
Mạng của bạn · 2/6 vị trí sạc tương thích sẵn sàng

- A1 · CCS2 · tối đa 120 kW · Sẵn sàng · cập nhật 42 giây trước
- A2 · CCS2 · tối đa 120 kW · Đang sạc · từ 14:08
- B1 · CCS2 · tối đa 60 kW  · Lỗi · đối tác báo lúc 13:52
- B2 · Type 2 · tối đa 22 kW · Không rõ · dữ liệu quá cũ
```

Người dùng phải thấy rõ cổng `Không rõ` **không** được tính là cổng trống.

---

## 7. Điều kiện pháp lý và dữ liệu cạnh tranh

> **Phạm vi:** Planner **không** đánh giá điều kiện đất (chủ mặt bằng, diện tích, chỗ đỗ, lối vào, thuê) và **không** đánh giá điện lưới (công suất cấp, đấu nối, viễn thông). Hai nhóm này không có trường dữ liệu, không có gate và không vào điểm. Điều kiện duy nhất được kiểm tra trước khi coi một ứng viên là đáng khảo sát là **pháp lý**. Riêng giá thuê vẫn có thể được dùng như một tham số tùy chọn của công thức (mục 4.5, Bước 4).

### 7.1. Hai lớp: có khoảng trống nguồn cung và không vướng pháp lý

Một điểm chỉ “đáng khảo sát” nếu qua cả hai lớp:

```text
Có nhu cầu / còn khoảng trống nguồn cung (Gap_i cao)
                    VÀ
Không có bằng chứng vướng điều kiện pháp lý
```

Điều kiện pháp lý cụ thể phải được xác minh theo quy định địa phương và đối tác tại Việt Nam; tài liệu này không phải tư vấn pháp lý.

### 7.2. Hồ sơ pháp lý của ứng viên

| Nhóm | Câu hỏi cần trả lời | Bằng chứng |
|---|---|---|
| Quy hoạch và mục đích sử dụng | Vị trí có được phép dùng cho hoạt động trạm sạc theo quy hoạch/mục đích sử dụng hiện hành không? | Văn bản/ý kiến cơ quan có thẩm quyền, tra cứu quy hoạch |
| Giấy phép xây dựng và lắp đặt | Có cần giấy phép hoặc thủ tục nào trước khi thi công, và có rào cản nào không? | Hướng dẫn của cơ quan, hồ sơ nộp, kết quả |
| An toàn phòng cháy chữa cháy | Có yêu cầu thẩm duyệt/nghiệm thu nào áp dụng không? | Văn bản thẩm duyệt, biên bản |
| Đăng ký kinh doanh và điều kiện hoạt động | Doanh nghiệp có đủ điều kiện kinh doanh dịch vụ sạc tại vị trí này không? | Giấy đăng ký, ngành nghề, giấy phép con nếu có |
| Bảo vệ dữ liệu | Việc thu và dùng dữ liệu trạm/người dùng có tuân thủ quy định không? | Hợp đồng dữ liệu, đánh giá nội bộ (xem mục 12.3) |

```text
candidate_legal_assessment
  candidate_id
  zoning_status, permit_status, fire_safety_status
  business_license_status, data_compliance_status
  gate_status, blocking_reason
  evidence_id, verified_at, verified_by
```

Mỗi trường nhận một trong các trạng thái ở mục 7.3; trường chưa kiểm tra là `unknown`, không phải “đạt”. Hồ sơ pháp lý và văn bản đính kèm giới hạn quyền xem, không đưa lên bản đồ công khai.

### 7.3. Gate pháp lý trước khi đưa vào danh sách ứng viên

| Kết quả gate | Khi nào dùng | Xử lý trong Planner |
|---|---|---|
| `blocked` | Đã có bằng chứng bị cấm hoặc không thể xin phép/hoạt động hợp pháp tại vị trí | Loại khỏi danh sách ứng viên; nêu lý do loại. Gate không là số hạng trong điểm $\text{Gap}_i$ |
| `conditional` | Có tín hiệu tốt nhưng còn một hay nhiều thủ tục pháp lý phải xác minh | Có thể ưu tiên **khảo sát**, không gọi là “nên xây” |
| `ready_for_next_stage` | Bằng chứng pháp lý tối thiểu đã đủ cho bước phân tích sâu | Giữ trong danh sách ứng viên, đủ điều kiện sang bước phân tích sâu |
| `unknown` | Chưa có bằng chứng | Không ẩn đi; hiển thị việc cần làm và độ bất định |

Ví dụ: ứng viên có `Gap` cao nhưng `zoning_status = unknown` và `permit_status = unknown` phải cho kết quả “ưu tiên thu thập bằng chứng pháp lý”, không phải “top 1 để xây ngay”.

### 7.4. Dữ liệu cạnh tranh trong hồ sơ ứng viên

Khi nhìn quanh candidate, Planner cần hiển thị:

- Các trạm đóng góp lớn nhất vào $\text{Cung}_i$ (mục 4.5), cùng khoảng cách tới trạm gần nhất của mình và của đối thủ.
- Khi có dữ liệu (giai đoạn P3): vị trí sạc **tương thích** trong 5/10/15 phút lái xe, không chỉ bán kính thẳng.
- Công suất và loại đầu cắm có thể phục vụ nhóm xe mục tiêu.
- Giờ hoạt động, quyền truy cập, phí đỗ/giá sạc nếu có quyền dùng dữ liệu.
- Tình trạng sẵn sàng/lỗi lịch sử nếu có feed hợp lệ.
- Vùng phục vụ chồng lấn với trạm của doanh nghiệp để thấy nguy cơ tự cạnh tranh.
- Những trạm còn là `unknown` thay vì giả vờ là không tồn tại.

Không thu thập bằng cách vượt cơ chế bảo vệ, truy cập trái phép hay sao chép dữ liệu không được cấp quyền. Với dữ liệu mạng khác, bước an toàn là catalog tĩnh có nguồn trước; dữ liệu thời gian thực chỉ có khi được chia sẻ hợp pháp.

---

## 8. Cách Planner ra quyết định sau khi mở rộng

### 8.1. Luồng quyết định đề xuất

Điểm xếp hạng chỉ đến từ công thức khoảng trống ở mục 4.5. Điều kiện cứng, bằng chứng và rủi ro đi **kèm** kết quả, không bị trộn vào một con số.

```text
Nguồn dữ liệu có version, độ mới và bằng chứng
                    │
                    ▼
1. Tính nhu cầu D_i từng ô (Flow + POI, chuẩn hóa 0–1)
                    │
                    ▼
2. Tính nguồn cung Cung_i (mọi trạm, giảm theo khoảng cách)
   → Gap_i = D_i / (1 + Cung_i)
                    │
                    ▼
3. Điều chỉnh chi phí đất (lọc theo ngưỡng giá thuê, hoặc chia cho Rent + ε)
                    │
                    ▼
4. Cờ ăn nhu cầu của mình: d_own < ngưỡng → gắn cờ hoặc loại
                    │
                    ▼
5. Xếp hạng ô, gộp ô liền kề thành cụm, lấy 10–20 ứng viên khảo sát
                    │
                    ▼
6. Gắn cho từng ứng viên: gate pháp lý (blocked → loại,
   conditional/unknown → vẫn giữ nhưng nêu việc cần làm), bằng chứng thiếu,
   bước tiếp theo
```

### 8.2. Các thành phần: cái nào nằm trong điểm, cái nào đi kèm

| Thành phần | Có trong điểm? | Cách dùng |
|---|---|---|
| Nhu cầu tiềm năng $D_i$ | Có | $w_1 \widetilde{\text{Flow}}_i + w_2 \widetilde{\text{POI}}_i$ |
| Nguồn cung quanh ô $\text{Cung}_i$ | Có | $\sum_k n_k e^{-d_{ik}/\lambda}$, gồm trạm của mình và đối thủ |
| Chi phí đất | Tùy chọn | Lọc theo ngưỡng, hoặc chia $\text{Gap}_i / (\widetilde{\text{Rent}}_i + \varepsilon)$ |
| Ăn nhu cầu của mình | Không, là cờ/lọc | $d_i^{\text{own}}$ nhỏ hơn ngưỡng thì gắn cờ hoặc loại |
| Pháp lý (quy hoạch, giấy phép, PCCC, điều kiện kinh doanh) | Không, là gate | `blocked` loại; `conditional`/`unknown` giữ lại kèm việc cần xác minh |
| Giá trị chiến lược, rủi ro, chất lượng dữ liệu | Không, là thông tin đi kèm | Hiển thị bên cạnh điểm, kèm nhãn độ tin cậy |

Công thức tổng hợp (xem mục 4.5):

$$\text{Gap}_i = \frac{D_i}{1 + \text{Cung}_i}, \qquad \text{Điểm}_i = \frac{\text{Gap}_i}{\widetilde{\text{Rent}}_i + \varepsilon} \ \text{(nếu dùng bước chia)}$$

Đây là khung diễn giải, không phải “AI tự quyết”. $w_1, w_2, \lambda$ và các ngưỡng thuộc về kịch bản và người chịu trách nhiệm ra quyết định; mỗi kết quả ghi lại chúng (và chạy sensitivity) để người xem không tưởng rằng thứ hạng là khách quan tuyệt đối. Nếu sau này muốn thêm thành phần vào điểm (chiến lược, rủi ro), phải chứng minh nó cải thiện kết quả trên dữ liệu thật và ghi thành thay đổi công thức có version, không cộng thêm âm thầm.

### 8.3. Đầu ra và cách hiển thị bất định

Đầu ra của mỗi lần chạy:

1. **Heatmap điểm khoảng trống** để nhìn tổng quan.
2. **Danh sách 10–20 ô điểm cao nhất** làm ứng viên khảo sát. Gộp các ô liền kề thành một cụm (hoặc chọn các ô cách nhau tối thiểu 1 km) để không đi khảo sát cùng một chỗ nhiều lần.
3. **Kèm mỗi ứng viên:** nhu cầu $D_i$, nguồn cung $\text{Cung}_i$ (và các trạm đóng góp lớn nhất), khoảng cách tới trạm gần nhất của mình và của đối thủ, giá thuê tham khảo, cờ ăn nhu cầu, nhãn chất lượng dữ liệu đầu vào.

Khi bằng chứng còn thiếu, kết quả vẫn trả về nhưng nói rõ là ưu tiên **khảo sát**, không phải quyết định xây:

```text
Ưu tiên khảo sát: Cao (không phải quyết định xây)

Điểm
- Nhu cầu D = 0,81 (Flow proxy 0,74; POI 0,88)
- Nguồn cung quanh ô = 0,6 cổng quy đổi → Gap = 0,51
- Trạm của mình gần nhất: 2,3 km (không bị cờ ăn nhu cầu)

Điều chưa xác minh
- Quy hoạch/mục đích sử dụng chưa xác nhận.
- Giấy phép xây dựng và PCCC chưa kiểm tra.
- Flow hiện là proxy từ cấp đường, chưa có đếm xe theo giờ.
- Giá thuê: chưa có (không áp dụng bước điều chỉnh chi phí).

Bước tiếp theo
1. Tra cứu quy hoạch và mục đích sử dụng tại vị trí.
2. Hỏi cơ quan có thẩm quyền về giấy phép xây dựng, PCCC.
3. Kiểm tra điều kiện kinh doanh dịch vụ sạc.
```

Từ đó, “top 1” là **top 1 để khảo sát trước**, một tuyên bố hợp lý hơn nhiều so với “đây là điểm nên xây ngay”.

### 8.4. Phạm vi: sàng lọc, chưa tối ưu danh mục

Công thức ở đây chọn từng ô/cụm độc lập rồi gộp thành danh sách khảo sát. Nó **không** giải bài toán chọn tập vị trí, loại sạc và số vị trí sạc dưới ràng buộc ngân sách và độ phủ; hai ứng viên cạnh nhau không tự làm giảm điểm của nhau ngoài cách gộp cụm và khoảng cách tối thiểu 1 km. Tối ưu danh mục là bước sau (P5), chỉ nên mở khi dữ liệu pháp lý và chi phí đã được xác minh, không phải khi đầu vào vẫn synthetic.

---

## 9. Kiến trúc dữ liệu, API và giao diện cần xây

### 9.1. Kiến trúc mục tiêu

```text
Nguồn dân cư / POI / traffic / khảo sát / CPO / đối tác
                         │
                         ▼
              Adapter và kiểm tra dữ liệu
       (quyền truy cập, schema, nguồn, thời điểm)
                         │
        ┌────────────────┼─────────────────┐
        ▼                ▼                 ▼
  Kho event thô    Kho dữ liệu không gian  Kho bằng chứng khảo sát
        │                │                 │
        └──────────┬─────┴───────┬─────────┘
                   ▼             ▼
      Feature theo ô/thời gian   Trạng thái EVSE/cổng hiện tại
                   │             │
                   └──────┬──────┘
                          ▼
         Snapshot Planner có version + engine chấm điểm
                          │
                          ▼
    Bản đồ / báo cáo / API / audit log / danh sách việc khảo sát
```

Snapshot file hiện tại vẫn hữu ích cho demo và tái lập. Khi pilot thật, nguồn runtime nên là database có version; mỗi lần chạy Planner đóng băng một snapshot logic để báo cáo có thể tái tạo về sau.

### 9.2. Các bảng/đối tượng nên bổ sung

Tên bảng là đề xuất, chưa phải migration đã thực hiện.

| Nhóm | Bảng/đối tượng gợi ý | Vai trò |
|---|---|---|
| Tổ chức/mạng | `organizations`, `station_operators`, `station_network_relationships` | Biết ai là ai từ góc nhìn từng doanh nghiệp |
| Catalog trạm | `stations`, `evses`, `connectors` | Mô hình đúng Station → EVSE → Connector |
| Trạng thái | `port_status_events`, `port_status_current`, `data_source_health` | Lưu lịch sử, trạng thái hiện tại và độ mới dữ liệu |
| Không gian nhu cầu | `demand_cells`, `traffic_segments`, `poi_activity_profiles`, `charging_demand_observations` | Tách tín hiệu nhu cầu theo nơi/thời gian |
| Candidate/pháp lý | `planning_candidates`, `candidate_legal_assessments`, `site_evidence` | Lưu site, hồ sơ pháp lý và bằng chứng riêng khỏi catalog trạm |
| Chạy Planner | `planning_snapshots`, `planning_runs`, `planning_score_components`, `planning_actions` | Tái lập kết quả, giải thích điểm và giao việc khảo sát |

### 9.3. Hợp đồng API gợi ý

Các API thay đổi phải giữ rõ phạm vi public, partner và nội bộ.

| API gợi ý | Người dùng | Mục đích |
|---|---|---|
| `GET /api/v1/planning/stations` | Planner được phân quyền | Lấy trạm với nhãn quan hệ mạng, nguồn và độ mới |
| `GET /api/v1/planning/stations/{id}/ports` | Planner/driver theo quyền | Trả EVSE/cổng, trạng thái, nguồn, thời điểm và cờ `inferred` |
| `POST /api/v1/integrations/{source}/events` | Adapter nội bộ/đối tác | Nhận event trạng thái, xác thực, chống trùng |
| `POST /api/v1/planning/candidates/{id}/evidence` | Người khảo sát có quyền | Đính kèm văn bản pháp lý, biên bản và ngày xác minh |
| `POST /api/v1/planning/runs` | Planner | Chạy theo snapshot/version/kịch bản rõ ràng |
| `GET /api/v1/planning/runs/{id}/report` | Planner/decision maker | Báo cáo lý do, điều kiện còn thiếu và cấu hình đã dùng |

Phản hồi trạng thái cổng cần có “envelope” thay vì chỉ trả danh sách:

```json
{
  "stationId": "...",
  "coverage": "per_evse",
  "source": "partner_ocpi",
  "lastObservedAt": "2026-10-17T14:10:00Z",
  "freshness": "fresh",
  "ports": [
    {"evseId": "A1", "status": "available", "isInferred": false}
  ]
}
```

Nếu `coverage = aggregate_station`, API không nên trả danh sách `ports` giả tạo; chỉ trả số đếm tổng và nhãn `isInferred`.

### 9.4. Thay đổi giao diện Planner

#### Bản đồ

- Marker/layer riêng: **Mạng của bạn**, **Mạng liên kết**, **Mạng khác**, **Chưa xác minh**, candidate và khu vực nhu cầu.
- Layer nhu cầu tách: cư dân, hoạt động ban ngày, traffic đo được, traffic proxy, nguồn cung quanh ô ($\text{Cung}_i$), điểm khoảng trống ($\text{Gap}_i$).
- Chú giải bắt buộc có ngày dữ liệu và nhãn `measured/estimated/proxy/synthetic`.
- Bộ lọc theo loại đầu cắm, công suất, giờ mở cửa, quan hệ mạng, độ mới dữ liệu.
- Không để màu của “trạm đối thủ” gợi ý rằng trạm đó kém chất lượng hoặc không nên dùng.

#### Panel chi tiết trạm

- Tên nhà vận hành, nhãn quan hệ từ góc nhìn doanh nghiệp, nguồn và ngày xác minh.
- Danh sách EVSE/cổng với công suất, trạng thái, thời điểm cập nhật và tình trạng dữ liệu cũ.
- `Tổng từ occupancy` và `Chi tiết từng cổng` là hai kiểu dữ liệu khác nhau, cần hiện nhãn rõ.

#### Panel chi tiết candidate

Năm tab nên có:

1. **Nhu cầu:** cư dân, điểm đến, luồng xe, khung giờ, bằng chứng quan sát.
2. **Nguồn cung/cạnh tranh:** trạm tương thích theo thời gian lái xe, công suất và độ tin cậy.
3. **Pháp lý:** quy hoạch, giấy phép, PCCC, điều kiện kinh doanh, trạng thái gate.
4. **Bằng chứng:** nguồn, ảnh/tài liệu, người xác minh, ngày xác minh.
5. **Việc tiếp theo:** các kiểm tra cần hoàn thành trước khi nâng trạng thái candidate.

### 9.5. Phân quyền và audit

| Vai trò | Có thể làm gì |
|---|---|
| Người xem | Xem lớp công khai/được cấp quyền, không thấy giá thuê hoặc hồ sơ pháp lý nội bộ |
| Analyst Planner | Tạo run, xem evidence đã được phép, so sánh scenario |
| Người khảo sát | Thêm ảnh/biên bản, không tự xác nhận kết luận pháp lý hoặc sửa trọng số chính sách |
| Quản lý đầu tư | Duyệt evidence, thay đổi scenario được kiểm soát, xuất báo cáo |
| Quản trị đối tác | Thiết lập adapter, quyền nguồn, SLA, mapping trạng thái |

Mọi thao tác quan trọng cần audit: ai nhập/chỉnh/sửa/xóa bằng chứng, khi nào, thay đổi gì; run nào dùng phiên bản dữ liệu nào; ai đã xuất báo cáo.

---

## 10. Hướng phát triển mô hình dự báo nhu cầu

### 10.1. Không nhảy thẳng sang mô hình sâu

XGBoost hiện trong repo là baseline cho **occupancy ngắn hạn của trạm**, không phải mô hình demand Planner đã được đưa vào runtime. Dữ liệu dân cư/traffic mới không tự động làm Planner có “AI dự báo nhu cầu”.

Muốn huấn luyện mô hình nhu cầu, phải có nhãn thực tế, chẳng hạn:

```text
số phiên sạc / kWh / thời gian chờ / số yêu cầu bị bỏ
theo ô không gian × khung giờ × loại sạc
```

### 10.2. Thứ tự kỹ thuật phù hợp

| Giai đoạn | Cách làm | Giá trị | Điều kiện vào giai đoạn |
|---|---|---|---|
| 1. Score có giải thích | Dùng dữ liệu và trọng số kịch bản; không gọi là ML | Có Planner minh bạch ngay | Dữ liệu nguồn và nhãn chất lượng rõ |
| 2. Baseline thống kê | So sánh với “cùng giờ/cùng ngày tuần trước” hoặc trung bình lịch sử | Biết bài toán có dự báo được không | Có dữ liệu sessions/kWh đủ liên tục |
| 3. Mô hình bảng | XGBoost/LightGBM hoặc mô hình count với dân cư, POI, traffic, cung hiện hữu, thời gian | Baseline mạnh, dễ diễn giải | Có nhãn thật và split theo thời gian/khu vực |
| 4. Bất định và calibration | Trả khoảng dự báo, không chỉ một điểm | Planner biết khi nào không nên tin quá mức | Đánh giá ổn định qua nhiều kỳ |
| 5. Mô hình không-thời gian sâu | LSTM/GRU, Temporal Fusion Transformer hoặc graph model cho mạng trạm | Chỉ dùng nếu benchmark chứng minh hơn baseline | Nhiều lịch sử, nhiều trạm/ô và sự phụ thuộc không gian rõ |

Mô hình sâu không mặc định tốt hơn. Nếu dữ liệu ít, lệch hoặc nhiều missing values, mô hình bảng được kiểm chứng thường là lựa chọn an toàn hơn.

### 10.3. Quy tắc đánh giá model

- Train ở quá khứ, test ở tương lai; không xáo trộn ngẫu nhiên làm lộ dữ liệu tương lai.
- Có test theo khu vực/điểm mới để tránh model chỉ nhớ vị trí cũ.
- Báo cáo MAE/WAPE cho lượng phiên/kWh, sai số ở giờ cao điểm và sai số vùng xa trung tâm.
- So sánh với baseline đơn giản, không chỉ báo số đẹp của model mới.
- Kiểm tra feature leakage: không dùng trạng thái/công suất chỉ biết sau thời điểm dự báo.
- Chỉ đưa feature vào trọng số quyết định chính sau khi chứng minh đóng góp trên dữ liệu chưa thấy.

### 10.4. Cách dữ liệu mới hỗ trợ các phần hiện có

| Dữ liệu mới | Hỗ trợ Planner | Hỗ trợ Driver Journey |
|---|---|---|
| EVSE/cổng và status thật | Biết nguồn cung thực, độ tin cậy và chỗ thiếu | Gợi ý trạm ít rủi ro, dự báo chờ tốt hơn |
| Quan hệ mạng | Tính tự cạnh tranh, partnership và độ phủ | Có thể điều hướng đúng theo thỏa thuận đối tác |
| Dân cư/điểm đến/traffic | Đặt candidate ở vùng có khả năng có cầu | Sau này làm feature bối cảnh cho demand/occupancy |
| Pháp lý và chi phí | Biến ranking thành shortlist có thể làm | Không trực tiếp ảnh hưởng luồng tài xế, nhưng giúp mạng trạm tốt hơn |

---

## 11. Lộ trình thực hiện và tiêu chí hoàn thành

### Giai đoạn P0 — Làm dữ liệu minh bạch trước

**Việc cần làm**

- Chuẩn hóa nhãn `measured/official/verified/estimated/proxy/synthetic/unknown`.
- Bổ sung `source`, `observed_at`, `verified_at`, `confidence` vào dữ liệu Planner và report.
- Dán nhãn rõ population/traffic/demand hiện tại là gì trong UI và Markdown export.
- Chuẩn hóa entity Station → EVSE → Connector trên schema, không cần telemetry thật ngay.
- Thêm quan hệ mạng theo tổ chức, bắt đầu từ dữ liệu tĩnh được xác minh.

**Hoàn thành khi**

- Người xem không thể nhầm traffic proxy là số xe đo được.
- Mỗi candidate top có danh sách bằng chứng thiếu.
- Không còn dùng nhãn toàn cục `is_competitor`.

### Giai đoạn P1 — Catalog trạm và chi tiết cổng

**Việc cần làm**

- Import template cho catalog trạm: operator, thương hiệu, vị trí, công suất, EVSE, connector, giờ mở cửa, nguồn.
- Hiển thị “Mạng của bạn / liên kết / mạng khác / chưa xác minh” theo tổ chức đăng nhập.
- Thêm UI list EVSE/cổng; phân biệt aggregate với per-port.
- Bổ sung event store, deduplication, mapping trạng thái và quy tắc `stale`.
- Viết test cho event đến trễ, event trùng, trạng thái nguồn mâu thuẫn và cổng không tương thích.

**Hoàn thành khi**

- Một station có thể hiển thị chính xác năng lực theo EVSE/connector.
- Không có cổng giả được sinh ra từ aggregate occupancy.
- Mỗi trạng thái có nguồn, thời điểm và độ mới.

### Giai đoạn P2 — Pilot telemetry một CPO/mạng trạm

**Việc cần làm**

- Chọn một đối tác vận hành trạm và ký thỏa thuận dữ liệu tối thiểu.
- Làm adapter OCPP/API thực, lưu raw event, retry/replay và dashboard chất lượng dữ liệu.
- Xác định SLA độ mới, event mapping và quy trình xử lý lỗi cùng đối tác.
- Ghi nhận phiên sạc/kWh/queue ở mức đã được phép để tạo nhãn đánh giá.

**Hoàn thành khi**

- Có một khoảng lịch sử telemetry thật được đối soát với đối tác.
- Dashboard cho biết tỷ lệ data stale/offline và không âm thầm coi cổng `unknown` là available.
- Driver Journey và Planner dùng chung catalog/trạng thái đã chuẩn hóa, nhưng quyền xem phù hợp khác nhau.

### Giai đoạn P3 — Nhu cầu theo không gian và thời gian

**Việc cần làm**

- Tạo ô lưới cho pilot và pipeline population, POI/activity, road accessibility, traffic measured/proxy.
- Ký thỏa thuận hoặc lấy nguồn hợp lệ cho traffic theo giờ; nếu chưa có, giữ proxy riêng.
- Tính vùng phục vụ theo thời gian lái xe thay vì chỉ bán kính thẳng.
- Bổ sung metrics: unmet demand, effective compatible supply, own-network overlap.
- Chạy backtest: các feature mới giải thích/predict sessions hoặc kWh tốt hơn baseline không?

**Hoàn thành khi**

- Bản đồ demand phân biệt cư dân, hoạt động ban ngày, traffic đo/proxy và nhu cầu sạc thật.
- Không có slide/report nào gọi proxy là lưu lượng xe thực.
- Có báo cáo sai số hoặc giới hạn rõ ràng cho bất kỳ demand forecast nào.

### Giai đoạn P4 — Xác minh pháp lý và quyết định khảo sát

**Việc cần làm**

- Xây workflow candidate → khảo sát → evidence → review → gate status.
- Thêm hồ sơ pháp lý: quy hoạch/mục đích sử dụng, giấy phép xây dựng, PCCC, điều kiện kinh doanh.
- Giới hạn quyền xem hồ sơ pháp lý nội bộ và giá thuê.
- Cho phép Planner trả “ưu tiên khảo sát” và `blocked/conditional/ready_for_next_stage`.
- Thêm kịch bản trọng số, sensitivity analysis và xuất báo cáo có snapshot.

**Hoàn thành khi**

- Không có candidate `unknown` về pháp lý được trình bày như build-ready.
- Tất cả quyết định cao nhất có evidence + người xác minh + việc tiếp theo.
- Report tái tạo được từ version dữ liệu và cấu hình đã lưu.

### Giai đoạn P5 — Tối ưu danh mục và model demand đã kiểm chứng

**Việc cần làm**

- Benchmark model demand với baseline và dữ liệu thật.
- Thêm khoảng bất định vào ranking và policy “không tự động quyết định khi confidence thấp”.
- Mở rộng ngoài công thức sàng lọc (mục 8.4): tối ưu nhiều candidate/cấu hình theo ngân sách, độ phủ, tiến độ và tự cạnh tranh.
- Đo sau đầu tư: utilization, session, kWh, wait time, abandonment, payback theo dữ liệu được phép.

**Hoàn thành khi**

- Có closed loop: dự báo → lựa chọn site → vận hành → kết quả thật → cập nhật model/giả định.
- Portfolio không chỉ chọn các điểm điểm cao độc lập mà cân bằng mạng lưới và ngân sách.

### Phụ thuộc giữa các giai đoạn

```text
P0 minh bạch dữ liệu
  → P1 catalog + mô hình EVSE/cổng
    → P2 telemetry thật
      → P3 demand theo thời gian/khu vực có nhãn thật
        → P4 pháp lý có evidence
          → P5 model demand + tối ưu portfolio
```

P4 có thể bắt đầu xác minh pháp lý song song với P2/P3, nhưng không nên tuyên bố thuật toán đã xác định site xây cuối cùng trước khi hai luồng bằng chứng đủ.

---

## 12. Kiểm thử, đo hiệu quả và quản trị dữ liệu

### 12.1. Kịch bản kiểm thử bắt buộc

| Kịch bản | Kết quả đúng cần thấy |
|---|---|
| Trạm chỉ có occupancy tổng | UI nói tổng số chỗ theo aggregate; không gán status cho từng EVSE |
| Event trạng thái đến trễ | Trạng thái hiện tại không bị event cũ ghi đè; lịch sử vẫn lưu event để audit |
| Dữ liệu đối tác quá cũ | Cổng thành `unknown/stale`, không tính là available |
| Trạm đối thủ gần nhưng ít công suất/tắt ban đêm | Không bị coi là nguồn cung tương đương trạm phù hợp |
| Nhiều trạm cùng thương hiệu | Không suy ra quan hệ “của mình” nếu chưa có evidence theo tổ chức |
| Vị trí demand cao nhưng chưa xác minh pháp lý | Không xếp là build-ready; ưu tiên thu thập bằng chứng pháp lý hoặc `blocked` đúng evidence |
| Traffic chỉ là loại đường | Bản đồ/report hiện nhãn proxy, không hiển thị số xe tưởng tượng |
| Thay đổi trọng số kịch bản | Report giữ cả hai kết quả và lý do thứ hạng thay đổi |

### 12.2. Chỉ số nên theo dõi

| Nhóm | Chỉ số |
|---|---|
| Chất lượng nguồn trạng thái | tỷ lệ event trễ, tỷ lệ `unknown`, độ trễ p50/p95, tỷ lệ map lỗi, uptime adapter |
| Catalog/mạng | tỷ lệ trạm có operator/relationship đã xác minh, tỷ lệ EVSE/connector đầy đủ |
| Nhu cầu | coverage ô lưới, tỷ lệ measured vs proxy, sai số sessions/kWh so với thực tế, lỗi giờ cao điểm |
| Candidate | tỷ lệ site có pháp lý đã xác minh, thời gian từ candidate đến quyết định, nguyên nhân loại phổ biến |
| Giá trị vận hành | utilization, queue/wait, abandonment, session, kWh, khả năng tiếp cận, tự cạnh tranh |

### 12.3. Quyền riêng tư và pháp lý

- Chỉ dùng lưu lượng/di chuyển ở mức **tổng hợp theo ô và khung giờ** cho Planner.
- Không lưu GPS thô, lịch sử cá nhân, biển số hay mã thanh toán trong bảng không gian dùng chung.
- Tách bảng định danh/giao dịch khỏi bảng feature phân tích; kiểm soát quyền truy cập và thời hạn lưu.
- Đặt ngưỡng tối thiểu số quan sát trước khi xuất heatmap để không suy ra hành vi một cá nhân.
- Có hợp đồng, mục đích sử dụng, quyền truy cập và quy trình xoá/lưu dữ liệu rõ trước khi nhận dữ liệu CPO, fleet, nhà mạng hoặc nhà cung cấp traffic.
- Rà soát quy định Việt Nam và hợp đồng cụ thể với tư vấn pháp lý/đối tác trước pilot; tài liệu này không phải tư vấn pháp lý.

### 12.4. Quản trị mô hình và scoring

- Không cho model/trọng số mới chạy production nếu không vượt baseline bằng chỉ số đã chốt.
- Lưu version feature, model, snapshot và metric đi kèm mỗi run.
- Có rollback về model/trọng số trước nếu chất lượng giảm.
- Audit mọi thay đổi trọng số và override thủ công của chuyên gia.
- Không dùng score để tự động phê duyệt đầu tư lớn; quyết định cuối cần người chịu trách nhiệm và evidence ngoài hệ thống.

---

## 13. Cách trình bày lại với ban giám khảo

### Thông điệp 30 giây

> Chúng em tiếp nhận góp ý rằng Planner cần nhìn cả nhu cầu, cạnh tranh và khả năng xây thật. Thiết kế mới vì vậy không chỉ thêm heatmap: nó tách dân cư, luồng xe và nhu cầu sạc; phân biệt mạng của doanh nghiệp với mạng khác theo từng khách hàng; đọc trạng thái từng vị trí sạc khi có nguồn xác thực; và bắt buộc kiểm tra pháp lý trước khi gọi một site là khả thi. Kết quả không nói “AI bảo xây ở đây”, mà nói “đây là điểm nên khảo sát trước, dựa trên các bằng chứng này, và còn thiếu các xác minh này”.

### Minh họa demo nên chuẩn bị

1. **Bật/tắt bốn lớp nhu cầu:** dân cư, điểm đến, traffic proxy/đo được, nhu cầu chưa được phục vụ.
2. **So sánh hai candidate:** một nơi đông dân nhưng bị `blocked` về pháp lý; một nơi demand thấp hơn chút nhưng pháp lý đã xác minh. Để người xem thấy tại sao không chỉ chọn heatmap nóng nhất.
3. **Phân biệt 3 nguồn cung:** mạng của bạn, mạng liên kết và mạng khác; hiển thị công suất/giờ mở cửa/độ mới, không chỉ marker.
4. **Mở chi tiết cổng:** cho thấy sẵn sàng, đang sạc, lỗi, dữ liệu cũ; demo aggregate và per-port khác nhau ra sao.
5. **Báo cáo top candidate:** lý do điểm cao, evidence source, mức bất định và checklist khảo sát tiếp theo.

### Những điều không nên hứa quá mức

- Không nói đã có traffic thời gian thực nếu mới dùng loại đường hoặc POI proxy.
- Không nói có trạng thái trực tiếp của trạm đối thủ khi chưa có feed/đối tác hợp lệ.
- Không nói Planner tự quyết định đầu tư cuối cùng.
- Không nói mô hình ML chứng minh demand nếu chưa đánh giá trên session/kWh thật.

---

## 14. Nguồn tham khảo

- [Alternative Fuels Data Center — Electric Vehicle Site Selection](https://afdc.energy.gov/files/u/publication/ev-site-selection.pdf?5aa9a81db5=): khung tham khảo chung về chọn vị trí sạc; Planner chỉ dùng phần liên quan đến nhu cầu, cạnh tranh và pháp lý.
- [Alternative Fuels Data Center — EV Readiness](https://afdc.energy.gov/fuels/electricity-ev-readiness): các yếu tố chuẩn bị hạ tầng sạc, gồm dân số, hành vi đi lại, loại hình nhà ở, hành lang giao thông và khả năng cấp điện.
- [Open Charge Alliance — OCPP](https://openchargealliance.org/protocols/ocpp-protocols/): chuẩn giao tiếp giữa thiết bị sạc và hệ quản trị trạm.
- [EVRoaming Foundation — OCPI](https://evroaming.org/ocpi/): chuẩn trao đổi dữ liệu địa điểm/trạng thái và roaming giữa các bên trong hệ sinh thái sạc.
- [Tổng cục Thống kê — dữ liệu không gian kinh tế–xã hội](https://giskinhtexahoi.gso.gov.vn/introduceNew/): nguồn khởi đầu cho dữ liệu dân số/bối cảnh theo địa bàn.
- [WorldPop — Methods](https://www.worldpop.org/Methods/): mô tả cách tạo lớp phân bố dân số ước lượng; chỉ dùng với nhãn estimate và theo điều khoản nguồn.
- [TomTom Traffic Stats — Introduction](https://docs.tomtom.com/traffic-stats/documentation/product-information/introduction?source_app=b2b&source_product=traffic-apis): ví dụ nguồn traffic lịch sử theo hợp đồng; probe data không đồng nghĩa tổng số xe.
- [README dữ liệu Planner hiện có](../../data_platform/station_planning/README.md) và [README POI/giao thông hiện có](../../raw_data/official_poi_transport/README.md): ranh giới chính xác của dữ liệu demo trong repository.

