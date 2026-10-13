"""Canonical DATA_PLAN views; derive from existing fixture, never invent observations."""

from __future__ import annotations

import copy
from collections import Counter, defaultdict


def quantile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def align_tables(
    cfg,
    template_id,
    population,
    existing,
    candidates,
    nodes,
    demand,
    operations,
    requests,
    poi,
    model_keys,
    finance_package,
    wards,
):
    """Mutate additive columns and return the canonical observation/administrative-cell views."""
    boundary_id = "hcm-ADMINISTRATIVE_2025-nine-wards"
    scenario_ids = {profile: f"{template_id}-{profile}" for profile in cfg["demand"]["profiles"]}
    for ward in wards:
        p = ward["properties"]
        p.update(
            boundary_id=p["unit_id"],
            boundary_version="ADMINISTRATIVE_2025",
            valid_from=None,
            valid_from_status="unknown",
            legacy_area=None,
            legacy_area_status="unknown",
            source_url=cfg["context"]["source_url"],
        )
    for site in existing:
        site.update(
            power_kw=site["port_count"] * site["power_kw_per_port"],
            power_kw_scope="site",
            source_url=None,
            source_url_status="not_applicable",
            source_url_notes="Local synthetic fixture; no public URL for this generated inventory.",
            connector_type_status="unknown",
            boundary_id=boundary_id,
            boundary_version="ADMINISTRATIVE_2025",
        )
    for candidate in candidates:
        candidate.update(
            candidate_subtype=candidate["candidate_type"],
            candidate_type="parcel",
            parcel_status="synthetic_site_hypothesis_no_verified_parcel_boundary",
            source_url=cfg["context"]["source_url"],
            source_url_scope="location_context_only",
            boundary_id=boundary_id,
            boundary_version="ADMINISTRATIVE_2025",
        )
    for node in nodes:
        node.update(
            source_ref="generation_config.json#/demand",
            source_url=None,
            administrative_cell_id=node["unit_id"],
        )
    for key, rows in (("demand", demand), ("operations", operations), ("requests", requests)):
        for row in rows:
            row.update(
                scenario_id=scenario_ids[row["scenario_profile"]],
                quality_status="fully_synthetic_illustrative_not_calibrated",
                source_ref="generation_config.json#/"
                + ("demand" if key == "demand" else "operations"),
            )
            if key in ("demand", "requests"):
                row.update(demand_node_id=row["cell_id"], administrative_cell_id=row["unit_id"])

    waits = defaultdict(list)
    for request in requests:
        if request["status"] == "completed":
            waits[(request["scenario_profile"], request["site_id"], request["start_time"])].append(
                request["wait_minutes"]
            )
    observations = []
    for i, row in enumerate(operations, 1):
        values = waits[(row["scenario_profile"], row["site_id"], row["interval_start"])]
        observations.append(
            {
                "observation_id": f"synthetic-observation-{i:07d}",
                "site_id": row["site_id"],
                "unit_id": row["unit_id"],
                "scenario_id": row["scenario_id"],
                "scenario_profile": row["scenario_profile"],
                "interval_start": row["interval_start"],
                "interval_minutes": row["interval_minutes"],
                "session_count": row["completed_sessions"],
                "energy_kwh": row["delivered_energy_kwh"],
                "peak_ports_busy": row["occupied_ports_peak"],
                "available_ports": row["available_ports"],
                "wait_p50_min": quantile(values, 0.5),
                "wait_p90_min": quantile(values, 0.9),
                "abandon_count": row["abandoned_requests"],
                "demand_class": "synthetic",
                "source_type": "synthetic",
                "is_synthetic": True,
                "quality_status": "derived_synthetic_operational_view",
                "source_ref": "station_operations.csv;charging_requests.csv",
                "wait_population": "completed_sessions_started_in_interval",
                "wait_quantile_method": "linear_interpolation; null_if_no_completed_session",
            }
        )

    populations = {r["unit_id"]: r for r in population}
    model_weight = {r["feature_id"]: r["modeling_weight"] for r in model_keys}
    mixtures = defaultdict(Counter)
    for feature in poi:
        p = feature["properties"]
        mixtures[p["pilot_unit_id"]][p["category_group"]] += model_weight[p["feature_id"]]
    totals = defaultdict(lambda: [0, 0.0, 0.0])
    for row in demand:
        value = totals[(row["scenario_profile"], row["unit_id"], row["interval_start"])]
        value[0] += row["session_count"]
        value[1] += row["energy_kwh"]
        value[2] += row["expected_sessions"]
    cells = []
    for (profile, uid, moment), (sessions, energy, expected) in sorted(totals.items()):
        mix = mixtures[uid]
        mix_total = sum(mix.values())
        cells.append(
            {
                "cell_id": uid,
                "unit_id": uid,
                "period": moment,
                "interval_minutes": cfg["calendar"]["interval_minutes"],
                "spatial_resolution": "administrative_ward_ADMINISTRATIVE_2025",
                "population_or_flow": populations[uid]["population"],
                "population_reference_date": None,
                "ev_share_scenario": cfg["demand"]["ev_share"],
                "demand_profile_multiplier": cfg["demand"]["profiles"][profile],
                "home_charging_share": cfg["demand"]["home_charging_share"],
                "poi_mix": {name: value / mix_total for name, value in sorted(mix.items())},
                "estimated_sessions": sessions,
                "estimated_kwh": round(energy, 6),
                "expected_sessions": round(expected, 6),
                "source_type": "synthetic",
                "scenario_id": scenario_ids[profile],
                "scenario_profile": profile,
                "is_synthetic": True,
                "quality_status": "aggregated_synthetic_requests_not_observed_demand",
                "source_ref": "demand_intervals.csv;population.csv;poi_model_weights.csv",
                "population_status": populations[uid]["population_status"],
                "poi_mix_status": "derived_context_proxy",
                "value_status": "estimated",
            }
        )

    finance_package.update(
        source="generation_config.json#/finance;selected_electricity_tariffs.csv",
        effective_from=None,
        effective_to=None,
        rules=[],
        units={key: value["unit"] for key, value in finance_package["inputs"].items()},
        effective_date_status="unknown_for_real_contract; synthetic_period_in_generation_config",
    )
    for value in finance_package["inputs"].values():
        value.update(
            legacy_value_status=value["value_status"],
            value_status="provided",
            quality_status="provided_illustrative_assumption_not_observed_market_value",
        )
    metadata = {
        "boundary_id": boundary_id,
        "boundary_version": "ADMINISTRATIVE_2025",
        "valid_from": None,
        "valid_to": None,
        "value_status": "unknown",
        "field_status": {
            "boundary_id": "provided",
            "boundary_version": "provided",
            "source_url": "provided",
            "valid_from": "unknown",
            "crosswalk_ref": "unknown",
            "legacy_area": "unknown",
        },
        "source_url": cfg["context"]["source_url"],
        "source_ref": cfg["sources"]["boundaries"],
        "legacy_area": None,
        "legacy_area_status": "unknown",
        "crosswalk_ref": None,
        "crosswalk_status": "unknown",
        "crosswalk_required_for_this_snapshot": False,
        "notes": (
            "Current joins use coordinates/current unit IDs only. "
            "No historical administrative crosswalk supplied; none invented."
        ),
        "unit_ids": sorted(populations),
    }
    return observations, cells, metadata, scenario_ids


def scenario_config(cfg, scenario, scenario_ids):
    config = {
        "scenario_id": scenario["scenario_id"],
        "version": scenario["scenario_version"],
        "owner": scenario["owner"],
        "effective_from": None,
        "created_at": scenario["created_at"],
        "study_area": scenario["study_area"],
        "boundary_version": "ADMINISTRATIVE_2025",
        "pilot_extent": "pilot_extent.geojson",
        "horizon_years": scenario["planning_horizon_years"],
        "data_snapshot_id": cfg["snapshot_id"],
        "algorithm_version": scenario["reproducibility"]["algorithm_version"],
        "technical": {
            "coverage_minutes": cfg["access"]["target_access_minutes"],
            "capacity_target": cfg["constraints"]["capacity_target"],
            "connector_mix": None,
            "candidate_rules": "technical_constraints_package.json",
            "access_model_ref": "access_model.json",
            "charger_options": [cfg["constraints"]["charger_option"]],
        },
        "policy": {
            "enabled": False,
            "priority_zones": [],
            "minimum_coverage_share": None,
            "grant_per_port": None,
            "eligibility_rules": None,
        },
        "finance": copy.deepcopy(scenario["finance"]["inputs"]),
        "demand_profiles": {
            name: {"scenario_id": sid, "multiplier": cfg["demand"]["profiles"][name]}
            for name, sid in scenario_ids.items()
        },
        "source": "generation_config.json;scenario.json",
        "quality_status": "demo_mixed_source_and_synthetic",
        "is_synthetic": True,
        "value_status": "provided",
        "units": {
            "horizon_years": "year",
            "coverage_minutes": "minute",
            "budget_vnd": "VND",
            "capex_per_port_vnd": "VND/port",
            "annual_opex_per_site_vnd": "VND/site/year",
            "discount_rate": "fraction/year",
            "revenue_vnd_per_kwh": "VND/kWh",
        },
        "notes": (
            "Provided scenario values are illustrative, not observed market/site facts. "
            "Nullable disabled-policy inputs are not_applicable; "
            "missing physical inputs are unknown."
        ),
        "field_status": {
            "effective_from": "unknown",
            "technical.connector_mix": "unknown",
            "policy.minimum_coverage_share": "not_applicable",
            "policy.grant_per_port": "not_applicable",
            "policy.eligibility_rules": "not_applicable",
            "finance.tariff_vnd_per_kwh": "not_applicable",
        },
    }
    return config


def coerce_csv_row(row, definition):
    """Convert CSV primitives for a typed schema check; blank remains null, never zero."""
    import json

    result = dict(row)
    for key, spec in definition["properties"].items():
        if key not in row:
            continue
        value = row[key]
        kinds = spec.get("type", [])
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if value == "" and "null" in kinds:
            result[key] = None
        elif "integer" in kinds:
            result[key] = int(value)
        elif "number" in kinds:
            result[key] = float(value)
        elif "boolean" in kinds:
            if value not in ("True", "False"):
                raise ValueError(f"Invalid CSV boolean: {key}={value}")
            result[key] = value == "True"
        elif "object" in kinds or "array" in kinds:
            result[key] = json.loads(value)
    return result
