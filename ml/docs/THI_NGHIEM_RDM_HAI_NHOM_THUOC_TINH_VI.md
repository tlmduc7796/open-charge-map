# Thí nghiệm RDM: hai nhóm thuộc tính

## Mục đích

Mô hình dự báo thời gian nhả cổng (RDM) phải trả lời: **từ thời điểm đang
quan sát, còn bao lâu xe mới rút dây và cổng rảnh thật sự?** Nhãn đúng là thời
gian đến `disconnect_at`, không phải thời điểm xe ngừng nhận điện.

Thí nghiệm này đo giá trị của các thuộc tính bổ sung một cách công bằng. Nó
không biến dữ liệu mô phỏng thành dữ liệu thật, và không thay thế RDM hiện có.

## Pipeline mới

```text
Nhiều lần chạy simulator, mỗi lần một seed độc lập
        |
        +-- seed train: học
        +-- seed validation: chọn cách làm
        +-- seed test: chấm cuối, không dùng chỉnh model
        |
        v
Lấy snapshot mỗi 5 phút trong khi xe còn cắm
        |
        +-- chỉ giữ thông tin đã biết đúng tại snapshot
        +-- nhãn = thời gian còn lại đến lúc rút dây
        |
        +---------------------------+
        |                           |
        v                           v
RDM cơ bản                    RDM mở rộng trong mô phỏng
        |                           |
        +------------ so sánh ------+
                     |
                     v
Chỉ khi có telemetry Việt Nam thật: train lại RDM cơ bản,
rồi mới cân nhắc đưa kết quả vào Queue Lab.
```

Việc chia theo **seed**, thay vì chia từng hàng hoặc từng phiên, bảo đảm thế
giới mô phỏng chưa từng thấy ở validation/test. Toàn bộ snapshot của một phiên
luôn thuộc cùng một tập.

## Hai nhóm thuộc tính

### RDM cơ bản — hướng tới dữ liệu vận hành thật

Đây là nhóm duy nhất có thể trở thành ứng viên production sau khi được train
lại và kiểm chứng bằng dữ liệu nhà vận hành Việt Nam:

- thời gian xe đã cắm;
- điện năng đã cấp đến thời điểm đó;
- công suất hiện tại;
- công suất tối đa của cổng;
- giờ trong ngày và thứ trong tuần;
- cờ xe đang lấy điện hay đã ngừng lấy điện nhưng vẫn chiếm cổng;
- trạm, cổng và chuẩn đầu cắm.

Các cột này cần đến từ inventory cổng và luồng trạng thái/đo điện trực tiếp.
Nếu một nhà vận hành không cung cấp một cột, cột đó không được giả vờ là có.

### RDM mở rộng — chỉ đo giá trị thông tin trong simulator

Ngoài nhóm cơ bản, profile này dùng SOC lúc cắm, SOC hiện tại suy ra từ meter,
công suất tối đa xe nhận được, dung lượng pin và nhóm xe. Trong đời thật, các
thông tin này cần sự đồng ý của người dùng hoặc quyền truy cập hợp lệ từ
provider. Vì simulator chủ động biết chúng, kết quả của profile này **không
được** dùng làm con số quảng bá hay artifact phục vụ hệ thống.

Mục tiêu duy nhất: nếu nó tốt hơn rõ rệt, đội biết chính xác thuộc tính nào
đáng xin thêm trong hợp tác với provider/OCPP.

## Các cột bị cấm làm đầu vào

Không được đưa vào train:

- `disconnect_at`: đáp án cần dự báo;
- `done_charging_at`: thông tin tương lai tại snapshot;
- điện năng cuối phiên, SOC khi rút, thời lượng idle và lý do kết thúc: đều
  chỉ biết sau khi phiên kết thúc.

SOC mục tiêu cũng chưa được dùng trong thí nghiệm đầu tiên: output phiên hiện
tại của simulator không lưu nó như một tín hiệu lúc xe cắm. Khi hệ thống có
một trường SOC mục tiêu được consent và lưu đúng thời điểm, nó có thể được thêm
vào **profile mở rộng** để kiểm chứng tiếp.

## Cách chạy và đọc kết quả

```powershell
.\.venv\Scripts\python.exe ml\src\experiment_rdm_feature_profiles.py
```

Kết quả nằm ở `ml/results/rdm/feature_profile_experiment/report.json` và gồm:

- MAE: sai số tuyệt đối trung bình của dự báo điển hình, đơn vị phút;
- median absolute error: sai số trung vị, ít bị các phiên cực dài chi phối;
- RMSE: phạt nặng sai số lớn;
- interval coverage: tỉ lệ đáp án thật nằm trong khoảng dự báo sớm–muộn;
- quantile crossing: tỉ lệ ba dự báo bị đảo thứ tự; càng gần 0 càng tốt.

Không chọn model theo điểm test. Test chỉ được xem một lần sau khi profile,
feature và tham số đã cố định theo validation.

## Kết quả lần chạy đầu tiên

Lần chạy ngày 06-10-2026 dùng bốn seed để học (3.712 phiên), hai seed để
validation (1.864 phiên) và hai seed khác để test (1.821 phiên). Có 76.400,
40.960 và 42.679 snapshot tương ứng. Các seed test không được dùng trong quá
trình fit model.

| Nhóm thuộc tính | MAE validation | MAE test | Sai số trung vị test | Đáp án nằm trong khoảng sớm--muộn, test |
| --- | ---: | ---: | ---: | ---: |
| RDM cơ bản | 76,5 phút | 99,4 phút | 51,8 phút | 69,9% |
| RDM mở rộng trong mô phỏng | 63,5 phút | 86,0 phút | 36,7 phút | 69,1% |

Nhóm mở rộng giảm khoảng **13,4 phút MAE** trên test so với nhóm cơ bản. Điều
đó cho thấy SOC và đặc tính xe có tín hiệu hữu ích trong simulator. Nhưng khoảng
sớm--muộn chỉ chứa đáp án khoảng 70%, thấp hơn mức trực giác mong đợi cho một
khoảng 10--90% (xấp xỉ 80%), và MAE test vẫn rất cao. Do đó cả hai vẫn chỉ phù
hợp cho demo/replay nội bộ, chưa phải ETA cho người dùng thật.

Sự chênh lệch giữa validation và test cũng là một cảnh báo lành mạnh: dù chung
luật simulator, từng thế giới ngẫu nhiên vẫn có thể rất khác. Nó càng củng cố
quyết định phải kiểm chứng lại trên telemetry Việt Nam thật trước khi phục vụ.

## Quyết định sau thí nghiệm

1. Nếu RDM cơ bản không đủ tốt: giữ Queue Lab ở chế độ scenario/demo, ưu tiên
   thu telemetry thật.
2. Nếu RDM mở rộng cải thiện mạnh nhưng RDM cơ bản không cải thiện: ghi nhận
   chính xác dữ liệu provider cần bổ sung, không deploy model mở rộng.
3. Nếu RDM cơ bản ổn định trên dữ liệu thật và replay Queue Lab: khi đó mới
   nối nó với API realtime, luôn trả khoảng sớm/điển hình/muộn thay vì hứa một
   thời gian chờ duy nhất.
