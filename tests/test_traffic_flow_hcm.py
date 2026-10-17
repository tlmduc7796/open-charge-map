"""Contract checks for the nine-ward historical traffic-condition export."""

from __future__ import annotations

import json
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "raw_data" / "traffic_flow_hcm"
SNAPSHOT_DIR = ROOT / "data_platform" / "station_planning" / "planner_v2"


def read_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def test_traffic_condition_exports_keep_vehicle_counts_unknown() -> None:
    manifest = read_json("collection_manifest.json")

    assert manifest["vehicle_count_available"] is False
    assert manifest["vehicle_count_status"] == "not_available_in_source"
    assert manifest["counts"]["selected_wards"] == 9
    assert manifest["counts"]["selected_segments"] > 0
    assert manifest["counts"]["selected_observations"] > 0

    for name in (
        "traffic_condition_observations_9_wards.json",
        "traffic_condition_daily_9_wards.json",
        "traffic_condition_weekly_9_wards.json",
        "traffic_condition_monthly_9_wards.json",
    ):
        payload = read_json(name)
        assert payload["data_classification"] == "observed_historical_traffic_condition_not_vehicle_volume"
        assert payload["vehicle_count_available"] is False
        assert payload["records"]
        assert all(record["vehicle_count"] is None for record in payload["records"])
        assert all(record["vehicle_count_status"] == "not_available_in_source" for record in payload["records"])


def test_traffic_condition_aggregates_cover_every_selected_ward() -> None:
    manifest = read_json("collection_manifest.json")
    expected_ward_ids = {ward["ward_id"] for ward in manifest["wards"]}

    for name in (
        "traffic_condition_daily_9_wards.json",
        "traffic_condition_weekly_9_wards.json",
        "traffic_condition_monthly_9_wards.json",
    ):
        records = read_json(name)["records"]
        periods = {record["period"] for record in records}
        assert periods
        for period in periods:
            assert {record["ward_id"] for record in records if record["period"] == period} == expected_ward_ids


def test_canonical_planner_v2_traffic_contract_keeps_volume_unknown() -> None:
    manifest = json.loads((SNAPSHOT_DIR / "snapshot_manifest.json").read_text(encoding="utf-8"))
    registry_rows = list(csv.DictReader((SNAPSHOT_DIR / "source_registry.csv").open(encoding="utf-8-sig", newline="")))
    observation_rows = list(
        csv.DictReader((SNAPSHOT_DIR / "traffic_observations.csv").open(encoding="utf-8-sig", newline=""))
    )

    assert manifest["snapshot_id"] == "hcm-planner-v2-2026-10-17-traffic-condition-v1"
    assert manifest["timezone"] == "Asia/Ho_Chi_Minh"
    assert manifest["crs"] == "EPSG:4326"
    source_ids = {row["source_id"] for row in registry_rows}
    assert len(source_ids) == 2
    assert observation_rows
    assert all(row["source_id"] in source_ids for row in observation_rows)
    assert all(row["vehicle_count"] == "" for row in observation_rows)
    assert all(row["vehicle_volume_vph"] == "" for row in observation_rows)
    assert all(row["source_type"] == "unknown" for row in observation_rows)
    assert all(row["quality_status"] == "unknown" for row in observation_rows)
    assert all(row["is_proxy"] == "false" for row in observation_rows)
    assert all(row["is_synthetic"] == "false" for row in observation_rows)
