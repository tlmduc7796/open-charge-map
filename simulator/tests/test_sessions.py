import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from script.arrivals import generate_arrivals
from script.config import resolve
from script.sessions import (
    can_use,
    charging_power_kw,
    in_band,
    load_ports,
    simulate_sessions,
)

SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "catalog_snapshot.json").read_text(encoding="utf-8")
)
INPUTS = resolve({}, SNAPSHOT)
CONFIG, STATIONS, VEHICLES = INPUTS.config, INPUTS.stations, INPUTS.vehicles
VEHICLE_BY_ID = {v["vehicle_id"]: v for v in VEHICLES}
DAY = "2026-08-01"
FIXED = {"median": 1.0, "sigma": 0}  # sigma 0 makes the log-normal exactly its median


def fixed_config(**overrides) -> dict:
    """Deterministic config: constant delays, constant idle, no early unplug."""
    config = {
        **CONFIG,
        "connect_delay_min": FIXED,
        "auth_delay_min": FIXED,
        "idle_min_by_band": [{"start_hour": 0, "end_hour": 24, "median": 8.0, "sigma": 0}],
        "early_unplug": {"default_probability": 0.0, "bands": [], "fraction_range": [0.5, 0.95]},
    }
    return {**config, **overrides}


def station(station_id: str, *connectors: tuple[str, str, float, int]) -> list[dict]:
    """One station with explicit ports `<station_id>_P<k>`; each tuple is (type, current, kW, n)."""
    ports = []
    for connector, current, power, count in connectors:
        for _ in range(count):
            ports.append(
                {
                    "port_id": f"{station_id}_P{len(ports) + 1}",
                    "connector": connector,
                    "current": current,
                    "max_power_kw": power,
                }
            )
    return [{"station_id": station_id, "name": station_id, "ports": ports}]


ONE_DC = station("S1", ("CCS2", "DC", 160, 1))


def arrival(n: int, at: str, vehicle: str = "EV_VF5_PLUS", soc=(0.2, 0.8), patience=30.0,
            station_id: str = "S1") -> dict:
    return {
        "arrival_id": f"A{n}",
        "station_id": station_id,
        "t_arrival": f"{DAY}T{at}+07:00",
        "vehicle_id": vehicle,
        "soc_start": soc[0],
        "soc_target": soc[1],
        "patience_min": patience,
    }


def run(config: dict, stations: list[dict], arrivals: list[dict]) -> dict:
    return simulate_sessions(config, stations, VEHICLES, arrivals)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_second_vehicle_waits_for_the_port_to_be_released() -> None:
    arrivals = [arrival(1, "12:00:00"), arrival(2, "12:05:00", patience=60.0)]
    result = run(fixed_config(), ONE_DC, arrivals)
    first, second = result["sessions"]
    assert first["charge_min"] == pytest.approx(29.783, abs=0.05)  # 0.6*37.23/(50*0.9)*60
    assert first["idle_min"] == pytest.approx(8.0, abs=0.02)
    assert at(second["t_connect"]) >= at(first["t_disconnect"])
    waits = {row["arrival_id"]: row["wait_min"] for row in result["queue_log"]}
    assert waits["A1"] == 0 and waits["A2"] > 30
    assert second["port_id"] == first["port_id"] == "S1_P1"


def test_impatient_vehicle_leaves_without_a_session() -> None:
    arrivals = [arrival(1, "12:00:00"), arrival(2, "12:05:00", patience=10.0)]
    result = run(fixed_config(), ONE_DC, arrivals)
    assert len(result["sessions"]) == 1
    log = {row["arrival_id"]: row for row in result["queue_log"]}
    assert log["A2"]["outcome"] == "reneged" and log["A2"]["port_id"] == ""
    assert log["A2"]["queue_len_on_arrival"] == 0 and log["A2"]["wait_min"] == 10.0


def test_incompatible_vehicle_never_gets_a_port() -> None:
    result = run(fixed_config(), ONE_DC, [arrival(1, "12:00:00", vehicle="EV_GBT_CITY_DEMO")])
    assert result["sessions"] == []
    assert result["queue_log"][0]["outcome"] == "reneged"


def test_dc_ports_are_preferred_over_ac_at_a_mixed_station() -> None:
    mixed = station("S1", ("CCS2", "DC", 180, 2), ("Type2", "AC", 11, 2))
    arrivals = [arrival(i, f"12:00:0{i}") for i in range(1, 5)]
    result = run(fixed_config(), mixed, arrivals)
    ports = {p["port_id"]: p["current"] for p in result["ports"]}
    used = [ports[s["port_id"]] for s in result["sessions"]]
    assert used == ["DC", "DC", "AC", "AC"]
    assert result["queue_log"][3]["queue_len_on_arrival"] == 0


def test_charging_time_follows_port_and_vehicle_power_not_a_fixed_duration() -> None:
    """A DC port is limited by the vehicle; a weak AC port by its own rating."""
    ac_slow = station("S1", ("Type2", "AC", 3.5, 1))
    dc_fast = station("S1", ("CCS2", "DC", 80, 1))
    dc = run(fixed_config(), dc_fast, [arrival(1, "12:00:00")])["sessions"][0]
    ac = run(fixed_config(), ac_slow, [arrival(1, "12:00:00")])["sessions"][0]
    assert dc["avg_power_kw"] == 50.0  # VF5 DC limit, below the 80 kW port
    assert ac["avg_power_kw"] == 3.5  # port limit, below the 6.6 kW vehicle limit
    assert dc["charge_min"] < 40 < 400 < ac["charge_min"]


def test_idle_and_early_unplug_depend_on_finish_time() -> None:
    config = fixed_config(
        idle_min_by_band=[
            {"start_hour": 6, "end_hour": 22, "median": 8.0, "sigma": 0},
            {"start_hour": 22, "end_hour": 6, "median": 180.0, "sigma": 0},
        ]
    )
    day = run(config, ONE_DC, [arrival(1, "12:00:00")])["sessions"][0]
    night = run(config, ONE_DC, [arrival(1, "23:00:00")])["sessions"][0]
    assert day["idle_min"] == pytest.approx(8.0, abs=0.02)
    assert night["idle_min"] == pytest.approx(180.0, abs=0.02)
    assert day["end_reason"] == night["end_reason"] == "target_reached"

    always_at_night = {
        "default_probability": 0.0,
        "bands": [{"start_hour": 22, "end_hour": 6, "probability": 1.0}],
        "fraction_range": [0.5, 0.95],
    }
    config = fixed_config(early_unplug=always_at_night)
    day = run(config, ONE_DC, [arrival(1, "12:00:00")])["sessions"][0]
    night = run(config, ONE_DC, [arrival(1, "23:00:00")])["sessions"][0]
    assert day["end_reason"] == "target_reached" and day["soc_end"] == 0.8
    assert night["end_reason"] == "user_unplug" and 0.2 < night["soc_end"] < 0.8
    assert night["idle_min"] == 0 and night["t_charge_end"] == night["t_disconnect"]


def test_queueing_matches_the_md1_formula() -> None:
    """One port, Poisson arrivals, constant service: W_q = rho * S / (2 * (1 - rho))."""
    config = fixed_config(
        idle_min_by_band=[{"start_hour": 0, "end_hour": 24, "median": 5.0, "sigma": 0}]
    )
    probe = run(config, ONE_DC, [arrival(1, "01:00:00")])["sessions"][0]
    service_min = probe["connected_min"]
    rho = 0.6
    rng = np.random.default_rng(7)
    origin = at(f"{DAY}T00:00:00+07:00")
    t, arrivals = 0.0, []
    for n in range(1, 20001):
        t += rng.exponential(service_min / rho)
        moment = (origin + timedelta(minutes=t)).isoformat()
        arrivals.append({**arrival(n, "00:00:00", patience=1e9), "t_arrival": moment})
    config = {**config, "end_date": "2030-01-01"}
    result = run(config, ONE_DC, arrivals)
    waits = [row["wait_min"] for row in result["queue_log"]]
    expected = rho * service_min / (2 * (1 - rho))
    assert sum(waits) / len(waits) == pytest.approx(expected, rel=0.1)


@pytest.fixture(scope="module")
def full_run() -> dict:
    config = {**CONFIG, "end_date": "2026-08-10"}
    arrivals = generate_arrivals(config, STATIONS, VEHICLES)
    result = simulate_sessions(config, STATIONS, VEHICLES, arrivals)
    return {"config": config, "arrivals": arrivals, **result}


def test_full_run_is_reproducible(full_run: dict) -> None:
    again = simulate_sessions(full_run["config"], STATIONS, VEHICLES, full_run["arrivals"])
    assert again["sessions"] == full_run["sessions"]


def test_every_arrival_is_logged_once_and_served_ones_have_sessions(full_run: dict) -> None:
    log = full_run["queue_log"]
    assert len(log) == len(full_run["arrivals"])
    served = sum(row["outcome"] == "served" for row in log)
    assert served == len(full_run["sessions"]) > 0
    assert any(row["outcome"] == "reneged" for row in log)


def test_session_invariants(full_run: dict) -> None:
    ports = {p.port_id: p for station_ports in load_ports(STATIONS).values()
             for p in station_ports}
    by_port = defaultdict(list)
    for s in full_run["sessions"]:
        vehicle = VEHICLE_BY_ID[s["vehicle_id"]]
        port = ports[s["port_id"]]
        t = [at(s[k]) for k in ("t_connect", "t_charge_start", "t_charge_end", "t_disconnect")]
        assert t[0] <= t[1] < t[2] <= t[3]
        assert 0 <= s["soc_start"] < s["soc_end"] <= 1
        assert can_use(vehicle, port)
        limit = charging_power_kw(vehicle, port)
        assert s["min_power_kw"] <= s["avg_power_kw"] <= s["max_power_kw"] <= limit + 1e-9
        stored = (s["soc_end"] - s["soc_start"]) * vehicle["usable_battery_kwh"]
        assert s["energy_kwh"] * vehicle["charging_efficiency"] == pytest.approx(
            stored, rel=0.01, abs=0.01
        )
        assert s["connected_min"] == pytest.approx(
            s["charge_min"] + s["idle_min"] + (t[1] - t[0]).total_seconds() / 60, abs=0.01
        )
        assert s["charge_min"] == pytest.approx((t[2] - t[1]).total_seconds() / 60, abs=0.01)
        assert s["end_reason"] in {"target_reached", "user_unplug"}
        assert s["data_source"] == "synthetic" and s["is_synthetic"] == "true"
        by_port[s["port_id"]].append((t[0], t[3]))
    for intervals in by_port.values():
        intervals.sort()
        assert all(a[1] <= b[0] for a, b in zip(intervals, intervals[1:], strict=False))


def test_ports_come_from_the_snapshot_with_their_database_ids() -> None:
    ports = load_ports(STATIONS)
    expected = {s["station_id"]: [p["port_id"] for p in s["ports"]] for s in SNAPSHOT["stations"]}
    assert {sid: [p.port_id for p in plist] for sid, plist in ports.items()} == expected


def test_in_band_handles_midnight_wraparound() -> None:
    assert in_band(23, 22, 6) and in_band(2, 22, 6) and not in_band(12, 22, 6)
    assert in_band(6, 6, 22) and not in_band(22, 6, 22)
