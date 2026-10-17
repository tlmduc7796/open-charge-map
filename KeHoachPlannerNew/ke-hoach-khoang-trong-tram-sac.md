# Kế hoạch tìm khoảng trống trạm sạc để đi khảo sát

## 1. Mục tiêu

Tìm các khu vực **nhu cầu cao, nguồn cung trạm sạc quanh đó thấp (cả đối thủ lẫn trạm của mình), chi phí đất chấp nhận được**, để chọn ra danh sách địa điểm đi khảo sát thực địa.

Đây là bước **sàng lọc**, không phải dự đoán doanh thu hay lợi nhuận. Không cần mô hình tối ưu, không cần dữ liệu phiên sạc hay hiệu chỉnh hệ số phức tạp.

## 2. Dữ liệu cần có (bản tối thiểu)

| Dữ liệu | Dùng để | Gợi ý nguồn |
|---|---|---|
| Lưới ô phủ khu vực (hexagon hoặc grid) | Đơn vị tính điểm | Tự tạo bằng GIS/Python |
| Lưu lượng xe hoặc mật độ đường theo ô | Nhu cầu theo dòng xe | Dữ liệu giao thông, đếm xe, hoặc cấp đường/mật độ đường làm proxy |
| POI theo ô (siêu thị, văn phòng, khách sạn, bãi đỗ...) | Nhu cầu tại điểm đến | OpenStreetMap hoặc dữ liệu bản đồ khác |
| Danh sách trạm sạc: tọa độ, số cổng, tách **đối thủ** và **của mình** | Nguồn cung đã có, cờ ăn nhu cầu | Dữ liệu bản đồ, hệ thống của bạn, khảo sát |
| Giá thuê đất tham khảo theo khu vực (thô cũng được) | Lọc hoặc điều chỉnh điểm | Tin rao thuê mặt bằng, môi giới |

## 3. Cách tính

### Bước 1. Nhu cầu tiềm năng của ô $i$

Chuẩn hóa mỗi chỉ số về thang 0–1 (min-max hoặc thứ hạng phần trăm), rồi cộng có trọng số:

$$D_i = w_1 \cdot \widetilde{\text{Flow}}_i + w_2 \cdot \widetilde{\text{POI}}_i, \qquad w_1 + w_2 = 1$$

- Bắt đầu với $w_1 = w_2 = 0{,}5$.
- Làm sạc nhanh dọc đường: tăng $w_1$. Làm sạc ở điểm đến (trung tâm thương mại, văn phòng): tăng $w_2$.

### Bước 2. Nguồn cung đã có quanh ô $i$

Mỗi trạm đóng góp giảm dần theo khoảng cách:

$$\text{Cung}_i = \sum_{k} n_k \cdot e^{-d_{ik}/\lambda}$$

- $n_k$: số cổng của trạm $k$ (gồm trạm của bạn và đối thủ).
- $d_{ik}$: khoảng cách từ ô $i$ đến trạm $k$.
- $\lambda$: bán kính ảnh hưởng, ví dụ 1 km trong nội đô, vài km ở vùng thưa.

### Bước 3. Điểm khoảng trống

$$\text{Gap}_i = \frac{D_i}{1 + \text{Cung}_i}$$

Ô có nhu cầu cao mà nguồn cung quanh đó thấp sẽ có điểm cao.

### Bước 4. Điều chỉnh theo chi phí đất (tùy chọn)

Chọn một trong hai cách:

- **Lọc:** loại các ô có giá thuê vượt ngưỡng chấp nhận.
- **Chia:** chuẩn hóa $\widetilde{\text{Rent}}_i$ về thang 0–1, rồi

$$\text{Điểm}_i = \frac{\text{Gap}_i}{\widetilde{\text{Rent}}_i + \varepsilon}$$

với $\varepsilon$ là hằng số nhỏ (ví dụ 0,1) để không chia cho 0.

### Bước 5. Cờ ăn nhu cầu của chính mình

$$d_i^{\text{own}} = \min_{k \in J_{\text{own}}} d_{ik}$$

Nếu $d_i^{\text{own}}$ nhỏ hơn một ngưỡng (ví dụ 500 m đến 1 km) thì gắn cờ hoặc loại ô đó, vì trạm mới ở đó dễ lấy khách của trạm cũ.

## 4. Đầu ra

1. **Heatmap điểm khoảng trống** để nhìn tổng quan.
2. **Danh sách 10–20 ô điểm cao nhất** làm ứng viên khảo sát. Gộp các ô liền kề thành một cụm (hoặc chọn các ô cách nhau tối thiểu 1 km) để không đi khảo sát cùng một chỗ nhiều lần.
3. Kèm mỗi ứng viên: nhu cầu $D_i$, nguồn cung quanh đó, khoảng cách tới trạm gần nhất của bạn và của đối thủ, giá thuê tham khảo.
