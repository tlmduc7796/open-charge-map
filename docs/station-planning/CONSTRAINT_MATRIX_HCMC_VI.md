# Ma trận ràng buộc tham khảo — quy hoạch trạm sạc TP.HCM

## Mục đích và cách dùng

Demo v3 dùng các tham số và cách xử lý unknown trong [P7_P8_DECISIONS_VI.md](P7_P8_DECISIONS_VI.md). Ma trận dưới đây vẫn là taxonomy tham khảo; nguồn công khai không xác nhận các ngưỡng demo hay feasibility của từng ứng viên.

Đây là **ma trận khởi điểm cho demo kỹ thuật**, không phải tiêu chuẩn pháp lý, tiêu chuẩn ngành hay trọng số lấy từ một doanh nghiệp. Nguồn doanh nghiệp công khai giúp xác định các yếu tố thực tế cần xét; họ không công bố công thức/weights nội bộ. Vì vậy file tách rõ:

1. **Hard feasibility gates:** candidate có được phép đưa vào danh sách xếp hạng/triển khai hay không.
2. **Technical opportunity score:** so sánh độ hấp dẫn kỹ thuật/độ phủ khi chưa có economics mật.
3. **Policy overlay:** tổ chức có thể cấu hình ưu tiên/điều kiện công.
4. **Optional finance overlay:** áp economics của doanh nghiệp khi họ cung cấp hoặc chọn giả định công khai.

`0–5` là thang đánh giá minh họa; mặc định chưa được calibration ở TP.HCM. `unknown` không bằng 0 và không nên được biến thành `feasible` hoặc `infeasible`.

## A. Hard feasibility gates

| ID | Cổng kiểm tra | Trạng thái loại | Trạng thái chưa rõ | Trạng thái đạt | Lý do đưa vào |
|---|---|---|---|---|---|
| H1 | Nằm trong địa giới TP.HCM được pin theo phiên bản | Ngoài boundary → loại khỏi run hiện tại | Không rõ CRS/boundary → chặn run hoặc sửa dữ liệu | Hình học hợp lệ trong boundary → tiếp tục | Kết quả phải cùng địa giới và version; TP.HCM sau hợp nhất gồm địa bàn TP.HCM cũ, Bình Dương cũ, Bà Rịa–Vũng Tàu cũ |
| H2 | Candidate/site có quyền tiếp cận và có thể dùng làm trạm | Chủ đất/đơn vị quản lý xác nhận không thể cấp quyền → loại | Chưa có thông tin quyền/site host → giữ dạng conditional, không xếp là “ready” | Có xác nhận hoặc nguồn site host đáng tin → tiếp tục | EVgo nêu site host/site control và bất động sản là phần của việc phát triển site |
| H3 | Quy hoạch, cấp phép, an toàn và yêu cầu tiếp cận | Cơ quan/đơn vị có thẩm quyền xác nhận không đáp ứng → loại | Chưa thẩm tra → conditional | Có trạng thái đáp ứng sơ bộ; cần lưu căn cứ | Việt Nam đang yêu cầu xử lý chỗ đỗ, sạc, tải điện nội bộ/an toàn PCCC ở chung cư; cần kiểm tra đúng loại địa điểm |
| H4 | Khả năng kết nối/công suất điện | Utility/grid study xác nhận không thể cấp trong horizon → loại hoặc đánh dấu requires-upgrade | Chưa có grid data → unknown, không coi là “grid available” | Công suất/đường đấu nối được xác nhận sơ bộ → tiếp tục | NREL EVI-LOCATE dùng utility assets như transformer/service panel; EVgo nêu grid upgrades/interconnection |
| H5 | Khả năng tiếp cận đường và xe mục tiêu | Không thể ra/vào an toàn hoặc không phục vụ được phương tiện mục tiêu → loại | Chưa xác minh road access → conditional | Có access phù hợp và loại phương tiện rõ → tiếp tục | Siting gắn với khả năng tiếp cận, traffic, loại charger và site layout |
| H6 | Phương án kỹ thuật hợp lệ | Không có cấu hình charger/port hợp chuẩn với use case → loại cấu hình đó | Connector/load/site layout chưa rõ → chưa chốt capacity | Có profile công suất, connector, số port và footprint hợp lý → tiếp tục | NREL EVI-LOCATE bắt đầu từ charger/port needs và assets tại site |

**Quy tắc xử lý:** chỉ loại candidate khi có bằng chứng “confirmed infeasible”. Nếu unknown, vẫn có thể đưa vào nghiên cứu/đề xuất sơ bộ nhưng phải hiện nhãn `conditional` và không được gọi là ready-to-build. Khi hard gate không đủ thông tin, kết quả là “cần thẩm tra”, không phải điểm thấp.

## B. Technical opportunity score mặc định cho demo

Tổng trọng số đề xuất là 100. Đây là **giả định thiết kế của team để tạo baseline giải thích được**, không phải trọng số EVgo/NREL hoặc thống kê được hiệu chỉnh tại TP.HCM. Có thể thay trong scenario config.

| Thành phần | Trọng số tham khảo | Metric/proxy có thể dùng | Chấm 0–5: gợi ý diễn giải |
|---|---:|---|---|
| D1. Nhu cầu tiềm năng | 30 | session/kWh đã quan sát; EV/vehicle flow; OD; home-charging access; fleet/tourism scenario; unmet-demand proxy | 0 = ít tín hiệu; 3 = nhiều tín hiệu độc lập mức vừa; 5 = nhu cầu được hỗ trợ bởi nhiều nguồn phù hợp và ổn định. Synthetic/proxy phải mang nhãn riêng |
| D2. Đóng góp độ phủ mới | 25 | phần demand cells/OD được tiếp cận thêm theo thời gian đi đường, sau khi tính trạm existing và các site đã chọn | 0 = gần như trùng vùng phục vụ; 3 = cải thiện rõ ở một cụm; 5 = mở vùng tiếp cận mới/giảm khoảng trống lớn |
| D3. Lưới và khả năng triển khai kỹ thuật | 20 | grid capacity/upgrade status, khoảng cách utility assets, site footprint, charger layout, access | 0 = nhiều trở ngại đã biết; 3 = có thể triển khai nhưng cần upgrade/verification; 5 = có dữ liệu utility/site tốt và ít việc phải nâng cấp |
| D4. Phù hợp mạng lưới/segment | 15 | highway/urban/industrial/coastal; site host; fleet partner; POI; dwell time; connector/power mix | 0 = không khớp use case; 3 = có segment/host phù hợp; 5 = nhiều tín hiệu độc lập về điểm dừng/đội xe/đối tác |
| D5. Bổ sung mạng lưới và tính sẵn sàng cung | 10 | overlap/competitor availability, distance to compatible reliable sites, uptime/status, option expand-existing | 0 = không lấp gap hoặc bị trùng mạnh; 3 = cải thiện cục bộ; 5 = lấp gap có bằng chứng và phương án mở rộng hợp lý |

Điểm tham khảo:

```text
technical_score = sum(weight_i * score_i / 5) / sum(weights_with_known_scores) * 100
evidence_coverage = sum(weights_with_known_scores) / 100
```

Luôn báo cả `technical_score` và `evidence_coverage`. Nếu dữ liệu một yếu tố là unknown, yếu tố đó không bị coi là 0; score hiển thị là provisional, kèm phần trọng số chưa có bằng chứng. Không so sánh hai candidate như chắc chắn hơn nhau nếu evidence coverage chênh lệch lớn. Ngưỡng evidence tối thiểu cần để xếp hạng là một tham số demo cần chọn, không phải chuẩn đã xác thực.

## C. Policy overlay có cấu hình

| Cấu hình policy | Kiểu | Tác động lên hệ thống | Nguồn/owner mong đợi |
|---|---|---|---|
| Khu vực cần ưu tiên | hard eligibility hoặc bonus score tùy quy định | Loại ngoài vùng hoặc cộng thành phần policy riêng; không âm thầm đổi D1–D5 | Cơ quan quy hoạch/chủ chương trình |
| Mục tiêu phủ dịch vụ | constraint/target | Bắt portfolio đạt tỷ lệ/nhóm tiếp cận định nghĩa trước | Cơ quan/đơn vị đặt mục tiêu |
| Grant/trợ cấp/incentive | financial input | Giảm chi phí trong economic scenario, theo điều kiện/thời kỳ áp dụng | Bên cấp chương trình và bên finance xác nhận |
| Zoning, access, safety, permit | hard feasibility | Pass/fail/conditional kèm căn cứ | Nguồn pháp lý/đơn vị thẩm định |
| Nhóm người dùng/địa bàn ưu tiên | soft objective hoặc constraint | Báo riêng equity/public-service outcome và trade-off với cost/return | Cơ quan/đơn vị sở hữu policy |

Không tự suy luận “chính sách hỗ trợ” thành tiền trợ cấp hay tiêu chí cấp phép. Cần dữ liệu rule, điều kiện đủ, khu vực áp dụng và effective date.

## D. Optional finance overlay

| Input/metric | Ví dụ | Cách xử lý |
|---|---|---|
| CAPEX | charger, civil works, transformer/connection, land/lease | Nhận theo site/port hoặc theo range; lưu units và source |
| OPEX | energy tariff, demand charge, rent, maintenance, network/operations | Cần thời kỳ và cách áp giá; tariff Việt Nam cần cập nhật/version theo quy định/hợp đồng |
| Revenue/use | price per kWh/session, utilization ramp, fleet contract | Không suy từ demand proxy thành doanh thu chắc chắn; lưu assumptions |
| Hurdle/decision rule | budget, payback limit, NPV threshold, risk tolerance | Do investor cấu hình; không có default “chuẩn thị trường” |
| Output | cashflow, NPV, payback, break-even cost, scenario range | Chỉ tính khi đủ input và được finance owner xác nhận công thức; nếu không thì `unknown` hoặc illustrative scenario |

EVgo công khai dùng financial modeling, GIS, expected utilization/traffic, EV penetration, fleet, site host, grants/policies, financial return, incentive capture, usage và network coverage trong network planning. NREL công khai có EVI-LOCATE cho bố trí/cost estimate theo charger needs và utility assets; EVI-FAST cho financial scenarios (payback/NPV/break-even) theo usage, cost, electricity prices và demand charges. Điều này ủng hộ việc technical engine có adapter/finance layer; không cung cấp trọng số nội bộ hay số finance cho TP.HCM.

## E. Hồ sơ ranking cho ba mục đích

1. **Technical opportunity (default demo):** dùng D1–D5; finance tắt; cho ra tiềm năng, độ phủ, công suất và evidence gaps.
2. **Public/policy scenario:** giữ D1–D5 làm technical profile; áp policy hard gates/targets và báo coverage/equity outcome riêng.
3. **Investor scenario:** giữ cùng candidate/demand/topology; finance package bật; thêm feasibility và economics theo rule/formula đã cung cấp. So sánh nhiều investor packages nếu các đối tác có tiêu chí khác nhau.

Không gộp các profile thành một score nếu người dùng chưa đồng ý mục tiêu. Báo Pareto/trade-off khi coverage, grid readiness và economic return kéo theo hướng khác nhau.

## F. Nguồn tham khảo và phạm vi áp dụng

- [EVgo 2025 Form 10-K, SEC](https://www.sec.gov/Archives/edgar/data/1821159/000110465926024827/evgo-20251231x10k.htm): mô tả public charging site planning và các loại input; dữ liệu/weights của họ là proprietary, nguồn chỉ hỗ trợ taxonomy.
- [NREL EVI-X](https://www.nrel.gov/transportation/evi-x): bộ công cụ network, site, grid, utilization và financial analysis.
- [NREL EVI-LOCATE](https://evi-locate.nrel.gov/): site design/cost workflow, charger needs và utility assets.
- [Thông tư giá điện cho sạc xe điện (Chinhphu.vn)](https://xaydungchinhsach.chinhphu.vn/quy-dinh-moi-ve-gia-ban-le-dien-cho-sac-xe-dien-119251209083343081.htm): ví dụ policy/tariff input tại Việt Nam; cần kiểm tra bản pháp lý hiệu lực khi chạy thật.
- [Công điện 27/CĐ-TTg](https://chinhphu.vn/?classid=0&docid=217406&pageid=27160): nêu vướng mắc hạ tầng sạc/chỗ đỗ/tải điện/an toàn ở chung cư; áp dụng làm nhóm kiểm tra, không thay thẩm định site.
- [Nghị quyết 202/2025/QH15, Công báo Chính phủ](https://congbao.chinhphu.vn/van-ban/nghi-quyet-so-202-2025-qh15-45050.htm): căn cứ địa giới cấp tỉnh mới; dùng kèm nguồn geometry/mã hành chính chính thức khi chuẩn bị dữ liệu.
