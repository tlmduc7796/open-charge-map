import json
from collections import Counter
from datetime import datetime, timedelta

import pytest

from simulator.arrivals import (
    CONFIG_PATH,
    STATIONS_PATH,
    VEHICLES_PATH,
    WEATHER_PATH,
    RateModel,
    generate_arrivals,
    load_stations,
    normalize,
    simulation_window,
)
from simulator.weather import HOUR, classify, load_weather_categories

CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
STATIONS = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
VEHICLES = json.loads(VEHICLES_PATH.read_text(encoding="utf-8"))
STATION_BY_ID = {s.station_id: s for s in load_stations(STATIONS)}
AUDI = STATION_BY_ID["ST_EVO_AUDI_HCM"]
DEUTSCHES = STATION_BY_ID["ST_EVO_DEUTSCHES_HAUS"]
LAVIDA = STATION_BY_ID["ST_EVO_LAVIDA_Q7"]


def cloudy_weather(config: dict = CONFIG) -> dict[datetime, str]:
    start, end = simulation_window(config)
    hours = int((end - start) / HOUR)
    return {start + i * HOUR: "cloudy" for i in range(hours)}


def run(config: dict = CONFIG, weather: dict[datetime, str] | None = None) -> list[dict]:
    return generate_arrivals(config, STATIONS, VEHICLES, weather or cloudy_weather(config))


def count_by(rows: list[dict], key) -> Counter:
    return Counter(key(datetime.fromisoformat(row["t_arrival"])) for row in rows)


def test_same_seed_is_reproducible_and_other_seed_differs() -> None:
    first, second = run(), run()
    assert first == second
    assert run({**CONFIG, "seed": CONFIG["seed"] + 1}) != first


def test_factor_tables_are_normalized_and_poi_is_bounded() -> None:
    assert len(CONFIG["hour_factors_raw"]) == 24
    assert len(CONFIG["weekday_factors_raw"]) == 7
    assert sum(normalize(CONFIG["hour_factors_raw"])) / 24 == pytest.approx(1)
    assert sum(normalize(CONFIG["weekday_factors_raw"])) / 7 == pytest.approx(1)
    low, high = CONFIG["poi_factor_bounds"]
    station_ids = {feature["properties"]["station_id"] for feature in STATIONS["features"]}
    assert set(CONFIG["poi_factor"]) == station_ids
    assert all(low <= value <= high for value in CONFIG["poi_factor"].values())
    with pytest.raises(ValueError):
        RateModel({**CONFIG, "poi_factor": {**CONFIG["poi_factor"], "ST_EVO_AUDI_HCM": 9}}, {})


def test_station_rate_is_port_weighted_average_of_ac_and_dc() -> None:
    config = {**CONFIG, "poi_factor": {k: 1.0 for k in CONFIG["poi_factor"]}}
    model = RateModel(config, {})
    r = config["rate_per_port_per_day"]
    # Audi: 2 DC + 2 AC ports; Deutsches Haus: 4 AC; Lavida: 1 DC.
    assert model.base_rate(AUDI) == pytest.approx((2 * r["DC"] + 2 * r["AC"]) / 24)
    assert model.base_rate(DEUTSCHES) == pytest.approx(4 * r["AC"] / 24)
    assert model.base_rate(LAVIDA) == pytest.approx(r["DC"] / 24)
    counts = Counter(row["station_id"] for row in run(config))
    expected = model.base_rate(AUDI) / model.base_rate(LAVIDA)
    assert counts[AUDI.station_id] / counts[LAVIDA.station_id] == pytest.approx(expected, rel=0.1)


def test_midday_peak_is_highest_and_weekend_beats_monday() -> None:
    rows = run()
    by_hour = count_by(rows, lambda t: t.hour)
    mean = lambda hours: sum(by_hour[h] for h in hours) / len(hours)  # noqa: E731
    assert mean([11, 12, 13]) > mean([17, 18, 19]) > mean(range(0, 6))
    assert by_hour[12] == max(by_hour.values())
    by_weekday = count_by(rows, lambda t: t.weekday())
    assert by_weekday[5] > by_weekday[0]


def test_weather_classification_and_factors() -> None:
    weather_config = CONFIG["weather"]

    def row(rain: float, cloud: float, is_day: int) -> dict:
        return {"precipitation_mm": rain, "cloud_cover_pct": cloud, "is_day": is_day}

    assert classify(row(2.0, 100, 1), weather_config) == "rain"
    assert classify(row(0.0, 10, 1), weather_config) == "sunny"
    assert classify(row(0.0, 80, 1), weather_config) == "cloudy"
    assert classify(row(0.0, 0, 0), weather_config) == "cloudy"  # no "sunny" at night

    when = datetime.fromisoformat("2026-08-12T12:00:00+07:00")

    def rate(category: str) -> float:
        # Deutsches Haus has only AC ports, so its factor equals the AC factor.
        return RateModel(CONFIG, {when: category}).rate(DEUTSCHES, when)

    assert rate("rain") == pytest.approx(0.85 * rate("cloudy"))
    assert rate("sunny") == pytest.approx(1.05 * rate("cloudy"))


def test_vehicles_are_compatible_and_socs_are_valid() -> None:
    rows = run()
    vehicles = {v["vehicle_id"]: v for v in VEHICLES}
    for row in rows:
        vehicle = vehicles[row["vehicle_id"]]
        usable = {*vehicle["ac_connectors"], *vehicle["dc_connectors"]}
        assert STATION_BY_ID[row["station_id"]].connectors & usable
        assert 0 <= row["soc_start"] < row["soc_target"] <= 1
        assert row["patience_min"] > 0
        assert "current" not in row
    assert "EV_GBT_CITY_DEMO" not in {r["vehicle_id"] for r in rows}


def test_peak_utilization_makes_queues_likely_at_midday() -> None:
    model = RateModel(CONFIG, {})
    service = CONFIG["assumed_service_min"]
    for station in STATION_BY_ID.values():
        capacity = sum(station.ports[c] * 60 / service[c] for c in station.ports)
        midday = [
            model.base_rate(station) * model.hour_factors[h] * model.poi(station)
            for h in (11, 12, 13)
        ]
        rho = sum(midday) / 3 / capacity
        assert 1.0 <= rho <= 1.5, (station.station_id, rho)


def test_saved_weather_covers_the_simulation_window() -> None:
    weather = load_weather_categories(WEATHER_PATH, CONFIG["weather"])
    start, end = simulation_window(CONFIG)
    hours = [start + timedelta(hours=i) for i in range(int((end - start) / HOUR))]
    assert all(hour in weather for hour in hours)
    assert set(weather.values()) <= {"sunny", "cloudy", "rain"}
