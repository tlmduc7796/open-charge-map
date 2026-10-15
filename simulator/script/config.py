"""Cấu hình simulator: giá trị mặc định, nạp file của người dùng, kiểm tra và áp lên snapshot DB.

Người dùng chỉ ghi phần muốn đổi vào `simulator.config.json`; phần còn lại lấy từ DEFAULTS.
Khoá lạ là lỗi (để gõ sai tên không bị bỏ qua âm thầm). `resolve()` trả về đúng những gì lõi
mô phỏng cần: config phẳng, danh sách trạm đã chọn và danh sách xe đã điền giá trị giả định.

Mọi giá trị trong DEFAULTS là giả định, không phải số đo thực tế.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # thư mục simulator/
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "simulator.config.json"
EXAMPLE_PATH = ROOT / "config.example.json"

DEFAULTS: dict = {
    # --- tham số hướng người dùng (có trong config.example.json) ---
    "seed": 20260801,
    "start_date": "2026-08-01",
    "end_date": "2026-08-30",
    "stations": "all",  # "all" hoặc danh sách mã trạm (stations.code)
    "rate_per_port_per_day": {"DC": 18.0, "AC": 4.5},  # lượt đến / cổng / ngày
    "station_factor": {},  # {mã trạm: hệ số nhân nhu cầu}, mặc định 1.0
    "vehicle_weights": None,  # None = chia đều các xe trong snapshot
    "soc_start": {"a": 2.0, "b": 3.0},  # Beta(a, b)
    "soc_target": [
        {"weight": 0.40, "value": 0.8},
        {"weight": 0.25, "value": 0.9},
        {"weight": 0.35, "value": 1.0},
    ],
    "patience_min": {"median": 20.9, "sigma": 0.6},
    # --- nâng cao ---
    "advanced": {
        "hour_factors_raw": [
            0.1, 0.1, 0.1, 0.1, 0.1, 0.2, 0.4, 0.7, 1.0, 1.3, 1.8, 2.6,
            3.0, 2.4, 1.5, 1.4, 1.6, 2.0, 2.2, 1.8, 1.2, 0.8, 0.5, 0.3,
        ],
        "weekday_factors_raw": [1.0, 1.0, 1.0, 1.05, 1.15, 1.2, 0.9],
        "station_factor_bounds": [0.5, 2.0],
        "soc_start_bounds": [0.05, 0.8],
        "min_soc_gain": 0.1,
        "port_preference": ["DC", "AC"],
        "connect_delay_min": {"median": 1.5, "sigma": 0.5},
        "auth_delay_min": {"median": 1.0, "sigma": 0.6},
        "min_charge_min": 1.0,
        "idle_min_by_band": [
            {"start_hour": 6, "end_hour": 22, "median": 8.0, "sigma": 0.9},
            {"start_hour": 22, "end_hour": 6, "median": 180.0, "sigma": 0.7},
        ],
        "early_unplug": {
            "default_probability": 0.10,
            "bands": [{"start_hour": 22, "end_hour": 6, "probability": 0.35}],
            "fraction_range": [0.5, 0.95],
        },
        # DB không lưu các giá trị này; khớp ASSUMED_* trong backend/app/catalog_repository.py.
        "vehicle_assumptions": {
            "charging_efficiency": 0.9,
            "max_ac_power_kw": 3.3,  # chỉ dùng khi xe không có công suất AC trong DB
            "max_dc_power_kw": 50.0,  # chỉ dùng khi xe không có công suất DC trong DB
        },
    },
}

# Khoá có giá trị là dict với khoá tự do (mã trạm, mã xe), nên không so với DEFAULTS.
FREE_KEYS = {"station_factor", "vehicle_weights"}


class ConfigError(ValueError):
    """Config không hợp lệ; thông báo nói rõ khoá nào sai."""


@dataclass(frozen=True)
class RunInputs:
    """Đầu vào của một lần chạy: config phẳng, trạm (kèm cổng) và xe đã điền giả định."""

    config: dict
    stations: list[dict]
    vehicles: list[dict]


def load_user_config(path: Path) -> dict:
    """Đọc file config của người dùng; file không tồn tại nghĩa là toàn bộ dùng mặc định."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name} không phải JSON hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} phải là một object JSON")
    return data


def new_user_config(snapshot: dict) -> dict:
    """Config khởi tạo cho người dùng: bản mẫu, với `station_factor` liệt kê sẵn mọi trạm (1.0)."""
    template = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    template["station_factor"] = {
        station["station_id"]: 1.0 for station in snapshot["stations"]
    }
    return template


def _merge(defaults: dict, override: dict, path: str = "") -> dict:
    unknown = sorted(set(override) - set(defaults))
    if unknown:
        raise ConfigError(f"Khoá không hợp lệ: {', '.join(path + key for key in unknown)}")
    merged: dict = {}
    for key, default in defaults.items():
        if key not in override:
            merged[key] = copy.deepcopy(default)
        elif key not in FREE_KEYS and isinstance(default, dict):
            value = override[key]
            if not isinstance(value, dict):
                raise ConfigError(f"{path}{key} phải là object")
            merged[key] = _merge(default, value, f"{path}{key}.")
        else:
            merged[key] = copy.deepcopy(override[key])
    return merged


def _number(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} phải là số")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} phải >= {minimum}")
    return float(value)


def _lognormal(spec: object, name: str) -> None:
    if not isinstance(spec, dict) or set(spec) < {"median", "sigma"}:
        raise ConfigError(f"{name} cần median và sigma")
    if _number(spec["median"], f"{name}.median") <= 0:
        raise ConfigError(f"{name}.median phải > 0")
    _number(spec["sigma"], f"{name}.sigma", minimum=0)


def _parse_date(value: object, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(f"{name} phải có dạng YYYY-MM-DD") from exc


def _validate(cfg: dict) -> None:
    adv = cfg["advanced"]
    if not isinstance(cfg["seed"], int) or isinstance(cfg["seed"], bool):
        raise ConfigError("seed phải là số nguyên")
    if _parse_date(cfg["end_date"], "end_date") < _parse_date(cfg["start_date"], "start_date"):
        raise ConfigError("end_date phải không sớm hơn start_date")

    selection = cfg["stations"]
    if selection != "all" and not (
        isinstance(selection, list) and selection and all(isinstance(s, str) for s in selection)
    ):
        raise ConfigError('stations phải là "all" hoặc danh sách mã trạm khác rỗng')

    for current in ("DC", "AC"):
        _number(cfg["rate_per_port_per_day"][current], f"rate_per_port_per_day.{current}",
                minimum=0)
    if sorted(adv["port_preference"]) != ["AC", "DC"]:
        raise ConfigError("advanced.port_preference phải chứa đúng AC và DC")

    for name, size in (("hour_factors_raw", 24), ("weekday_factors_raw", 7)):
        values = adv[name]
        if not isinstance(values, list) or len(values) != size:
            raise ConfigError(f"advanced.{name} phải có {size} giá trị")
        for value in values:
            _number(value, f"advanced.{name}", minimum=0)
        if sum(values) <= 0:
            raise ConfigError(f"advanced.{name} phải có tổng > 0")

    low, high = adv["station_factor_bounds"]
    if not isinstance(cfg["station_factor"], dict):
        raise ConfigError("station_factor phải là object {mã trạm: hệ số}")
    for station_id, factor in cfg["station_factor"].items():
        value = _number(factor, f"station_factor.{station_id}")
        if not low <= value <= high:
            raise ConfigError(f"station_factor.{station_id} phải nằm trong [{low}, {high}]")

    weights = cfg["vehicle_weights"]
    if weights is not None:
        if not isinstance(weights, dict) or not weights:
            raise ConfigError("vehicle_weights phải là null hoặc object {mã xe: trọng số}")
        for vehicle_id, weight in weights.items():
            _number(weight, f"vehicle_weights.{vehicle_id}", minimum=0)
        if sum(weights.values()) <= 0:
            raise ConfigError("vehicle_weights cần ít nhất một trọng số > 0")

    if not cfg["soc_target"] or any(
        _number(o["weight"], "soc_target.weight") <= 0
        or not 0 < _number(o["value"], "soc_target.value") <= 1
        for o in cfg["soc_target"]
    ):
        raise ConfigError("soc_target cần danh sách {weight > 0, value trong (0, 1]}")
    if _number(cfg["soc_start"]["a"], "soc_start.a") <= 0 or _number(
        cfg["soc_start"]["b"], "soc_start.b"
    ) <= 0:
        raise ConfigError("soc_start.a và soc_start.b phải > 0")

    _lognormal(cfg["patience_min"], "patience_min")
    _lognormal(adv["connect_delay_min"], "advanced.connect_delay_min")
    _lognormal(adv["auth_delay_min"], "advanced.auth_delay_min")
    for band in adv["idle_min_by_band"]:
        _lognormal(band, "advanced.idle_min_by_band")


def build_config(user_config: dict) -> dict:
    """Gộp config người dùng vào DEFAULTS rồi kiểm tra; trả về config dạng lồng (có `advanced`)."""
    cfg = _merge(DEFAULTS, user_config)
    _validate(cfg)
    return cfg


def _select_stations(selection: str | list[str], stations: list[dict]) -> list[dict]:
    if selection == "all":
        return list(stations)
    known = {station["station_id"] for station in stations}
    missing = sorted(set(selection) - known)
    if missing:
        raise ConfigError(f"stations: không có trong snapshot: {', '.join(missing)}")
    wanted = set(selection)
    return [station for station in stations if station["station_id"] in wanted]


def _resolve_vehicles(rows: list[dict], assumptions: dict) -> list[dict]:
    """Đổi dòng xe của snapshot sang dạng lõi cần, điền giá trị giả định cho phần DB thiếu."""
    return [
        {
            "vehicle_id": row["vehicle_id"],
            "usable_battery_kwh": float(row["battery_kwh"]),
            "max_ac_power_kw": float(row["max_ac_kw"] or assumptions["max_ac_power_kw"]),
            "max_dc_power_kw": float(row["max_dc_kw"] or assumptions["max_dc_power_kw"]),
            "ac_connectors": list(row["ac_connectors"]),
            "dc_connectors": list(row["dc_connectors"]),
            "charging_efficiency": float(assumptions["charging_efficiency"]),
        }
        for row in rows
        if row.get("battery_kwh")
    ]


def resolve(user_config: dict, snapshot: dict) -> RunInputs:
    """Kết hợp config người dùng với snapshot DB thành đầu vào cho lõi mô phỏng."""
    cfg = build_config(user_config)
    stations = _select_stations(cfg["stations"], snapshot["stations"])
    if not stations:
        raise ConfigError("Không có trạm nào để mô phỏng (snapshot rỗng?)")
    vehicles = _resolve_vehicles(snapshot["vehicles"], cfg["advanced"]["vehicle_assumptions"])
    if not vehicles:
        raise ConfigError("Snapshot không có xe nào dùng được (cần pin và công suất sạc)")

    all_stations = {station["station_id"] for station in snapshot["stations"]}
    unknown = sorted(set(cfg["station_factor"]) - all_stations)
    if unknown:
        raise ConfigError(f"station_factor: không có trong snapshot: {', '.join(unknown)}")

    vehicle_ids = {vehicle["vehicle_id"] for vehicle in vehicles}
    given = cfg["vehicle_weights"]
    if given is None:
        weights = {vehicle_id: 1.0 for vehicle_id in sorted(vehicle_ids)}
    else:
        unknown = sorted(set(given) - vehicle_ids)
        if unknown:
            raise ConfigError(f"vehicle_weights: không có trong snapshot: {', '.join(unknown)}")
        weights = {
            vehicle_id: float(given.get(vehicle_id, 0.0)) for vehicle_id in sorted(vehicle_ids)
        }

    flat = {key: value for key, value in cfg.items() if key != "advanced"}
    flat.update(cfg["advanced"])
    flat["vehicle_weights"] = weights
    return RunInputs(config=flat, stations=stations, vehicles=vehicles)
