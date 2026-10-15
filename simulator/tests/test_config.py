import json
from pathlib import Path

import pytest
from script.config import (
    DEFAULTS,
    EXAMPLE_PATH,
    ConfigError,
    build_config,
    load_user_config,
    new_user_config,
    resolve,
)

SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "catalog_snapshot.json").read_text(encoding="utf-8")
)


def test_empty_config_uses_defaults_and_equal_vehicle_weights() -> None:
    inputs = resolve({}, SNAPSHOT)
    assert inputs.config["seed"] == DEFAULTS["seed"]
    assert inputs.config["hour_factors_raw"] == DEFAULTS["advanced"]["hour_factors_raw"]
    assert inputs.config["vehicle_weights"] == {
        "EV_GBT_CITY_DEMO": 1.0,
        "EV_VF5_PLUS": 1.0,
        "EV_VF7_ECO": 1.0,
    }
    assert [s["station_id"] for s in inputs.stations] == [
        "ST_MIXED", "ST_AC_ONLY", "ST_DC_ONE",
    ]


def test_user_values_override_defaults_and_partial_dicts_merge() -> None:
    cfg = build_config({"seed": 7, "rate_per_port_per_day": {"DC": 30}})
    assert cfg["seed"] == 7
    assert cfg["rate_per_port_per_day"] == {"DC": 30, "AC": 4.5}
    assert cfg["patience_min"] == DEFAULTS["patience_min"]


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"sed": 1}, "sed"),
        ({"advanced": {"hour_factor": []}}, "advanced.hour_factor"),
        ({"patience_min": {"mean": 5}}, "patience_min.mean"),
        ({"start_date": "2026-09-01", "end_date": "2026-08-01"}, "end_date"),
        ({"start_date": "01/09/2026"}, "start_date"),
        ({"stations": []}, "stations"),
        ({"rate_per_port_per_day": {"DC": -1}}, "rate_per_port_per_day.DC"),
        ({"station_factor": {"ST_MIXED": 9}}, "station_factor.ST_MIXED"),
        ({"vehicle_weights": {"EV_VF5_PLUS": 0}}, "vehicle_weights"),
        ({"soc_target": []}, "soc_target"),
        ({"patience_min": {"median": 0, "sigma": 0.5}}, "patience_min.median"),
        ({"advanced": {"port_preference": ["DC"]}}, "port_preference"),
        ({"advanced": {"hour_factors_raw": [1.0] * 23}}, "hour_factors_raw"),
    ],
)
def test_invalid_config_names_the_offending_key(bad: dict, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        build_config(bad)


def test_station_selection_and_unknown_station() -> None:
    inputs = resolve({"stations": ["ST_DC_ONE"]}, SNAPSHOT)
    assert [s["station_id"] for s in inputs.stations] == ["ST_DC_ONE"]
    with pytest.raises(ConfigError, match="ST_NOPE"):
        resolve({"stations": ["ST_NOPE"]}, SNAPSHOT)
    with pytest.raises(ConfigError, match="ST_NOPE"):
        resolve({"station_factor": {"ST_NOPE": 1.2}}, SNAPSHOT)


def test_vehicle_weights_default_to_zero_for_unlisted_vehicles() -> None:
    inputs = resolve({"vehicle_weights": {"EV_VF5_PLUS": 3}}, SNAPSHOT)
    assert inputs.config["vehicle_weights"] == {
        "EV_GBT_CITY_DEMO": 0.0,
        "EV_VF5_PLUS": 3.0,
        "EV_VF7_ECO": 0.0,
    }
    with pytest.raises(ConfigError, match="EV_NOPE"):
        resolve({"vehicle_weights": {"EV_NOPE": 1}}, SNAPSHOT)


def test_missing_vehicle_values_use_documented_assumptions() -> None:
    snapshot = {
        **SNAPSHOT,
        "vehicles": [
            {
                "vehicle_id": "EV_X",
                "battery_kwh": 40.0,
                "max_ac_kw": None,
                "max_dc_kw": None,
                "ac_connectors": ["Type2"],
                "dc_connectors": ["CCS2"],
            }
        ],
    }
    (vehicle,) = resolve({}, snapshot).vehicles
    assumed = DEFAULTS["advanced"]["vehicle_assumptions"]
    assert vehicle["usable_battery_kwh"] == 40.0
    assert vehicle["max_ac_power_kw"] == assumed["max_ac_power_kw"]
    assert vehicle["max_dc_power_kw"] == assumed["max_dc_power_kw"]
    assert vehicle["charging_efficiency"] == assumed["charging_efficiency"]
    override = {"advanced": {"vehicle_assumptions": {"charging_efficiency": 0.8}}}
    assert resolve(override, snapshot).vehicles[0]["charging_efficiency"] == 0.8


def test_missing_file_means_defaults_and_bad_json_is_reported(tmp_path: Path) -> None:
    assert load_user_config(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="broken.json"):
        load_user_config(broken)


def test_example_file_matches_the_defaults() -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    user_facing = {key: value for key, value in DEFAULTS.items() if key != "advanced"}
    assert example == user_facing


def test_new_user_config_lists_every_station_so_it_is_easy_to_edit() -> None:
    created = new_user_config(SNAPSHOT)
    assert created["station_factor"] == {
        "ST_MIXED": 1.0,
        "ST_AC_ONLY": 1.0,
        "ST_DC_ONE": 1.0,
    }
    assert {k: v for k, v in created.items() if k != "station_factor"} == {
        k: v for k, v in DEFAULTS.items() if k not in {"advanced", "station_factor"}
    }
    # A freshly created file is valid and changes nothing: every factor is the neutral 1.0.
    assert resolve(created, SNAPSHOT).config["station_factor"] == created["station_factor"]
