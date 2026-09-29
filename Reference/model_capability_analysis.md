# 🧠 Phân tích khả năng mô hình — DL có thực sự "hiểu" data?

**Ngày:** 2026-09-29  
**Tham chiếu:** [LSTM_Markov](file:///d:/Code/open-charge-map/Reference/LSTM_Markov_head_thoi_gian_cho.md) · [PHASE_04](file:///d:/Code/open-charge-map/Reference/PHASE_04_OCCUPANCY_MODEL.md) · [Data Gap Analysis](file:///C:/Users/ADMIN/.gemini/antigravity-ide/brain/00b9e835-cc00-4328-a2ea-c1edc6a511c5/data_gap_analysis.md)

---

## 1. Câu hỏi gốc: DL có học được "nhân quả" không?

### 1.1 Thực tế: DL học **tương quan (correlation)**, KHÔNG phải nhân quả (causation)

```
Correlation: "Khi trời mưa, occupancy giảm"     ← DL học được cái này
Causation:   "Trời mưa → người ít ra đường → ít xe đến sạc → occupancy giảm"  ← DL KHÔNG hiểu cái này
```

**Tại sao đây là vấn đề thực tế:**

| Tình huống | Tương quan (DL thấy) | Nhân quả (thực tế) | Hệ quả |
|---|---|---|---|
| Trạm mới mở gần mall | Occupancy cao vì gần mall | Nhiều xe hơn vì POI hút người | DL đoán đúng nhưng **không biết tại sao** |
| VinFast mở chính sách open-network | Không có data lịch sử | Demand sẽ tăng do xe hãng khác | DL **fail hoàn toàn** vì chưa thấy pattern này |
| Ngày Tết nhưng trạm ở highway | Data quá khứ: Tết → demand giảm (nội thành) | Highway demand thực tế TĂNG | DL có thể **đoán sai** vì generalize từ pattern nội thành |

> [!WARNING]
> **Kết luận thẳng:** DL thuần túy (LSTM, Transformer) **không đảm bảo** dự đoán đúng khi gặp tình huống chưa có trong training data. Nó giỏi nội suy (interpolation), yếu ngoại suy (extrapolation).

### 1.2 Ngành đang xử lý vấn đề này như thế nào?

Xu hướng 2025-2026 là **Hybrid Pipeline** — không dùng DL một mình:

```
┌─────────────────────────────────────────────────────────┐
│               HYBRID PIPELINE (3 layers)                │
│                                                         │
│  Layer 1: ML/DL Prediction                              │
│  ├── XGBoost / LSTM / Transformer                       │
│  ├── Dự đoán: occupancy tại thời điểm t+5, t+10, t+15  │
│  └── Blackbox nhưng accurate                            │
│                                                         │
│  Layer 2: Physics / Domain Knowledge                    │
│  ├── Queueing Theory (M(t)/M/s)                         │
│  ├── Markov Chain transitions (r_k, b_k)                │
│  ├── Chuyển đổi: occupancy → wait time probability      │
│  └── Whitebox, có lý thuyết toán học backing            │
│                                                         │
│  Layer 3: Interpretability / Safety                     │
│  ├── SHAP values → giải thích tại sao                   │
│  ├── Confidence intervals → biết khi nào không tin được │
│  ├── Causal validation → kiểm tra logic nhân quả        │
│  └── Override rules → constraints cứng (0 ≤ occ ≤ 1)   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Điểm mấu chốt:** DL chỉ là **Layer 1** — nó dự đoán occupancy (cái nó giỏi). Việc chuyển occupancy thành **wait time** được xử lý bằng **toán học** (Layer 2 — Markov/Queueing), không phải DL.

---

## 2. Về Embedding — Có cần không?

### 2.1 Embedding là gì, nói đơn giản

```python
# Thay vì dùng station_id = "urbanev_1001" (string, vô nghĩa cho model)
# Embedding biến nó thành vector có ý nghĩa:

station_1001 = [0.82, -0.31, 0.55, 0.12, ...]  # 8 dimensions
#                ↑       ↑       ↑       ↑
#             "gần mall" "nội thành" "AC+DC" "20 ports"
```

### 2.2 Khi nào cần embedding?

| Mô hình | Cần embedding? | Lý do |
|---|---|---|
| **XGBoost (Phase 04)** | ❌ Không | XGBoost xử lý categorical features trực tiếp. Lag features + temporal features là đủ. |
| **LSTM + Markov head** | ✅ Có | Doc LSTM_Markov nói rõ: "embedding trạm, loại trụ, công suất" là input cho nhánh Ngữ cảnh → MLP. Embedding giúp LSTM **phân biệt** trạm mall vs highway. |
| **Transformer / STGNN** | ✅ Bắt buộc | Transformer cần token embedding. STGNN cần node embedding để build adjacency graph. |

### 2.3 Embedding học được gì?

Embedding KHÔNG cần được thiết kế thủ công — model tự học trong quá trình training:

```
Trạm ở mall    → embedding gần nhau → model học: "giống nhau về pattern"
Trạm ở highway → embedding xa hơn   → model học: "pattern khác"
```

Nhưng **chỉ học được nếu có đủ data** từ nhiều loại trạm khác nhau. Với 50 stations từ UrbanEV, embedding sẽ **overfitting** nếu dimension quá cao (nên dùng 4-8 dims max).

---

## 3. XGBoost có dự đoán được thời gian chờ không?

### 3.1 Trả lời ngắn: XGBoost dự đoán **occupancy**, KHÔNG trực tiếp dự đoán wait time

```
XGBoost output: occupancy_ratio tại t+5, t+10, t+15  (con số 0.0 → 1.0)

KHÔNG phải:     "Bạn sẽ chờ 7 phút"  ← XGBoost KHÔNG trả lời câu này trực tiếp
```

### 3.2 Nhưng: Có thể **suy ra** wait time từ occupancy!

Đây chính là thứ file LSTM_Markov mô tả. Có **3 cách** chuyển occupancy → wait time:

#### Cách 1: Rule-based (đơn giản nhất, dùng cho MVP demo)

```python
def estimate_wait_simple(occupancy_ratio, total_ports, avg_session_min=30):
    """Ước lượng thời gian chờ đơn giản từ occupancy."""
    available = total_ports * (1 - occupancy_ratio)
    
    if available >= 1:
        return 0  # Có trụ trống → không chờ
    else:
        # Ước lượng: chờ = (phần dư / tốc độ phục vụ)
        queue_position = 1  # giả sử 1 xe trước bạn
        service_rate = total_ports / avg_session_min  # xe/phút
        return queue_position / service_rate  # phút
```

**Pro:** Nhanh, dễ hiểu, demo được ngay  
**Con:** Rất thô, không có xác suất, không có confidence interval

#### Cách 2: Markov Chain (từ LSTM_Markov doc — chính xác nhất)

```
Input:  occupancy tại t, t+5, t+10, t+15  (từ XGBoost hoặc LSTM)
        ↓
Step 1: Tính trạng thái y_k = 1 (kẹt) hay 0 (trống) dựa trên ngưỡng
Step 2: Ước lượng r_k (xác suất giải phóng), b_k (xác suất chiếm lại)
Step 3: Tính π_k = P(kẹt tại mốc k)
Step 4: Tính G_k = P(vẫn kẹt liên tục từ lúc đến đến mốc k)
        ↓
Output: Phân phối thời gian chờ W
        - P(W = 0) = xác suất dùng ngay
        - Trung vị
        - P80, P90
        - E[W] = kỳ vọng
```

**Pro:** Có lý thuyết toán học chắc chắn, có phân phối xác suất đầy đủ  
**Con:** Cần r_k, b_k chính xác — hoặc ước lượng từ data hoặc dùng LSTM head

#### Cách 3: Queueing Theory M(t)/M/s (physics-informed)

```
Input:  Arrival rate λ(t) (từ ML prediction hoặc traffic data)
        Service rate μ    (từ avg session duration)
        s = total_ports   (số server)
        ↓
Model:  Non-stationary M(t)/M/s queue
        ↓
Output: P(wait > w) cho mọi w
        E[Wait time]
        Queue length distribution
```

**Pro:** Mô hình vật lý chính xác nhất khi biết λ(t) và μ  
**Con:** Cần biết arrival rate — thường phải ước lượng

### 3.3 Chiến lược đề xuất: XGBoost + Markov (MVP demo)

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│   XGBoost    │ ──→ │  Markov Chain │ ──→ │  Wait Time       │
│              │     │  (Toán học)   │     │  Distribution    │
│ Input:       │     │               │     │                  │
│ - lag_1..12  │     │ Input:        │     │ Output:          │
│ - hour_sin   │     │ - occ(t+5)    │     │ - P(W=0) = 22%  │
│ - weather    │     │ - occ(t+10)   │     │ - median = 5min  │
│ - calendar   │     │ - occ(t+15)   │     │ - P80 = 14min   │
│              │     │ - total_ports │     │ - E[W] = 7min   │
│ Output:      │     │               │     │                  │
│ occ(t+5,10,  │     │ Tính:         │     │ Phát biểu:       │
│       15)    │     │ r_k, b_k,     │     │ "Khoảng 5 phút.  │
│              │     │ π_k, G_k      │     │  80% ≤ 14 phút"  │
└──────────────┘     └───────────────┘     └──────────────────┘
```

> [!IMPORTANT]
> **Kết luận:** XGBoost KHÔNG dự đoán wait time trực tiếp, nhưng XGBoost + Markov Chain **HOÀN TOÀN CÓ THỂ** cho ra wait time probability distribution chất lượng cao, **và demo được ngay** mà không cần DL.

---

## 4. So sánh chi tiết khả năng từng mô hình

### 4.1 Bảng so sánh tổng quát

| Tiêu chí | XGBoost | LSTM + Markov | Transformer | STGNN |
|---|---|---|---|---|
| **Dự đoán occupancy** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Dự đoán wait time** | ⚠️ Cần Markov layer | ✅ Native (Markov head) | ⚠️ Cần wrapper | ⚠️ Cần wrapper |
| **Giải thích được (XAI)** | ⭐⭐⭐⭐⭐ (SHAP) | ⭐⭐⭐ (r_k, b_k interpretable) | ⭐⭐ (attention maps) | ⭐⭐ |
| **Data cần** | ~100K+ rows | ~500K+ rows | ~1M+ rows | ~1M+ rows, multi-station |
| **Bắt tình huống mới** | ❌ Kém | ⚠️ Trung bình | ⚠️ Trung bình | ⭐⭐⭐ (spatial transfer) |
| **Training effort** | 🟢 Phút | 🟡 Giờ | 🔴 Giờ-Ngày | 🔴 Ngày |
| **Deploy complexity** | 🟢 Rất dễ | 🟡 Trung bình | 🔴 Phức tạp | 🔴 Rất phức tạp |
| **Nhân quả** | ❌ Không | ⚠️ Semi (r_k, b_k có physical meaning) | ❌ Không | ⚠️ Spatial causality |

### 4.2 Mô hình nào phù hợp cho từng giai đoạn?

#### Giai đoạn 1: MVP Demo (Ngay bây giờ)
**→ XGBoost + Markov Chain rule-based**

```
Lý do:
✅ Data hiện tại đủ (2.6M rows occupancy + weather + calendar)
✅ Train trong vài phút
✅ SHAP giải thích được → biết feature nào quan trọng
✅ Markov layer cho wait time distribution
✅ Deploy dễ (joblib save/load)
✅ Baseline metric để so sánh sau này
```

#### Giai đoạn 2: LSTM + Markov Head (Khi có thêm data)
**→ Theo đúng thiết kế trong LSTM_Markov doc**

```
Lý do:
✅ Markov head cho wait time BY DESIGN — không cần wrapper
✅ r_k, b_k có ý nghĩa vật lý → giải thích được
✅ LSTM capture sequential patterns tốt hơn XGBoost
✅ Station embedding cho phép transfer learning
⚠️ Cần: thêm POI data, nhiều trạm hơn, ít nhất 1 năm data
```

#### Giai đoạn 3: Transformer / Foundation (Khi scale)
**→ Fine-tune TimesFM hoặc Chronos trên multi-domain data**

```
Lý do:
✅ Pretrained knowledge từ millions of time series
✅ Multi-horizon forecasting native
✅ Có thể handle exogenous variables
⚠️ Cần: rất nhiều data, GPU, causal validation layer
⚠️ PHẢI wrap bằng: SHAP + Markov + constraint validation
```

---

## 5. Chiến lược "cover" DL — Đảm bảo model làm đúng việc

### 5.1 Pre-DL Safeguards (Trước khi train)

| Safeguard | Mô tả | Áp dụng cho |
|---|---|---|
| **Causal feature selection** | Chỉ đưa feature có causal link vào model. Loại bỏ spurious correlations (VD: stock price KHÔNG ảnh hưởng charging) | Tất cả |
| **Temporal split** | Train/val/test theo thời gian, KHÔNG random shuffle → tránh data leakage | ✅ Đã làm |
| **Domain constraints** | 0 ≤ occupancy ≤ 1, wait_time ≥ 0 | Tất cả |

### 5.2 Post-DL Validation (Sau khi train)

| Validation | Mô tả | Tool |
|---|---|---|
| **SHAP analysis** | Feature nào model đang dùng? Có hợp lý không? | `shap` library |
| **Reliability diagram** | Khi model nói "70% occupancy" → thực tế có phải 70%? | Calibration plot |
| **Stress test** | Đưa edge cases vào: Tết, mưa bão, trạm 100% full, trạm mới | Manual test |
| **Persistence baseline** | Model phải tốt hơn "đoán bằng giá trị hiện tại" ít nhất 5% | MAE comparison |
| **Monotonicity check** | Rush hour → occupancy phải cao hơn 3AM. Mưa to → demand giảm | Logic validation |

### 5.3 Runtime Safety (Khi deploy)

```python
def safe_predict(model, features, total_ports):
    """Prediction với safety constraints."""
    raw_pred = model.predict(features)
    
    # Hard constraints
    pred = np.clip(raw_pred, 0.0, 1.0)  # occupancy trong [0, 1]
    
    # Confidence check
    if model_uncertainty(features) > THRESHOLD:
        return fallback_to_persistence(features)  # dùng giá trị hiện tại
    
    # Physics validation
    occupied = pred * total_ports
    if occupied > total_ports:
        occupied = total_ports  # không thể vượt capacity
    
    return pred
```

---

## 6. Tổng kết — Trả lời trực tiếp câu hỏi

### Q: DL có thực sự học được nhân quả không?
**A: Không.** DL học tương quan. Nhưng **không cần nhân quả** để dự đoán tốt, miễn là:
- Data đủ đa dạng (cover nhiều tình huống)
- Có Layer 2 (Markov/Queueing) xử lý phần "vật lý"
- Có Layer 3 (SHAP + constraints) để validate

### Q: Cần embedding không?
**A: XGBoost không cần. LSTM/Transformer cần.** Embedding sẽ tự học nếu có đủ data từ nhiều loại trạm.

### Q: XGBoost có dự đoán wait time được không?
**A: Gián tiếp — Có.** XGBoost → occupancy → Markov Chain → wait time distribution. Đây là pipeline **đề xuất cho MVP demo**.

### Q: Model nào làm ngay được?
**A: XGBoost + Markov layer.** Đây là giải pháp:
- ✅ Thực chiến nhất
- ✅ Demo được ngay
- ✅ Giải thích được (SHAP)
- ✅ Data hiện tại đủ
- ✅ Là baseline để so sánh khi scale lên DL sau

### Q: Khi nào nên scale lên DL?
**A: Khi có 3 điều kiện:**
1. XGBoost baseline đã chạy và có metric rõ ràng
2. Có thêm ít nhất 6 tháng data (để được 1 năm full seasons)
3. Có thêm domain data (POI, traffic proxy, session data)

Khi đó, scale lên LSTM + Markov head theo đúng thiết kế trong doc, với SHAP + calibration + stress test wrapping xung quanh.

> [!TIP]
> **Chiến lược tối ưu:** Bắt đầu từ XGBoost (nhanh, hiểu được, demo được), dùng SHAP để hiểu data → quyết định DL có giúp gì thêm không. Nếu XGBoost đã đủ tốt cho use case → **không cần DL**. DL chỉ thêm giá trị khi có **spatial patterns** (multi-station) hoặc **long-range temporal dependencies** mà XGBoost không capture được.
