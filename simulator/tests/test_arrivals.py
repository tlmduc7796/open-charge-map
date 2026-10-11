import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest
from script.arrivals import (
    RateModel,
    generate_arrivals,
    load_stations,
    normalize,
    simulation_window,
)
from script.config import resolve

SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "catalog_snapshot.json").read_text(encoding="utf-8")
)
INPUTS = resolve({}, SNAPSHOT)
CONFIG, STATIONS, VEHICLES = INPUTS.config, INPUTS.stations, INPUTS.vehicles
STATION_BY_ID = {s.station_id: s for s in load_stations(STATIONS)}
MIXED = STATION_BY_ID["ST_MIXED"]  # 2 DC + 2 AC ports
AC_ONLY = STATION_BY_ID["ST_AC_ONLY"]  # 4 AC ports
DC_ONE = STATION_BY_ID["ST_DC_ONE"]  # 1 DC port

# Assumed service time per session, used only to sanity-check the demand level against capacity.
SERVICE_MIN = {"DC": 40.0, "AC": 150.0}


def run(config: dict = CONFIG) -> list[dict]:
    return generate_arrivals(config, STATIONS, VEHICLES)


def count_by(rows: list[dict], key) -> Counter:
    return Counter(key(datetime.fromisoformat(row["t_arrival"])) for row in rows)


def test_window_is_whole_days_in_vietnam_time() -> None:
    start, end = simulation_window({**CONFIG, "start_date": "2026-08-01", "end_date": "2026-08-01"})
    assert start.isoformat() == "2026-08-01T00:00:00+07:00"
    assert end.isoformat() == "2026-08-02T00:00:00+07:00"


def test_same_seed_is_reproducible_and_other_seed_differs() -> None:
    first, second = run(), run()
    assert first == second
    assert run({**CONFIG, "seed": CONFIG["seed"] + 1}) != first


def test_factor_tables_are_normalized() -> None:
    assert len(CONFIG["hour_factors_raw"]) == 24
    assert len(CONFIG["weekday_factors_raw"]) == 7
    assert sum(normalize(CONFIG["hour_factors_raw"])) / 24 == pytest.approx(1)
    assert sum(normalize(CONFIG["weekday_factors_raw"])) / 7 == pytest.approx(1)


def test_station_rate_is_port_weighted_average_of_ac_and_dc() -> None:
    model = RateModel(CONFIG)
    r = CONFIG["rate_per_port_per_day"]
    assert model.base_rate(MIXED) == pytest.approx((2 * r["DC"] + 2 * r["AC"]) / 24)
    assert model.base_rate(AC_ONLY) == pytest.approx(4 * r["AC"] / 24)
    assert model.base_rate(DC_ONE) == pytest.approx(r["DC"] / 24)
    counts = Counter(row["station_id"] for row in run())
    expected = model.base_rate(MIXED) / model.base_rate(DC_ONE)
    assert counts[MIXED.station_id] / counts[DC_ONE.station_id] == pytest.approx(expected, rel=0.15)


def test_station_factor_scales_only_that_station() -> None:
    boosted = {**CONFIG, "station_factor": {"ST_AC_ONLY": 2.0}}
    base, scaled = RateModel(CONFIG), RateModel(boosted)
    assert scaled.max_rate(AC_ONLY) == pytest.approx(2 * base.max_rate(AC_ONLY))
    assert scaled.max_rate(MIXED) == pytest.approx(base.max_rate(MIXED))
    when = datetime.fromisoformat("2026-08-12T12:00:00+07:00")
    assert scaled.rate(AC_ONLY, when) == pytest.approx(2 * base.rate(AC_ONLY, when))


def test_zero_demand_station_has_no_arrivals() -> None:
    config = {**CONFIG, "rate_per_port_per_day": {"DC": 0.0, "AC": 4.5}}
    stations = {r["station_id"] for r in run(config)}
    assert "ST_DC_ONE" not in stations
    assert {"ST_MIXED", "ST_AC_ONLY"} <= stations


def test_midday_peak_is_highest_and_weekend_beats_monday() -> None:
    rows = run()
    by_hour = count_by(rows, lambda t: t.hour)

    def mean(hours) -> float:
        return sum(by_hour[h] for h in hours) / len(hours)

    assert mean([11, 12, 13]) > mean([17, 18, 19]) > mean(range(0, 6))
    assert by_hour[12] == max(by_hour.values())
    by_weekday = count_by(rows, lambda t: t.weekday())
    assert by_weekday[5] > by_weekday[0]


def test_vehicles_are_compatible_and_socs_are_valid() -> None:
    rows = run()
    vehicles = {v["vehicle_id"]: v for v in VEHICLES}
    assert rows
    for row in rows:
        vehicle = vehicles[row["vehicle_id"]]
        usable = {*vehicle["ac_connectors"], *vehicle["dc_connectors"]}
        assert STATION_BY_ID[row["station_id"]].connectors & usable
        assert 0 <= row["soc_start"] < row["soc_target"] <= 1
        assert row["patience_min"] > 0
    assert "EV_GBT_CITY_DEMO" not in {r["vehicle_id"] for r in rows}  # no GBT connector anywhere


def test_peak_utilization_makes_queues_likely_at_midday() -> None:
    model = RateModel(CONFIG)
    for station in STATION_BY_ID.values():
        capacity = sum(station.ports[c] * 60 / SERVICE_MIN[c] for c in station.ports)
        midday = [model.base_rate(station) * model.hour_factors[h] for h in (11, 12, 13)]
        rho = sum(midday) / 3 / capacity
        assert 1.0 <= rho <= 1.5, (station.station_id, rho)
