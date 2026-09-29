# Smart EV Journey — Vấn đề và giải pháp

## 1. Tóm tắt dự án

**Smart EV Journey** là hệ thống hỗ trợ tài xế xe điện lựa chọn trạm sạc phù hợp cho một hành trình cụ thể. Thay vì chỉ hiển thị trạm gần nhất, hệ thống đánh giá đồng thời khả năng tương thích, mức pin còn lại, khả năng tiếp cận trạm, độ lệch tuyến, thời gian chờ dự kiến và thời gian sạc để đề xuất các lựa chọn an toàn, hợp lý hơn.

> **Thông điệp cốt lõi:** Trạm sạc tốt nhất không nhất thiết là trạm gần nhất; đó là trạm mà xe có thể đến an toàn, có đầu sạc phù hợp và giúp người dùng hoàn thành hành trình với tổng thời gian hợp lý.

## 2. Vấn đề cần giải quyết

### 2.1. Quyết định sạc hiện nay còn thiếu thông tin

Khi cần sạc giữa hành trình, tài xế thường phải tự ghép nhiều thông tin rời rạc:

- trạm nào nằm gần tuyến đường;
- trạm có hỗ trợ đúng chuẩn đầu sạc của xe hay không;
- lượng pin hiện tại có đủ để tới trạm và vẫn giữ mức pin dự phòng an toàn hay không;
- trạm đang hoạt động hay có cổng sạc bị lỗi;
- khi tới nơi có phải xếp hàng hay không;
- việc ghé trạm làm hành trình dài thêm bao lâu;
- cần sạc trong bao lâu để đạt mức pin mong muốn.

Một bản đồ chỉ hiển thị vị trí trạm chưa trả lời đầy đủ các câu hỏi này. Người dùng vẫn phải tự so sánh và ra quyết định trong khi các điều kiện tại trạm có thể thay đổi theo thời gian.

### 2.2. “Trạm gần nhất” có thể không phải lựa chọn tốt nhất

Khoảng cách địa lý chỉ là một phần của quyết định. Một trạm gần có thể:

- không tương thích với xe;
- nằm ngoài phạm vi di chuyển an toàn khi pin thấp;
- đang quá tải hoặc có hàng chờ dài;
- có cổng sạc ngừng hoạt động;
- có công suất không phù hợp, làm thời gian sạc kéo dài;
- yêu cầu một quãng đường vòng lớn so với hành trình chính.

Nếu hệ thống chỉ ưu tiên khoảng cách, tài xế có thể đến một trạm không sử dụng được hoặc mất nhiều thời gian hơn so với việc chọn một trạm xa hơn một chút.

### 2.3. Trạng thái trạm thay đổi làm gợi ý nhanh chóng lỗi thời

Tình trạng đông đột ngột, cổng sạc gặp sự cố hoặc nhiều xe cùng hướng tới một trạm có thể làm thay đổi lựa chọn tối ưu. Một đề xuất tĩnh, không xét trạng thái vận hành và nhu cầu sắp tới, khó phản ánh đúng điều kiện khi tài xế thực sự đến nơi.

### 2.4. Hệ quả đối với người dùng và mạng lưới sạc

Các hạn chế trên dẫn đến:

- lo lắng hết pin trước khi đến được trạm;
- mất thời gian đi vòng hoặc chờ sạc;
- trải nghiệm không ổn định vì đến nơi mới biết trạm không phù hợp;
- một số trạm bị tập trung quá nhiều xe trong khi các trạm khác còn khả năng phục vụ;
- khó lập kế hoạch cho một hành trình dài hoặc hành trình có mức pin ban đầu thấp.

## 3. Đối tượng sử dụng chính

### Tài xế xe điện

Người cần tìm một điểm sạc phù hợp với xe, mức pin và tuyến đường hiện tại, đặc biệt khi thời gian hoặc lượng pin còn lại bị giới hạn.

### Đơn vị vận hành mạng lưới sạc

Đơn vị muốn cung cấp thông tin hữu ích hơn cho người dùng và có cơ sở để phân bổ nhu cầu giữa các trạm dựa trên trạng thái vận hành.

### Nền tảng bản đồ hoặc ứng dụng di chuyển

Hệ thống cần tích hợp khả năng đề xuất điểm sạc vào luồng lập kế hoạch hành trình thay vì chỉ hiển thị danh sách điểm trên bản đồ.

## 4. Giải pháp của Smart EV Journey

Smart EV Journey biến việc tìm trạm sạc thành một bài toán **đề xuất theo hành trình và theo trạng thái**. Người dùng cung cấp xe, mức pin hiện tại, mức pin mong muốn, điểm đi và điểm đến. Hệ thống sau đó thực hiện bốn bước chính.

### Bước 1 — Loại các trạm không thể sử dụng

Hệ thống kiểm tra từng trạm theo các điều kiện bắt buộc:

- trạm có phục vụ công cộng và đang hoạt động;
- chuẩn đầu sạc của trạm tương thích với xe;
- xe đủ năng lượng để đi tới trạm;
- mức pin dự kiến khi đến trạm không thấp hơn ngưỡng dự phòng an toàn;
- có dữ liệu tuyến đường để đánh giá hành trình.

Các trạm bị loại đi kèm mã lý do, giúp người dùng hiểu vì sao một lựa chọn không phù hợp thay vì chỉ nhận một danh sách trống.

### Bước 2 — Ước lượng điều kiện khi xe tới trạm

Hệ thống không chỉ nhìn trạng thái tại thời điểm hiện tại mà đánh giá trạm ở thời điểm dự kiến xe đến. Các thành phần được sử dụng gồm:

- số cổng đang hoạt động và số cổng đang bận;
- hàng chờ hiện tại;
- thời lượng trung bình của một phiên sạc;
- tải dự kiến tại trạm;
- các lượt đến đã được người dùng xác nhận;
- sự kiện như ùn tắc tại trạm hoặc cổng sạc ngừng hoạt động.

Từ đó, hệ thống ước lượng thời gian chờ bằng mô hình hàng đợi Erlang C kết hợp với trạng thái runtime của trạm.

### Bước 3 — Tính tác động lên toàn bộ hành trình

Với mỗi trạm hợp lệ, hệ thống tính:

- quãng đường và thời gian đi tới trạm;
- độ lệch tuyến so với hành trình đi thẳng;
- mức pin dự kiến khi tới trạm;
- lượng điện cần nạp để đạt mức pin mục tiêu;
- thời gian sạc dự kiến dựa trên công suất hiệu dụng của xe và trạm;
- thời gian chờ dự kiến.

Nhờ vậy, đề xuất phản ánh chi phí thời gian thực tế của việc ghé trạm, thay vì chỉ dựa trên khoảng cách thẳng trên bản đồ.

### Bước 4 — Xếp hạng và cập nhật đề xuất

Các trạm đủ điều kiện được xếp hạng theo bốn nhóm tiêu chí:

1. thời gian chờ;
2. độ lệch tuyến;
3. thời gian sạc;
4. độ an toàn của mức pin khi đến trạm.

Khi trạng thái trạm thay đổi, hệ thống tính lại thứ hạng. Ví dụ, nếu trạm đang đứng đầu trở nên quá tải hoặc mất toàn bộ cổng hoạt động, trạm đó sẽ mất hạng hoặc bị loại và người dùng nhận được lựa chọn thay thế.

## 5. Vấn đề và cách giải pháp xử lý

| Vấn đề của người dùng | Cách Smart EV Journey xử lý | Kết quả mong đợi |
|---|---|---|
| Không biết trạm có dùng được cho xe hay không | Kiểm tra chuẩn đầu sạc và công suất giữa xe với trạm | Loại sớm các trạm không tương thích |
| Lo ngại hết pin trước khi đến trạm | Ước lượng năng lượng tiêu thụ, SOC khi đến và ngưỡng pin dự phòng | Chỉ đề xuất các trạm có thể tiếp cận an toàn |
| Đến trạm mới biết phải chờ lâu | Kết hợp occupancy dự kiến, hàng chờ, tốc độ phục vụ và planned arrivals | Cung cấp thời gian chờ ước lượng trước khi chọn trạm |
| Trạm gần nhưng làm hành trình lâu hơn | So sánh route đi thẳng với route đi qua từng trạm | Đánh giá đúng độ lệch tuyến |
| Không biết tổng thời gian cần dành cho việc sạc | Ước lượng cả thời gian chờ và thời gian sạc | Hỗ trợ lập kế hoạch hành trình thực tế hơn |
| Trạm đột ngột quá tải hoặc gặp sự cố | Nhận sự kiện runtime và xếp hạng lại | Đưa ra lựa chọn thay thế khi điều kiện thay đổi |
| Khó hiểu vì sao hệ thống đề xuất hoặc loại một trạm | Hiển thị các thành phần điểm và lý do loại | Tăng tính minh bạch của đề xuất |

## 6. Luồng trải nghiệm người dùng

1. Người dùng chọn mẫu xe và nhập mức pin hiện tại, mức pin mục tiêu.
2. Người dùng chọn điểm đi và điểm đến.
3. Hệ thống tìm tuyến và đánh giá các trạm sạc công cộng có liên quan.
4. Các trạm không tương thích, không hoạt động hoặc không thể tiếp cận an toàn bị loại.
5. Các trạm còn lại được xếp hạng theo thời gian chờ, độ lệch tuyến, thời gian sạc và an toàn SOC.
6. Người dùng xem tuyến đường, thông tin trạm và lý do xếp hạng trên bản đồ.
7. Người dùng xác nhận trạm đã chọn; lượt đến dự kiến được ghi nhận để hỗ trợ tính tải tương lai.
8. Nếu có sự cố hoặc ùn tắc, hệ thống cập nhật trạng thái và đề xuất lại.

## 7. Giá trị mà dự án mang lại

### Đối với tài xế

- giảm số quyết định phải tự tính toán trong lúc di chuyển;
- hạn chế rủi ro chọn trạm không tương thích hoặc không thể tiếp cận an toàn;
- nhìn thấy trước các thành phần thời gian của phương án sạc;
- có lựa chọn thay thế khi điều kiện tại trạm thay đổi;
- hiểu được lý do đằng sau mỗi đề xuất.

### Đối với hệ sinh thái sạc

- tạo nền tảng để phân bổ nhu cầu hợp lý hơn giữa các trạm;
- đưa planned arrivals vào đánh giá tải thay vì chỉ phản ứng với trạng thái hiện tại;
- cung cấp kiến trúc có thể tích hợp dữ liệu vận hành thực, mô hình dự báo và dịch vụ bản đồ;
- chứng minh một luồng end-to-end từ dữ liệu xe, trạm và tuyến đường đến quyết định có thể giải thích.

## 8. Điểm khác biệt của giải pháp

Smart EV Journey không dừng ở chức năng “tìm trạm sạc gần đây”. Điểm khác biệt nằm ở việc kết hợp ba lớp thông tin:

- **Ràng buộc kỹ thuật:** tương thích đầu sạc, công suất, năng lượng và pin dự phòng;
- **Ngữ cảnh hành trình:** tuyến đường, ETA và độ lệch tuyến;
- **Trạng thái vận hành:** occupancy, hàng chờ, cổng hoạt động, planned arrivals và sự kiện tại trạm.

Sự kết hợp này giúp hệ thống trả lời câu hỏi có giá trị thực tế hơn: **“Với chiếc xe, mức pin và hành trình hiện tại, tôi nên ghé trạm nào?”**

## 9. Phạm vi MVP hiện tại

MVP hiện đã minh họa được:

- lựa chọn xe, SOC, điểm đi và điểm đến;
- kiểm tra compatibility và reachability;
- route trực tiếp và route qua trạm bằng cache hoặc dịch vụ routing;
- ước lượng thời gian sạc;
- ước lượng thời gian chờ bằng Erlang C;
- xếp hạng trạm và giải thích các thành phần điểm;
- loại trạm kèm lý do;
- thay đổi đề xuất khi có congestion hoặc port outage;
- xác nhận và hủy planned arrival;
- giao diện bản đồ với cơ chế fallback khi dịch vụ ngoài không sẵn sàng.

## 10. Giới hạn và cách trình bày trung thực

Để đánh giá đúng phạm vi của bản demo, cần nêu rõ:

- Bản demo hiện dùng **persistence forecast** cho occupancy; artifact mô hình ML của Phase 03–04 chưa được hoàn thành.
- UrbanEV được định hướng dùng để huấn luyện và đánh giá **occupancy forecast**, không cung cấp ground truth về thời gian chờ.
- Thời gian chờ không phải đầu ra ML trực tiếp. Nó được ước lượng từ occupancy dự kiến cùng dữ liệu hàng chờ, capacity, thời lượng phiên sạc và giả định arrival rate.
- Queue, runtime events, planned arrivals và một số thuộc tính trạm trong demo là dữ liệu synthetic hoặc giả định có gắn nhãn rõ ràng.
- Kết quả từ dữ liệu UrbanEV tại Shenzhen không nên được tuyên bố là đại diện chính xác cho hành vi sạc tại Việt Nam.
- Hệ thống hiện là MVP hỗ trợ ra quyết định, chưa phải cam kết thời gian chờ thực tế hay hệ thống điều phối trạm thương mại.

## 11. Phát biểu ngắn dùng khi thuyết trình

> Người dùng xe điện hiện có thể tìm thấy trạm sạc trên bản đồ, nhưng vẫn khó biết trạm nào thực sự phù hợp với chiếc xe, lượng pin và hành trình của mình. Trạm gần nhất có thể không tương thích, không đủ an toàn để tới, đang quá tải hoặc khiến tổng thời gian hành trình dài hơn. Smart EV Journey giải quyết vấn đề đó bằng cách kết hợp dữ liệu xe, trạng thái trạm và tuyến đường để lọc các trạm không phù hợp, ước lượng thời gian chờ và sạc, sau đó xếp hạng những lựa chọn tốt nhất. Khi trạm quá tải hoặc gặp sự cố, hệ thống cập nhật đề xuất để tài xế có phương án thay thế kịp thời.

## 12. Tiêu chí đánh giá thành công

Giải pháp được xem là đạt mục tiêu MVP khi:

- không đề xuất trạm không tương thích, không hoạt động hoặc không thể tiếp cận an toàn;
- mỗi đề xuất hiển thị được độ lệch tuyến, SOC khi đến, thời gian chờ và thời gian sạc;
- mỗi trạm bị loại có lý do rõ ràng;
- sự kiện congestion hoặc outage làm kết quả thay đổi hợp lý mà không cần tải lại toàn bộ ứng dụng;
- các kịch bản cố định có thể reset và chạy lại ổn định;
- nguồn dữ liệu thật, dữ liệu synthetic và các giới hạn của mô hình được phân biệt rõ.

---

Tài liệu liên quan:

- [README dự án](../README.md)
- [Hướng dẫn demo](DEMO_GUIDE.md)
- [Data contract MVP](SMART_EV_JOURNEY_DATA_CONTRACT_MVP.md)
- [Thiết kế routing và recommendation](PHASE_07_BACKEND_ROUTING_RECOMMENDATION.md)
- [Kịch bản kiểm thử động](PHASE_10_DYNAMIC_DEMO_TESTING.md)
