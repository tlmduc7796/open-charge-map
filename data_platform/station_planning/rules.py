"""P7 proxy access and P8 demo constraints, independent of API/DB/ranking."""

from __future__ import annotations

import math


def distance_m(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [*a[:2], *b[:2]])
    h = math.sin((lat2 - lat1) / 2) ** 2
    h += math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, h)))


def access_metrics(distance, access, profile):
    speed = access["speed_kmh_by_profile"][profile]
    factor = access["circuity_factor"]
    overhead = access["fixed_access_minutes"]
    target = access["target_access_minutes"]
    values = [distance, speed, factor, overhead, target]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Access parameters must be finite")
    if distance < 0 or speed <= 0 or factor < 1 or overhead < 0 or target <= 0:
        raise ValueError("Invalid access distance/speed/circuity/overhead/target")
    proxy_distance = distance * factor
    minutes = proxy_distance / 1000 / speed * 60 + overhead
    return proxy_distance, minutes, minutes <= target


def build_access_matrix(nodes, existing, candidates, access):
    rows = []
    targets = [("existing_site", r["site_id"], r) for r in existing]
    targets += [("candidate_site", r["candidate_id"], r) for r in candidates]
    for node in nodes:
        for kind, target_id, target in targets:
            distance = distance_m([node["lon"], node["lat"]], [target["lon"], target["lat"]])
            for profile, speed in access["speed_kmh_by_profile"].items():
                proxy_distance, minutes, within = access_metrics(distance, access, profile)
                rows.append(
                    {
                        "cell_id": node["cell_id"],
                        "source_unit_id": node["unit_id"],
                        "target_id": target_id,
                        "target_type": kind,
                        "target_unit_id": target["unit_id"],
                        "access_profile": profile,
                        "distance_geodesic_m": round(distance, 6),
                        "distance_proxy_m": round(proxy_distance, 6),
                        "travel_minutes_proxy": round(minutes, 6),
                        "target_access_minutes": access["target_access_minutes"],
                        "within_access_target": within,
                        "circuity_factor_assumption": access["circuity_factor"],
                        "speed_kmh_assumption": speed,
                        "fixed_access_minutes_assumption": access["fixed_access_minutes"],
                        "method_version": access["version"],
                        "source_type": "scenario",
                        "value_status": "illustrative",
                        "is_synthetic": True,
                        "road_connectivity_status": "unknown",
                        "connector_compatibility_status": "unknown",
                    }
                )
    return rows


def candidate_constraints(candidate, cfg, *, valid_geometry, inside_pilot, nominal_capex):
    """Evaluate data/scenario gates; preserve unverified physical feasibility."""
    rows = []
    candidate_id = candidate["candidate_id"]

    def add(rule, status, value, unit, source_type, reason, source_ref=None):
        rows.append(
            {
                "candidate_id": candidate_id,
                "constraint_id": rule,
                "status": status,
                "value": value,
                "unit": unit,
                "source_type": source_type,
                "reason_code": reason,
                "package_id": cfg["constraints"]["package_id"],
                "source_ref": source_ref
                or (
                    "generation_config.json" if source_type == "scenario" else "candidate_sites.csv"
                ),
            }
        )

    add(
        "valid_geometry",
        "pass" if valid_geometry else "fail",
        valid_geometry,
        "boolean",
        "synthetic",
        "valid_coordinate" if valid_geometry else "invalid_coordinate",
    )
    add(
        "inside_pilot",
        "pass" if inside_pilot else "fail",
        inside_pilot,
        "boolean",
        "synthetic",
        "inside_selected_pilot" if inside_pilot else "outside_selected_pilot",
    )
    gap = candidate["nearest_fixture_site_distance_m"]
    far_enough = gap >= cfg["candidates"]["minimum_existing_distance_m"]
    add(
        "new_site_fixture_spacing",
        "pass" if far_enough else "fail",
        gap,
        "m",
        "scenario",
        "meets_demo_spacing" if far_enough else "violates_demo_spacing",
    )
    option = cfg["constraints"]["charger_option"]
    option_ok = (
        option["charger_type"] == "DC"
        and isinstance(option["port_count"], int)
        and not isinstance(option["port_count"], bool)
        and option["port_count"] > 0
        and math.isfinite(option["power_kw_per_port"])
        and option["power_kw_per_port"] > 0
    )
    power = option["port_count"] * option["power_kw_per_port"]
    add(
        "technical_option",
        "pass" if option_ok else "fail",
        power,
        "kW",
        "scenario",
        "valid_demo_option" if option_ok else "invalid_demo_option",
    )
    # Raw values without field-level source evidence do not confirm physical feasibility.
    evidence = candidate.get("feasibility_evidence", {})

    def confirmed(field):
        meta = evidence.get(field, {})
        return (
            meta.get("value_status") == "provided"
            and meta.get("source_type") == "observed"
            and bool(meta.get("source_ref"))
        )

    access = candidate.get("access_feasible") if confirmed("access_feasible") else None
    add(
        "land_site_control",
        "unknown" if access is None else "pass" if access else "fail",
        access,
        "boolean",
        "unknown" if access is None else "observed",
        "site_control_unverified" if access is None else "confirmed_site_control",
        evidence.get("access_feasible", {}).get("source_ref"),
    )
    grid = candidate.get("grid_capacity_kw") if confirmed("grid_capacity_kw") else None
    add(
        "grid_capacity",
        "unknown" if grid is None else "pass" if grid >= power else "fail",
        grid,
        "kW",
        "unknown" if grid is None else "observed",
        "grid_capacity_unverified" if grid is None else "confirmed_grid_capacity",
        evidence.get("grid_capacity_kw", {}).get("source_ref"),
    )
    permit = candidate.get("permit_status", "unknown") if confirmed("permit_status") else "unknown"
    permit_status = {"confirmed_approved": "pass", "confirmed_rejected": "fail"}.get(
        permit, "unknown"
    )
    add(
        "permit_safety",
        permit_status,
        None if permit_status == "unknown" else permit,
        "status",
        "unknown" if permit_status == "unknown" else "observed",
        "permit_safety_unverified" if permit_status == "unknown" else "confirmed_permit_safety",
        evidence.get("permit_status", {}).get("source_ref"),
    )
    add("physical_road_access", "unknown", None, "boolean", "unknown", "road_access_unverified")
    add("connector_compatibility", "unknown", None, "connector", "unknown", "connector_unverified")
    affordable = nominal_capex <= cfg["constraints"]["portfolio_budget_vnd"]
    add(
        "individual_budget",
        "pass" if affordable else "fail",
        nominal_capex,
        "VND",
        "scenario",
        "fits_demo_budget_individually" if affordable else "exceeds_demo_budget_individually",
    )
    return rows


def eligibility_from_constraints(rows):
    if any(r["status"] == "fail" for r in rows):
        return "excluded"
    if any(r["status"] in ("unknown", "conditional") for r in rows):
        return "conditional"
    return "pass"


def constraints_package(cfg):
    package = dict(cfg["constraints"])
    package["access_model_ref"] = "access_model.json"
    definitions = [
        {"id": "valid_geometry", "effect": "hard_gate", "phase": "data_preparation"},
        {"id": "inside_pilot", "effect": "hard_gate", "phase": "data_preparation"},
        {"id": "new_site_fixture_spacing", "effect": "hard_gate", "phase": "data_preparation"},
        {"id": "technical_option", "effect": "hard_gate", "phase": "configuration"},
        *[
            {"id": name, "effect": "hard_gate_if_confirmed", "phase": "physical_feasibility"}
            for name in (
                "land_site_control",
                "grid_capacity",
                "permit_safety",
                "physical_road_access",
                "connector_compatibility",
            )
        ],
        {"id": "individual_budget", "effect": "hard_gate", "phase": "scenario_screening"},
        {
            "id": "portfolio_budget",
            "effect": "hard_gate",
            "phase": "portfolio_selection",
            "value": cfg["constraints"]["portfolio_budget_vnd"],
            "unit": "VND",
            "status": "illustrative",
            "cost_profile": "base_cost",
        },
        {
            "id": "evidence_coverage",
            "effect": "ranking_gate",
            "phase": "ranking",
            "value": cfg["constraints"]["minimum_evidence_coverage"],
            "unit": "fraction",
            "status": "illustrative",
        },
    ]
    package.update(
        source="generation_config.json#/constraints",
        effective_from=None,
        effective_to=None,
        formula_version="demo-constraints-evaluation-v1",
        quality_status="illustrative_technical_rules_with_unknown_physical_feasibility",
        units={
            "portfolio_budget_vnd": "VND",
            "power_kw_per_port": "kW/port",
            "minimum_evidence_coverage": "fraction",
            "maximum_utilization": "fraction",
        },
    )
    # Same rule envelope as the existing scenario schema; phase lives in notes/value.
    package["rules"] = []
    for definition in definitions:
        value = {"phase": definition["phase"]}
        if "value" in definition:
            value.update(threshold=definition["value"], unit=definition["unit"])
        if definition["effect"] == "hard_gate_if_confirmed":
            value["requires_confirmed_evidence"] = True
        if "cost_profile" in definition:
            value["cost_profile"] = definition["cost_profile"]
        package["rules"].append(
            {
                "rule_id": definition["id"],
                "category": "technical_demo",
                "effect": "hard_gate",
                "value_status": "illustrative",
                "source_ref": "generation_config.json#/constraints",
                "value": value,
                "effective_date": None,
                "notes": (
                    "Demo rule; physical feasibility fails only with confirmed source evidence."
                ),
            }
        )
    package["unverified_inputs"] = cfg["unknown_inputs"]
    package["limitations"] = [
        "Chốt cách xử lý unknown không xác nhận đất/điện/cấp phép là khả thi.",
        "Ma trận P7 là proxy scenario; cần áp capacity, opening hours và compatibility riêng.",
        "Individual budget pass không chứng minh toàn bộ portfolio nằm trong budget.",
        "Utilization target là giả định sizing; chưa chạy sizing/ranking/portfolio engine.",
        "Không coi tỷ trọng tiêu chí có dữ liệu là xác suất thành công hoặc độ tin cậy thực tế.",
    ]
    return package
