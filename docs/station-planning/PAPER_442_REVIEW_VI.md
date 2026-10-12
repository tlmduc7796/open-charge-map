# Bài báo 442: Demand Prediction and Placement Optimization for EV Charging Stations

**Nguồn:** Gopalakrishnan và cộng sự, IJCAI 2016. Bản PDF trong repository: [`442.pdf`](references/442.pdf).

## Bài báo giải quyết gì?

Bài toán gồm hai phần nối tiếp:

1. Dự báo nhu cầu tại trạm/vị trí từ dữ liệu sử dụng sạc và các “view” bên ngoài như POI, giao thông và nhu cầu ở các trạm lân cận. Tác giả dùng Multiple Dependent Regression (MDR), dựa trên Canonical Correlation Analysis để kết hợp nhiều nguồn đặc trưng.
2. Chọn vị trí và số lượng chỗ/cổng sạc dưới ngân sách. Formulation kết hợp mục tiêu phục vụ nhu cầu với độ phủ các địa điểm quan tâm trong bán kính tiếp cận; mô hình Erlang-C/M/M/N liên kết mục tiêu thời gian chờ với số chỗ sạc cần thiết. Heuristic IPAC luân phiên bước knapsack và set cover.

Đây là cấu trúc tham khảo hữu ích: **dự báo nhu cầu + độ phủ + ngân sách + capacity/service constraint**. Nó gần với hướng của team hơn bài toán chỉ dự đoán queue cho một trạm.

## Kết quả và giới hạn

- Thử nghiệm tại North East England trên 252 điểm sạc công cộng, dữ liệu nhu cầu theo giờ từ 07:00 đến 23:00.
- MDR giảm RMSE khoảng 27% so với linear regression đơn giản, 21% so với multiple linear regression và 18% so với Bayesian CCA trong protocol của bài báo.
- Leave-one-station-out đánh giá khả năng dự đoán trạm bị giữ lại trong cùng bối cảnh; đây không phải temporal holdout để chứng minh dự báo tương lai qua nhiều năm.
- IPAC được so với heuristic đơn giản, ILP và relaxed LP trong study area; kết quả gần LP relaxation và cải thiện khoảng 10–15% so với heuristic đơn giản ở nhiều trường hợp ngân sách hạn chế. Heuristic không bảo đảm nghiệm tối ưu toàn cục.
- Một số chi tiết giản lược, gồm dữ liệu/chi phí theo thị trường Anh thời điểm 2016 và giả định hàng đợi Poisson/exponential/homogeneous. Demand served dưới ngân sách không đồng nghĩa tối đa hóa lợi nhuận ròng.
- Bài báo dùng nhu cầu quan sát và đặc trưng xung quanh trạm; bài toán Việt Nam cần xử lý nhu cầu chưa quan sát do thiếu nguồn cung, quyền tiếp cận, độ phủ lưới điện, giá/uptime và khác biệt địa phương.

## Cách áp dụng cho đề án

1. Mượn cấu trúc bài toán và baseline coverage/knapsack, không bê nguyên mô hình hay tham số.
2. Thêm phương án mở rộng trạm hiện có; so marginal coverage với xây mới.
3. Dùng queue/occupancy từ branch `fix/ui` làm tín hiệu và capacity scenario tại cung hiện hữu; không nhập cả bài toán wait prediction vào site planner.
4. Khi chưa có Vietnamese ground truth, trình bày synthetic scenario và sensitivity, không claim accuracy/ROI.
5. Với dữ liệu thật: temporal holdout + spatial/corridor holdout; đánh giá khả năng tổng quát hóa vùng và thời gian.
6. Thay chi phí/ràng buộc bằng dữ liệu operator/local grid, rồi mới xem xét kinh tế đầu tư.

## Liên kết đọc thêm

- Bài báo tham khảo được lưu tại [`references/442.pdf`](references/442.pdf).
- [NREL EVI-X Modeling Suite](https://www.nrel.gov/transportation/evi-x.html) mô hình hóa bài toán hạ tầng theo vùng, site, hành lang và đội xe.
- [Nghiên cứu 2025 về nhu cầu quan sát và quyết định vị trí](https://www.sciencedirect.com/science/article/pii/S2590198225003185) chỉ ra observed demand có thể là proxy không hoàn hảo cho nhu cầu thực.
- [Nghiên cứu về demand bị censor bởi số lượng charger](https://doi.org/10.1016/j.trc.2023.104189) phân tích nhu cầu bị giới hạn khi nguồn cung sạc sẵn có.
