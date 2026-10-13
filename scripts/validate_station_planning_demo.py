"""Independently reconcile the saved planning fixture (standard library only)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data_platform/station_planning/demo_hcmc_v3"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def close(a, b, tolerance=1e-4):
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=tolerance)


def validate(path=DEFAULT_SNAPSHOT):
    path = path.resolve()
    cfg = load_json(path / "generation_config.json")
    manifest = load_json(path / "manifest.json")
    checks = {}
    source_paths = [ROOT / v["path"] for v in manifest["source_files"].values()]
    checks["no_excluded_source_read"] = not {p.resolve() for p in source_paths}.intersection(
        (ROOT / p).resolve() for p in cfg["excluded_sources"]
    )
    checks["source_hashes_match"] = all(
        hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
        for entry in manifest["source_files"].values()
    )
    checks["output_hashes_match"] = all(
        hashlib.sha256((path / name).read_bytes()).hexdigest() == entry["sha256"]
        for name, entry in manifest["files"].items()
    )
    tables = {
        name: load_csv(path / (name + ".csv"))
        for name in (
            "population",
            "existing_sites",
            "candidate_sites",
            "demand_nodes",
            "demand_intervals",
            "station_operations",
            "charging_requests",
            "selected_electricity_tariffs",
            "electricity_cost_intervals",
            "candidate_cost_assumptions",
            "finance_period_summary",
        )
    }
    sites = {r["site_id"]: r for r in tables["existing_sites"]}
    candidates = {r["candidate_id"]: r for r in tables["candidate_sites"]}
    nodes = {r["cell_id"]: r for r in tables["demand_nodes"]}
    wards = {r["unit_id"]: r for r in tables["population"]}
    checks["ids_unique_and_scope_counts"] = (
        len(sites) == len(tables["existing_sites"]) == 37
        and len(wards) == len(tables["population"]) == 9
        and len(nodes) == len(tables["demand_nodes"]) == 9 * cfg["demand"]["nodes_per_ward"]
        and len(candidates) == len(tables["candidate_sites"]) == 9 * cfg["candidates"]["per_ward"]
        and len({r["request_id"] for r in tables["charging_requests"]})
        == len(tables["charging_requests"])
    )
    context_ids = {
        f["properties"]["feature_id"]
        for name in ("context_poi.geojson", "context_transport.geojson")
        for f in load_json(path / name)["features"]
    }
    checks["synthetic_and_unknown_labels"] = all(
        r["source_type"] == "synthetic" and r["is_synthetic"] == "True"
        for key in (
            "existing_sites",
            "candidate_sites",
            "demand_nodes",
            "demand_intervals",
            "station_operations",
            "charging_requests",
            "candidate_cost_assumptions",
        )
        for r in tables[key]
    ) and all(
        r["context_feature_id"] in context_ids
        and r["eligibility"] == "conditional"
        and all(
            r[k] == ""
            for k in (
                "access_feasible",
                "grid_capacity_kw",
                "land_cost_vnd",
                "interconnection_cost_vnd",
            )
        )
        and r["permit_status"] == "unknown"
        for r in candidates.values()
    )
    checks["population_not_duplicated"] = all(
        close(
            sum(
                float(n["population_allocation_weight"])
                for n in nodes.values()
                if n["unit_id"] == uid
            ),
            1,
        )
        and close(
            sum(float(n["population_proxy"]) for n in nodes.values() if n["unit_id"] == uid),
            float(w["population"]),
        )
        for uid, w in wards.items()
    )
    demand = {
        (r["scenario_profile"], r["cell_id"], r["interval_start"]): r
        for r in tables["demand_intervals"]
    }
    operations = {
        (r["scenario_profile"], r["site_id"], r["interval_start"]): r
        for r in tables["station_operations"]
    }
    costs = {
        (r["scenario_profile"], r["site_id"], r["interval_start"]): r
        for r in tables["electricity_cost_intervals"]
    }
    expected_slots = cfg["calendar"]["days"] * 1440 // cfg["calendar"]["interval_minutes"]
    profiles = cfg["demand"]["profiles"]
    checks["time_series_complete"] = (
        len(demand)
        == len(tables["demand_intervals"])
        == len(nodes) * expected_slots * len(profiles)
        and len(operations)
        == len(tables["station_operations"])
        == len(sites) * expected_slots * len(profiles)
        and costs.keys() == operations.keys()
        and len(costs) == len(tables["electricity_cost_intervals"])
    )
    request_counts = Counter()
    request_energy = defaultdict(float)
    delivered_by_slot = defaultdict(float)
    sessions_by_slot = Counter()
    arrivals_by_slot = Counter()
    abandoned_by_slot = Counter()
    occupied_minutes = defaultdict(float)
    requests_valid = True
    for r in tables["charging_requests"]:
        profile, sid, cid = r["scenario_profile"], r["site_id"], r["cell_id"]
        arrival = datetime.fromisoformat(r["arrival_time"])
        key = (profile, cid, r["arrival_time"])
        requested = float(r["requested_energy_kwh"])
        delivered = float(r["delivered_energy_kwh"])
        requests_valid &= (
            sid in sites
            and cid in nodes
            and key in demand
            and r["unit_id"] == sites[sid]["unit_id"] == nodes[cid]["unit_id"]
            and requested > 0
            and 0 <= delivered <= requested
        )
        request_counts[key] += 1
        request_energy[key] += requested
        arrivals_by_slot[(profile, sid, r["arrival_time"])] += 1
        if r["status"] == "completed":
            start, end = map(datetime.fromisoformat, (r["start_time"], r["end_time"]))
            op_key = (profile, sid, r["start_time"])
            requests_valid &= (
                arrival <= start < end
                and op_key in operations
                and close(delivered, requested)
                and close(
                    (end - start).total_seconds() / 3600 * float(r["charging_power_kw"]), delivered
                )
                and close(float(r["wait_minutes"]), (start - arrival).total_seconds() / 60)
                and float(r["wait_minutes"]) <= cfg["operations"]["maximum_wait_minutes"]
                and (end - start).total_seconds() / 60 <= cfg["calendar"]["interval_minutes"]
            )
            delivered_by_slot[op_key] += delivered
            sessions_by_slot[op_key] += 1
            occupied_minutes[op_key] += (end - start).total_seconds() / 60
        else:
            requests_valid &= r["status"] in ("pending", "abandoned") and delivered == 0
            requests_valid &= r["start_time"] == r["end_time"] == ""
            if r["status"] == "abandoned":
                abandoned_by_slot[(profile, sid, r["resolution_time"])] += 1
                requests_valid &= (
                    float(r["wait_minutes"]) > cfg["operations"]["maximum_wait_minutes"]
                )
    checks["request_energy_and_timestamps"] = bool(requests_valid)
    checks["demand_reconciles_to_requests"] = all(
        request_counts[key] == int(r["session_count"])
        and close(request_energy[key], r["energy_kwh"])
        for key, r in demand.items()
    )
    port_bounds = True
    queue_balances = defaultdict(int)
    for key, r in sorted(operations.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        profile, sid, moment = key
        total, available, occupied = map(
            int, (r["total_ports"], r["available_ports"], r["occupied_ports_peak"])
        )
        port_bounds &= (
            total == int(sites[sid]["port_count"])
            and 0 <= occupied <= available <= total
            and sessions_by_slot[key] == int(r["completed_sessions"]) == occupied
            and close(delivered_by_slot[key], r["delivered_energy_kwh"])
            and close(occupied_minutes[key] / int(r["interval_minutes"]), r["occupied_ports_mean"])
            and int(r["arrived_requests"]) == arrivals_by_slot[key]
            and int(r["abandoned_requests"]) == abandoned_by_slot[key]
        )
        if r["open_by_schedule"] == "False":
            port_bounds &= available == occupied == 0
        queue_balances[(profile, sid)] += (
            arrivals_by_slot[key] - sessions_by_slot[key] - abandoned_by_slot[key]
        )
        port_bounds &= queue_balances[(profile, sid)] == int(r["queue_length_end"]) >= 0
    pending = Counter(
        (r["scenario_profile"], r["site_id"])
        for r in tables["charging_requests"]
        if r["status"] == "pending"
    )
    checks["operations_reconcile_ports_energy_and_queues"] = bool(port_bounds) and all(
        balance == pending[key] for key, balance in queue_balances.items()
    )
    tariff_ok = True
    for key, row in costs.items():
        moment = datetime.fromisoformat(key[2])
        minute = moment.hour * 60 + moment.minute
        day_group = "sunday" if moment.isoweekday() == 7 else "mon_sat"
        selected = [
            r
            for r in tables["selected_electricity_tariffs"]
            if r["day_group"] == day_group
            and int(r["start_minute"]) <= minute < int(r["end_minute"])
        ]
        tariff_ok &= len(selected) == 1
        if len(selected) != 1:
            continue
        tariff = selected[0]
        energy = float(operations[key]["delivered_energy_kwh"])
        grid_energy = energy / cfg["operations"]["grid_delivery_efficiency"]
        expected_cost = grid_energy * float(tariff["price_vnd_per_kwh_ex_vat"])
        tariff_ok &= (
            int(tariff["end_minute"]) >= minute + int(row["interval_minutes"])
            and row["schedule_id"] == cfg["finance"]["schedule_id"]
            and row["voltage_band_id"] == cfg["finance"]["voltage_band_id"]
            and row["period_code"] == tariff["period_code"]
            and close(row["grid_energy_kwh"], grid_energy)
            and close(row["electricity_cost_vnd_ex_vat"], expected_cost, 0.02)
            and close(
                row["electricity_cost_vnd_inc_vat"],
                expected_cost * (1 + float(tariff["vat_rate"])),
                0.02,
            )
        )
    checks["tariff_boundaries_and_cost_arithmetic"] = bool(tariff_ok)
    checks["candidate_costs_add_up"] = all(
        r["candidate_id"] in candidates
        and close(
            r["total_capex_vnd"],
            sum(
                float(r[k]) for k in ("charger_capex_vnd", "site_setup_vnd", "interconnection_vnd")
            ),
        )
        and close(
            r["annual_opex_ex_electricity_vnd"],
            sum(
                float(r[k])
                for k in ("annual_lease_vnd", "annual_fixed_opex_vnd", "annual_maintenance_vnd")
            ),
        )
        for r in tables["candidate_cost_assumptions"]
    )
    checks["period_finance_not_claimed_profit"] = all(
        r["npv"] == r["payback_years"] == ""
        and close(
            r["illustrative_revenue_vnd_ex_vat"],
            float(r["delivered_energy_kwh"]) * cfg["finance"]["revenue_vnd_per_kwh_ex_vat"],
            0.05,
        )
        and close(
            r["revenue_minus_electricity_vnd"],
            float(r["illustrative_revenue_vnd_ex_vat"]) - float(r["electricity_cost_vnd_ex_vat"]),
            0.02,
        )
        for r in tables["finance_period_summary"]
    )
    if "access" in cfg:
        access = cfg["access"]
        rows = load_csv(path / "access_matrix.csv")
        target_by_id = {**sites, **candidates}
        expected_pairs = {
            (cid, tid, profile)
            for cid in nodes
            for tid in target_by_id
            for profile in access["speed_kmh_by_profile"]
        }
        actual_pairs = {(r["cell_id"], r["target_id"], r["access_profile"]) for r in rows}
        checks["access_all_pairs_all_profiles"] = actual_pairs == expected_pairs and len(
            rows
        ) == len(actual_pairs)
        access_ok = True
        for r in rows:
            node, target = nodes[r["cell_id"]], target_by_id[r["target_id"]]
            lat1, lat2 = math.radians(float(node["lat"])), math.radians(float(target["lat"]))
            dlat = lat2 - lat1
            dlon = math.radians(float(target["lon"]) - float(node["lon"]))
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            distance = 2 * 6371008.8 * math.atan2(math.sqrt(a), math.sqrt(max(0, 1 - a)))
            speed = access["speed_kmh_by_profile"][r["access_profile"]]
            proxy_distance = distance * access["circuity_factor"]
            minutes = proxy_distance / 1000 / speed * 60 + access["fixed_access_minutes"]
            access_ok &= (
                close(r["distance_geodesic_m"], distance, 1e-5)
                and close(r["distance_proxy_m"], proxy_distance, 1e-5)
                and close(r["travel_minutes_proxy"], minutes, 1e-5)
                and (r["within_access_target"] == "True")
                == (minutes <= access["target_access_minutes"])
                and r["target_type"]
                == ("existing_site" if r["target_id"] in sites else "candidate_site")
                and r["source_unit_id"] == node["unit_id"]
                and r["target_unit_id"] == target["unit_id"]
                and r["source_type"] == "scenario"
                and r["value_status"] == "illustrative"
                and r["road_connectivity_status"]
                == r["connector_compatibility_status"]
                == "unknown"
            )
        checks["access_proxy_arithmetic_and_provenance"] = bool(access_ok)
        results = load_csv(path / "candidate_constraints.csv")
        eligibilities = load_csv(path / "candidate_eligibility.csv")
        grouped = defaultdict(list)
        for r in results:
            grouped[r["candidate_id"]].append(r)
        physical = {
            "land_site_control",
            "grid_capacity",
            "permit_safety",
            "physical_road_access",
            "connector_compatibility",
        }
        checks["constraints_unknown_not_zero_or_pass"] = (
            set(grouped) == set(candidates)
            and len(results) == len(candidates) * 10
            and all(
                r["status"] == "unknown" and r["value"] == "" and r["source_type"] == "unknown"
                for r in results
                if r["constraint_id"] in physical
            )
        )
        eligibility_ok = len(eligibilities) == len(candidates)
        for r in eligibilities:
            statuses = Counter(x["status"] for x in grouped[r["candidate_id"]])
            expected = (
                "excluded" if statuses["fail"] else "conditional" if statuses["unknown"] else "pass"
            )
            eligibility_ok &= (
                r["eligibility"] == expected
                and r["ready_to_build"] == "False"
                and (r["screening_allowed"] == "True") == (expected != "excluded")
                and int(r["unknown_constraints"]) == statuses["unknown"] == 5
                and int(r["passed_constraints"]) == statuses["pass"] == 5
                and int(r["failed_constraints"]) == 0
            )
        checks["constraint_eligibility_and_budget_package"] = bool(eligibility_ok) and (
            cfg["constraints"]["portfolio_budget_vnd"] == cfg["finance"]["budget_vnd"]
            and close(sum(cfg["constraints"]["score_weights"].values()), 100)
            and 0 < cfg["constraints"]["minimum_evidence_coverage"] <= 1
            and load_json(path / "technical_constraints_package.json")[
                "public_policy_overlay"
            ].startswith("disabled")
        )
    if not all(checks.values()):
        failed = [key for key, ok in checks.items() if not ok]
        raise ValueError("Saved dataset validation failed: " + ", ".join(failed))
    return {"status": "PASS", "snapshot_id": manifest["snapshot_id"], "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, nargs="?", default=DEFAULT_SNAPSHOT)
    args = parser.parse_args()
    print(json.dumps(validate(args.snapshot), ensure_ascii=False, indent=2))
