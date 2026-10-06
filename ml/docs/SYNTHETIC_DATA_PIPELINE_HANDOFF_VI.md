# Handoff: ACN → CTGAN → Gold synthetic data

## Mục đích của giai đoạn này

Repository chưa có lịch sử phiên sạc hoặc occupancy công khai của Việt Nam đủ
để train và đánh giá ML. Giai đoạn này tạo **dữ liệu tổng hợp có provenance**
để kiểm tra pipeline, XGBoost occupancy, RDM và logic DES. Nó không tạo ground
truth vận hành của Việt Nam và không cho phép bật serving production.

Luồng dữ liệu hiện tại:

```text
ACN-Data Caltech 2018–2021 (raw session summaries)
  → privacy-minimized behavior table
  → CTGAN behavior prior
  → matched Vietnam station topology, provider_reported only
  → physical allocation and replay
  → Gold sessions / telemetry_5min / occupancy_5min
```

## Những gì đã lấy và đã tạo

### External ACN source

`ml/data/external/acn/raw/` là Git-ignored. Đã tải session summary Caltech:

| Năm | Sessions |
| --- | ---: |
| 2018 | 15,297 |
| 2019 | 10,617 |
| 2020 | 2,472 |
| 2021 | 3,038 |
| Tổng | 31,424 |

Raw ACN không được commit vì dung lượng và vì API token. Các manifest cạnh
file raw ghi hash, thời điểm tải và source. Không đặt token trong source;
collector đọc `ACNDATA_API_TOKEN` từ environment hoặc `.env` bị ignore.

ACN charging-current time series đã được thử trên lát thời gian nhỏ để xác
minh adapter. Chưa mirror toàn bộ time series 2018–2021: API phục vụ series
theo session, nên hơn 31k sessions sẽ cần công việc tải tiếp có checkpoint,
rate limit và kiểm tra retention riêng.

### CTGAN behavior prior

`ml/src/build_ctgan_behavior_dataset.py` gộp raw exports, de-duplicate và
loại bỏ user ID, ACN session ID, station/port ID và disconnect timestamp khỏi
features CTGAN. CTGAN chỉ học các biến hành vi nguồn:

- giờ đến, thứ đến;
- thời gian đỗ và thời gian sạc;
- năng lượng giao/yêu cầu và minutes available.

`ml/src/train_ctgan_behavior.py` train sampler local. `30 epochs` được chọn
cho scenario Gold hiện tại sau khi fidelity check trên held-out 2021 tốt hơn
run 200 epochs theo sai lệch tổng hợp. Đây là lựa chọn experiment, không phải
claim về hành vi Việt Nam. Kết quả fidelity nằm ở `ml/results/ctgan/` (ignored).

### Vietnam topology policy

`data/static/stations.geojson` là candidate catalog, không phải GeoJSON
FeatureCollection. Generator chỉ dùng candidate thỏa cả hai điều kiện:

1. có `matched_station_id`; và
2. `verification.technical_status == "provider_reported"`.

Vì vậy 16 trạm/211 cổng được dùng. Những candidate có connector gắn nhãn
`synthetic` hoặc `unknown` không bị biến thành ràng buộc vật lý giả.

## Gold product hiện có

Scenario: HCM topology, 01/01/2026–01/04/2026 local time, seed `20261004`,
`1.5 sessions/port/day` là **scenario assumption**. Output ở
`ml/data/gold/hcmc_ctgan_q1_2026/` và đều Git-ignored.

| File | Grain | Dùng cho |
| --- | --- | --- |
| `stations.parquet` | station | inventory, topology confidence |
| `ports.parquet` | port | connector và max power |
| `sessions.parquet` | session | RDM lifecycle labels, DES replay |
| `telemetry_5min.parquet` | session × 5 phút | RDM features/labels |
| `occupancy_5min.parquet` | station × 5 phút | XGBoost occupancy, LSTM experiment |

Gold output buộc các invariant: một session trên một port tại một thời điểm,
energy không vượt công suất port × thời lượng × hiệu suất giả định, queue tối
đa 120 phút, occupancy không vượt capacity. Mọi bảng có `is_synthetic=true`,
`source=acn_ctgan_conditioned_vietnam_topology`, `quality_flag` synthetic,
manifest hash và temporal split 60/20/20.

`telemetry_5min` là replay piecewise-constant từ Gold sessions; nó không phải
dòng/công suất đo thực tế từ trạm. Vì vậy chỉ dùng để test RDM pipeline và
replay/DES, không dùng làm bằng chứng accuracy của RDM trong vận hành.

## Train được gì ngay bây giờ?

1. **XGBoost occupancy:** có thể train benchmark end-to-end từ
   `occupancy_5min.parquet`. Output chỉ là `synthetic evaluation model`, không
   được đưa backend serving.
2. **RDM quantile:** có thể build observation dataset từ `sessions.parquet` và
   `telemetry_5min.parquet`, sau đó train để kiểm tra split, leakage và contract.
   Accuracy không đại diện cho provider telemetry thật vì telemetry là synthetic.
3. **LSTM/Markov/Transformer:** chưa nên coi là bước kế tiếp. LSTM có thể chạy
   research experiment sau baseline XGBoost, nhưng không có lý do để tin nó tốt
   hơn. Markov cần state/port-status product; Transformer cần lịch sử thật và
   context được phục vụ khi inference.

## Lệnh tái lập

```powershell
# Gộp ACN historical summary thành behavior dataset
.\.venv\Scripts\python.exe ml\src\build_ctgan_behavior_dataset.py `
  --input ml\data\external\acn\raw\acn_caltech_2018_sessions.json `
          ml\data\external\acn\raw\acn_caltech_2019_sessions.json `
          ml\data\external\acn\raw\acn_caltech_2020_sessions.json `
          ml\data\external\acn\raw\acn_caltech_2021_sessions.json `
  --output ml\data\derived\acn\ctgan_behavior_2018_2021.parquet `
  --train-end 2020-06-30T23:59:59+00:00 `
  --validation-end 2021-03-31T23:59:59+00:00

# Tái sinh Gold scenario
.\.venv\Scripts\python.exe ml\src\build_gold_synthetic.py `
  --model ml\artifacts\ctgan\acn_caltech_behavior_2018_2021.pkl `
  --stations data\static\stations.geojson `
  --output-dir ml\data\gold\hcmc_ctgan_q1_2026 `
  --start 2026-01-01 --end 2026-04-01 --sessions-per-port-day 1.5
```

## Việc tiếp theo

Baseline XGBoost occupancy và quantile RDM đã được train trên Gold để xác minh
training contracts; artifacts/metrics đều là `synthetic_evaluation_only`. Để
đi tới production, cần OCPP/operator data Việt Nam append-only, telemetry thật,
audit freshness/missingness, backtest theo thời gian, calibration và review
quyền riêng tư trước khi đổi serving status.

## Kết quả train và benchmark hiện tại

Ba experiment đã chạy trên Gold Q1/2026. Test của occupancy đã được mở có chủ
đích cho benchmark exploratory; không được dùng để tiếp tục chọn hyperparameter.

| Experiment | Validation mean MAE | Kết quả |
| --- | ---: | --- |
| Persistence occupancy | 0.049078 | Baseline: dự báo trạng thái hiện tại giữ nguyên. |
| XGBoost, 12 lag | 0.070331 | Thua persistence ở cả 12 horizon. |
| XGBoost, 12 lag + seasonal prior | 0.071334 | Cũng thua persistence ở cả 12 horizon. |

Ví dụ validation: ở +5 phút persistence MAE `0.016286`, XGBoost baseline
`0.024643`, seasonal `0.025824`; ở +60 phút lần lượt `0.078358`, `0.109355`,
`0.109020`. Do đó không có occupancy model nào được promote, và không nên thử
LSTM/Transformer chỉ để tìm một model phức tạp hơn. Với Gold simulator hiện
tại, trạng thái occupancy vừa quan sát đã là dự báo tốt hơn.

RDM quantile đã train với 499,279 train observations và 168,749 validation
observations. Validation p50 có MAE `186.42` phút, median absolute error
`137.01` phút; coverage p10/p50/p90 là `11.1% / 50.6% / 87.7%`, quantile
crossing `0.43%`. Test RDM chưa được mở. Các số này chỉ cho biết contract,
split và quantile artifact chạy được trên telemetry synthetic; chúng không
cho biết hệ thống dự đoán người dùng Việt Nam chính xác bao nhiêu.

## Có thể tích hợp model vào hệ thống chưa?

**Chưa cho live/production.** Không có artifact nào được backend tự động nạp
hoặc dùng để quyết định route/ETA. Có thể dùng chúng trong Queue Lab, DES và
offline demo với nhãn rõ `synthetic_evaluation_only`:

- Occupancy: dùng **persistence** làm baseline demo; không dùng hai XGBoost
  artifact vì chúng thua baseline theo MAE.
- RDM: DES có thể nhận ba duration scenario từ artifact quantile: `p10` là
  optimistic, `p50` là typical, `p90` là conservative. Đây là ý nghĩa đúng
  của thiết kế "nhiều kết quả", thay vì ép một ETA duy nhất.
- Một câu trả lời UI an toàn có thể là: "Khả năng có cổng trong 10–35 phút;
  kịch bản điển hình 20 phút; confidence thấp vì là mô phỏng." Khoảng này chỉ
  hợp lệ trong demo/replay cho đến khi được calibration trên event thật.

Occupancy artifact hiện trả nhiều **horizon** (+5 đến +60 phút) nhưng vẫn là
point forecast cho mỗi horizon; nó chưa có prediction interval. Muốn khoảng
uncertainty occupancy thật sự cần quantile/conformal model hoặc ensemble,
rồi calibration bằng historical operator data.

### Gate trước khi đưa vào production

1. Thu OCPP/operator VN append-only: snapshot occupancy, fault/offline,
   port/session lifecycle và `disconnect_at`.
2. Rebuild cùng schema, audit timezone/freshness/missingness và phân quyền.
3. Backtest rolling-origin so với persistence theo station, connector và giờ
   cao điểm; chỉ promote model nếu thắng rõ rệt và calibrated.
4. Replay RDM p10/p50/p90 trong DES, so predicted wait với wait thật; thiết
   lập fallback về operator duration hoặc "không đủ dữ liệu" khi telemetry stale.
5. Chỉ sau các gate đó mới viết serving adapter và bật feature flag có giám sát.
