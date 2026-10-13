"""Prepare the approved nine-ward planning fixture without reading ref.kml.

This is a data-preparation tool, not the planning/recommendation engine.
Install scripts/requirements-station-planning.txt, or pass --dependency-dir
when dependencies were installed into a task-local directory.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.metadata
import json
import math
import re
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/station_planning_demo.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_platform.station_planning.data_plan import (  # noqa: E402
    align_tables,
    scenario_config,
)
from data_platform.station_planning.rules import (  # noqa: E402
    build_access_matrix,
    candidate_constraints,
    constraints_package,
    distance_m,
    eligibility_from_constraints,
)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path, rows):
    if not rows:
        raise ValueError(f"Cannot infer columns for empty table: {path.name}")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def fc(features):
    return {"type": "FeatureCollection", "features": features}


def point_feature(row, id_field):
    return {
        "type": "Feature",
        "id": row[id_field],
        "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
        "properties": row,
    }


def open_at(opening, moment):
    if opening.startswith("24/7"):
        return True
    times = re.findall(r"\d{2}:\d{2}", opening)
    if len(times) != 2:
        raise ValueError(f"Unsupported hours: {opening}")
    start, end = [int(v[:2]) * 60 + int(v[3:]) for v in times]
    minute = moment.hour * 60 + moment.minute
    return start <= minute < end if start < end else minute >= start or minute < end


def prepare(config_path=DEFAULT_CONFIG, output=None):
    import numpy as np
    import shapely
    from shapely.geometry import MultiLineString, mapping, shape
    from shapely.ops import unary_union

    cfg = read_json(config_path)
    out = (output or ROOT / cfg["output_directory"]).resolve()
    if not out.is_relative_to(ROOT.resolve()):
        raise ValueError("Output must be inside this workspace")
    source_paths = {k: (ROOT / v).resolve() for k, v in cfg["sources"].items()}
    excluded = {(ROOT / p).resolve() for p in cfg["excluded_sources"]}
    if excluded.intersection(source_paths.values()) or any(
        p.name.casefold() == "ref.kml" for p in source_paths.values()
    ):
        raise ValueError("Excluded input present in source allowlist")
    if any(not p.is_relative_to((ROOT / "raw_data").resolve()) for p in source_paths.values()):
        raise ValueError("Source outside raw_data")
    # Read only explicitly approved files. Never glob/read historical catalog files.
    inputs = {k: read_json(p) for k, p in source_paths.items() if p.suffix != ".csv"}
    ward_report = inputs["ward_selection"]
    wanted = {"hcm_2025_" + v for v in ward_report["ward_admin_ids"].values()}
    wards = sorted(
        [f for f in inputs["boundaries"]["features"] if f["properties"]["unit_id"] in wanted],
        key=lambda f: f["properties"]["unit_id"],
    )
    assert len(wards) == 9 and len(inputs["existing_sites"]["features"]) == 37
    ward_shapes = {f["properties"]["unit_id"]: shape(f["geometry"]) for f in wards}
    assert all(g.is_valid for g in ward_shapes.values())
    pilot = unary_union(list(ward_shapes.values()))
    assert pilot.is_valid
    ward_by_name = {f["properties"]["unit_name"]: f["properties"]["unit_id"] for f in wards}

    def locate(point):
        matches = sorted(uid for uid, geo in ward_shapes.items() if geo.covers(point))
        return matches[0] if matches else None

    population = []
    for f in wards:
        p = f["properties"]
        population.append(
            {
                **p,
                "source_type": "observed",
                "is_synthetic": False,
                "source_ref": cfg["sources"]["boundaries"],
                "source_url": cfg["context"]["source_url"],
            }
        )

    existing = []
    for f in inputs["existing_sites"]["features"]:
        p = f["properties"]
        match = re.search(r"có (\d+) cổng", p["Trụ sạc:"])
        if not match:
            raise ValueError(f"Unknown ports in selected fixture: {p['Tên']}")
        lon, lat = f["geometry"]["coordinates"][:2]
        uid = ward_by_name[p["Phường:"]]
        assert ward_shapes[uid].covers(shape(f["geometry"]))
        existing.append(
            {
                "site_id": p["Tên"],
                "unit_id": uid,
                "lat": lat,
                "lon": lon,
                "site_type": "urban",
                "charger_type": "DC",
                "connector_type": None,
                "port_count": int(match.group(1)),
                "power_kw_per_port": 80,
                "power_status": "synthetic_assumption",
                "access_type": "public",
                "opening_hours": p["Hoạt động:"].split(" •")[0],
                "price_vnd_per_kwh": None,
                "uptime_ratio": None,
                "valid_from": None,
                "valid_to": None,
                "source_type": "synthetic",
                "is_synthetic": True,
                "quality_status": "demo_fixture_not_verified_inventory",
                "source_ref": cfg["sources"]["existing_sites"],
            }
        )
    existing.sort(key=lambda r: r["site_id"])

    # Keep all source POI records; only downweight flagged duplicates for modeling.
    poi = []
    for f in inputs["poi"]["features"]:
        g = shape(f["geometry"])
        if not pilot.covers(g):
            continue
        item = copy.deepcopy(f)
        item["properties"]["pilot_unit_id"] = locate(g)
        poi.append(item)
    poi.sort(key=lambda f: f["properties"]["feature_id"])
    group_counts = Counter(
        f["properties"]["possible_duplicate_group"]
        for f in poi
        if f["properties"].get("possible_duplicate_group")
    )
    model_keys = []
    for f in poi:
        p = f["properties"]
        group = p.get("possible_duplicate_group")
        weight = 1 / group_counts[group] if group else 1
        model_keys.append(
            {
                "feature_id": p["feature_id"],
                "unit_id": p["pilot_unit_id"],
                "possible_duplicate_group": group,
                "modeling_weight": weight,
                "rule_status": "conservative_proxy_not_verified_entity_merge",
            }
        )
    model_weight = {r["feature_id"]: r["modeling_weight"] for r in model_keys}

    transport = []
    for f in inputs["transport"]["features"]:
        geo = shape(f["geometry"])
        if not geo.intersects(pilot):
            continue
        clipped = geo.intersection(pilot)
        if clipped.geom_type == "GeometryCollection":
            lines = []
            for part in clipped.geoms:
                if part.geom_type == "LineString":
                    lines.append(part)
                elif part.geom_type == "MultiLineString":
                    lines.extend(part.geoms)
            clipped = MultiLineString(lines) if lines else clipped
        # A line touching only at a boundary point is not a transport point record.
        if geo.geom_type != "Point" and clipped.geom_type not in ("LineString", "MultiLineString"):
            continue
        if clipped.is_empty:
            continue
        item = copy.deepcopy(f)
        item["geometry"] = mapping(clipped)
        p = item["properties"]
        ids = sorted(uid for uid, g in ward_shapes.items() if g.intersects(clipped))
        p.update(
            {
                "pilot_unit_ids": ids,
                "pilot_unit_id": ids[0] if len(ids) == 1 else None,
                "geometry_clipped_to_pilot": not geo.equals(clipped),
            }
        )
        transport.append(item)
    transport.sort(key=lambda f: f["properties"]["feature_id"])
    assert all(f["properties"].get("traffic_volume_vehicles_per_hour") is None for f in transport)
    transport_points = [f for f in transport if f["geometry"]["type"] == "Point"]

    def transport_count(coords):
        radius = cfg["candidates"]["transport_context_radius_m"]
        return sum(
            distance_m(coords, f["geometry"]["coordinates"]) <= radius for f in transport_points
        )

    def nearest_existing(coords):
        return min(distance_m(coords, [r["lon"], r["lat"]]) for r in existing)

    pool_by_ward = defaultdict(list)
    for f in [*poi, *transport_points]:
        p = f["properties"]
        if p["category"] not in cfg["candidates"]["eligible_categories"]:
            continue
        coords = f["geometry"]["coordinates"][:2]
        uid = locate(shape(f["geometry"]))
        gap = nearest_existing(coords)
        if uid is None or gap < cfg["candidates"]["minimum_existing_distance_m"]:
            continue
        pool_by_ward[uid].append((f, gap, transport_count(coords)))

    candidates = []
    chosen_coords = []
    for uid in sorted(wanted):
        pool = pool_by_ward[uid]
        for n in range(cfg["candidates"]["per_ward"]):
            if n == 0:
                ordered = sorted(pool, key=lambda x: (-x[1], x[0]["properties"]["feature_id"]))
                reason = "poi_context_with_fixture_coverage_gap"
            else:
                ordered = sorted(
                    pool, key=lambda x: (-x[2], -x[1], x[0]["properties"]["feature_id"])
                )
                reason = "transport_infrastructure_context_for_traffic_scenario"
            selected = next(
                (
                    x
                    for x in ordered
                    if all(
                        distance_m(x[0]["geometry"]["coordinates"], c)
                        >= cfg["candidates"]["minimum_candidate_spacing_m"]
                        for c in chosen_coords
                    )
                ),
                None,
            )
            if selected is None:
                raise ValueError(f"Insufficient distinct grounded candidates in {uid}")
            f, gap, count = selected
            p = f["properties"]
            lon, lat = f["geometry"]["coordinates"][:2]
            high = count >= cfg["candidates"]["high_traffic_proxy_threshold_points"]
            candidates.append(
                {
                    "candidate_id": f"cand-{uid}-{n + 1:02d}",
                    "unit_id": uid,
                    "lat": lat,
                    "lon": lon,
                    "candidate_type": "poi_grounded_synthetic_site",
                    "context_feature_id": p["feature_id"],
                    "context_name": p["name"],
                    "context_category": p["category"],
                    "generation_reason": reason,
                    "nearest_fixture_site_distance_m": round(gap, 3),
                    "distance_method": "great_circle_screening_not_access_matrix",
                    "transport_points_within_radius": count,
                    "traffic_intensity_scenario": "high" if high else "base",
                    "traffic_status": cfg["candidates"]["traffic_status"],
                    "access_feasible": None,
                    "grid_capacity_kw": None,
                    "land_cost_vnd": None,
                    "interconnection_cost_vnd": None,
                    "permit_status": "unknown",
                    "eligibility": "conditional",
                    "source_type": "synthetic",
                    "is_synthetic": True,
                    "quality_status": "location_grounded_deployment_unverified",
                    "source_ref": "context_poi.geojson"
                    if f in poi
                    else "context_transport.geojson",
                }
            )
            chosen_coords.append([lon, lat])

    # Demand support nodes are chosen independently of candidates/site rankings.
    nodes = []
    for ward in wards:
        uid = ward["properties"]["unit_id"]
        points = [f for f in poi if f["properties"]["pilot_unit_id"] == uid]
        centroid = ward_shapes[uid].representative_point()
        anchors = [
            min(
                points,
                key=lambda f: distance_m(f["geometry"]["coordinates"], [centroid.x, centroid.y]),
            )
        ]
        while len(anchors) < cfg["demand"]["nodes_per_ward"]:
            anchors.append(
                max(
                    points,
                    key=lambda f: min(
                        distance_m(f["geometry"]["coordinates"], a["geometry"]["coordinates"])
                        for a in anchors
                    ),
                )
            )
        weights = [0.0] * len(anchors)
        for f in points:
            i = min(
                range(len(anchors)),
                key=lambda i: distance_m(
                    f["geometry"]["coordinates"], anchors[i]["geometry"]["coordinates"]
                ),
            )
            weights[i] += model_weight[f["properties"]["feature_id"]]
        total = sum(weights)
        mix = cfg["demand"]["poi_allocation_weight"]
        for i, anchor in enumerate(anchors):
            lon, lat = anchor["geometry"]["coordinates"][:2]
            share = (1 - mix) / len(anchors) + mix * weights[i] / total
            nodes.append(
                {
                    "cell_id": f"demand-{uid}-{i + 1:02d}",
                    "unit_id": uid,
                    "lat": lat,
                    "lon": lon,
                    "spatial_resolution": "point_supported_poi_cluster",
                    "population_allocation_weight": share,
                    "population_proxy": ward["properties"]["population"] * share,
                    "population_reference_date": None,
                    "context_feature_id": anchor["properties"]["feature_id"],
                    "weighted_poi_count": weights[i],
                    "source_type": "synthetic",
                    "is_synthetic": True,
                    "quality_status": "synthetic_demand_support_not_measured_cell",
                }
            )

    with source_paths["tariffs"].open(encoding="utf-8-sig", newline="") as f:
        tariffs = [
            r
            for r in csv.DictReader(f)
            if r["schedule_id"] == cfg["finance"]["schedule_id"]
            and r["voltage_band_id"] == cfg["finance"]["voltage_band_id"]
        ]
    assert tariffs
    for days in ("mon_sat", "sunday"):
        rows = sorted(
            [r for r in tariffs if r["day_group"] == days], key=lambda r: int(r["start_minute"])
        )
        assert int(rows[0]["start_minute"]) == 0 and int(rows[-1]["end_minute"]) == 1440
        assert all(a["end_minute"] == b["start_minute"] for a, b in zip(rows, rows[1:]))

    def tariff_at(moment):
        minute = moment.hour * 60 + moment.minute
        group = "sunday" if moment.isoweekday() == 7 else "mon_sat"
        matches = [
            r
            for r in tariffs
            if r["day_group"] == group and int(r["start_minute"]) <= minute < int(r["end_minute"])
        ]
        assert len(matches) == 1
        return matches[0]

    cal = cfg["calendar"]
    start = datetime.fromisoformat(cal["start"])
    step = cal["interval_minutes"]
    assert step == 30
    moments = [start + timedelta(minutes=i * step) for i in range(cal["days"] * 48)]
    demand_cfg = cfg["demand"]
    total_hour_weight = sum(demand_cfg["hour_weights"])
    demand_rows, operation_rows, requests, electricity = [], [], [], []
    by_ward_sites = {uid: [r for r in existing if r["unit_id"] == uid] for uid in wanted}
    summaries = {}
    for profile_index, (profile, multiplier) in enumerate(demand_cfg["profiles"].items()):
        rng = np.random.default_rng(np.random.SeedSequence([cfg["seed"], profile_index, 1]))
        op_rng = np.random.default_rng(np.random.SeedSequence([cfg["seed"], profile_index, 2]))
        queues = {s["site_id"]: deque() for s in existing}
        for interval_index, moment in enumerate(moments):
            arrivals = defaultdict(list)
            for node in nodes:
                mean = node["population_proxy"] * demand_cfg["vehicles_per_person"]
                mean *= demand_cfg["ev_share"] * (1 - demand_cfg["home_charging_share"])
                mean *= demand_cfg["sessions_per_ev_per_day"] * multiplier
                if moment.isoweekday() >= 6:
                    mean *= demand_cfg["weekend_multiplier"]
                mean *= demand_cfg["hour_weights"][moment.hour] / total_hour_weight / 2
                count = int(rng.poisson(mean))
                energies = np.clip(
                    rng.normal(
                        demand_cfg["energy_per_session_mean_kwh"],
                        demand_cfg["energy_per_session_std_kwh"],
                        count,
                    ),
                    demand_cfg["energy_per_session_min_kwh"],
                    demand_cfg["energy_per_session_max_kwh"],
                )
                energies = [round(float(e), 6) for e in energies]
                demand_rows.append(
                    {
                        "scenario_profile": profile,
                        "cell_id": node["cell_id"],
                        "unit_id": node["unit_id"],
                        "interval_start": moment.isoformat(),
                        "interval_minutes": step,
                        "expected_sessions": round(mean, 6),
                        "session_count": count,
                        "energy_kwh": round(sum(energies), 6),
                        "source_type": "synthetic",
                        "is_synthetic": True,
                    }
                )
                for energy in energies:
                    arrivals[node["unit_id"]].append((node["cell_id"], energy))
            arrived = Counter()
            for uid in sorted(wanted):
                sites = by_ward_sites[uid]
                probabilities = np.array([s["port_count"] for s in sites], dtype=float)
                probabilities /= probabilities.sum()
                for cell_id, energy in arrivals[uid]:
                    site = sites[int(op_rng.choice(len(sites), p=probabilities))]
                    sid = site["site_id"]
                    request = {
                        "request_id": f"{profile}-request-{len(requests) + 1:07d}",
                        "scenario_profile": profile,
                        "cell_id": cell_id,
                        "site_id": sid,
                        "unit_id": uid,
                        "arrival_time": moment.isoformat(),
                        "start_time": None,
                        "end_time": None,
                        "resolution_time": None,
                        "status": "pending",
                        "requested_energy_kwh": energy,
                        "delivered_energy_kwh": 0.0,
                        "wait_minutes": None,
                        "charging_power_kw": None,
                        "source_type": "synthetic",
                        "is_synthetic": True,
                    }
                    requests.append(request)
                    queues[sid].append(request)
                    arrived[sid] += 1
            for site in existing:
                sid = site["site_id"]
                online = open_at(site["opening_hours"], moment)
                available = site["port_count"] if online else 0
                if (
                    online
                    and op_rng.random() < cfg["operations"]["outage_probability_per_interval"]
                ):
                    available = 0
                elif online:
                    available -= int(
                        op_rng.binomial(
                            available, cfg["operations"]["partial_port_outage_probability"]
                        )
                    )
                abandoned = 0
                while queues[sid]:
                    wait = (
                        moment - datetime.fromisoformat(queues[sid][0]["arrival_time"])
                    ).total_seconds() / 60
                    if wait <= cfg["operations"]["maximum_wait_minutes"]:
                        break
                    request = queues[sid].popleft()
                    request.update(
                        status="abandoned", wait_minutes=wait, resolution_time=moment.isoformat()
                    )
                    abandoned += 1
                served, energy, busy_minutes = [], 0.0, 0.0
                for _ in range(min(available, len(queues[sid]))):
                    request = queues[sid].popleft()
                    power = cfg["operations"]["power_kw_per_port_assumption"]
                    duration = request["requested_energy_kwh"] / power * 60
                    assert duration <= step
                    finish = moment + timedelta(minutes=duration)
                    wait = (
                        moment - datetime.fromisoformat(request["arrival_time"])
                    ).total_seconds() / 60
                    request.update(
                        status="completed",
                        start_time=moment.isoformat(),
                        end_time=finish.isoformat(),
                        resolution_time=finish.isoformat(),
                        delivered_energy_kwh=request["requested_energy_kwh"],
                        charging_power_kw=power,
                        wait_minutes=wait,
                    )
                    served.append(request)
                    energy += request["delivered_energy_kwh"]
                    busy_minutes += duration
                operation_rows.append(
                    {
                        "scenario_profile": profile,
                        "site_id": sid,
                        "unit_id": site["unit_id"],
                        "interval_start": moment.isoformat(),
                        "interval_minutes": step,
                        "total_ports": site["port_count"],
                        "available_ports": available,
                        "occupied_ports_peak": len(served),
                        "occupied_ports_mean": round(busy_minutes / step, 6),
                        "arrived_requests": arrived[sid],
                        "completed_sessions": len(served),
                        "abandoned_requests": abandoned,
                        "queue_length_end": len(queues[sid]),
                        "delivered_energy_kwh": round(energy, 6),
                        "open_by_schedule": online,
                        "source_type": "synthetic",
                        "is_synthetic": True,
                    }
                )
                tariff = tariff_at(moment)
                # Half-hour intervals align with every tariff breakpoint in the selected schedule.
                assert moment.minute in (0, 30)
                assert int(tariff["end_minute"]) >= moment.hour * 60 + moment.minute + step
                grid_energy = energy / cfg["operations"]["grid_delivery_efficiency"]
                ex_vat = grid_energy * float(tariff["price_vnd_per_kwh_ex_vat"])
                electricity.append(
                    {
                        "scenario_profile": profile,
                        "site_id": sid,
                        "interval_start": moment.isoformat(),
                        "interval_minutes": step,
                        "delivered_energy_kwh": round(energy, 6),
                        "grid_energy_kwh": round(grid_energy, 6),
                        "schedule_id": tariff["schedule_id"],
                        "schedule_status": tariff["schedule_status"],
                        "voltage_band_id": tariff["voltage_band_id"],
                        "voltage_selection_status": cfg["finance"]["voltage_selection_status"],
                        "period_code": tariff["period_code"],
                        "price_vnd_per_kwh_ex_vat": int(tariff["price_vnd_per_kwh_ex_vat"]),
                        "vat_rate": float(tariff["vat_rate"]),
                        "electricity_cost_vnd_ex_vat": round(ex_vat, 2),
                        "electricity_cost_vnd_inc_vat": round(
                            ex_vat * (1 + float(tariff["vat_rate"])), 2
                        ),
                        "tariff_source_type": "observed",
                        "energy_source_type": "synthetic",
                        "efficiency_status": "illustrative_assumption",
                    }
                )
        selected_requests = [r for r in requests if r["scenario_profile"] == profile]
        statuses = Counter(r["status"] for r in selected_requests)
        summaries[profile] = {
            "requests": len(selected_requests),
            "completed": statuses["completed"],
            "abandoned": statuses["abandoned"],
            "pending_at_horizon": statuses["pending"],
            "demand_kwh": round(sum(r["requested_energy_kwh"] for r in selected_requests), 6),
            "delivered_kwh": round(sum(r["delivered_energy_kwh"] for r in selected_requests), 6),
        }

    finance_cfg = cfg["finance"]
    finance_package = {
        "package_id": "hcmc-demo-finance-v1",
        "version": 1,
        "owner": "student-team",
        "quality_status": "mixed_source_and_illustrative_assumptions",
        "formula_version": finance_cfg["formula_version"],
        "selected_tariff": {
            k: finance_cfg[k]
            for k in ("schedule_id", "voltage_band_id", "voltage_selection_status")
        },
        "tariff_source_ref": "selected_electricity_tariffs.csv",
        "tariff_status": tariffs[0]["schedule_status"],
        "inputs": {},
        "reference_new_site_ports": finance_cfg["reference_new_site_ports"],
        "reference_configuration_status": "finance_comparison_only_not_sizing_recommendation",
        "warnings": [
            "Chi phí là giả định demo, không phải giá thị trường.",
            "Lịch điện là tham chiếu lịch sử; không xác nhận hợp đồng của trạm.",
            "Không annualize một tuần synthetic thành dự báo doanh thu năm.",
            "Access là proxy demo; đất/điện/permit vẫn chưa được xác nhận khả thi.",
        ],
    }
    finance_units = {
        "budget_vnd": "VND",
        "capex_per_port_vnd": "VND/port",
        "site_setup_vnd": "VND/site",
        "interconnection_vnd": "VND/site",
        "annual_lease_vnd": "VND/site/year",
        "annual_fixed_opex_vnd": "VND/site/year",
        "maintenance_fraction_of_charger_capex": "fraction/year",
        "revenue_vnd_per_kwh_ex_vat": "VND/kWh",
        "discount_rate": "fraction/year",
        "payback_limit_years": "year",
    }
    for key, unit in finance_units.items():
        finance_package["inputs"][key] = {
            "value": finance_cfg[key],
            "unit": unit,
            "value_status": "illustrative",
            "source_type": "scenario",
            "is_synthetic": True,
            "source_ref": "generation_config.json#/finance/" + key,
        }
    cost_rows = []
    for candidate in candidates:
        for cost_profile, factor in finance_cfg["cost_sensitivity_factors"].items():
            ports = finance_cfg["reference_new_site_ports"]
            charger = ports * finance_cfg["capex_per_port_vnd"] * factor
            setup = finance_cfg["site_setup_vnd"] * factor
            connection = finance_cfg["interconnection_vnd"] * factor
            lease = finance_cfg["annual_lease_vnd"] * factor
            fixed = finance_cfg["annual_fixed_opex_vnd"] * factor
            maintenance = charger * finance_cfg["maintenance_fraction_of_charger_capex"]
            cost_rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "cost_profile": cost_profile,
                    "reference_port_count": ports,
                    "charger_capex_vnd": round(charger),
                    "site_setup_vnd": round(setup),
                    "interconnection_vnd": round(connection),
                    "total_capex_vnd": round(charger + setup + connection),
                    "annual_lease_vnd": round(lease),
                    "annual_fixed_opex_vnd": round(fixed),
                    "annual_maintenance_vnd": round(maintenance),
                    "annual_opex_ex_electricity_vnd": round(lease + fixed + maintenance),
                    "cost_status": "illustrative_assumptions_not_market_estimates",
                    "grid_feasibility_status": "unknown",
                    "source_type": "synthetic",
                    "is_synthetic": True,
                }
            )
    finance_summaries = []
    for profile in demand_cfg["profiles"]:
        e = [r for r in electricity if r["scenario_profile"] == profile]
        delivered = sum(r["delivered_energy_kwh"] for r in e)
        cost = sum(r["electricity_cost_vnd_ex_vat"] for r in e)
        revenue = delivered * finance_cfg["revenue_vnd_per_kwh_ex_vat"]
        finance_summaries.append(
            {
                "scenario_profile": profile,
                "period_days": cal["days"],
                "delivered_energy_kwh": round(delivered, 6),
                "electricity_cost_vnd_ex_vat": round(cost, 2),
                "illustrative_revenue_vnd_ex_vat": round(revenue, 2),
                "revenue_minus_electricity_vnd": round(revenue - cost, 2),
                "metric_status": "scenario_before_other_costs_not_profit",
                "npv": None,
                "payback_years": None,
            }
        )

    access_rows, constraint_rows, eligibility_rows = [], [], []
    if "access" in cfg and "constraints" in cfg:
        assert cfg["constraints"]["portfolio_budget_vnd"] == finance_cfg["budget_vnd"]
        assert (
            cfg["constraints"]["charger_option"]["port_count"]
            == finance_cfg["reference_new_site_ports"]
        )
        access_rows = build_access_matrix(nodes, existing, candidates, cfg["access"])
        base_costs = {
            r["candidate_id"]: r["total_capex_vnd"]
            for r in cost_rows
            if r["cost_profile"] == cfg["constraints"]["portfolio_cost_profile"]
        }
        for candidate in candidates:
            point = shape(point_feature(candidate, "candidate_id")["geometry"])
            finite = all(math.isfinite(candidate[k]) for k in ("lat", "lon"))
            rows = candidate_constraints(
                candidate,
                cfg,
                valid_geometry=finite
                and -90 <= candidate["lat"] <= 90
                and -180 <= candidate["lon"] <= 180,
                inside_pilot=pilot.buffer(1e-9).covers(point),
                nominal_capex=base_costs[candidate["candidate_id"]],
            )
            constraint_rows.extend(rows)
            eligibility = eligibility_from_constraints(rows)
            candidate["eligibility"] = eligibility
            eligibility_rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "eligibility": eligibility,
                    "screening_allowed": eligibility != "excluded",
                    "ready_to_build": False,
                    "passed_constraints": sum(r["status"] == "pass" for r in rows),
                    "failed_constraints": sum(r["status"] == "fail" for r in rows),
                    "unknown_constraints": sum(r["status"] == "unknown" for r in rows),
                    "required_grid_capacity_kw_scenario": cfg["constraints"]["charger_option"][
                        "port_count"
                    ]
                    * cfg["constraints"]["charger_option"]["power_kw_per_port"],
                    "base_capex_vnd_assumption": base_costs[candidate["candidate_id"]],
                    "package_id": cfg["constraints"]["package_id"],
                }
            )

    checks = {}
    checks["source_allowlist_excludes_ref"] = not excluded.intersection(source_paths.values())
    checks["nine_wards_and_37_sites"] = len(wards) == 9 and len(existing) == 37
    # Floating-point line intersections can lie a few ulps beyond the boundary.
    # 1e-9 degrees is about 0.1 mm, not a coverage or travel-time threshold.
    checks["geometries_within_pilot"] = all(
        pilot.buffer(1e-9).covers(shape(f["geometry"])) for f in [*poi, *transport]
    )
    checks["candidate_spacing_and_existing_exclusion"] = all(
        nearest_existing([c["lon"], c["lat"]]) >= cfg["candidates"]["minimum_existing_distance_m"]
        for c in candidates
    ) and all(
        distance_m(a, b) >= cfg["candidates"]["minimum_candidate_spacing_m"]
        for i, a in enumerate(chosen_coords)
        for b in chosen_coords[i + 1 :]
    )
    checks["population_allocation_conserved"] = all(
        abs(sum(r["population_allocation_weight"] for r in nodes if r["unit_id"] == uid) - 1) < 1e-9
        for uid in wanted
    )
    checks["port_and_energy_bounds"] = all(
        0 <= r["occupied_ports_peak"] <= r["available_ports"] <= r["total_ports"]
        and r["delivered_energy_kwh"] <= r["occupied_ports_peak"] * 80 * step / 60 + 1e-5
        for r in operation_rows
    )
    checks["closed_sites_have_no_charging"] = all(
        r["available_ports"] == r["occupied_ports_peak"] == 0
        for r in operation_rows
        if not r["open_by_schedule"]
    )
    checks["request_count_and_energy_conserved"] = all(
        summaries[p]["requests"]
        == sum(r["session_count"] for r in demand_rows if r["scenario_profile"] == p)
        and summaries[p]["requests"]
        == sum(summaries[p][k] for k in ("completed", "abandoned", "pending_at_horizon"))
        and math.isclose(
            summaries[p]["demand_kwh"],
            sum(r["energy_kwh"] for r in demand_rows if r["scenario_profile"] == p),
            abs_tol=1e-4,
        )
        for p in demand_cfg["profiles"]
    )
    checks["session_duration_and_energy_consistent"] = all(
        math.isclose(
            (
                datetime.fromisoformat(r["end_time"]) - datetime.fromisoformat(r["start_time"])
            ).total_seconds()
            / 3600
            * r["charging_power_kw"],
            r["delivered_energy_kwh"],
            abs_tol=1e-5,
        )
        for r in requests
        if r["status"] == "completed"
    )
    checks["traffic_is_not_measured_flow"] = all(
        f["properties"].get("traffic_volume_vehicles_per_hour") is None for f in transport
    )
    if access_rows:
        checks["access_matrix_complete"] = len(access_rows) == len(nodes) * (
            len(existing) + len(candidates)
        ) * len(cfg["access"]["speed_kmh_by_profile"])
        checks["constraints_preserve_unknown_feasibility"] = all(
            r["eligibility"] == "conditional"
            and r["unknown_constraints"] == 5
            and not r["ready_to_build"]
            for r in eligibility_rows
        )
    if not all(checks.values()):
        raise ValueError(f"Validation failed: {checks}")

    template_id = read_json(ROOT / "docs/station-planning/examples/hcmc-scenario-base.json")[
        "scenario_id"
    ]
    observations, cells, boundary_metadata, scenario_ids = align_tables(
        cfg,
        template_id,
        population,
        existing,
        candidates,
        nodes,
        demand_rows,
        operation_rows,
        requests,
        poi,
        model_keys,
        finance_package,
        wards,
    )
    checks["data_plan_views_conserve_sessions_energy"] = (
        sum(r["estimated_sessions"] for r in cells) == sum(r["session_count"] for r in demand_rows)
        and math.isclose(
            sum(r["estimated_kwh"] for r in cells),
            sum(r["energy_kwh"] for r in demand_rows),
            abs_tol=1e-4,
        )
        and len(observations) == len(operation_rows)
    )
    if not all(checks.values()):
        raise ValueError(f"DATA_PLAN alignment failed: {checks}")
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "generation_config.json", cfg)
    write_json(out / "pilot_units.geojson", fc(wards))
    write_json(
        out / "pilot_extent.geojson",
        fc(
            [
                {
                    "type": "Feature",
                    "id": cfg["snapshot_id"],
                    "geometry": mapping(pilot),
                    "properties": {
                        "pilot_extent_id": cfg["snapshot_id"],
                        "unit_ids": sorted(wanted),
                        "boundary_version": "ADMINISTRATIVE_2025",
                        "legal_effective_date": None,
                        "boundary_id": boundary_metadata["boundary_id"],
                        "valid_from": None,
                        "source_url": cfg["context"]["source_url"],
                    },
                }
            ]
        ),
    )
    write_json(out / "context_poi.geojson", fc(poi))
    write_json(out / "context_transport.geojson", fc(transport))
    write_json(out / "existing_sites.geojson", fc([point_feature(r, "site_id") for r in existing]))
    write_json(
        out / "candidate_sites.geojson", fc([point_feature(r, "candidate_id") for r in candidates])
    )
    write_json(out / "demand_nodes.geojson", fc([point_feature(r, "cell_id") for r in nodes]))
    for filename, rows in {
        "population.csv": population,
        "poi_model_weights.csv": model_keys,
        "existing_sites.csv": existing,
        "candidate_sites.csv": candidates,
        "demand_nodes.csv": nodes,
        "demand_intervals.csv": demand_rows,
        "station_operations.csv": operation_rows,
        "charging_requests.csv": requests,
        "selected_electricity_tariffs.csv": tariffs,
        "electricity_cost_intervals.csv": electricity,
        "candidate_cost_assumptions.csv": cost_rows,
        "finance_period_summary.csv": finance_summaries,
        "demand_observations.csv": observations,
        "demand_cells.csv": cells,
        "demand_node_cell_map.csv": [
            {
                "node_id": n["cell_id"],
                "cell_id": n["unit_id"],
                "unit_id": n["unit_id"],
                "population_allocation_weight": n["population_allocation_weight"],
                "source_ref": "demand_nodes.csv;pilot_units.geojson",
            }
            for n in nodes
        ],
    }.items():
        write_csv(out / filename, rows)
    write_json(out / "finance_package.json", finance_package)
    write_json(out / "boundary_metadata.json", boundary_metadata)
    write_json(
        out / "data_plan_contract.schema.json",
        read_json(ROOT / "docs/station-planning/schemas/planning-datasets.schema.json"),
    )
    write_json(
        out / "data_plan_alignment_report.json",
        {
            "status": "prepared_for_schema_validation",
            "contract_version": cfg["dataset_contract_version"],
            "basis": "docs/station-planning/DATA_PLAN_VI.md",
            "new_views": {
                "demand_observations.csv": len(observations),
                "demand_cells.csv": len(cells),
            },
            "added_fields": {
                "existing_sites": ["power_kw", "power_kw_scope", "source_url", "source_url_status"],
                "candidate_sites": ["candidate_subtype", "parcel_status"],
                "boundary": [
                    "boundary_id",
                    "boundary_version",
                    "valid_from",
                    "source_url",
                    "crosswalk_ref",
                    "crosswalk_status",
                ],
                "finance_package": ["source", "effective_from", "effective_to", "units", "rules"],
            },
            "unknowns_preserved": [
                "connector type",
                "physical dates",
                "local fixture public URL",
                "historical crosswalk",
                "legacy area",
                "land/grid/permit",
            ],
            "not_generated": {
                "od_flows.csv": "administrative demand_cells chosen; no OD input or model",
                "scenario_run_results": "recommendation engine has not run; no results fabricated",
            },
        },
    )
    if access_rows:
        write_csv(out / "access_matrix.csv", access_rows)
        write_json(out / "access_model.json", cfg["access"])
        write_json(out / "technical_constraints_package.json", constraints_package(cfg))
        write_csv(out / "candidate_constraints.csv", constraint_rows)
        write_csv(out / "candidate_eligibility.csv", eligibility_rows)
    write_json(
        out / "validation_report.json",
        {
            "status": "PASS",
            "checks": checks,
            "scenario_summaries": summaries,
            "counts": {
                "wards": len(wards),
                "sites": len(existing),
                "candidates": len(candidates),
                "poi": len(poi),
                "transport": len(transport),
                "demand_nodes": len(nodes),
                "demand_intervals": len(demand_rows),
                "operation_intervals": len(operation_rows),
                "requests": len(requests),
                "selected_tariff_intervals": len(tariffs),
                "flagged_duplicate_groups": len(group_counts),
                "access_pairs_profiles": len(access_rows),
                "candidate_constraint_results": len(constraint_rows),
                "demand_observations": len(observations),
                "administrative_demand_cells": len(cells),
            },
            "pending_parts": cfg["pending_parts"],
        },
    )
    scenario = read_json(ROOT / "docs/station-planning/examples/hcmc-scenario-base.json")
    scenario.update(
        scenario_version=cfg.get("scenario_version", 4), created_at="2026-10-13T00:00:00+07:00"
    )
    scenario["study_area"]["boundary_geometry_ref"] = "pilot_units.geojson"
    scenario["data_profile"].update(
        data_snapshot_id=cfg["snapshot_id"],
        notes=(
            "Prepared nine-ward fixture. P7 access_matrix.csv uses scenario travel proxies. "
            "P8 technical_constraints_package.json defines gates and unknown handling; "
            "candidate_constraints.csv retains unverified physical feasibility. See manifest.json, "
            "generation_config.json and validation_report.json. No ref.kml reads. "
            "Costs and station operations are illustrative; tariff is a historical reference."
        ),
    )
    scenario["demand"].update(
        ev_share=demand_cfg["ev_share"],
        home_charging_share=demand_cfg["home_charging_share"],
        value_status="illustrative",
        source_ref="generation_config.json#/demand",
    )
    scenario["reproducibility"]["random_seed"] = cfg["seed"]
    if access_rows:
        scenario["technical_gates"]["target_access_minutes"] = cfg["access"][
            "target_access_minutes"
        ]
        scenario["scoring"]["minimum_evidence_coverage"] = cfg["constraints"][
            "minimum_evidence_coverage"
        ]
        scenario["scoring"]["weights"] = cfg["constraints"]["score_weights"]
    # Package prepared; enable in a downstream adapter after its supported metrics are defined.
    scenario["finance"]["mode"] = "illustrative_assumptions"
    scenario["finance"]["formula_version"] = finance_cfg["formula_version"]
    scenario["finance"]["inputs"].update(
        budget_vnd=finance_cfg["budget_vnd"],
        capex_per_port_vnd=finance_cfg["capex_per_port_vnd"],
        annual_opex_per_site_vnd=(
            finance_cfg["annual_fixed_opex_vnd"]
            + finance_cfg["annual_lease_vnd"]
            + finance_cfg["reference_new_site_ports"]
            * finance_cfg["capex_per_port_vnd"]
            * finance_cfg["maintenance_fraction_of_charger_capex"]
        ),
        revenue_vnd_per_kwh=finance_cfg["revenue_vnd_per_kwh_ex_vat"],
        discount_rate=finance_cfg["discount_rate"],
        payback_limit_years=finance_cfg["payback_limit_years"],
        tariff_regime_ref="selected_electricity_tariffs.csv",
        assumption_range_ref="finance_package.json",
    )
    write_json(out / "scenario.json", scenario)
    write_json(out / "scenario_config.json", scenario_config(cfg, scenario, scenario_ids))
    from scripts.validate_station_planning_contract import validate_contract

    contract_result = validate_contract(out)
    alignment_report = read_json(out / "data_plan_alignment_report.json")
    alignment_report.update(contract_result)
    write_json(out / "data_plan_alignment_report.json", alignment_report)
    write_json(
        out / "data_dictionary.json",
        {
            "snapshot_id": cfg["snapshot_id"],
            "csv_null": "empty field; never zero",
            "crs": "EPSG:4326 for web processing; no independent assertion of source CRS",
            "timezone": cal["timezone"],
            "dataset_contract_version": cfg["dataset_contract_version"],
            "dataset_schema_ref": "data_plan_contract.schema.json",
            "data_plan_views": {
                "power_kw": (
                    "port_count * power_kw_per_port; total synthetic site nameplate, "
                    "not grid connection capacity"
                ),
                "source_url": (
                    "null for local synthetic inventory, not_applicable; "
                    "source_ref identifies actual input file"
                ),
                "candidate_type": (
                    "parcel is a synthetic site hypothesis; "
                    "candidate_subtype retains POI grounding; "
                    "no parcel boundary verified"
                ),
                "demand_observations": (
                    "37,296 synthetic station/interval rows derived from operations/requests; "
                    "not observed telemetry"
                ),
                "demand_cells": (
                    "9,072 ward/profile/interval rows aggregated from 27 node time series; "
                    "population_or_flow is a repeated static attribute, "
                    "never sum across periods/profiles"
                ),
                "wait_quantiles": (
                    "linear p50/p90 over completed sessions started in slot; "
                    "null when no completed session, not zero; excludes unserved waits"
                ),
                "poi_mix": (
                    "JSON object of normalized weighted context category shares; "
                    "encoded as JSON in CSV; context proxy"
                ),
                "scenario_config": (
                    "DATA_PLAN-facing configuration view; "
                    "scenario.json keeps existing strict scenario schema"
                ),
                "scenario_id": (
                    "per-profile scenario IDs link cells, observations, demand, operations "
                    "and requests; scenario_config maps IDs to profiles"
                ),
            },
            "access_matrix": (
                "P7 full demand-node/target matrix across wards, with fast/normal/slow speed "
                "assumptions. Circuity * great-circle distance, plus fixed overhead. "
                "Geometric reachability does not prove road connectivity, connector compatibility, "
                "opening hours or available capacity."
            ),
            "candidate_constraints": (
                "P8 per-candidate data/scenario checks and five unverified physical gates. "
                "Unknown keeps eligibility conditional; fail excludes only the affected candidate. "
                "Individual affordability is not a portfolio budget result."
            ),
            "context": (
                "Source-reported population and source POI/transport; "
                "no measured charging demand or traffic volume."
            ),
            "demand_nodes": (
                "Synthetic point-supported clusters; population weights sum to one per ward. "
                "Not a polygon grid or access matrix."
            ),
            "candidate_sites": (
                "Synthetic deployment proposals anchored to collected context; "
                "all feasibility unknown. Traffic labels are scenario/proxy."
            ),
            "demand_intervals": (
                "Poisson synthetic request counts; energy sum of synthetic request energy; "
                "low/base/high are assumptions, not probabilities."
            ),
            "station_operations": (
                "Peak online occupied ports and time-weighted mean; one job per port/slot. "
                "Availability can change between slots. All served jobs finish within slot."
            ),
            "charging_requests": (
                "One row per generated request: completed, abandoned or pending. "
                "Abandoned/pending energy is not delivered. Assignment by ward and "
                "port weights is synthetic, not driver routing."
            ),
            "electricity_cost_intervals": (
                "Delivered kWh / assumed efficiency * selected source price; VND before VAT "
                "and cash payment with source VAT. Thirty-minute slots align with tariff changes."
            ),
            "candidate_cost_assumptions": (
                "Illustrative nominal four-port costs and sensitivity cases, not sizing, "
                "grid feasibility or market quotes. OPEX excludes electricity."
            ),
            "finance_period_summary": (
                "Synthetic period revenue minus electricity only, not profit; "
                "NPV/payback unavailable. No annual extrapolation."
            ),
            "units": {
                "lat": "degree",
                "lon": "degree",
                "population": "person",
                "power_kw_per_port": "kW/port",
                "energy_kwh": "kWh",
                "interval_minutes": "minute",
                "wait_minutes": "minute",
                "nearest_fixture_site_distance_m": "m great circle",
                "all_cost_vnd_fields": "VND",
                "annual_cost_fields": "VND/year",
                "population_allocation_weight": "fraction",
                "travel_minutes_proxy": "minute, illustrative proxy",
                "distance_proxy_m": "m, illustrative proxy",
            },
        },
    )
    produced = sorted(p for p in out.iterdir() if p.is_file() and p.name != "manifest.json")
    write_json(
        out / "manifest.json",
        {
            "snapshot_id": cfg["snapshot_id"],
            "prepared_on": cfg["prepared_on"],
            "generator_version": cfg["generator_version"],
            "generator": "scripts/prepare_station_planning_demo.py",
            "generator_sha256": digest(Path(__file__)),
            "rules_module_sha256": digest(ROOT / "data_platform/station_planning/rules.py"),
            "data_plan_module_sha256": digest(ROOT / "data_platform/station_planning/data_plan.py"),
            "dataset_contract_version": cfg["dataset_contract_version"],
            "configuration_source": {
                "path": str(config_path.resolve().relative_to(ROOT)),
                "sha256": digest(config_path),
            },
            "scenario_template": {
                "path": "docs/station-planning/examples/hcmc-scenario-base.json",
                "sha256": digest(ROOT / "docs/station-planning/examples/hcmc-scenario-base.json"),
            },
            "seed": cfg["seed"],
            "dependencies": {
                "numpy": np.__version__,
                "shapely": shapely.__version__,
                "jsonschema": importlib.metadata.version("jsonschema"),
            },
            "source_files": {
                k: {"path": cfg["sources"][k], "sha256": digest(p)} for k, p in source_paths.items()
            },
            "excluded_sources": cfg["excluded_sources"],
            "pending_parts": cfg["pending_parts"],
            "source_geometry_handling": (
                "pilot union; point inclusion; transport line intersection with pilot; "
                "no invented source coordinates"
            ),
            "geometry_validation_tolerance_degrees": 1e-9,
            "files": {p.name: {"bytes": p.stat().st_size, "sha256": digest(p)} for p in produced},
            "warnings": [
                "Observed context does not make synthetic charging data observed.",
                "Population reference dates and legal boundary effective date remain unknown.",
                "POI duplicate groups downweighted conservatively, not verified merged entities.",
                "Coverage gaps describe the selected simulated existing-site fixture.",
                "P7 is illustrative access, not road routing or measured journey time.",
                "P8 handles unknown feasibility; no statutory policy or investment approval.",
                "No ranking, capacity sizing or portfolio recommendation generated.",
            ],
        },
    )
    print(
        json.dumps(
            {
                "output": str(out),
                "status": "PASS",
                "counts": read_json(out / "validation_report.json")["counts"],
            },
            ensure_ascii=False,
        )
    )
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dependency-dir", type=Path)
    args = parser.parse_args()
    if args.dependency_dir:
        sys.path.insert(0, str(args.dependency_dir.resolve()))
    prepare(args.config, args.output)
