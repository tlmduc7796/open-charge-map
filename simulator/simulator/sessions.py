"""Mô phỏng phiên sạc: nhận các lượt xe đến (simulator/arrivals.py), cho xếp hàng, cấp cổng,
sạc và rút xe bằng SimPy, rồi ghi `sessions` và `ports` đúng docs/SIMULATOR_SESSION_SCHEMA.md.

Luồng của mỗi lượt đến:
  1. Có cổng tương thích còn trống: chọn theo port_preference (DC trước), rồi công suất cao nhất.
  2. Hết cổng: vào hàng FIFO của trạm, chờ tối đa `patience_min`; hết kiên nhẫn thì bỏ đi
     (không tạo phiên).
  3. Được cấp cổng: t_connect = lúc được cấp + trễ cắm; t_charge_start = t_connect + trễ xác thực.
  4. Sạc với công suất cố định P = min(công suất cổng, công suất xe).
  5. Rút xe phụ thuộc giờ sạc xong: có thể rút sớm (user_unplug) với xác suất theo giờ dự kiến
     sạc xong; nếu không thì sạc đủ soc_target rồi còn cắm thêm `idle` (dài hơn khi sạc xong
     ban đêm). Cổng được trả lúc t_disconnect và xe đầu hàng đợi được cấp tiếp.

Hàng đợi, thời gian chờ và xe bỏ đi KHÔNG thuộc schema sessions; chúng được ghi riêng vào
output/debug/queue_log.csv chỉ để kiểm thử. Mọi tham số là giả định trong
config/simulator.json.

Cách dùng:

    python -m simulator.sessions                # sinh lượt đến rồi mô phỏng, ghi 3 file CSV
    python -m simulator.sessions --output-dir out

    # Dùng trong code (ví dụ trong test):
    result = simulate_sessions(config, stations_geojson, vehicles, arrivals)
    result["sessions"], result["ports"], result["queue_log"]
"""

from __future__ import annotations

import argparse
import csv
import json
import zlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import simpy

from simulator.arrivals import (
    CONFIG_PATH,
    ROOT,
    STATIONS_PATH,
    VEHICLES_PATH,
    WEATHER_PATH,
    generate_arrivals,
    sample_lognormal,
    simulation_window,
)
from simulator.weather import load_weather_categories

OUTPUT_DIR = ROOT / "output"

PORT_FIELDS = ["port_id", "station_id", "connector", "current", "max_power_kw"]
SESSION_FIELDS = [
    "session_id",
    "station_id",
    "port_id",
    "vehicle_id",
    "t_connect",
    "t_charge_start",
    "t_charge_end",
    "t_disconnect",
    "soc_start",
    "soc_end",
    "energy_kwh",
    "avg_power_kw",
    "max_power_kw",
    "min_power_kw",
    "charge_min",
    "idle_min",
    "connected_min",
    "end_reason",
    "data_source",
    "is_synthetic",
    "synthetic_fields",
]
QUEUE_LOG_FIELDS = [
    "arrival_id",
    "station_id",
    "t_arrival",
    "queue_len_on_arrival",
    "wait_min",
    "outcome",
    "port_id",
]
# Các trường do mô phỏng sinh ra (mọi trường trừ khóa định danh), ghi vào synthetic_fields.
SYNTHETIC_FIELDS = ";".join(SESSION_FIELDS[4:18])


@dataclass(frozen=True)
class Port:
    """Một cổng sạc. `current` là AC hoặc DC; `connector` là chuẩn đầu cắm (Type2, CCS2...)."""

    port_id: str
    station_id: str
    connector: str
    current: str
    max_power_kw: float


def load_ports(stations_geojson: dict) -> dict[str, list[Port]]:
    """Sinh danh sách cổng của từng trạm từ `connectors[]` (dữ liệu chưa có id từng cổng).

    Mỗi connector có count = n sinh n cổng, đặt id `<station_id>_P<k>` với k tăng dần trong trạm.
    """
    ports: dict[str, list[Port]] = {}
    for feature in stations_geojson["features"]:
        props = feature["properties"]
        station_ports = []
        for connector in props["connectors"]:
            for _ in range(connector["count"]):
                station_ports.append(
                    Port(
                        port_id=f"{props['station_id']}_P{len(station_ports) + 1}",
                        station_id=props["station_id"],
                        connector=connector["type"],
                        current=connector["current"],
                        max_power_kw=connector["max_power_kw"],
                    )
                )
        ports[props["station_id"]] = station_ports
    return ports


def can_use(vehicle: dict, port: Port) -> bool:
    """Xe dùng được cổng nếu đầu cắm của cổng nằm trong đầu cắm cùng loại dòng điện của xe."""
    key = "ac_connectors" if port.current == "AC" else "dc_connectors"
    return port.connector in vehicle[key]


def charging_power_kw(vehicle: dict, port: Port) -> float:
    """Công suất sạc cố định = min(công suất cổng, công suất tối đa của xe theo loại dòng điện)."""
    key = "max_ac_power_kw" if port.current == "AC" else "max_dc_power_kw"
    return min(port.max_power_kw, vehicle[key])


def in_band(hour: int, start_hour: int, end_hour: int) -> bool:
    """Giờ có nằm trong [start_hour, end_hour) không; hỗ trợ khung qua nửa đêm (22 → 6)."""
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def sample_idle_min(rng: np.random.Generator, hour: int, bands: list[dict]) -> float:
    """Idle (phút còn cắm sau khi sạc xong) theo khung giờ sạc xong: log-normal của khung đó."""
    for band in bands:
        if in_band(hour, band["start_hour"], band["end_hour"]):
            return sample_lognormal(rng, band)
    raise ValueError(f"No idle band covers hour {hour}")


def early_unplug_probability(hour: int, config: dict) -> float:
    """Xác suất rút trước khi sạc đủ, theo giờ dự kiến sạc xong."""
    for band in config["bands"]:
        if in_band(hour, band["start_hour"], band["end_hour"]):
            return band["probability"]
    return config["default_probability"]


def session_rng(seed: int, station_id: str) -> np.random.Generator:
    """Bộ sinh ngẫu nhiên riêng cho phiên sạc của từng trạm, tách khỏi bộ sinh xe đến.

    Thêm khóa phụ (1) để không trùng với `station_rng` của arrivals.py, nên thêm bước này không
    làm đổi kết quả xe đến.
    """
    key = [seed, zlib.crc32(station_id.encode()), 1]
    return np.random.default_rng(np.random.SeedSequence(key))


class StationSim:
    """Trạng thái một trạm trong SimPy: cổng rảnh, hàng đợi FIFO và bộ sinh ngẫu nhiên riêng."""

    def __init__(self, ports: list[Port], rng: np.random.Generator):
        self.ports = ports
        self.free = list(ports)
        self.queue: deque[Waiting] = deque()
        self.rng = rng


@dataclass
class Waiting:
    """Một xe đang xếp hàng. `event` được kích hoạt kèm cổng được cấp khi tới lượt."""

    event: simpy.Event
    vehicle: dict


def pick_free_port(station: StationSim, vehicle: dict, preference: list[str]) -> Port | None:
    """Chọn cổng rảnh tương thích: theo thứ tự loại cổng ưu tiên, rồi công suất sạc cao nhất."""
    usable = [port for port in station.free if can_use(vehicle, port)]
    if not usable:
        return None
    return min(
        usable,
        key=lambda p: (preference.index(p.current), -charging_power_kw(vehicle, p), p.port_id),
    )


def release_port(station: StationSim, port: Port) -> None:
    """Trả cổng; nếu có xe đang chờ dùng được cổng này thì cấp ngay cho xe đầu hàng như vậy."""
    for waiting in station.queue:
        if can_use(waiting.vehicle, port):
            station.queue.remove(waiting)
            waiting.event.succeed(port)
            return
    station.free.append(port)


def plan_session(
    rng: np.random.Generator,
    config: dict,
    vehicle: dict,
    port: Port,
    arrival: dict,
    t_grant: datetime,
) -> dict:
    """Tính các mốc thời gian, SOC và lý do kết thúc của một phiên sau khi được cấp cổng.

    Công suất cố định P; thời gian sạc đủ `charge_min` = Δsoc × pin ÷ (P × hiệu suất). Giờ dự kiến
    sạc xong quyết định xác suất rút sớm; nếu không rút sớm thì idle phụ thuộc giờ sạc xong.
    Mọi mốc được làm tròn đến giây để các thời lượng dẫn xuất khớp tuyệt đối với các mốc.
    """
    power = charging_power_kw(vehicle, port)
    efficiency = vehicle["charging_efficiency"]
    pack = vehicle["usable_battery_kwh"]
    start_soc, target_soc = arrival["soc_start"], arrival["soc_target"]

    t_connect = t_grant + timedelta(minutes=sample_lognormal(rng, config["connect_delay_min"]))
    t_start = t_connect + timedelta(minutes=sample_lognormal(rng, config["auth_delay_min"]))
    full_min = (target_soc - start_soc) * pack / (power * efficiency) * 60
    expected_end = t_start + timedelta(minutes=full_min)

    early_cfg = config["early_unplug"]
    if rng.random() < early_unplug_probability(expected_end.hour, early_cfg):
        low, high = early_cfg["fraction_range"]
        charge_min = max(config["min_charge_min"], float(rng.uniform(low, high)) * full_min)
        soc_end = start_soc + power * efficiency * charge_min / 60 / pack
        end_reason, idle_min = "user_unplug", 0.0
    else:
        charge_min, soc_end, end_reason = full_min, target_soc, "target_reached"
        t_end = t_start + timedelta(minutes=charge_min)
        idle_min = sample_idle_min(rng, t_end.hour, config["idle_min_by_band"])

    t_charge_end = t_start + timedelta(minutes=charge_min)
    return {
        "t_connect": t_connect.replace(microsecond=0),
        "t_charge_start": t_start.replace(microsecond=0),
        "t_charge_end": t_charge_end.replace(microsecond=0),
        "t_disconnect": (t_charge_end + timedelta(minutes=idle_min)).replace(microsecond=0),
        "soc_end": soc_end,
        "power": power,
        "efficiency": efficiency,
        "pack": pack,
        "end_reason": end_reason,
    }


def customer(
    env: simpy.Environment,
    origin: datetime,
    station: StationSim,
    vehicle: dict,
    arrival: dict,
    config: dict,
    sessions: list[dict],
    queue_log: list[dict],
):
    """Quy trình của một lượt đến: chờ đến giờ, xếp hàng nếu cần, sạc, rút xe, trả cổng."""
    arrival_time = datetime.fromisoformat(arrival["t_arrival"])
    yield env.timeout((arrival_time - origin).total_seconds() / 60)
    queue_len = len(station.queue)

    port = pick_free_port(station, vehicle, config["port_preference"])
    if port is not None:
        station.free.remove(port)
    else:
        waiting = Waiting(env.event(), vehicle)
        station.queue.append(waiting)
        yield waiting.event | env.timeout(arrival["patience_min"])
        if not waiting.event.triggered:  # hết kiên nhẫn: bỏ đi, không tạo phiên
            station.queue.remove(waiting)
            queue_log.append(
                {
                    "arrival_id": arrival["arrival_id"],
                    "station_id": arrival["station_id"],
                    "t_arrival": arrival["t_arrival"],
                    "queue_len_on_arrival": queue_len,
                    "wait_min": round(arrival["patience_min"], 2),
                    "outcome": "reneged",
                    "port_id": "",
                }
            )
            return
        port = waiting.event.value

    t_grant = origin + timedelta(minutes=env.now)
    plan = plan_session(station.rng, config, vehicle, port, arrival, t_grant)
    queue_log.append(
        {
            "arrival_id": arrival["arrival_id"],
            "station_id": arrival["station_id"],
            "t_arrival": arrival["t_arrival"],
            "queue_len_on_arrival": queue_len,
            "wait_min": round((t_grant - arrival_time).total_seconds() / 60, 2),
            "outcome": "served",
            "port_id": port.port_id,
        }
    )
    sessions.append({"station_id": port.station_id, "port_id": port.port_id,
                     "vehicle_id": vehicle["vehicle_id"], "soc_start": arrival["soc_start"],
                     **plan})
    yield env.timeout((plan["t_disconnect"] - t_grant).total_seconds() / 60)
    release_port(station, port)


def minutes_between(earlier: datetime, later: datetime) -> float:
    """Số phút giữa hai mốc (đã làm tròn đến giây), làm tròn 3 chữ số thập phân."""
    return round((later - earlier).total_seconds() / 60, 3)


def to_session_row(plan: dict) -> dict:
    """Đổi kết quả plan_session thành một dòng của bảng sessions (chưa có session_id)."""
    energy = (plan["soc_end"] - plan["soc_start"]) * plan["pack"] / plan["efficiency"]
    power = round(plan["power"], 3)
    return {
        "station_id": plan["station_id"],
        "port_id": plan["port_id"],
        "vehicle_id": plan["vehicle_id"],
        "t_connect": plan["t_connect"].isoformat(),
        "t_charge_start": plan["t_charge_start"].isoformat(),
        "t_charge_end": plan["t_charge_end"].isoformat(),
        "t_disconnect": plan["t_disconnect"].isoformat(),
        "soc_start": round(plan["soc_start"], 4),
        "soc_end": round(plan["soc_end"], 4),
        "energy_kwh": round(energy, 3),
        "avg_power_kw": power,
        "max_power_kw": power,
        "min_power_kw": power,
        "charge_min": minutes_between(plan["t_charge_start"], plan["t_charge_end"]),
        "idle_min": minutes_between(plan["t_charge_end"], plan["t_disconnect"]),
        "connected_min": minutes_between(plan["t_connect"], plan["t_disconnect"]),
        "end_reason": plan["end_reason"],
        "data_source": "synthetic",
        "is_synthetic": "true",
        "synthetic_fields": SYNTHETIC_FIELDS,
    }


def simulate_sessions(
    config: dict, stations: dict, vehicles: list[dict], arrivals: list[dict]
) -> dict:
    """Hàm chính: chạy SimPy cho mọi lượt đến, trả về {"sessions", "ports", "queue_log"}.

    `arrivals` là kết quả của generate_arrivals (đã sắp theo thời gian). Là hàm thuần (không đọc
    file), nên test được với config và lượt đến giả. Mô phỏng chạy đến khi mọi xe đã rút.
    """
    origin = simulation_window(config)[0]
    vehicles_by_id = {vehicle["vehicle_id"]: vehicle for vehicle in vehicles}
    ports_by_station = load_ports(stations)
    station_sims = {
        station_id: StationSim(ports, session_rng(config["seed"], station_id))
        for station_id, ports in ports_by_station.items()
    }

    env = simpy.Environment()
    plans: list[dict] = []
    queue_log: list[dict] = []
    for arrival in arrivals:
        env.process(
            customer(
                env,
                origin,
                station_sims[arrival["station_id"]],
                vehicles_by_id[arrival["vehicle_id"]],
                arrival,
                config,
                plans,
                queue_log,
            )
        )
    env.run()

    rows = sorted((to_session_row(plan) for plan in plans), key=lambda r: r["t_connect"])
    for index, row in enumerate(rows, start=1):
        row["session_id"] = f"SES_{index:06d}"
    queue_log.sort(key=lambda row: (row["t_arrival"], row["arrival_id"]))
    port_rows = [
        {field: getattr(port, field) for field in PORT_FIELDS}
        for station_ports in ports_by_station.values()
        for port in station_ports
    ]
    return {"sessions": rows, "ports": port_rows, "queue_log": queue_log}


def write_csv(rows: list[dict], fields: list[str], path: Path) -> None:
    """Ghi các dòng ra CSV UTF-8 theo `fields`. Tự tạo thư mục cha."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    """Sinh lượt đến, mô phỏng phiên sạc rồi ghi sessions.csv, ports.csv và debug/queue_log.csv."""
    parser = argparse.ArgumentParser(
        description="Simulate charging sessions (usage: see the module docstring)."
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    vehicles = json.loads(VEHICLES_PATH.read_text(encoding="utf-8"))
    weather = load_weather_categories(WEATHER_PATH, config["weather"])
    arrivals = generate_arrivals(config, stations, vehicles, weather)
    result = simulate_sessions(config, stations, vehicles, arrivals)

    write_csv(result["sessions"], SESSION_FIELDS, args.output_dir / "sessions.csv")
    write_csv(result["ports"], PORT_FIELDS, args.output_dir / "ports.csv")
    write_csv(result["queue_log"], QUEUE_LOG_FIELDS, args.output_dir / "debug" / "queue_log.csv")
    served = len(result["sessions"])
    print(
        f"{len(arrivals)} arrivals -> {served} sessions, "
        f"{len(arrivals) - served} reneged. Output: {args.output_dir}"
    )


if __name__ == "__main__":
    main()
