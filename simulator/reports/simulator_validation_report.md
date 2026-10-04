# Báo cáo kiểm định dữ liệu phiên sạc mô phỏng

- Trạng thái: **PASS**
- Số phiên sạc: 4020; số cổng: 9; số lượt đến: 5305
- Nguồn kiểm tra: docs/SIMULATOR_SESSION_SCHEMA.md mục 7 (8 bất biến)

## Thống kê theo loại cổng

| Loại cổng | Số phiên | Sạc TB (phút) | Idle TB (phút) | Chiếm cổng TB (phút) | Rút sớm |
|---|---|---|---|---|---|
| DC | 2775 | 22 | 20 | 44 | 12% |
| AC | 1245 | 210 | 46 | 258 | 16% |

## Hàng đợi (từ debug/queue_log.csv, chỉ để kiểm thử)

| Trạm | Lượt đến | Bỏ đi | Được phục vụ phải chờ | Chờ TB khi phải chờ (phút) |
|---|---|---|---|---|
| ST_EVO_AUDI_HCM | 3024 | 18% | 34% | 13.1 |
| ST_EVO_DEUTSCHES_HAUS | 1360 | 38% | 20% | 16.1 |
| ST_EVO_LAVIDA_Q7 | 921 | 25% | 29% | 15.6 |

### Theo giờ đến

| Giờ | Lượt đến | Phải xếp hàng (có xe chờ lúc đến) | Bỏ đi |
|---|---|---|---|
| 00 | 25 | 0% | 20% |
| 01 | 20 | 0% | 10% |
| 02 | 11 | 0% | 9% |
| 03 | 20 | 0% | 5% |
| 04 | 21 | 0% | 0% |
| 05 | 42 | 2% | 10% |
| 06 | 78 | 1% | 3% |
| 07 | 129 | 2% | 6% |
| 08 | 197 | 3% | 7% |
| 09 | 239 | 5% | 11% |
| 10 | 348 | 13% | 15% |
| 11 | 504 | 31% | 29% |
| 12 | 618 | 48% | 43% |
| 13 | 459 | 43% | 42% |
| 14 | 289 | 25% | 27% |
| 15 | 292 | 16% | 19% |
| 16 | 292 | 13% | 16% |
| 17 | 377 | 16% | 20% |
| 18 | 439 | 26% | 29% |
| 19 | 349 | 25% | 26% |
| 20 | 233 | 10% | 16% |
| 21 | 171 | 8% | 12% |
| 22 | 101 | 5% | 17% |
| 23 | 51 | 4% | 22% |

## Ghi chú

- Lý do kết thúc: {'target_reached': 3501, 'user_unplug': 519}.
- Tất cả tham số hành vi (kiên nhẫn, idle theo giờ, xác suất rút sớm, công suất cố định) là giả định trong config/simulator.json, không phải số đo thực tế.
- Hàng đợi, thời gian chờ và xe bỏ đi không thuộc schema sessions (chỉ nằm trong debug).
