"""Mô hình xe đến: sinh lượt xe đến cho từng trạm bằng quá trình Poisson không đồng nhất
(thuật toán thinning). Xe đến theo trạm, không gắn nhãn AC/DC; việc chọn cổng thuộc bước
hàng đợi.

Tốc độ đến (xe/giờ) của một trạm tại thời điểm t:

    λ(t) = base × f_giờ[h] × f_thứ[d] × f_thời_tiết[w] × g_poi

    base = Σ_c (số cổng loại c × r_c) × demand_scale / 24      (c ∈ {AC, DC})

Tức là một tốc độ chung cho trạm, bằng số cổng × trung bình có trọng số của r_DC và r_AC.
Hệ số thời tiết của trạm là trung bình có trọng số (theo số cổng × r_c) của hệ số AC và DC.
Mọi hệ số là giả định, đặt trong config/simulator.json. Lượt đến, hàng đợi và thời gian chờ
chỉ dùng nội bộ (debug), KHÔNG thuộc schema sessions (xem docs/SIMULATOR_SESSION_SCHEMA.md).

Cách dùng:

    # 1. Lấy thời tiết một lần (cần mạng): python scripts/fetch_weather.py
    # 2. Sinh lượt đến, ghi output/debug/arrivals.csv:
    python -m simulator.arrivals
    python -m simulator.arrivals --config config/simulator.json --output out.csv

    # Dùng trong code (ví dụ trong test):
    rows = generate_arrivals(config, stations_geojson, vehicles, weather_by_hour)

Mỗi dòng đầu ra có các cột trong FIELDS. Cùng seed trong config cho cùng kết quả.
"""

from __future__ import annotations

import argparse
import csv
import json
import zlib
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np

from simulator.weather import LOCAL_TZ, load_weather_categories

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "simulator.json"
STATIONS_PATH = ROOT / "inputs" / "stations.geojson"
VEHICLES_PATH = ROOT / "inputs" / "vehicles.json"
WEATHER_PATH = ROOT / "inputs" / "weather_hcmc.json"
OUTPUT_PATH = ROOT / "output" / "debug" / "arrivals.csv"

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


def load_stations(stations_geojson: dict) -> list[Station]:
    """Đọc trạm từ GeoJSON. Chỉ dùng `station_id` và `connectors[]`; bỏ qua mọi trường khác.

    Ví dụ Audi (2 cổng CCS2 DC + 2 cổng Type2 AC) cho ports = {"AC": 2, "DC": 2}.
    """
    stations = []
    for feature in stations_geojson["features"]:
        props = feature["properties"]
        ports = {"AC": 0, "DC": 0}
        for connector in props["connectors"]:
            ports[connector["current"]] += connector["count"]
        stations.append(
            Station(
                station_id=props["station_id"],
                ports=ports,
                connectors=frozenset(c["type"] for c in props["connectors"]),
            )
        )
    return stations


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
    """Tính tốc độ đến λ(t) của một trạm từ config và thời tiết theo giờ.

    Dùng: `model = RateModel(config, weather)`, rồi `model.rate(station, when)` cho λ tại một
    thời điểm và `model.max_rate(station)` cho cận trên λ_max dùng khi thinning.
    `weather` là dict {đầu giờ (có múi giờ): "sunny" | "cloudy" | "rain"}.
    """

    def __init__(self, config: dict, weather: dict[datetime, str]):
        self.config = config
        self.weather = weather
        self.hour_factors = normalize(config["hour_factors_raw"])
        self.weekday_factors = normalize(config["weekday_factors_raw"])
        low, high = config["poi_factor_bounds"]
        for station_id, value in config["poi_factor"].items():
            if not low <= value <= high:
                raise ValueError(f"poi_factor for {station_id} must be within [{low}, {high}]")

    def _weights(self, station: Station) -> dict[str, float]:
        """Trọng số mỗi loại cổng = số cổng × r_c (xe/ngày của loại cổng đó)."""
        rates = self.config["rate_per_port_per_day"]
        return {current: station.ports[current] * rates[current] for current in station.ports}

    def base_rate(self, station: Station) -> float:
        """Tốc độ nền (xe/giờ) = Σ số cổng × r_c × demand_scale / 24, tăng theo quy mô trạm."""
        return sum(self._weights(station).values()) * self.config["demand_scale"] / 24

    def poi(self, station: Station) -> float:
        """Hệ số POI cố định của trạm (đọc từ config, không gọi API)."""
        return self.config["poi_factor"][station.station_id]

    def weather_factor(self, station: Station, category: str) -> float:
        """Hệ số thời tiết của trạm: trung bình có trọng số của hệ số AC và DC."""
        weights = self._weights(station)
        factors = self.config["weather"]["factors"][category]
        return sum(weights[c] * factors[c] for c in weights) / sum(weights.values())

    def rate(self, station: Station, when: datetime) -> float:
        """λ (xe/giờ) tại thời điểm `when`: nền × giờ × thứ × thời tiết × POI.

        Báo lỗi ValueError nếu thiếu dữ liệu thời tiết của giờ đó.
        """
        hour_start = when.replace(minute=0, second=0, microsecond=0)
        try:
            category = self.weather[hour_start]
        except KeyError:
            raise ValueError(f"No weather data for {hour_start.isoformat()}") from None
        return (
            self.base_rate(station)
            * self.hour_factors[when.hour]
            * self.weekday_factors[when.weekday()]
            * self.weather_factor(station, category)
            * self.poi(station)
        )

    def max_rate(self, station: Station) -> float:
        """Cận trên λ_max của trạm (mọi hệ số lấy giá trị lớn nhất), dùng cho thinning."""
        weather_max = max(
            self.weather_factor(station, category)
            for category in self.config["weather"]["factors"]
        )
        return (
            self.base_rate(station)
            * max(self.hour_factors)
            * max(self.weekday_factors)
            * weather_max
            * self.poi(station)
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
    theo giờ, thứ và thời tiết. `window` là (start, end).
    """
    start, end = window
    config = model.config
    weights = config["vehicle_weights"]
    candidates = compatible_vehicles(station, vehicles, weights)
    rng = station_rng(config["seed"], station)
    max_rate = model.max_rate(station)

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


def generate_arrivals(
    config: dict, stations: dict, vehicles: list[dict], weather: dict[datetime, str]
) -> list[dict]:
    """Hàm chính: sinh lượt đến cho mọi trạm.

    Gộp kết quả, sắp xếp theo thời gian rồi đánh `arrival_id`. Là hàm thuần (không đọc file,
    không gọi mạng), nên test được bằng config và thời tiết giả.
    """
    model = RateModel(config, weather)
    window = simulation_window(config)
    rows = []
    for station in load_stations(stations):
        rows.extend(generate_station(station, model, vehicles, window))
    rows.sort(key=lambda row: (row["t_arrival"], row["station_id"]))
    for index, row in enumerate(rows, start=1):
        row["arrival_id"] = f"ARR_{index:06d}"
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    """Ghi các dòng ra CSV UTF-8 theo FIELDS. Tự tạo thư mục cha."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """Đọc config, trạm, xe và thời tiết đã lưu, sinh lượt đến rồi ghi CSV (không gọi mạng)."""
    parser = argparse.ArgumentParser(
        description="Generate simulated arrivals (usage: see the module docstring)."
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    vehicles = json.loads(VEHICLES_PATH.read_text(encoding="utf-8"))
    weather = load_weather_categories(WEATHER_PATH, config["weather"])
    rows = generate_arrivals(config, stations, vehicles, weather)
    write_csv(rows, args.output)
    print(f"Wrote {len(rows)} arrivals to {args.output}")


if __name__ == "__main__":
    main()
