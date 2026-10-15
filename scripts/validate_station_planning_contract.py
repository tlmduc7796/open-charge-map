"""Validate saved canonical DATA_PLAN tables with JSON Schema and independent reconciliation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_platform.station_planning.data_plan import coerce_csv_row  # noqa: E402

DEFAULT = ROOT / "data_platform/station_planning/demo_hcmc_v3"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def validate_contract(out=DEFAULT):
    from jsonschema import Draft202012Validator, FormatChecker

    schema = load_json(out / "data_plan_contract.schema.json")
    rows_by_table = {}
    counts = {}
    for name, definition_name in schema["x-tables"].items():
        definition = schema["$defs"][definition_name]
        validator = Draft202012Validator(definition, format_checker=FormatChecker())
        rows = []
        for index, raw in enumerate(load_csv(out / name), 2):
            try:
                row = coerce_csv_row(raw, definition)
                validator.validate(row)
            except Exception as error:
                raise ValueError(f"{name}, CSV line {index}: {error}") from error
            rows.append(row)
        rows_by_table[name] = rows
        counts[name] = len(rows)
    for name, definition_name in schema["x-json-files"].items():
        Draft202012Validator(
            schema["$defs"][definition_name], format_checker=FormatChecker()
        ).validate(load_json(out / name))

    checks = {}
    sites = rows_by_table["existing_sites.csv"]
    candidates = rows_by_table["candidate_sites.csv"]
    cells = rows_by_table["demand_cells.csv"]
    observations = rows_by_table["demand_observations.csv"]
    config = load_json(out / "scenario_config.json")
    checks["power_units_and_unknowns_preserved"] = all(
        r["power_kw_scope"] == "site"
        and r["power_kw"] == r["port_count"] * r["power_kw_per_port"]
        and r["source_url"] is None
        and r["source_url_status"] == "not_applicable"
        and r["connector_type"] is None
        for r in sites
    )
    checks["candidate_type_is_synthetic_parcel_hypothesis"] = all(
        r["candidate_type"] == "parcel"
        and r["candidate_subtype"] == "poi_grounded_synthetic_site"
        and r["parcel_status"] == "synthetic_site_hypothesis_no_verified_parcel_boundary"
        and r["access_feasible"] is None
        and r["grid_capacity_kw"] is None
        for r in candidates
    )
    originals = load_csv(out / "demand_intervals.csv")
    totals = defaultdict(lambda: [0, 0.0])
    for r in originals:
        total = totals[(r["scenario_profile"], r["unit_id"], r["interval_start"])]
        total[0] += int(r["session_count"])
        total[1] += float(r["energy_kwh"])
    seen = set()
    aggregate_ok = True
    for r in cells:
        key = (r["scenario_profile"], r["unit_id"], r["period"])
        aggregate_ok &= key not in seen and r["cell_id"] == r["unit_id"]
        seen.add(key)
        aggregate_ok &= (
            r["estimated_sessions"] == totals[key][0]
            and math.isclose(r["estimated_kwh"], totals[key][1], abs_tol=1e-4)
            and math.isclose(sum(r["poi_mix"].values()), 1, abs_tol=1e-9)
            and r["scenario_id"] == config["demand_profiles"][r["scenario_profile"]]["scenario_id"]
        )
    checks["administrative_cells_conserve_node_demand"] = (
        bool(aggregate_ok) and seen == totals.keys()
    )

    node_map = load_csv(out / "demand_node_cell_map.csv")
    nodes = {r["cell_id"]: r for r in load_csv(out / "demand_nodes.csv")}
    checks["node_to_administrative_cell_mapping"] = (
        len(node_map) == len(nodes) == 27
        and {r["node_id"] for r in node_map} == set(nodes)
        and all(r["cell_id"] == r["unit_id"] == nodes[r["node_id"]]["unit_id"] for r in node_map)
    )
    ops = {
        (r["scenario_profile"], r["site_id"], r["interval_start"]): r
        for r in load_csv(out / "station_operations.csv")
    }
    waits = defaultdict(list)
    for r in load_csv(out / "charging_requests.csv"):
        if r["status"] == "completed":
            waits[(r["scenario_profile"], r["site_id"], r["start_time"])].append(
                float(r["wait_minutes"])
            )
    observation_ok = True
    keys = set()
    for r in observations:
        key = (r["scenario_profile"], r["site_id"], r["interval_start"])
        observation_ok &= key not in keys
        keys.add(key)
        source = ops[key]
        observation_ok &= (
            r["session_count"] == int(source["completed_sessions"])
            and r["peak_ports_busy"] == int(source["occupied_ports_peak"])
            and r["available_ports"] == int(source["available_ports"])
            and r["abandon_count"] == int(source["abandoned_requests"])
            and math.isclose(r["energy_kwh"], float(source["delivered_energy_kwh"]), abs_tol=1e-5)
            and r["source_type"] == r["demand_class"] == "synthetic"
            and r["scenario_id"] == config["demand_profiles"][r["scenario_profile"]]["scenario_id"]
        )
        samples = sorted(waits[key])
        for field, percentile in (("wait_p50_min", 0.5), ("wait_p90_min", 0.9)):
            if not samples:
                observation_ok &= r[field] is None
            else:
                pos = (len(samples) - 1) * percentile
                low, high = math.floor(pos), math.ceil(pos)
                expected = samples[low] * (1 - (pos - low)) + samples[high] * (pos - low)
                observation_ok &= math.isclose(r[field], expected, abs_tol=1e-8)
    checks["synthetic_observations_reconcile_with_operations_and_waits"] = (
        bool(observation_ok) and keys == ops.keys()
    )
    metadata = load_json(out / "boundary_metadata.json")
    checks["no_fabricated_boundary_dates_or_crosswalk"] = (
        metadata["valid_from"] is None and metadata["crosswalk_ref"] is None
    )
    checks["schema_fields_types_enums_formats"] = True
    if not all(checks.values()):
        raise ValueError(f"DATA_PLAN checks failed: {checks}")
    return {
        "status": "PASS",
        "dataset_contract_version": "1.0",
        "snapshot_id": config["data_snapshot_id"],
        "validated_csv_rows": counts,
        "validated_json_files": list(schema["x-json-files"]),
        "checks": checks,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, nargs="?", default=DEFAULT)
    parser.add_argument("--dependency-dir", type=Path)
    args = parser.parse_args()
    if args.dependency_dir:
        sys.path.insert(0, str(args.dependency_dir.resolve()))
    print(json.dumps(validate_contract(args.snapshot), ensure_ascii=False, indent=2))
