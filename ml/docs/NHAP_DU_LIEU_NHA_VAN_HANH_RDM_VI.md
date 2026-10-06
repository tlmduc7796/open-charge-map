# Nhập dữ liệu nhà vận hành để train RDM

## Mục tiêu

Tài liệu này là cổng vào duy nhất cho dữ liệu vận hành thật của Việt Nam. Nó
không biến file CSV bất kỳ thành dữ liệu đủ điều kiện production: trước tiên
chuẩn hóa, giữ lineage, kiểm tra nhãn và tách train/validation/test theo thời
gian/session.

## Ba file cần nhận từ provider

1. **Sessions:** mỗi phiên có `session_id`, `station_id`, `port_id`,
   `connection_at`, `disconnect_at`; `done_charging_at` và tổng điện cuối phiên
   được phép có nhưng không là feature. Thiếu `disconnect_at` được giữ là
   censored và bị loại khỏi nhãn RDM.
2. **Telemetry:** mỗi lần quan sát có `session_id`, `station_id`, `port_id`,
   `observed_at`, `energy_delivered_kwh`, `current_power_kw`. Nên có
   `received_at` để kiểm tra event đến trễ.
3. **Port inventory:** `station_id`, `port_id`, `max_power_kw`. Đây là ảnh chụp
   cấu hình cổng tại giai đoạn export, không được lấy thông số hiện tại gán ngược
   cho dữ liệu quá khứ nếu cổng đã thay đổi.

Timestamp bắt buộc có timezone. Hệ thống lưu UTC, nhưng tự tạo giờ/thứ theo
`Asia/Ho_Chi_Minh` để model học nhịp trong ngày.

## Các bước chạy

```powershell
# 1. Chuẩn hóa raw export. `provider_hcm` là tên giả; thay bằng nguồn thật.
.\.venv\Scripts\python.exe ml\src\prepare_operator_rdm_data.py `
  --sessions ml\data\raw\provider\sessions.csv `
  --telemetry ml\data\raw\provider\telemetry.csv `
  --source provider_hcm `
  --sessions-output ml\data\silver\provider\sessions.parquet `
  --telemetry-output ml\data\silver\provider\telemetry.parquet

# 2. Tạo bảng học RDM cơ bản, an toàn cho vận hành.
.\.venv\Scripts\python.exe ml\src\build_rdm_dataset.py `
  --sessions ml\data\silver\provider\sessions.parquet `
  --telemetry ml\data\silver\provider\telemetry.parquet `
  --port-inventory ml\data\raw\provider\ports.csv `
  --output ml\data\gold\provider\rdm_live_safe.parquet `
  --train-end 2026-06-01T00:00:00+07:00 `
  --validation-end 2026-08-01T00:00:00+07:00

# 3. Chỉ train/validation trước; không mở test khi còn đang chỉnh model.
.\.venv\Scripts\python.exe ml\src\train_rdm_quantile.py `
  --dataset ml\data\gold\provider\rdm_live_safe.parquet `
  --artifact-dir ml\artifacts\rdm\provider_live_safe `
  --feature-profile live_safe --execute
```

Tên cột kiểu OCPP/vendor thông dụng như `sessionID`, `stationID`, `portID`,
`EVSEID`, `connectionTime`, `disconnectTime`, `kWhDelivered`, `power_kw` được
adapter nhận diện. Nếu provider có schema khác, thêm adapter riêng; không sửa
thẳng model để nuốt raw CSV.

## Rào chắn chống leakage

Feature RDM cơ bản chỉ gồm dữ liệu đã biết tại `observed_at`: thời gian đã cắm,
điện đã cấp, công suất hiện tại, cổng/trạm/connector, công suất danh định cổng,
giờ/thứ địa phương và cờ đang rút điện.

Không được đưa `disconnect_at`, `done_charging_at`, điện năng cuối phiên, SOC
khi rời, idle duration hay lý do kết thúc vào feature. Các cột này là nhãn hoặc
biến chỉ biết sau tương lai.

## Trước khi train và nối Queue Lab

- Xem manifest cạnh từng Parquet: số dòng, hash raw input, số session censored
  và feature thực tế.
- Chấm baseline theo station/connector/giai đoạn phiên trước, rồi mới so RDM.
- Test là giai đoạn thời gian cuối, chỉ mở sau khi đóng thiết kế theo validation.
- Replay P10/P50/P90 vào Queue Lab và chấm sai số thời điểm bắt đầu sạc.
- Provider duration vẫn được ưu tiên. RDM chỉ là fallback sau calibration,
  monitoring telemetry stale và rollback review.

Raw operator data có thể chứa dữ liệu nhạy cảm. Không commit vào Git, chỉ giữ
theo chính sách retention/quyền truy cập của provider.
