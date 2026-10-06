# Giải thích quy trình dữ liệu và kiểm thử mô hình

## Mục tiêu của giai đoạn này

Hiện chưa có dữ liệu vận hành công khai, đủ chi tiết và đáng tin cậy từ trạm
sạc Việt Nam. Vì vậy giai đoạn này không nhằm tạo một mô hình để đưa ngay vào
người dùng thật. Mục tiêu là dựng một sân tập có luật rõ ràng, để biết code,
cách chia dữ liệu, cách đo điểm và mô phỏng hàng đợi có hoạt động đúng hay
không.

Tất cả dữ liệu tạo ra trong giai đoạn này là dữ liệu mô phỏng. Nó hữu ích để
kiểm tra hệ thống, nhưng không phải bằng chứng rằng hành vi người dùng Việt
Nam ngoài đời giống như vậy.

## Dữ liệu được tạo ra như thế nào

1. Lấy các phiên sạc cũ từ một nguồn công khai ở Mỹ. Chúng chỉ cho biết những
   kiểu hành vi phổ biến: xe thường đến vào giờ nào, sạc bao lâu, đỗ bao lâu,
   cần bao nhiêu điện.
2. Dùng một bộ sinh dữ liệu để tạo các hành vi mới có hình dạng gần với nguồn
   trên. Bộ sinh này không mang tên, mã người dùng hay mã trạm gốc sang dữ liệu
   mới.
3. Đặt các hành vi đó vào các trạm ở Việt Nam mà thông số số cổng và công suất
   đã được xác nhận. Một cổng không thể phục vụ hai xe cùng lúc; điện cấp không
   được vượt quá công suất cổng; xe chờ quá lâu có thể không được phục vụ.
4. Từ các phiên sạc đã mô phỏng, tính lại cứ năm phút trạm có bao nhiêu cổng
   đang bận. Đây là lịch sử độ đông của trạm.

Kết quả có ba nhóm dữ liệu:

- Danh sách phiên sạc: xe bắt đầu, ngừng lấy điện và rút khỏi cổng lúc nào.
- Diễn biến sạc năm phút một lần trong từng phiên.
- Độ đông của từng trạm năm phút một lần.

## Persistence là gì?

Persistence không phải là lấy trung bình. Nó chỉ nói rất đơn giản:

> Tình trạng đang thấy bây giờ sẽ vẫn giữ nguyên ở tương lai gần.

Ví dụ lúc 18:00 một trạm có 3 trong 4 cổng đang bận. Dự báo persistence cho
18:05, 18:10 và 18:15 đều là 3 trong 4 cổng bận.

Nó thường mạnh ở dự báo ngắn vì xe đã cắm sạc thường ở lại nhiều hơn năm phút.
Tình trạng một trạm có quán tính: trong năm phút kế tiếp, phần lớn xe chưa kịp
rời đi và số xe mới đến thường chưa đủ làm tình trạng thay đổi lớn.

Persistence không nói xu hướng người dùng cố định mãi mãi. Nó chỉ tận dụng
thông tin mới nhất, vốn rất giá trị cho vài phút đến một giờ sắp tới.

## Vì sao hai mô hình cây quyết định thua persistence?

Mô hình cây quyết định đã được cho xem 12 trạng thái gần nhất, tức một giờ
vừa qua. Nó cố học quy luật để đoán 5 đến 60 phút tiếp theo. Trên dữ liệu mô
phỏng hiện tại, nó thua persistence ở mọi mốc thời gian.

Điều này không có nghĩa mô hình cây quyết định luôn kém. Nó có nghĩa dữ liệu
hiện tại chưa cho nó tín hiệu tốt hơn trạng thái mới nhất. Có ba nguyên nhân
chính:

1. Mỗi phiên sạc kéo dài khá lâu, nên trạng thái hiện tại tự nó đã rất tốt.
2. Trong kịch bản mô phỏng, số lượt xe trung bình mỗi ngày được giữ khá đều;
   biến động còn lại chủ yếu là ngẫu nhiên. Không mô hình nào đoán được chính
   xác một lượt xe ngẫu nhiên chưa xảy ra.
3. Chỉ có ba tháng dữ liệu mô phỏng. Điều này đủ để kiểm tra kỹ thuật, nhưng
   chưa đủ để kết luận quy luật giờ cao điểm thật ở Việt Nam.

Lần thử thứ hai đã thêm thông tin kiểu “khung giờ và thứ này trước đây trạm
thường đông bao nhiêu”. Kết quả vẫn không thắng. Vì vậy dừng ở đây là quyết
định đúng: không nhảy sang mô hình phức tạp hơn chỉ để tìm điểm số đẹp.

## Cách kiểm thử được làm như thế nào?

Dữ liệu được chia theo thời gian, không trộn ngẫu nhiên:

```text
Phần đầu giai đoạn  → dùng để học
Phần giữa giai đoạn → dùng để chọn và kiểm tra mô hình
Phần cuối giai đoạn → giữ lại để kiểm tra cuối cùng
```

Ở mỗi thời điểm, hệ thống nhìn một giờ gần nhất rồi dự báo độ đông cho các mốc
5, 10, 15 ... đến 60 phút sau. Hai cách dự báo được so cạnh nhau:

- Persistence: giữ nguyên tình trạng hiện tại.
- Mô hình cây quyết định: học từ lịch sử gần nhất, và trong lần thứ hai có
  thêm quy luật giờ/thứ.

Điểm lỗi là sai khác trung bình tuyệt đối giữa dự báo và tình trạng thật trong
dữ liệu mô phỏng. Điểm càng thấp càng tốt. Cả hai lần mô hình cây đều có điểm
cao hơn persistence, nên chưa được dùng.

## Mô hình dự báo thời gian nhả cổng là gì?

Mô hình này trả lời câu hỏi khác: một xe đang cắm ở cổng sẽ rút cổng sau bao
lâu? Thời điểm xe ngừng lấy điện chưa chắc là lúc cổng rảnh; xe có thể đã sạc
xong nhưng vẫn đỗ và cắm dây.

Thay vì buộc mô hình trả một con số duy nhất, nó trả ba kịch bản:

- Kịch bản thuận lợi: cổng rảnh sớm.
- Kịch bản điển hình: cổng rảnh vào khoảng giữa.
- Kịch bản thận trọng: cổng rảnh muộn.

Đây là phần phù hợp với thiết kế “nhiều kết quả”. Bộ mô phỏng hàng đợi có thể
dùng ba thời điểm này để cho người dùng thấy khoảng chờ thay vì một lời hứa
chắc chắn.

## Có thể dùng bộ mô phỏng để kiểm tra mô hình nhả cổng không?

Có. Đây là ứng dụng đúng của nó ở thời điểm này.

Quy trình kiểm tra là: sinh một kịch bản mô phỏng mới với hạt ngẫu nhiên khác;
tại một thời điểm giữa phiên sạc, che thời điểm rút cổng thật; đưa các quan sát
đến thời điểm đó vào mô hình; so ba kịch bản mô hình trả về với thời điểm rút
cổng mà bộ mô phỏng đã biết. Sau đó đưa các kịch bản này vào hàng đợi để xem
thời gian chờ ước lượng khác thời gian chờ thật của kịch bản bao nhiêu.

Việc này kiểm tra được luồng dữ liệu, không leak đáp án, và cách DES xử lý bất
định. Nó chưa kiểm tra được người dùng thật, vì cả câu hỏi lẫn đáp án đều là
mô phỏng.

## Hiện có thể dùng gì trong hệ thống?

- Có thể dùng trong màn hình demo, Queue Lab và kiểm thử nội bộ.
- Với dự báo độ đông, hiện dùng cách giữ nguyên tình trạng mới nhất; nó thắng
  hai mô hình đã thử trên dữ liệu mô phỏng.
- Với thời gian nhả cổng, có thể dùng ba kịch bản thuận lợi, điển hình và thận
  trọng trong mô phỏng hàng đợi.
- Không được dùng các kết quả này để nói với người dùng thật rằng thời gian
  chờ sẽ chính xác, hoặc để tự động chọn đường đi/trạm sạc.

Để đi tới sử dụng thật, cần dữ liệu vận hành từ trạm ở Việt Nam: tình trạng
cổng theo thời gian, cổng lỗi/offline, lúc xe cắm, lúc xe rút và công suất/năng
lượng khi sạc. Khi đó lặp lại đúng phép so sánh trên dữ liệu thật. Chỉ khi mô
hình thắng cách giữ nguyên trạng thái hiện tại một cách ổn định thì mới cân
nhắc bật nó cho người dùng.
