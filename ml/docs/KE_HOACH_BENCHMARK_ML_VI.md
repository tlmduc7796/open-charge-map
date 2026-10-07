# Kế hoạch benchmark các mô hình ML

## Mục đích

Benchmark không nhằm tìm một thuật toán "thắng mọi nơi". Mục đích là trả lời
minh bạch ba câu hỏi khác nhau:

1. Với một trạm, sau 5--60 phút tỷ lệ cổng bận sẽ là bao nhiêu?
2. Một cổng đang bị chiếm còn bao lâu mới được nhả vật lý?
3. Khi người dùng đến, họ phải chờ bao lâu sau khi xét cổng tương thích và
   hàng đợi đã xác nhận?

Mỗi câu có nhãn và metric khác nhau. Không cộng các điểm đó thành một bảng rồi
gọi một model là tốt nhất toàn hệ thống.

## Những benchmark đã có trước kế hoạch này

- Persistence so với XGBoost occupancy trên Gold; persistence thắng ở mọi mốc.
- RDM quantile trên Gold: kiểm tra dataset, split và artifact, không phải
  accuracy vận hành.
- RDM cơ bản so với RDM giàu thông tin trên nhiều simulator seed.
- Replay RDM qua Queue Lab: chấm sai số chờ trong scenario đã xác nhận.

Các bài trên trả lời các câu hỏi có ích, nhưng dùng report/dataset khác nhau.
Chúng chưa phải một leaderboard occupancy chung có cùng protocol.

## Protocol occupancy thống nhất, phiên bản 1

### Dataset và cách chia

Gold occupancy 5 phút tại TP.HCM là dataset duy nhất của benchmark này. Mỗi
trạm được chia theo thời gian: phần đầu học, phần giữa chọn, phần cuối chấm.
Không trộn ngẫu nhiên các điểm 5 phút.

Tập test Gold đã từng được mở trong các thử nghiệm trước, vì vậy report hiện
tại luôn gắn nhãn **exploratory**, không được gọi là test production chưa thấy.
Khi có dữ liệu provider thật, protocol và code giữ nguyên nhưng tạo một test
window mới, chỉ mở một lần sau khi khóa thiết kế.

### Các ứng viên

| Ứng viên | Vai trò |
| --- | --- |
| Giữ nguyên trạng thái | Baseline tối thiểu: trạng thái mới nhất lặp lại. |
| Cùng giờ hôm qua | Bắt chu kỳ ngày. |
| Cùng giờ tuần trước | Bắt chu kỳ theo thứ trong tuần. |
| Markov theo trạm | Học xác suất chuyển số cổng bận mỗi 5 phút. |
| XGBoost | Học quan hệ phi tuyến từ một giờ occupancy gần nhất. |
| LSTM nhỏ | Học trực tiếp chuỗi một giờ occupancy gần nhất. |

Không đưa Transformer/LLM vào benchmark đầu vì Gold chỉ có ba tháng synthetic.
Model lớn có thể tạo điểm đẹp trong sân tập nhưng không chứng minh được giá trị
ngoài đời.

### Mốc và metric

Lộ trình đầy đủ chấm 5, 10, ..., 60 phút. Lần chạy đầu dùng năm mốc đại diện:
5, 15, 30, 45 và 60 phút để chi phí CPU hợp lý.

Để demo tái lập được trên laptop, lần chạy đầu giới hạn số dòng học của
XGBoost và LSTM theo seed cố định; giới hạn này được ghi ngay trong report. Nó
không phải kết quả cuối để công bố accuracy, còn lần benchmark trên dữ liệu thật
sẽ dùng ngân sách train thống nhất đầy đủ hoặc được ghi rõ tương tự.

- MAE: sai số trung bình của tỷ lệ cổng bận; nhỏ hơn tốt hơn.
- RMSE: phạt nặng các sai số lớn.
- Accuracy có-cổng: sau khi quy đổi dự báo ratio thành câu hỏi "trạm còn ít
  nhất một cổng không?"; đây là metric gần trải nghiệm người dùng.

Một ứng viên chỉ được gọi là thắng nếu tốt hơn baseline trên validation. Điểm
test exploratory chỉ để báo cáo, không dùng chỉnh lại model.

## Protocol RDM và Queue Lab

RDM không so chung với occupancy. Bảng RDM giữ các ứng viên: trung vị lịch sử
theo trạm/connector, XGBoost quantile, survival model; LSTM-RDM chỉ thêm khi
có telemetry thật dày và đủ session hoàn chỉnh.

Chấm RDM bằng sai số phút, sai số trung vị, calibration khoảng sớm--muộn và
quantile crossing. Sau đó replay vào Queue Lab để chấm sai số thời điểm người
dùng bắt đầu sạc. Đây mới là thước đo tác động sản phẩm.

## Quyết định hiện tại

Gold benchmark chỉ giúp chọn cách làm cho demo và phát hiện vấn đề pipeline.
Không model synthetic nào được đưa serving. Khi có telemetry Việt Nam thật,
chạy đúng protocol này, thêm baseline theo provider duration và freeze một tập
test theo thời gian trước khi chọn model production.

## Cách chạy

```powershell
.\.venv\Scripts\python.exe ml\src\benchmark_gold_occupancy_models.py
```

Report được ghi dưới `ml/results/occupancy/gold_model_benchmark/` và chứa
leaderboard theo từng mốc cùng mọi giới hạn nêu trên.

## Kết quả lần chạy Gold đầu tiên

Lần chạy đầu gồm 248.464 dòng học, 82.752 dòng validation và 82.736 dòng test
exploratory. Tất cả model dùng cùng feature dataset, cùng split và cùng năm
mốc. XGBoost và LSTM được giới hạn ngân sách train như đã ghi ở trên.

| Mốc | Persistence | Markov | XGBoost | LSTM |
| ---: | ---: | ---: | ---: | ---: |
| 5 phút | 0,0163 | 0,0246 | 0,0250 | 0,0939 |
| 15 phút | 0,0296 | 0,0446 | 0,0444 | 0,1029 |
| 30 phút | 0,0475 | 0,0706 | 0,0691 | 0,1119 |
| 45 phút | 0,0634 | 0,0928 | 0,0906 | 0,1234 |
| 60 phút | 0,0784 | 0,1124 | 0,1095 | 0,1320 |

Các số là MAE trên validation; nhỏ hơn tốt hơn. Baseline theo cùng giờ hôm qua
và cùng giờ tuần trước còn kém hơn nhiều (xấp xỉ 0,24--0,26 MAE), nên không đưa
vào bảng để giữ dễ đọc. Persistence thắng ở cả năm mốc.

Kết luận đúng không phải là "LSTM vô dụng" hay "XGBoost sai". Nó chỉ nói rằng
trong Gold hiện tại, trạng thái mới nhất chứa tín hiệu mạnh hơn các quy luật
synthetic còn lại. Không model nào được promote; kết quả này là benchmark
exploratory phục vụ demo và quyết định thu telemetry Việt Nam thật.
