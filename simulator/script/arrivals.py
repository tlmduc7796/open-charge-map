"""Mô hình xe đến: sinh lượt xe đến cho từng trạm bằng quá trình Poisson không đồng nhất
(thuật toán thinning). Xe đến theo trạm, không gắn nhãn AC/DC; việc chọn cổng thuộc bước
hàng đợi (sessions.py).

Tốc độ đến (xe/giờ) của một trạm tại thời điểm t:

    λ(t) = base × f_giờ[h] × f_thứ[d] × g_trạm

    base = Σ_c (số cổng loại c × r_c) / 24      (c ∈ {AC, DC})

Tức là một tốc độ chung cho trạm, bằng số cổng × trung bình có trọng số của r_DC và r_AC.
`g_trạm` là hệ số người dùng đặt cho từng trạm (`station_factor`, mặc định 1.0).
Mọi hệ số là giả định, đặt trong config. Lượt đến, hàng đợi và thời gian chờ chỉ dùng nội bộ
(debug), KHÔNG thuộc schema sessions (xem docs/SIMULATOR_SESSION_SCHEMA.md).

Dùng trong code:

    arrivals = generate_arrivals(config, stations, vehicles)   # đầu vào từ config.resolve()

Cùng seed trong config cho cùng kết quả.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

import numpy as np

LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh không có DST

# Các cột của arrivals.csv, theo đúng thứ tự ghi ra.
FIELDS = [
    "arrival_id",  # ARR_000001, đánh số sau khi sắp xếp theo thời gian
    "station_id",
    "t_arrival",  # thời điểm đến, ISO-8601 +07:00
    "vehicle_id",
    "soc_start",  # mức pin khi đến, [0, 1]
    "soc_target",  # mức pin muốn sạc tới, [0, 1]
    "patience_min",  # số phút chịu chờ tối đa trước khi bỏ đi
]


@dataclass(frozen=True)
class Station:
    """Một trạm với số cổng theo loại dòng điện và các chuẩn đầu cắm có trong trạm."""

    station_id: str
    ports: dict[str, int]  # {"AC": số cổng AC, "DC": số cổng DC}
    connectors: frozenset[str]  # ví dụ {"CCS2", "Type2"}


def load_stations(stations: list[dict]) -> list[Station]:
    """Đọc trạm từ snapshot. Chỉ dùng `station_id` và `ports[]` (connector, current).

    Ví dụ trạm có 2 cổng CCS2 DC + 2 cổng Type2 AC cho ports = {"AC": 2, "DC": 2}.
    """
    result = []
    for station in stations:
        ports = {"AC": 0, "DC": 0}
        for port in station["ports"]:
            ports[port["current"]] += 1
        result.append(
            Station(
                station_id=station["station_id"],
                ports=ports,
                connectors=frozenset(port["connector"] for port in station["ports"]),
            )
        )
    return result


def normalize(values: list[float]) -> list[float]:
    """Chia cho trung bình để trung bình mới bằng 1, nhờ đó `base` vẫn là tốc độ trung bình.

    Dùng cho bảng hệ số theo giờ (24 giá trị) và theo thứ (7 giá trị).
    """
    mean = sum(values) / len(values)
    return [value / mean for value in values]


def compatible_vehicles(station: Station, vehicles: list[dict], weights: dict[str, float]):
    """Các mẫu xe dùng được ít nhất một cổng của trạm (cùng chuẩn đầu cắm) và có trọng số > 0.

    Báo lỗi ValueError nếu không có xe nào, để cấu hình sai không bị bỏ qua âm thầm.
    """
    found = [
        vehicle
        for vehicle in vehicles
        if station.connectors & {*vehicle["ac_connectors"], *vehicle["dc_connectors"]}
        and weights.get(vehicle["vehicle_id"], 0) > 0
    ]
    if not found:
        raise ValueError(f"No compatible vehicle for {station.station_id}")
    return found


class RateModel:
    """Tính tốc độ đến λ(t) của một trạm từ config.

    Dùng: `model = RateModel(config)`, rồi `model.rate(station, when)` cho λ tại một thời điểm
    và `model.max_rate(station)` cho cận trên λ_max dùng khi thinning.
    """

    def __init__(self, config: dict):
        self.config = config
        self.hour_factors = normalize(config["hour_factors_raw"])
        self.weekday_factors = normalize(config["weekday_factors_raw"])

    def base_rate(self, station: Station) -> float:
        """Tốc độ nền (xe/giờ) = Σ số cổng × r_c / 24, tăng theo quy mô trạm."""
        rates = self.config["rate_per_port_per_day"]
        return sum(station.ports[c] * rates[c] for c in station.ports) / 24

    def factor(self, station: Station) -> float:
        """Hệ số nhu cầu của trạm do người dùng đặt (mặc định 1.0)."""
        return self.config["station_factor"].get(station.station_id, 1.0)

    def rate(self, station: Station, when: datetime) -> float:
        """λ (xe/giờ) tại thời điểm `when`: nền × giờ × thứ × hệ số trạm."""
        return (
            self.base_rate(station)
            * self.hour_factors[when.hour]
            * self.weekday_factors[when.weekday()]
            * self.factor(station)
        )

    def max_rate(self, station: Station) -> float:
        """Cận trên λ_max của trạm (mọi hệ số lấy giá trị lớn nhất), dùng cho thinning."""
        return (
            self.base_rate(station)
            * max(self.hour_factors)
            * max(self.weekday_factors)
            * self.factor(station)
        )


def sample_soc_start(rng: np.random.Generator, spec: dict) -> float:
    """Lấy mẫu SOC lúc đến theo Beta(a, b), dùng chung cho mọi xe và mọi loại cổng."""
    return float(rng.beta(spec["a"], spec["b"]))


def sample_soc_target(rng: np.random.Generator, options: list[dict]) -> float:
    """Chọn mức pin muốn sạc tới trong các giá trị cố định theo trọng số."""
    weights = np.array([option["weight"] for option in options], dtype=float)
    return float(options[int(rng.choice(len(options), p=weights / weights.sum()))]["value"])


def sample_lognormal(rng: np.random.Generator, spec: dict) -> float:
    """Lấy mẫu log-normal từ trung vị (`median`) và độ lệch (`sigma`); dùng cho độ kiên nhẫn."""
    return float(rng.lognormal(np.log(spec["median"]), spec["sigma"]))


def sample_arrival(
    rng: np.random.Generator,
    vehicles: list[dict],
    weights: dict[str, float],
    config: dict,
) -> dict:
    """Gán thuộc tính cho một lượt đến vừa được chấp nhận.

    Chọn mẫu xe theo trọng số (trong số xe tương thích), `soc_target`, `soc_start` (bị chặn
    trong soc_start_bounds và luôn thấp hơn soc_target ít nhất min_soc_gain) và độ kiên nhẫn.
    """
    probabilities = np.array([weights[v["vehicle_id"]] for v in vehicles], dtype=float)
    vehicle = vehicles[int(rng.choice(len(vehicles), p=probabilities / probabilities.sum()))]
    target = min(sample_soc_target(rng, config["soc_target"]), 1.0)
    low, high = config["soc_start_bounds"]
    start = sample_soc_start(rng, config["soc_start"])
    start = min(max(start, low), high, target - config["min_soc_gain"])
    return {
        "vehicle_id": vehicle["vehicle_id"],
        "soc_start": round(start, 3),
        "soc_target": round(target, 3),
        "patience_min": round(sample_lognormal(rng, config["patience_min"]), 1),
    }


def station_rng(seed: int, station: Station) -> np.random.Generator:
    """Bộ sinh ngẫu nhiên riêng cho từng trạm, suy ra từ seed + station_id.

    Nhờ vậy thêm hoặc bớt một trạm không làm đổi dữ liệu của các trạm khác.
    """
    key = [seed, zlib.crc32(station.station_id.encode())]
    return np.random.default_rng(np.random.SeedSequence(key))


def generate_station(
    station: Station,
    model: RateModel,
    vehicles: list[dict],
    window: tuple[datetime, datetime],
) -> list[dict]:
    """Sinh toàn bộ lượt đến của một trạm bằng thinning (Lewis-Shedler).

    Cách làm: sinh các thời điểm ứng viên với tốc độ cố định λ_max (khoảng cách ~ Exp(λ_max)),
    mỗi ứng viên được giữ lại với xác suất λ(t)/λ_max, nên số xe đến theo đúng λ(t) thay đổi
    theo giờ và thứ. `window` là (start, end).
    """
    start, end = window
    config = model.config
    weights = config["vehicle_weights"]
    candidates = compatible_vehicles(station, vehicles, weights)
    rng = station_rng(config["seed"], station)
    max_rate = model.max_rate(station)
    if max_rate <= 0:  # nhu cầu bằng 0: trạm không có lượt đến
        return []

    rows = []
    when = start
    while True:
        when += timedelta(hours=float(rng.exponential(1 / max_rate)))
        if when >= end:
            return rows
        if rng.random() * max_rate < model.rate(station, when):
            rows.append(
                {
                    "station_id": station.station_id,
                    "t_arrival": when.isoformat(timespec="seconds"),
                    **sample_arrival(rng, candidates, weights, config),
                }
            )


def simulation_window(config: dict) -> tuple[datetime, datetime]:
    """Trả về (start, end) theo giờ Việt Nam: 00:00 của start_date đến 00:00 ngày sau end_date.

    end_date được tính trọn ngày. Trạm bắt đầu trống lúc 00:00, chấp nhận được vì tải giờ này thấp.
    """
    start = datetime.combine(
        datetime.fromisoformat(config["start_date"]).date(), time.min, tzinfo=LOCAL_TZ
    )
    end = datetime.combine(
        datetime.fromisoformat(config["end_date"]).date(), time.min, tzinfo=LOCAL_TZ
    ) + timedelta(days=1)
    return start, end


def generate_arrivals(config: dict, stations: list[dict], vehicles: list[dict]) -> list[dict]:
    """Hàm chính: sinh lượt đến cho mọi trạm.

    Gộp kết quả, sắp xếp theo thời gian rồi đánh `arrival_id`. Là hàm thuần (không đọc file,
    không gọi mạng), nên test được bằng config và trạm giả.
    """
    model = RateModel(config)
    window = simulation_window(config)
    rows = []
    for station in load_stations(stations):
        rows.extend(generate_station(station, model, vehicles, window))
    rows.sort(key=lambda row: (row["t_arrival"], row["station_id"]))
    for index, row in enumerate(rows, start=1):
        row["arrival_id"] = f"ARR_{index:06d}"
    return rows
