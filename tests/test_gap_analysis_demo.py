"""The gap snapshot is reproducible and its simulated inventory is internally consistent."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data_platform" / "station_planning" / "gap_v1"
SCRIPT = ROOT / "scripts" / "prepare_gap_analysis_demo.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("prepare_gap_analysis_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rows(name: str) -> list[dict[str, str]]:
    with (SNAPSHOT / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_regenerating_reproduces_the_committed_files(tmp_path: Path) -> None:
    pytest.importorskip("shapely")  # pip install -r scripts/requirements-station-planning.txt
    generator = _load_generator()
    generator.build(generator.DEFAULT_CONFIG, tmp_path)
    for name in (
        "grid_cells.csv", "route_blocks.csv", "route_roads.csv", "gap_stations.csv",
        "gap_station_ports.csv",
    ):
        expected = hashlib.sha256((SNAPSHOT / name).read_bytes()).hexdigest()
        actual = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} differs from the generator output"


def test_manifest_hashes_match_files_and_labels_simulated_data() -> None:
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((SNAPSHOT / name).read_bytes()).hexdigest() == digest
    assert manifest["counts"]["wards"] == 9
    assert manifest["data_labels"]["flow"].startswith("synthetic")
    assert manifest["data_labels"]["rent"].startswith("synthetic")
    assert manifest["data_labels"]["stations"].startswith("synthetic")
    assert manifest["data_labels"]["legal"].startswith("unknown")


def test_cells_cover_nine_wards_with_observed_poi_and_synthetic_flow_and_rent() -> None:
    cells = _rows("grid_cells.csv")
    assert len({row["unit_id"] for row in cells}) == 9
    assert len({row["cell_id"] for row in cells}) == len(cells)
    assert {row["poi_status"] for row in cells} == {"observed_collected_official_source"}
    assert {row["flow_status"] for row in cells} == {"synthetic"}
    assert {row["rent_status"] for row in cells} == {"synthetic"}
    assert sum(float(row["poi_count"]) for row in cells) > 0
    assert all(250 <= float(row["flow_vph"]) <= 4250 for row in cells)
    assert all(100 <= float(row["rent_kvnd_m2_month"]) <= 1100 for row in cells)


def test_stations_are_split_between_own_network_and_competitors_with_consistent_power() -> None:
    stations = _rows("gap_stations.csv")
    groups = _rows("gap_station_ports.csv")
    by_station: dict[str, list[dict[str, str]]] = {}
    for group in groups:
        by_station.setdefault(group["station_id"], []).append(group)
    relationships = {row["relationship"] for row in stations}
    assert relationships == {"OWNED", "OTHER_NETWORK"}
    competitors = {r["operator_id"] for r in stations if r["relationship"] == "OTHER_NETWORK"}
    assert len(competitors) >= 3
    for row in stations:
        assert row["is_synthetic"] == "True"
        parts = by_station[row["station_id"]]
        assert int(row["port_count"]) == sum(int(p["port_count"]) for p in parts)
        assert float(row["total_power_kw"]) == round(
            sum(int(p["port_count"]) * float(p["power_kw_per_port"]) for p in parts), 1
        )
        assert int(row["dc_port_count"]) + int(row["ac_port_count"]) == int(row["port_count"])


def test_stations_respect_the_configured_minimum_spacing() -> None:
    stations = _rows("gap_stations.csv")
    config = json.loads((ROOT / "config" / "gap_analysis_demo.json").read_text(encoding="utf-8"))
    spacing = config["station_simulation"]["minimum_spacing_m"] - 30  # placement jitter is +-12 m
    cos = math.cos(math.radians(10.78))
    for index, first in enumerate(stations):
        for second in stations[index + 1 :]:
            dx = (float(first["lon"]) - float(second["lon"])) * 111_320 * cos
            dy = (float(first["lat"]) - float(second["lat"])) * 110_540
            assert math.hypot(dx, dy) >= spacing


def test_route_blocks_are_polygons_bounded_by_real_roads_with_labelled_simulated_values() -> None:
    blocks = _rows("route_blocks.csv")
    config = json.loads((ROOT / "config" / "gap_analysis_demo.json").read_text(encoding="utf-8"))
    route = config["route_division"]
    assert len({row["cell_id"] for row in blocks}) == len(blocks)
    assert len({row["unit_id"] for row in blocks}) == 9
    assert {row["flow_status"] for row in blocks} == {"synthetic"}
    assert {row["rent_status"] for row in blocks} == {"synthetic"}
    assert {row["poi_status"] for row in blocks} == {"observed_collected_official_source"}
    for row in blocks:
        rings = json.loads(row["polygon"])
        assert len(rings[0]) >= 4 and rings[0][0] == rings[0][-1]
        assert float(row["area_m2"]) >= route["min_block_m2"]
        if row["subdivided"] == "false":
            assert float(row["area_m2"]) <= 6_000_000  # whole blocks, however large
        else:
            assert float(row["area_m2"]) <= route["max_block_m2"] * 1.0001
        assert float(row["lat_min"]) < float(row["center_lat"]) < float(row["lat_max"])
        assert float(row["lon_min"]) < float(row["center_lon"]) < float(row["lon_max"])
    named = [row for row in blocks if row["road_names"]]
    assert len(named) > 0.9 * len(blocks)
    assert sum(float(row["poi_count"]) for row in blocks) > 0
    assert all(250 <= float(row["flow_vph"]) <= 4250 for row in blocks)
    assert sum(row["subdivided"] == "true" for row in blocks) > 0
    assert len({len(json.loads(row["polygon"])[0]) for row in blocks}) > 3  # not a regular grid


def test_roads_carry_simulated_flow_that_follows_road_class() -> None:
    roads = _rows("route_roads.csv")
    assert len({row["road_id"] for row in roads}) == len(roads) > 1000
    assert {row["flow_status"] for row in roads} == {"synthetic"}
    assert all(250 <= float(row["flow_vph"]) <= 4250 for row in roads)
    assert all(len(json.loads(row["coordinates"])) >= 2 for row in roads)

    def mean(kind: str) -> float:
        values = [float(r["flow_vph"]) for r in roads if r["road_type"] == kind]
        return sum(values) / len(values)

    assert mean("primary") > mean("tertiary") > mean("residential")
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_labels"]["road_flow"].startswith("synthetic")


def test_osm_roads_are_the_committed_source_of_the_blocks() -> None:
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))
    source = manifest["sources"]["osm_roads"]
    roads = ROOT / source["path"]
    assert roads.is_file()
    assert hashlib.sha256(roads.read_bytes()).hexdigest() == source["sha256"]
    assert "OpenStreetMap" in manifest["data_labels"]["roads"]
    assert (ROOT / "raw_data" / "osm_roads" / "README.md").is_file()


def test_alleys_and_unnamed_lanes_do_not_cut_blocks() -> None:
    generator = _load_generator()
    route = json.loads((ROOT / "config" / "gap_analysis_demo.json").read_text(encoding="utf-8"))[
        "route_division"
    ]
    keep = generator.keep_road
    assert keep({"highway": "primary", "name": "Hai Bà Trưng"}, route) == "primary"
    assert keep({"highway": "primary_link"}, route) == "primary"
    assert keep({"highway": "residential", "name": "Nguyễn Tuân"}, route) == "residential"
    assert keep({"highway": "residential", "name": "Hẻm 70 Bùi Đình Túy"}, route) is None
    assert keep({"highway": "residential", "name": "H\u1ebbm 5"}, route) is None
    assert keep({"highway": "residential"}, route) is None
    assert keep({"highway": "footway", "name": "Lối đi"}, route) is None


def test_blocks_are_the_land_between_roads_and_oversized_areas_are_split() -> None:
    pytest.importorskip("shapely")
    generator = _load_generator()
    shp = generator.load_shapely()
    wide = shp["box"](0, 0, 1000, 1000)
    pieces = generator.split_large(wide, 300_000, shp)
    assert len(pieces) == 4
    assert abs(sum(piece.area for piece in pieces) - wide.area) < 1e-6
    assert all(piece.area <= 300_000 for piece in pieces)
    assert generator.split_large(shp["box"](0, 0, 100, 100), 300_000, shp)[0].area == 10_000
