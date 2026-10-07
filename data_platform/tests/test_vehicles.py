from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from data_platform.vehicles import build_vehicle_bundle, load_vehicle_seed

DATA = Path(__file__).resolve().parents[1] / "data"


def _documents():
    catalog = json.loads((DATA / "static/vehicles.json").read_text(encoding="utf-8"))
    demo = json.loads((DATA / "demo/vehicles.json").read_text(encoding="utf-8"))
    return catalog, demo


def test_legacy_duplicates_merge_and_demo_only_vehicle_stays_labeled() -> None:
    bundle = load_vehicle_seed(DATA / "static/vehicles.json", DATA / "demo/vehicles.json")
    vehicles = {vehicle["code"]: vehicle for vehicle in bundle.vehicles}

    assert len(vehicles) == 21
    assert len(bundle.connectors) == 41
    assert bundle.matched_demo_ids == ("EV_VF5_PLUS", "EV_VF7_ECO", "EV_GBT_CITY_DEMO")
    assert "EV_VF5_PLUS" not in vehicles
    assert "EV_VF7_ECO" not in vehicles
    assert vehicles["VF5_PLUS_VN"]["provenance"]["_legacy_demo"]["vehicle_id"] == "EV_VF5_PLUS"
    assert vehicles["VF7_ECO_VN"]["consumption_kwh_per_100km"] == 13.545
    synthetic = vehicles["EV_GBT_CITY_DEMO"]
    assert (synthetic["market"], synthetic["is_active"]) == ("DEMO", False)
    assert synthetic["provenance"]["_demo_only"] is True
    assert synthetic["connectors"] == ("GBTAC", "GBTDC")
    assert synthetic["battery_kwh"] == 42
    assert synthetic["consumption_kwh_per_100km"] == 14.5


def test_missing_catalog_value_is_filled_from_matching_demo_profile() -> None:
    catalog, demo = _documents()
    catalog = copy.deepcopy(catalog)
    catalog["vehicles"][0]["max_ac_kw"] = None
    del catalog["vehicles"][0]["provenance"]["max_ac_kw"]

    vehicle = build_vehicle_bundle(catalog, demo).vehicles[0]

    assert vehicle["max_ac_kw"] == 6.6
    assert vehicle["provenance"]["max_ac_kw"]["provider"] == "legacy_demo_fixture"


def test_duplicate_catalog_code_is_rejected() -> None:
    catalog, demo = _documents()
    catalog = copy.deepcopy(catalog)
    catalog["vehicles"][1]["code"] = catalog["vehicles"][0]["code"]

    with pytest.raises(ValueError, match="duplicate vehicle code"):
        build_vehicle_bundle(catalog, demo)


def test_unmatched_real_demo_vehicle_requires_review() -> None:
    catalog, demo = _documents()
    demo = copy.deepcopy(demo)
    demo[0]["model"] = "Unknown model"

    with pytest.raises(ValueError, match="unmatched non-synthetic"):
        build_vehicle_bundle(catalog, demo)
