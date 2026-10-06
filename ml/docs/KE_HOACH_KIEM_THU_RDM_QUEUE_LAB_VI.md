# Kế hoạch kiểm thử dự báo nhả cổng và hàng đợi

## Câu hỏi cần trả lời

Khi người dùng dự kiến tới trạm sau 5, 15, 30, 45 hoặc 60 phút, cách nào trả
lời đúng hơn về việc có cổng phù hợp hay không và phải chờ bao lâu?

## Ba cách được so sánh

1. **Giữ nguyên trạng thái hiện tại:** nếu hiện tại đầy thì dự báo vẫn đầy.
2. **Dự báo độ đông bằng mô hình cây:** nhìn một giờ độ đông gần nhất và dự
   báo tỷ lệ cổng bận tại mốc người dùng tới.
3. **Dự báo nhả từng cổng rồi xếp hàng:** với mỗi xe đang cắm, mô hình dự đoán
   thời điểm xe rút dây theo ba kịch bản sớm, điển hình, muộn; Queue Lab xếp
   các xe vào cổng tương thích rảnh sớm nhất.

## Cách tạo bài thi

Một kịch bản simulator mới được sinh bằng hạt ngẫu nhiên khác với dữ liệu học.
Tại mỗi thời điểm hỏi, bài kiểm thử chỉ cho phép xem trạng thái cổng và phần
đầu của phiên sạc đã xảy ra. Thời điểm rút dây ở tương lai bị che; đó là đáp
án để chấm sau cùng.

Mỗi trạm được hỏi ở năm mốc đến: 5, 15, 30, 45 và 60 phút. Chấm riêng từng
mốc, không gộp thành một điểm chung rồi che mất lợi ích ở mốc xa.

## Thước đo

- Sai số thời gian nhả cổng: chênh lệch phút giữa dự đoán và thời điểm rút
  dây thật.
- Khả năng có cổng: dự báo có/không có cổng tương thích tại lúc người dùng
  tới có đúng không.
- Sai số thời gian chờ: chênh lệch giữa lúc dự báo và lúc xe thật sự có thể
  bắt đầu sạc.
- Ba kịch bản sớm/điển hình/muộn: đáp án thật có nằm trong khoảng sớm–muộn
  bao nhiêu phần trăm lần thử.

## Giới hạn bắt buộc ghi rõ

Simulator biết cả xe sẽ đến sau snapshot, còn Queue Lab realtime không được
phép biết những xe đó. Vì vậy báo cáo tách hai bài:

- **Bài snapshot:** chỉ xét các xe đang chiếm cổng tại lúc hỏi. Đây là phép
  kiểm tra đúng năng lực của mô hình nhả cổng và Queue Lab.
- **Bài toàn trạm:** tính cả xe mới tới sau snapshot. Đây đo tình huống thực
  tế khó hơn và cho thấy phần nhu cầu chưa quan sát có thể làm DES sai bao
  nhiêu.

Kết quả chỉ có giá trị kiểm thử nội bộ vì simulator và mô hình đều dùng dữ
liệu tổng hợp. Muốn dùng thật phải lặp lại bài tương tự trên dữ liệu cổng,
phiên và hàng đợi vận hành tại Việt Nam.

## Kết quả lần chạy đầu tiên

Kịch bản độc lập dùng hạt ngẫu nhiên `20261006`, sinh 935 phiên sạc và chấm
360 snapshot có session đang hoạt động. Mỗi snapshot được hỏi ở năm ETA.

| ETA | Persistence: đúng khả năng có cổng trong toàn trạm | XGBoost | RDM, bài snapshot |
| ---: | ---: | ---: | ---: |
| 5 phút | 95.8% | 70.8% | 98.6% |
| 15 phút | 87.5% | 76.4% | 87.5% |
| 30 phút | 83.3% | 75.0% | 83.3% |
| 45 phút | 70.8% | 65.3% | 84.7% |
| 60 phút | 70.8% | 63.9% | 84.7% |

Điểm RDM ở cột cuối chỉ xét các xe đã đang chiếm cổng trong snapshot. Nó chưa
tính xe mới sẽ đến sau snapshot, đúng giới hạn của Queue Lab realtime. Kết quả
này cho thấy tín hiệu nhả cổng có ích hơn persistence ở ETA xa trong bài toán
snapshot, nhưng chưa phải kết luận production.

RDM hiện có sai số nhả cổng trung bình 117.6 phút và khoảng dự báo sớm–muộn
chứa toàn bộ đáp án chỉ 73.6%. Hai số này chưa đạt để dùng thật. Nguyên nhân
chính là RDM học từ telemetry Gold dạng replay, sau đó bị chấm trên hành vi của
simulator có phân phối thời lượng khác. Đây là phát hiện hữu ích: pipeline
không leak, nhưng model chưa chuyển miền dữ liệu tốt.

Lần chạy này chưa đưa xe trong hàng đợi đã xác nhận vào Queue Lab; nó mới chấm
bước dự báo nhả cổng và khả năng có cổng. Bước tiếp theo là sinh queue thật từ
simulator hoặc một scenario có queue được xác nhận, truyền ba kịch bản thời
gian nhả vào Queue Lab, rồi chấm sai số thời điểm xe bắt đầu sạc.

## Replay RDM qua Queue Lab

Đã thực hiện replay thứ hai với hạt ngẫu nhiên `20261007`. Mỗi scenario lấy
snapshot một trạm đang có xe sạc, thêm **một xe đã xác nhận trong hàng đợi**
với thời lượng sạc cố định 30 phút, sau đó cho một xe yêu cầu vào sau xe đó.
Không có xe tương lai không quan sát nào được thêm vào; đây là phép kiểm tra
đúng phạm vi Queue Lab.

| Chỉ số | Kết quả |
| --- | ---: |
| Số scenario | 46 |
| Sai số tuyệt đối trung bình của thời gian chờ điển hình | 64.9 phút |
| Đáp án thật nằm trong khoảng sớm–muộn | 84.8% |
| Trung vị thời gian chờ thật | 0 phút |

Queue Lab đã nhận ba thời lượng sớm/điển hình/muộn từ RDM và xếp queue đúng
theo cổng tương thích. Tuy nhiên sai số 64.9 phút còn quá lớn để dùng cho người
dùng thật. Có nhiều scenario xe sau queue vẫn có cổng khác rảnh ngay, nên trung
vị thời gian chờ thật bằng 0; đây là lý do phải đọc thêm phân phối đầy đủ, không
chỉ nhìn một con số trung vị.

Kết luận: luồng kỹ thuật RDM → Queue Lab hoạt động và trả được khoảng bất định,
nhưng RDM chưa đủ tốt để kết quả được coi là ETA thật. Việc quan trọng tiếp theo
là thu telemetry/session/queue Việt Nam thật và lặp lại đúng replay này.
