# Phase 06 occupancy forecast and wait validation report

**Result:** `DEMO PASS / RELEASE BLOCKED`

**Branch:** `demo/backend-first`
**Validation date:** `2026-09-25`

## Completed for the backend demo

- `OccupancyForecastService` với interface 12-step occupancy ratio và horizon
  +5/+10/+15 phút.
- Persistence fallback có `prediction_source=persistence`; không giả mạo kết quả ML.
- Cờ horizon alignment, beyond-model-horizon, offline station, prediction clamp và
  model-inference failure.
- Synthetic repeated history chỉ dùng khi một model adapter được inject mà caller chưa có
  history; limitation được trả bằng flag.
- Schema/repository validation cho planned arrivals và queue assumptions.
- Baseline arrival rate, per-scenario override và planned-arrival projected rate.
- Erlang C wait estimator với current queue state tách riêng.
- Finite scoring cap cho overload và station offline.
- Config cho artifact, preprocessor, metadata và wait cap.
- Services được khởi tạo cùng FastAPI application state.

## Verification

- PASS — `33 passed` với `python -m pytest`.
- PASS — `ruff check backend` không có lỗi.
- PASS — persistence forecast trả occupancy hợp lệ và clamp theo capacity.
- PASS — còn cổng trống và không queue trả immediate wait bằng 0.
- PASS — full station + queue trả wait dương.
- PASS — tăng queue không làm wait giảm trong cùng điều kiện.
- PASS — port outage không làm wait giảm trong test cùng mức full/queue.
- PASS — invalid runtime capacity bị schema từ chối.
- PASS — planned arrivals bật/tắt được; hai planned arrivals tại Deutsches Haus tạo
  projected rate `6.6 vehicles/hour` trong evaluation window kiểm thử.
- PASS — overload trả `OVERLOADED`, `CAPPED_WAIT` và wait cap 120 phút.
- PASS — scenario override áp dụng đúng cặp scenario/station.

## Goal items not covered

1. **Load model/preprocessor/meta thật:** chưa cover vì Phase 03–04 được chủ động deferred
   trên nhánh demo và `ml/artifacts` chưa có artifact đã benchmark.
2. **UrbanEV-trained inference:** chưa cover vì không có model được chọn bằng tiêu chí
   MAE tốt hơn persistence ít nhất 5%. Demo hiện chỉ chạy persistence thật.
3. **Feature-contract validation đối với artifact:** interface đã khóa 12-step ratio và
   horizon, nhưng chưa thể đối chiếu metadata/artifact chưa tồn tại.
4. **Historical occupancy window thật của trạm Việt Nam:** chưa có nguồn history runtime;
   adapter hỗ trợ caller truyền history, còn synthetic repeated window được gắn flag rõ ràng.
5. **Đánh giá wait với observed ground truth:** UrbanEV không cung cấp queue/wait ground truth
   và `station_history.csv` là optional chưa được tạo. Phase 06 chỉ có deterministic sanity tests.

Các mục 1–3 chặn release gate. Mục 4–5 không chặn demo backend nhưng phải được trình bày
như limitation, không được gọi là dữ liệu thực hoặc metric thực địa.
