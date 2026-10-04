# simulation_lab — môi trường độc lập cho data-simulator

Thư mục này là bản sao tự chứa (self-contained) của module mô phỏng phiên sạc EV. Mọi thao tác chỉnh tham số, debug và sinh output đều làm trong đây; **không đọc hay ghi** vào `data/`, `config/`, `scripts/`, `tests/` ở gốc repo. Mã gốc ở `simulator/` ngoài repo root vẫn giữ nguyên.

Mô phỏng theo kiểu discrete-event (SimPy): trạm → tốc độ đến λ(t) (Poisson không thuần nhất, theo giờ/ngày/thời tiết/POI) → xe và SOC → hàng đợi, cấp cổng (bỏ đi nếu chờ quá kiên nhẫn) → sạc → rút xe. Thiết kế chi tiết: [docs/simulator.md](docs/simulator.md); schema đầu ra: [docs/SIMULATOR_SESSION_SCHEMA.md](docs/SIMULATOR_SESSION_SCHEMA.md).

> Mọi bản ghi là **dữ liệu tổng hợp** (`is_synthetic = true`). Các hệ số trong config là *giả định*, không phải số đo. Không đưa output vào dữ liệu huấn luyện UrbanEV.

## Cấu trúc

```
simulation_lab/
├── simulator/            # mã nguồn: weather.py, arrivals.py, sessions.py
├── config/simulator.json # toàn bộ tham số kịch bản (seed, λ, xe, SOC, kiên nhẫn, rút xe...)
├── inputs/               # đầu vào đã chụp sẵn
│   ├── stations.geojson  #   bản sao data/static/stations.geojson
│   ├── vehicles.json     #   bản sao data/static/vehicles.json
│   └── weather_hcmc.json #   thời tiết theo giờ (lấy từ API một lần)
├── output/               # đầu ra của lần chạy
│   ├── sessions.csv, ports.csv      # đúng schema (chỉ trường quan sát được)
│   └── debug/arrivals.csv, queue_log.csv  # chỉ để kiểm thử (arrival, hàng đợi, bỏ đi)
├── reports/              # báo cáo kiểm tra (simulator_validation_report.md)
├── scripts/              # fetch_weather.py, validate_simulator.py
├── tests/                # pytest cho arrivals và sessions
├── docs/                 # bản sao tài liệu thiết kế và schema
├── requirements.txt
└── pytest.ini
```

## Cài đặt

Python 3.12. Chạy mọi lệnh **từ thư mục `simulation_lab/`** (import dạng `simulator.*`):

```powershell
cd simulation_lab
python -m pip install -r requirements.txt     # numpy, simpy, pytest, ruff
```

## Quy trình thường dùng

```powershell
python scripts\fetch_weather.py [--force]     # (tuỳ chọn, cần mạng) tải thời tiết vào inputs/
python -m simulator.arrivals                  # chỉ sinh lượt đến -> output/debug/arrivals.csv
python -m simulator.sessions                  # sinh lượt đến + mô phỏng -> output/*.csv
python scripts\validate_simulator.py          # kiểm tra 8 bất biến, ghi reports/
pytest                                        # chạy test
```

Tuỳ chọn: `--config <file>` (arrivals, sessions), `--output <file>` (arrivals), `--output-dir <dir>` (sessions). Ví dụ thử một kịch bản mà không đè output chính:

```powershell
copy config\simulator.json config\scenario_a.json
# sửa config\scenario_a.json (vd. demand_scale, patience_min)
python -m simulator.sessions --config config\scenario_a.json --output-dir output\scenario_a
```

`validate_simulator.py` luôn đọc `output/` mặc định; với `--output-dir` khác, hãy tạm chạy ở `output/` hoặc sửa hằng `SIMULATED` trong script.

## Chỉnh tham số (config/simulator.json)

| Nhóm | Khoá | Ý nghĩa |
|---|---|---|
| Chung | `seed`, `start_date`, `end_date`, `demand_scale` | Tái lập kết quả, khoảng mô phỏng, nhân tốc độ đến |
| Tốc độ đến | `rate_per_port_per_day` (AC/DC), `hour_factors_raw`, `weekday_factors_raw` | λ0 và hệ số giờ/ngày |
| Thời tiết, POI | `weather.*`, `poi_factor`, `poi_factor_bounds` | `f_weather` theo loại cổng; `g(POI)` bị chặn để không lấn át |
| Xe, SOC | `vehicle_weights`, `soc_start`, `soc_target`, `min_soc_gain` | Cơ cấu xe, SOC bắt đầu/mục tiêu |
| Hàng đợi | `patience_min`, `port_preference` | Kiên nhẫn (lognormal), ưu tiên DC trước |
| Phiên sạc | `connect_delay_min`, `auth_delay_min`, `idle_min_by_band`, `early_unplug` | Trễ cắm/xác thực, thời gian cắm thừa, rút sớm |
| Kiểm tra | `assumed_service_min` | Thời gian phục vụ giả định để đối chiếu Erlang-C |

Cùng `seed` + cùng config + cùng inputs cho output giống hệt (đã kiểm: bản trong thư mục này khớp byte-by-byte với bản gốc).

## Debug

- `output/debug/queue_log.csv`: từng lượt đến với độ dài hàng đợi, thời gian chờ, bỏ đi. Dùng khi thấy tỉ lệ bỏ đi hoặc thời gian chờ bất thường.
- `output/debug/arrivals.csv`: đầu ra của bước sinh lượt đến (trước khi vào hàng đợi). So với `sessions.csv` để biết bao nhiêu lượt bị bỏ.
- `reports/simulator_validation_report.md`: kết quả kiểm tra bất biến (`t_arrival ≤ t_connect ≤ t_charge_start < t_charge_end ≤ t_disconnect`, bảo toàn năng lượng, `P_peak ≤ min(cổng, xe)`...) cùng đối chiếu hàng đợi.
- Các trường simulation-only (`t_arrival`, `queue_len_on_arrival`, `wait_min`, `balked`, `reneged`, `soc_target`) chỉ nằm ở `debug/`, không có trong `sessions.csv`.

## Lưu ý đồng bộ

- `inputs/stations.geojson` và `vehicles.json` là **bản chụp**. Nếu dữ liệu trạm/xe ở `data/static/` đổi và muốn mô phỏng theo, hãy copy lại thủ công.
- Chỉnh code ở đây **không** tự cập nhật `simulator/` ở gốc repo (và ngược lại). Muốn đưa thay đổi về gốc, copy lại và nhớ đổi đường dẫn (`ROOT/"inputs"`, `ROOT/"output"`, `ROOT/"reports"`) về `data/...` tương ứng.
- Phạm vi giữ nguyên như branch `feat/data-simulator`: giá, phí, chi phí vẫn ngoài phạm vi; thời tiết/POI chỉ là đầu vào của mô hình λ, không được rò sang recommender hay `sessions`.
