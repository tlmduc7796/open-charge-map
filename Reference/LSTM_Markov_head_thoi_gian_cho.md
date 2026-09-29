# **Dự đoán thời gian chờ bằng LSTM + Markov head** 

Cơ sở lý thuyết, thiết kế đầu vào/đầu ra và ví dụ tính chi tiết 

## **0. Tóm tắt** 

Mô hình nhận trạng thái hiện tại của trạm cùng ngữ cảnh, và dự đoán hai họ xác suất chuyển trạng thái theo từng mốc thời gian: xác suất được giải phóng _rk_ và xác suất bị chiếm lại _bk_ . Từ đó tính ra (i) xác suất kẹt tại mọi mốc, (ii) phân phối thời gian chờ nếu người dùng đến vào thời điểm _a_ bất kỳ trong tương lai, và (iii) các con số đại diện: kỳ vọng E[W] (trọng tâm của phân phối), trung vị và P80. Trung vị và P80 được thêm vào vì chúng bền hơn kỳ vọng trước giả định về phần đuôi. 

Toàn bộ các con số trong ví dụ được tính bằng code. Các giá trị _rk_ , _bk_ là số minh họa, không phải đầu ra của một model đã huấn luyện. Mô phỏng chuỗi Markov 2 triệu mẫu xác nhận các công thức trong mục 3 và 4 với sai lệch dưới 0.001. 

## **1. Bài toán và ký hiệu** 

Tại thời điểm tham chiếu _T_ bạn biết trạng thái trạm _y0_ . Bạn sẽ đến lúc _a_ phút sau _T_ . Câu hỏi: thời gian chờ _W_ của bạn phân phối thế nào? 

|**Ký hiệu**|**Ý nghĩa**|
|---|---|
|_T_|thời điểm tham chiếu (lúc chạy dự đoán), gốc thời gian|
|Δ|bước lưới, ví dụ 5 phút|
|_tk_|mốc thứ_k_:_tk_= kΔ, với k = 0, …, K−1 (ví dụ 0, 5, …, 25 phút kể từ_T_)|
|_yk_∈ {0,1}|trạng thái tại_tk_: 1 = kẹt, 0 = trống._y0_đã biết. Đây là**nhãn**khi huấn luyện|
|_x_|vector đặc trưng đầu vào: mọi thứ biết được tính đến_T_|
|_ok_|chỉ báo mốc_k_có quan sát được hay không (mask). Bằng 0.5 nếu mất dấu giữa<br>khoảng|
|_a_|thời điểm người dùng đến, tính bằng phút kể từ_T_, 0 ≤_a_≤_tK-1_|
|_W_|thời gian chờ đến khi trạm trống lần đầu;_W_= 0 nếu đến lúc trống|
|_rk_,_bk_|hazard giải phóng và hazard kẹt lại, là**đầu ra của mạng**(xem mục 3)|
|_πk_|P(_yk_= 1): xác suất kẹt tại mốc_k_, suy ra từ r, b|
|_Gk_|tích (1 −_ri_) với i = 1.._k_: xác suất chưa được giải phóng liên tục qua_k_bước|
|μ|phần dư trung bình sau mốc cuối (giả định của người dùng, mục 4.4)|



## **2. Các giả định** 

Mô hình chỉ đáng tin khi năm giả định sau tương đối đúng. Cột cuối nói điều gì xảy ra khi chúng sai. 

|**#**|**Giả định**|**Nếu sai**|
|---|---|---|
|A1|**Markov theo mốc**: P(_yk_|_yk-1_, …,_y0_,_x_) = P(_yk_|<br>_yk-1_,_k_,_x_)|Hazard phụ thuộc thời gian đã ở trong trạng thái.<br>Cách giảm: đưa tuổi trạng thái vào_x_|
|A2|Mọi thông tin về quá khứ nằm trong_x_|Thiếu đặc trưng, hoặc rò rỉ thông tin từ tương lai<br>khi dựng dữ liệu|
||Censoring không thông tin: việc mất dấu độc lập|Ước lượng lệch. Không có mẹo huấn luyện nào|
|A3|với trạng thái tương lai khi đã biết_x_và trạng thái<br>hiện tại|cứu được, và không kiểm chứng được từ chính dữ<br>liệu|



LSTM + Markov head: cơ sở lý thuyết và ví dụ 

Trang 1 

|**#**|**Giả định**|**Nếu sai**|
|---|---|---|
|A4|Nội suy tuyến tính giữa các mốc (mật độ đều<br>trong khoảng)|Sai số nếu hệ dao động nhanh hơn Δ; ước lượng<br>chờ có thể dài hơn thực tế khoảng 14–19% trong<br>một mô phỏng thời gian liên tục|
|A5|Sau mốc cuối, phần dư theo phân phối mũ với<br>trung bình μ|Kỳ vọng đổi theo μ; phân vị trong lưới không bị<br>ảnh hưởng|



## **3. Mô hình xác suất** 

### **3.1 Tham số** 

Mạng xuất _rk_ , _bk_ ∈ (0,1) với k = 1, …, K−1, mỗi số là một sigmoid: 



_rk_ trả lời câu hỏi "đang kẹt ở mốc trước, bước này có được giải phóng không"; _bk_ trả lời "đang trống ở mốc trước, bước này có bị chiếm lại không". Hai định nghĩa hướng về hai trạng thái **ngược nhau** , và đây là nguồn nhầm lẫn thường gặp nhất. Ma trận chuyển ở bước _k_ : 

||**→ trống**|**→ kẹt**|
|---|---|---|
|**từ trống**|1 −_bk_|_bk_|
|**từ kẹt**|_rk_|1 −_rk_|



Mỗi hàng là một phân phối Bernoulli độc lập, nên mô hình cần đúng hai số cho mỗi mốc. Khi _bk_ ≡ 0, trạng thái trống hấp thụ và mô hình quay về dạng "chỉ có thời điểm giải phóng đầu tiên". 

### **3.2 Đệ quy cho xác suất kẹt** **_πk_** 

Gọi _vk_ = (1 − _πk_ , _πk_ ) là phân phối trạng thái tại mốc _k_ . Theo tính Markov, _vk_ = _vk-1 Pk_ . Khai triển thành phần thứ hai (công thức xác suất toàn phần): có hai đường vào trạng thái kẹt, hoặc đang kẹt mà chưa được giải phóng, hoặc đang trống mà bị chiếm lại. 



### **3.3 Hành vi dài hạn** 

Khi r, b xấp xỉ hằng số trên một đoạn, đệ quy có điểm cố định và nghiệm dạng đóng: 



Kiểm tra điểm cố định: _π_<sup>*</sup> (1−r) + (1− _π_<sup>*</sup> )b = _π_<sup>*</sup> + b − _π_<sup>*</sup> (r+b) = _π_<sup>*</sup> . Diễn giải: 1/r là độ dài trung bình một đợt kẹt, 1/b là độ dài trung bình một đợt trống, nên _π_<sup>*</sup> = (1/r) / (1/r + 1/b) là tỷ lệ thời gian kẹt trong dài hạn, và trạng thái ban đầu bị "quên" theo cấp số nhân với tốc độ |λ|. Khác với hàm sống sót, _πk_ **không đơn điệu** : nó giảm nếu _πk-1_ > _π_<sup>*</sup> , tăng nếu nhỏ hơn. 

Ví dụ hằng số r = 0.4, b = 0.1: _π_<sup>*</sup> = 0.2, λ = 0.5. Xuất phát từ kẹt, _πk_ = 0.2 + 0.8·0.5<sup>k</sup> cho 0.6, 0.4, 0.3, …; xuất phát từ trống, _πk_ = 0.2 − 0.2·0.5<sup>k</sup> cho 0.1, 0.15, 0.175, … 

## **4. Thời gian chờ** 

### **4.1 Phân rã theo trạng thái lúc đến** 

Nếu đến lúc trạm trống thì _W_ = 0, xác suất 1 − π( _a_ ). Nếu đến lúc trạm kẹt thì _W_ là thời gian chờ đến lần trống đầu tiên. Vậy _W_ có **khối lượng tại 0** cộng với một phần liên tục. Không được bỏ khối lượng tại 0 khỏi phép tính, nếu không mọi phân vị bị đẩy lên quá cao. 

LSTM + Markov head: cơ sở lý thuyết và ví dụ 

Trang 2 

**4.2 Phân phối chờ khi đang kẹt** Giả sử kẹt tại _tk_ . Biến cố { _W_ > (j−k)Δ} nghĩa là _yk+1_ = … = _yj_ = 1. Theo Markov: 



Kết quả này chỉ dùng r, không dùng b, vì trong khoảng chờ quỹ đạo không rời trạng thái kẹt. Nó đúng với mọi _y0_ , chỉ cần trạng thái tại _tk_ là kẹt. G giảm đơn điệu theo cấu trúc vì là tích các số không vượt quá 1. 

### **4.3 Công thức tổng hợp** 

Với _w_ > 0, và π(·), G(·) là nội suy tuyến tính giữa các mốc (giả định A4): 



**4.4 Kỳ vọng (trọng tâm phân phối)** Vì E[ _W_ ] = ∫ P( _W_ > _w_ ) d _w_ , ta có: 



Tích phân dùng quy tắc hình thang. Vì G tuyến tính từng đoạn nên phép tính này **chính xác** , không phải xấp xỉ. Số hạng cuối dùng giả định A5: với đuôi mũ, ∫ G từ _tK-1_ đến ∞ bằng G( _tK-1_ )·μ. Mỗi phút thay đổi μ làm E[ _W_ ] đổi π( _a_ )·G( _tK-1_ )/G( _a_ ) phút. Vì μ do bạn chọn chứ không suy ra từ dữ liệu, nên báo cáo phần tích phân (cận dưới trung thực) kèm xác suất còn kẹt sau mốc cuối. 

### **4.5 Phân vị** 

Giải P( _W_ > _w_ ) = 1 − _q_ . Nếu _q_ ≤ 1 − π( _a_ ) thì phân vị bằng 0. Nếu không: 



Giải bằng nghịch đảo nội suy tuyến tính. Nếu vế phải nhỏ hơn G( _tK-1_ ) thì phân vị nằm ngoài lưới và chỉ kết luận được "lớn hơn _tK-1_ − _a_ phút". Phân vị không phụ thuộc μ khi nó rơi trong lưới, nên bền hơn kỳ vọng. 

## **5. Huấn luyện** 

### **5.1 Likelihood phân rã** 

Tính Markov làm xác suất của một quỹ đạo quan sát thành tích các xác suất chuyển. Lấy log âm, với BCE(p; y) = −[y ln p + (1−y) ln(1−p)]: 



Đọc công thức này theo ba điểm. **(a)** _yk-1_ là công tắc chọn nhánh, không phải nhãn: nó quyết định bước này dạy _rk_ hay _bk_ . **(b)** Nhãn thật là _yk_ , nhưng nhãn dương của _rk_ là 1 − _yk_ vì _rk_ dự đoán "trống", còn nhãn dương của _bk_ là _yk_ vì _bk_ dự đoán "kẹt". **(c)** Tích _ok-1_ · _ok_ : muốn học một bước chuyển thì phải biết cả hai đầu. 

LSTM + Markov head: cơ sở lý thuyết và ví dụ 

Trang 3 

Chuẩn hóa trên batch bằng tổng số bước hợp lệ, không phải N·(K−1), để mốc có ít quan sát không bị pha loãng: 



### **5.2 Ba tính chất lý thuyết cần nhớ** 

- **Proper scoring rule.** BCE có kỳ vọng nhỏ nhất tại xác suất thật, nên _rk_ , _bk_ học được là xác suất hiệu chuẩn. Vì vậy không dùng trọng số lớp (pos _w_ eight, scale _p_ os _w_ eight): chúng dịch điểm cực tiểu và phá calibration. 

- **Nghiệm không tham số.** Bỏ _x_ , cực đại hóa likelihood cho ước lượng đếm (life-table hai chiều), dùng để khởi tạo bias của head và làm đường chuẩn: 



- **Censoring miễn phí.** Mẫu mất dấu chỉ ngừng đóng góp từ mốc mất dấu (mask), không cần trọng số ngược xác suất. Điều kiện là giả định A3. 

### **5.3 Regularization và hiệu chuẩn** 

Hazard ở các mốc kề nhau thường gần nhau. Thêm phạt sai phân bậc hai lên logit _ρk_ = logit( _rk_ ), _βk_ = logit( _bk_ ); về mặt Bayes đây là tiên nghiệm Gauss làm mượt theo mốc: 



Đặt _λb_ lớn hơn _λr_ vì _bk_ nhiễu hơn (ít sự kiện dương). Khởi tạo bias bằng logit của ước lượng đếm ở trên. Sau huấn luyện, temperature scaling một tham số vô hướng trên tập validation để sửa độ tự tin chung. Chia train/validation theo thời gian hoặc theo nhóm mẫu, không chia ngẫu nhiên theo dòng. 

## **6. Kiến trúc LSTM + Markov head** 

### **6.1 Đầu vào** 

|**Nhánh**|**Nội dung**|**Kích thước**|
|---|---|---|
|Chuỗi (vào LSTM)|_m_bước trạng thái gần nhất_y-m+1_, …,_y0_, mỗi bước kèm mã giờ<br>sin/cos của bước đó|_m_×_ds_|
|Ngữ cảnh (vào MLP)|giờ và thứ tại_T_(mã tuần hoàn); cuối tuần/lễ; embedding trạm, loại<br>trụ, công suất;**tuổi trạng thái hiện tại**(đã ở_y0_bao nhiêu bước<br>liên tiếp); hazard nền theo khung giờ cho từng mốc tương lai (tính từ<br>tập train)|_dc_|



Mọi thứ phải lấy từ dữ liệu không muộn hơn _T_ . Nếu để lọt thông tin từ sau _T_ , điểm đánh giá sẽ đẹp giả một cách ngoạn mục. 

### **6.2 Các lớp** 

- LSTM đọc chuỗi và lấy trạng thái ẩn cuối _hs_ eq. 

- MLP đọc ngữ cảnh và cho _hc_ tx. 

- Nối hai vector, qua một lớp dense có dropout, ra biểu diễn _z_ . 

- Head tuyến tính ánh xạ _z_ sang 2(K−1) logit ( _ρ1_ .. _ρK-1_ , _β1_ .. _βK-1_ ). 

LSTM + Markov head: cơ sở lý thuyết và ví dụ 

Trang 4 

Không có đầu ra riêng cho _y0_ vì đã biết: _π0_ = _y0_ lấy thẳng từ quan sát. LSTM chỉ là hàm x ↦ (ρ, β), nên toàn bộ lý thuyết ở mục 3–5 giữ nguyên. Vì tuổi trạng thái nằm trong _x_ , mạng xấp xỉ được hiệu ứng semi-Markov ở phía **quá khứ** (kẹt càng lâu, _rk_ càng thấp), nhưng không thể ở phía sau _T_ , nơi quỹ đạo chưa biết. 

### **6.3 Đầu ra** 

|**Đầu ra**|**Định nghĩa**|**Ý nghĩa**|
|---|---|---|
|_rk_= σ(_ρk_)|P(_yk_= 0 |_yk-1_= 1,_x_)|đang kẹt ở mốc trước; xác suất**được giải phóng**<br>trong bước này|
|_bk_= σ(_βk_)|P(_yk_= 1 |_yk-1_= 0,_x_)|đang trống ở mốc trước; xác suất**bị chiếm lại**<br>trong bước này|



Với K = 6 có 10 số. Cả hai là xác suất chuyển **ròng** qua một bước Δ, không phải cường độ tức thời. Từ chúng suy ra _πk_ (mục 3.2), _Gk_ (mục 4.2) và mọi đại lượng ở mục 4. 

## **7. Ví dụ tính chi tiết** 

### **Ví dụ 0: dựng đầu vào** 

Trạm rất nhanh, thứ Ba 12:00, Δ = 5 phút, _m_ = 12 bước quá khứ (1 giờ). 

|**Nhánh**|**Nội dung**|**Kích thước**|
|---|---|---|
|Chuỗi|12 bước × (trạng thái, sin giờ, cos giờ)|12 × 3|
|Ngữ cảnh|giờ và thứ tại_T_(4), cuối tuần (1), embedding trạm (8), tuổi trạng thái (1),<br>hazard nền theo giờ của 5 mốc tương lai (10)|24|



Trạm đang kẹt ( _y0_ = 1) và đã kẹt 3 bước liên tiếp, tức 15 phút. 

### **Ví dụ 1: đến lúc T+8, trạm đang kẹt** 

Giả sử mạng xuất (số minh họa): 

|**k**|**1**|**2**|**3**|**4**|**5**|
|---|---|---|---|---|---|
|_tk_(phút)|5|10|15|20|25|
|_rk_|0.10|0.25|0.45|0.40|0.35|
|_bk_|0.08|0.12|0.15|0.12|0.10|



**Bước 1:** **_πk_** , xuất phát _π0_ = 1: 



**Bước 2:** **_Gk_** = tích (1 − _ri_ ): 

|**k**|**0**|**1**|**2**|**3**|**4**|**5**|
|---|---|---|---|---|---|---|
|_πk_|1.000|0.900|0.687|0.425|0.324|0.278|
|_Gk_|1.000|0.900|0.675|0.371|0.223|0.145|



**Bước 3: nội suy tại** **_a_ = 8.** _a_ nằm giữa mốc 5 và 10, hệ số (8−5)/5 = 0.6: 



Vậy P( _W_ = 0) = 1 − 0.772 = **22.8%** : đến lúc đó, 22.8% khả năng dùng được ngay. 

**Bước 4: hàm phân phối chờ.** Ví dụ _w_ = 5: G(13) = 0.675 + 0.6·(0.371 − 0.675) = 0.493, nên P( _W_ > 5) = 0.772 × 0.493 / 0.765 = 0.497, tức P( _W_ ≤ 5) = 50.3%. 

LSTM + Markov head: cơ sở lý thuyết và ví dụ 

Trang 5 

|**Chờ tối đa****_w_ (phút)**|**0**|**2**|**5**|**10**|**17**|
|---|---|---|---|---|---|
|P(_W_≤_w_)|22.8%|31.9%|50.3%|71.5%|85.4%|



**Bước 5: kỳ vọng.** Tích phân hình thang của G từ _a_ = 8 đến 25, theo từng đoạn: 

|**Đoạn**|**8 → 10**|**10 → 15**|**15 → 20**|**20 → 25**|**Tổng**|
|---|---|---|---|---|---|
|Di íh|2·(0.765+0.675)/2|5·(0.675+0.371)/2|5·(0.371+0.223)/2|5·(0.223+0.145)/2|**6460**|
|ện tc|= 1.440|= 2.616|= 1.485|= 0.919|**.**|



Chia cho G(8) = 0.765 được 8.44 phút, là kỳ vọng chờ khi đang kẹt, cắt cụt ở mốc 25 (RMST có điều kiện). Nhân π(8) = 0.772 được **6.52 phút** . Phần đuôi: G(25)/G(8) = 0.189 là xác suất vẫn kẹt sau mốc 25 nếu đã kẹt lúc 8. Với μ = 3 phút, cộng thêm 0.772 × 0.189 × 3 = 0.44, được **6.96 phút** . 

|**μ (phút)**|**3**|**5**|**10**|
|---|---|---|---|
|E[_W_] (phút)|6.96|7.25|7.98|



**Bước 6: phân vị.** Trung vị: giải G(8+ _w_ ) = 0.5 × 0.765 / 0.772 = 0.495, nằm giữa mốc 10 và 15 nên _t_ = 12.96, tức chờ **4.96 phút** . P80: **13.6 phút** . P90: mục tiêu 0.1 × 0.765 / 0.772 = 0.099 nhỏ hơn G(25) = 0.145, nên nằm ngoài lưới, chỉ kết luận được là hơn 17 phút. 

**Phát biểu cho người dùng:** "Khoảng 5 phút. 80% trường hợp xong trong 14 phút. Khoảng 15% khả năng phải chờ hơn 17 phút." 

### **Ví dụ 2: cùng r, b nhưng trạm đang trống** 

Chỉ đổi _π0_ = 0. Khi đó π = [0, 0.080, 0.170, 0.218, 0.225, 0.224]. Tại _a_ = 8: π(8) = 0.134, nên P( _W_ = 0) = 86.6%. Nhánh có điều kiện (đang kẹt lúc đến) **không đổi** : vẫn G( _a_ + _w_ )/G( _a_ ) với G(8) = 0.765. Thay đổi duy nhất là trọng số π( _a_ ) đặt lên nhánh đó. 

||**Đang kẹt (****_y0_ = 1)**|**Đang trống (****_y0_ = 0)**|
|---|---|---|
|P(_W_= 0)|22.8%|86.6%|
|Trung vị|4.96 phút|0|
|P80|13.6 phút|0|
|P90|ngoài lưới (hơn 17 phút)|3.7 phút|
|E[_W_], μ = 3|6.96 phút|1.21 phút|



Ca đang trống có phân phối hai đỉnh: đa số không chờ, nhưng cái đuôi xấu (bị chiếm trong 8 phút đầu) vẫn dài như ca đang kẹt. Trung vị bằng 0 che giấu điều đó, nên nên báo cả P90. 

### **Ví dụ 3: đến lúc nào thì tốt** 

Cùng r, b như trên, thay đổi thời điểm đến _a_ . Cột "ngoài lưới" nghĩa là phân vị vượt quá mốc 25. 

|**Đến lúc**|**_y0_=1: dùng**<br>**ngay**|**Trung vị**|**P80**|**E[****_W_]**|**_y0_=0: dùng**<br>**ngay**|**P80**|**E[****_W_]**|
|---|---|---|---|---|---|---|---|
|T+0|0%|12.9|21.5|14.1|100%|0|0|
|T+5|10%|7.9|16.5|9.4|92%|0|0.8|
|T+8|23%|5.0|13.6|7.0|87%|0|1.2|
|T+12|42%|1.3|10.1|4.4|81%|0|1.5|
|T+15|58%|0|8.1|3.3|78%|1.0|1.7|
|T+20|68%|0|ngoài lưới|2.0|78%|1.6|1.4|



Hai đường **hội tụ** khi _a_ tăng: trạng thái ban đầu bị quên dần theo _λ_<sup>k</sup> . Với _y0_ = 0, E[ _W_ ] tăng đến T+15 rồi giảm ở T+20. Phần giảm đó **một phần là hiệu ứng cắt cụt** : gần mốc cuối, lưới còn ít phút để tích 

LSTM + Markov head: cơ sở lý thuyết và ví dụ 

Trang 6 

lũy thời gian chờ, còn phần vượt lưới chỉ được tính bằng μ cố định. Đừng đọc nó như "đến muộn thì tốt hơn". 

### **Ví dụ 4: tính loss cho một mẫu huấn luyện** 

Quỹ đạo quan sát: y = (1, 1, 0, 1, ?, ?), mốc 4 và 5 mất dấu nên o = (1, 1, 1, 1, 0, 0). Dùng r, b ở Ví dụ 1: 

|**Bước**|**_yk-1_ →****_yk_**|**Dạy**|**Nhãn đưa vào BCE**|**Loss**|
|---|---|---|---|---|
|1|1 → 1|_r1_= 0.10|1 −_y1_= 0|−ln(0.90) = 0.105|
|2|1 → 0|_r2_= 0.25|1 −_y2_= 1|−ln(0.25) = 1.386|
|3|0 → 1|_b3_= 0.15|_y3_= 1|−ln(0.15) = 1.897|
|4, 5|mất dấu|||không đóng góp|



Tổng 3.389 trên 3 bước hợp lệ, trung bình 1.130 (chính là mẫu số chuẩn hóa ở mục 5.1). Bước 2 và 3 đắt vì mạng gán xác suất thấp cho các sự kiện đã xảy ra, đúng tín hiệu để nó tăng _r2_ và _b3_ cho các mẫu tương tự. 

## **8. Giới hạn cần nhớ** 

- **Rời rạc hóa.** _rk_ , _bk_ là xác suất chuyển ròng giữa hai mốc. Trong một mô phỏng thời gian liên tục, lưới 5 phút làm ước lượng chờ dài hơn thực tế khoảng 14–19%. Nếu cần độ chính xác dưới vài phút, dùng lưới mịn ở đoạn đầu (ví dụ 0, 1, 2, 3, 5, 8, 12, 20). 

- **Đuôi** sau mốc cuối là giả định μ, không suy ra được từ dữ liệu. Báo cáo phân vị, hoặc phần tích phân trong lưới kèm xác suất còn kẹt sau mốc cuối, thay vì một con số kỳ vọng duy nhất. 

- **Sai số nhân dồn.** _πk_ và _Gk_ là tích của nhiều thừa số, nên sai số nhỏ ở từng bước cộng dồn ở mốc xa. Kiểm tra bằng reliability diagram theo từng mốc; nếu lệch, thêm một số hạng BCE trực tiếp trên _πk_ tại các mốc quan sát được. 

- **Markov theo mốc.** Nếu trạm hay "nhấp nháy" (vừa trống xong dễ kẹt lại ngay) thì _bk_ phụ thuộc thời gian kể từ lần chuyển gần nhất. Đưa tuổi trạng thái vào _x_ để giảm vấn đề. 

- **Censoring có thông tin** (ví dụ khách bỏ đi khi trạm sắp trống) làm _rk_ lệch xuống. Kiểm tra cách dữ liệu bị mất dấu trước khi tin kết quả. 

- **Đánh giá.** Dùng NLL có mask và reliability diagram cho _πk_ , so với hai đường cơ sở là persistence (đoán _yt_ = _yt-1_ ) và life-table không đặc trưng. Tính khoảng tin cậy bằng block bootstrap theo nhóm mẫu. Không đánh giá bằng accuracy hay F1: đó là các chỉ số sau khi cắt ngưỡng và không nói gì về calibration. 

- **Siêu tham số** (ví dụ _m_ = 12 bước, dropout 0.2, Adam với tốc độ học 10<sup>-3</sup> ) chỉ là điểm khởi đầu, chưa được kiểm chứng cho bài toán của bạn. 

LSTM + Markov head: cơ sở lý thuyết và ví dụ 

Trang 7 

