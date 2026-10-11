# simulator — sinh dữ liệu phiên sạc từ catalog trong database

Mô phỏng kiểu discrete-event (SimPy): trạm → tốc độ đến λ(t) → xe và SOC → hàng đợi, cấp cổng
(bỏ đi nếu chờ quá kiên nhẫn) → sạc → rút xe. Trạm, cổng và xe lấy từ database; người dùng chỉ
chỉnh một file config nhỏ.

> Mọi bản ghi là **dữ liệu tổng hợp** (`is_synthetic = true`). Các tham số là *giả định*, không
> phải số đo. Chỉ dùng cho phát triển và đánh giá offline.

## Dùng

Python 3.12, chạy mọi lệnh từ thư mục `simulator/`:

```powershell
python -m pip install -r requirements.txt   # numpy, simpy, psycopg
python -m script pull                    # DB (chỉ đọc) -> data/catalog_snapshot.json
python -m script run                     # sinh lượt đến + phiên sạc + kiểm tra -> data/
python -m script occupancy               # sessions.csv + ports.csv -> data/station_occupancy_5m.csv
python -m script feed                    # phát lại station_occupancy_5m.csv vào backend mỗi 5 phút
```

- `pull` đọc `DATABASE_URL` (tham số `--database-url`, biến môi trường, `.env` gốc repo; mặc định là
  DB demo `127.0.0.1:5433`), chỉ chạy SELECT trong transaction READ ONLY, và tạo
  `simulator.config.json` nếu chưa có, với `station_factor` liệt kê sẵn mọi trạm (1.0) để sửa.
- `run` đọc snapshot + `simulator.config.json`, ghi vào `data/`, thoát mã ≠ 0 nếu vi phạm bất biến.
- Dùng `--config` và `--data-dir` để chạy nhiều kịch bản song song.

## Tham số

`simulator.config.json` chỉ cần chứa phần bạn muốn đổi; khoá lạ là lỗi.

| Khoá | Ý nghĩa | Mặc định |
|---|---|---|
| `seed` | tái lập kết quả | 20260801 |
| `start_date`, `end_date` | cửa sổ mô phỏng (tính trọn ngày) | 2026-08-01 … 2026-08-30 |
| `stations` | `"all"` hoặc danh sách mã trạm | `"all"` |
| `rate_per_port_per_day` | lượt đến / cổng / ngày, theo `DC` và `AC` | `{DC: 18, AC: 4.5}` |
| `station_factor` | `{mã trạm: hệ số}` nhân nhu cầu của trạm, trong [0.5, 2.0]; `pull` liệt kê sẵn mọi trạm | 1.0 |
| `vehicle_weights` | `{mã xe: trọng số}`; xe không liệt kê có trọng số 0 | chia đều |
| `soc_start`, `soc_target` | phân phối SOC khi đến (Beta) và mức muốn sạc tới | xem `config.example.json` |
| `patience_min` | kiên nhẫn chờ (log-normal: `median`, `sigma`) | median 20.9 |

Khối `advanced` (hệ số theo giờ/thứ, trễ cắm, idle, rút sớm, giả định về xe) có mặc định trong
`script/config.py`; ghi đè dưới khoá `advanced` khi cần.

## Đầu ra (`data/`, không commit)

| File | Nội dung |
|---|---|
| `sessions.csv`, `ports.csv` | đúng `docs/SIMULATOR_SESSION_SCHEMA.md` |
| `debug/arrivals.csv`, `debug/queue_log.csv` | lượt đến, hàng đợi, xe bỏ đi (chỉ để kiểm thử) |
| `validation_report.md` | kết quả các bất biến và thống kê hàng đợi |
| `run_manifest.json` | seed, sha256 snapshot/config/`sessions.csv`, số dòng |
| `station_occupancy_5m.csv` | do `occupancy` sinh; cột bảng `station_occupancy_5m` trừ `id`, `queue_length` |

> **Nạp vào database:** `database/compose.yaml` bind-mount thư mục `simulator/data/` và nạp 30 ngày gần
> nhất của `station_occupancy_5m.csv` mỗi khi container Postgres khởi động (xem `database/README.md`).
> Cần chạy `python -m script run` và `python -m script occupancy` trước.

`occupancy` đọc `sessions.csv`, `ports.csv` và ánh xạ mã trạm → UUID từ
`database/data/catalog/stations.sql` (không cần DB). Mỗi trạm × mỗi mốc 5 phút của các ngày trọn
vẹn có phiên (hoặc `--start-date/--end-date`): `occupied_ports` là số cổng có xe đang cắm tại đúng
mốc đó (`t_connect <= bucket_at < t_disconnect`, gồm cả xe đã sạc xong chưa rút);
`total_ports = operational_ports` vì simulator không có cổng hỏng. Không xuất `queue_length`
(nạp vào bảng sẽ là NULL). Ngày đầu bắt đầu từ trạng thái rỗng nên vài giờ đầu thấp hơn thực tế.

Cùng snapshot + config + seed cho `sessions.csv` giống hệt (so `sessions_sha256`).

## Phát lại occupancy vào backend (`feed`)

`feed` đóng vai nguồn đo thật: mỗi mốc 5 phút nó gửi **một batch** số cổng đang dùng của mọi trạm tới
`POST /api/v1/internal/station-occupancy`, nên trạng thái trạm trong backend luôn "tươi" mà không cần
bật `DEMO_RANDOM_SIMULATION`.

```powershell
python -m script feed                      # gửi ngay, rồi mỗi 5 phút (Ctrl+C để dừng)
python -m script feed --once               # đúng một batch rồi thoát
python -m script feed --dry-run            # chỉ in batch, không gọi backend
python -m script feed --at 2026-10-12T16:05:00+07:00 --dry-run   # giả lập thời điểm gửi
```

| Tham số | Mặc định |
|---|---|
| `--api-url` | `FEED_API_URL`, rồi `http://127.0.0.1:8000` |
| `--api-key` | `INTERNAL_API_KEY` (môi trường hoặc `.env` gốc repo); bắt buộc trừ khi `--dry-run` |
| `--csv` | `<data-dir>/station_occupancy_5m.csv` |
| `--delay-s` | 15: chờ sau mỗi mốc 5 phút rồi mới gửi |

- **Chọn dòng nguồn:** bucket hiện tại nằm trong khoảng dữ liệu của CSV thì phát lại đúng bucket đó;
  ngoài khoảng thì dịch theo **bội số 7 ngày** (cùng thứ, cùng giờ), như `load_history.sql`. CSV phải
  phủ ít nhất 7 ngày.
- **Ánh xạ:** UUID trong CSV được đổi sang mã trạm (`stations.code`) bằng
  `database/data/catalog/stations.sql`.
- **Chịu lỗi:** lỗi mạng/5xx thử lại 3 lần (chờ 2 s, 4 s); trạm backend báo "không tồn tại" bị bỏ rồi
  gửi lại phần còn lại (backend ghi cả batch trong một transaction); lỗi một lượt không dừng vòng lặp.
- **Độ cũ:** backend coi trạm là `unknown` khi bucket mới nhất cũ hơn `STATION_STATUS_STALE_AFTER_S`
  (mặc định 900 s = 3 nhịp bỏ lỡ).

## Cấu trúc

```
simulator/
├── config.example.json   # tham số người dùng
├── script/               # config, db, arrivals, sessions, validate, __main__
└── tests/                # pytest; fixtures/catalog_snapshot.json thay DB
```

```powershell
pytest                    # không cần DB
$env:SIMULATOR_TEST_DATABASE_URL = "..."   # tuỳ chọn: chạy test kéo DB thật (DB đã bootstrap)
```

## Giới hạn cần nhớ

- Công suất sạc cố định `P = min(công suất cổng, công suất xe)`, chưa có đường cong theo SOC; thời
  gian sạc suy ra từ vật lý, không học từ dữ liệu sạc thật.
- Không có thời tiết, POI hay ngày lễ; nhu cầu theo giờ/thứ là hệ số đặt tay.
- Database seed hiện chỉ có 1 mẫu xe và cổng CCS2 80 kW, nên cơ cấu xe và loại cổng rất hẹp.
