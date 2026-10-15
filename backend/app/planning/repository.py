"""Read-only adapter from the pinned M1 demo snapshot into the M2 domain contract."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from backend.app.planning.domain import (
    PlanningDataError,
    PlanningInfrastructureError,
    PlanningRunConfig,
)

SNAPSHOT_ID = "hcmc-nine-wards-demo-v3"
CITY_ID = "VN-HCMC"
BOUNDARY_VERSION = "ADMINISTRATIVE_2025"
PILOT_EXTENT_ID = "hcmc-nine-wards-demo-v3"
ACCESS_PROFILE = "normal"
DEMAND_SOURCE_PROFILES = {"low", "base", "high"}
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data_platform" / "station_planning" / "demo_hcmc_v3"


class FilePlanningDataRepository:
    """Load one immutable M1 snapshot; no database copy or write path is introduced."""

    def __init__(self, snapshot_directory: Path | None = None) -> None:
        self._directory = snapshot_directory or _DEFAULT_DATA_DIR
        self._lock = Lock()
        self._bundle: dict[str, Any] | None = None

    def load_dataset(self, config: PlanningRunConfig) -> Mapping[str, Any]:
        if config.data_snapshot_id != SNAPSHOT_ID:
            raise PlanningDataError(
                f"Planning snapshot '{config.data_snapshot_id}' is not available."
            )
        bundle = self._load_bundle()
        return self._build_dataset(bundle, config)

    def load_demo_catalog(self) -> Mapping[str, Any]:
        """Return the same snapshot's choices and map layers for the Planner screen."""
        bundle = self._load_bundle()
        return bundle["demo_catalog"]

    def _load_bundle(self) -> dict[str, Any]:
        if self._bundle is not None:
            return self._bundle
        with self._lock:
            if self._bundle is None:
                self._bundle = self._read_and_validate_snapshot()
        return self._bundle

    def _read_and_validate_snapshot(self) -> dict[str, Any]:
        manifest = self._read_json("manifest.json", verify=False)
        self._require(
            isinstance(manifest.get("files"), Mapping),
            "M1 manifest does not contain a valid file-hash index.",
        )
        if manifest.get("snapshot_id") != SNAPSHOT_ID:
            raise PlanningDataError(
                "The configured M1 directory does not contain the pinned snapshot."
            )

        names = (
            "scenario_config.json",
            "boundary_metadata.json",
            "technical_constraints_package.json",
            "access_model.json",
            "pilot_extent.geojson",
            "candidate_sites.csv",
            "candidate_constraints.csv",
            "candidate_cost_assumptions.csv",
            "candidate_eligibility.csv",
            "demand_nodes.csv",
            "demand_intervals.csv",
            "access_matrix.csv",
            "existing_sites.csv",
        )
        json_data = {
            name: self._read_json(name, manifest=manifest)
            for name in names
            if name.endswith((".json", ".geojson"))
        }
        csv_data = {name: self._read_csv(name, manifest) for name in names if name.endswith(".csv")}
        scenario = json_data["scenario_config.json"]
        package = json_data["technical_constraints_package.json"]
        access_model = json_data["access_model.json"]
        boundary_metadata = json_data["boundary_metadata.json"]
        boundary_feature = self._first_feature(json_data["pilot_extent.geojson"], "pilot extent")
        boundary_properties = boundary_feature.get("properties", {})
        self._require(
            isinstance(boundary_properties, Mapping),
            "The M1 pilot boundary feature has invalid properties.",
        )

        self._require(
            scenario.get("data_snapshot_id") == SNAPSHOT_ID
            and scenario.get("boundary_version") == BOUNDARY_VERSION
            and boundary_metadata.get("boundary_version") == BOUNDARY_VERSION
            and boundary_properties.get("pilot_extent_id") == PILOT_EXTENT_ID
            and access_model.get("baseline_profile") == ACCESS_PROFILE,
            "M1 scenario, boundary, or access profile does not match the pinned planning contract.",
        )
        self._require(
            boundary_feature["geometry"].get("type") in {"Polygon", "MultiPolygon"},
            "The M1 pilot boundary is not a polygon.",
        )

        candidates = self._index_rows(
            csv_data["candidate_sites.csv"], "candidate_id", "candidate_sites.csv"
        )
        existing = self._index_rows(csv_data["existing_sites.csv"], "site_id", "existing_sites.csv")
        demand_nodes = self._index_rows(csv_data["demand_nodes.csv"], "cell_id", "demand_nodes.csv")
        eligibility = self._index_rows(
            csv_data["candidate_eligibility.csv"], "candidate_id", "candidate_eligibility.csv"
        )
        costs = {
            row["candidate_id"]: row
            for row in csv_data["candidate_cost_assumptions.csv"]
            if row.get("cost_profile") == "base_cost"
        }
        constraints: dict[str, dict[str, dict[str, str]]] = {}
        for row in csv_data["candidate_constraints.csv"]:
            constraints.setdefault(row["candidate_id"], {})[row["constraint_id"]] = row

        self._require(
            len(candidates) == 18 and len(existing) == 37 and len(demand_nodes) == 27,
            "The pinned M1 snapshot does not contain the expected demo feature counts.",
        )
        self._require(
            set(candidates) == set(eligibility) == set(costs) == set(constraints),
            "Candidate, eligibility, cost, and constraint IDs do not align in M1.",
        )
        required_constraint_ids = {
            "valid_geometry",
            "inside_pilot",
            "new_site_fixture_spacing",
            "technical_option",
            "land_site_control",
            "grid_capacity",
            "permit_safety",
            "physical_road_access",
            "connector_compatibility",
            "individual_budget",
        }
        self._require(
            all(set(facts) == required_constraint_ids for facts in constraints.values()),
            "M1 candidate constraint sets do not match the technical package.",
        )
        self._require(
            all(row.get("boundary_version") == BOUNDARY_VERSION for row in candidates.values())
            and all(row.get("boundary_version") == BOUNDARY_VERSION for row in existing.values()),
            "A site record does not match the pinned boundary version.",
        )

        access_rows = [
            row
            for row in csv_data["access_matrix.csv"]
            if row.get("access_profile") == ACCESS_PROFILE
        ]
        expected_access_pairs = len(demand_nodes) * (len(candidates) + len(existing))
        self._require(
            len(access_rows) == expected_access_pairs,
            "The M1 normal-profile access matrix is incomplete or contains duplicate pairs.",
        )
        access_by_target: dict[str, dict[str, float]] = {}
        nearest_existing: dict[str, float] = {}
        for row in access_rows:
            node_id = row["cell_id"]
            target_id = row["target_id"]
            target_type = row.get("target_type")
            valid_target = (target_type == "candidate_site" and target_id in candidates) or (
                target_type == "existing_site" and target_id in existing
            )
            minutes = self._optional_float(row.get("travel_minutes_proxy"))
            self._require(
                valid_target and node_id in demand_nodes and minutes is not None and minutes >= 0,
                "The M1 access matrix contains an invalid demand node or travel-time proxy.",
            )
            access_by_target.setdefault(target_id, {})[node_id] = minutes
            if row.get("target_type") == "existing_site":
                nearest_existing[node_id] = min(
                    nearest_existing.get(node_id, float("inf")), minutes
                )
        self._require(
            set(nearest_existing) == set(demand_nodes),
            "Existing-site access does not cover every M1 demand node.",
        )
        self._require(
            set(access_by_target) == set(candidates) | set(existing)
            and all(set(values) == set(demand_nodes) for values in access_by_target.values()),
            "The M1 access matrix has missing or duplicate site-to-demand pairs.",
        )

        intervals_by_profile: dict[str, list[dict[str, str]]] = {
            name: [] for name in DEMAND_SOURCE_PROFILES
        }
        for row in csv_data["demand_intervals.csv"]:
            profile = row.get("scenario_profile")
            if profile in intervals_by_profile:
                intervals_by_profile[profile].append(row)
        expected_interval_count = len(demand_nodes) * 7 * 48
        self._require(
            all(len(rows) == expected_interval_count for rows in intervals_by_profile.values()),
            "The M1 low/base/high demand interval series is incomplete.",
        )
        self._require(
            all(
                all(
                    sum(
                        (row.get("demand_node_id") or row.get("cell_id")) == node_id for row in rows
                    )
                    == 7 * 48
                    for node_id in demand_nodes
                )
                for rows in intervals_by_profile.values()
            ),
            "M1 demand intervals do not contain one complete week for every demand node.",
        )

        candidates_for_catalog = []
        for candidate_id, row in candidates.items():
            self._valid_point(row, f"candidate {candidate_id}")
            candidates_for_catalog.append(
                {
                    "candidate_id": candidate_id,
                    "label": row.get("context_name") or candidate_id,
                    "candidate_type": row.get("candidate_type") or "unknown",
                    "eligibility": eligibility[candidate_id].get("eligibility", "conditional"),
                    "is_synthetic": self._as_bool(row.get("is_synthetic")),
                    "location": {"lat": float(row["lat"]), "lon": float(row["lon"])},
                    "source_ref": row.get("source_ref"),
                }
            )
        existing_for_catalog = []
        for site_id, row in existing.items():
            self._valid_point(row, f"existing site {site_id}")
            existing_for_catalog.append(
                {
                    "site_id": site_id,
                    "label": site_id,
                    "site_type": row.get("site_type") or "unknown",
                    "charger_type": row.get("charger_type") or "unknown",
                    "port_count": self._optional_int(row.get("port_count")),
                    "power_kw": self._optional_float(row.get("power_kw")),
                    "is_synthetic": self._as_bool(row.get("is_synthetic")),
                    "location": {"lat": float(row["lat"]), "lon": float(row["lon"])},
                    "source_ref": row.get("source_ref"),
                }
            )
        weekly_demand = {
            profile: {node_id: 0.0 for node_id in demand_nodes}
            for profile in DEMAND_SOURCE_PROFILES
        }
        for profile, rows in intervals_by_profile.items():
            for interval in rows:
                node_id = interval.get("demand_node_id") or interval.get("cell_id")
                value = self._optional_float(interval.get("expected_sessions"))
                self._require(
                    node_id in demand_nodes and value is not None and value >= 0,
                    "M1 demand intervals contain an invalid node or expected session value.",
                )
                weekly_demand[profile][node_id] += value
        nodes_for_catalog = []
        for node_id, row in demand_nodes.items():
            self._valid_point(row, f"demand node {node_id}")
            nodes_for_catalog.append(
                {
                    "demand_node_id": node_id,
                    "unit_id": row.get("unit_id") or "unknown",
                    "location": {"lat": float(row["lat"]), "lon": float(row["lon"])},
                    "nearest_existing_access_minutes_proxy": round(nearest_existing[node_id], 4),
                    "is_synthetic": self._as_bool(row.get("is_synthetic")),
                    "weekly_expected_sessions": {
                        profile: round(totals[node_id], 6)
                        for profile, totals in weekly_demand.items()
                    },
                }
            )

        charger = package.get("charger_option", {})
        portfolio_budget = package.get("portfolio_budget_vnd")
        demo_catalog = {
            "contract_version": "0.1",
            "study_area": {
                "city_id": CITY_ID,
                "boundary_version": BOUNDARY_VERSION,
                "pilot_extent_id": PILOT_EXTENT_ID,
            },
            "snapshot": {
                "data_snapshot_id": SNAPSHOT_ID,
                "prepared_on": manifest.get("prepared_on"),
                "dataset_contract_version": manifest.get("dataset_contract_version"),
                "boundary_id": boundary_metadata.get("boundary_id"),
                "geometry": boundary_feature["geometry"],
                "properties": boundary_feature.get("properties", {}),
            },
            "defaults": {
                "horizon_years": scenario.get("horizon_years", 3),
                "seed": manifest.get("seed", 0),
                "config_version": "technical-demo-v1",
                "demand_scenario": "base",
                "coverage_minutes": access_model.get("target_access_minutes", 15),
                "charger_option": {
                    "charger_type": charger.get("charger_type", "DC"),
                    "port_count": charger.get("port_count", 4),
                    "power_kw_per_port": charger.get("power_kw_per_port", 80),
                },
                "budget_vnd": None,
                "portfolio_budget_vnd": portfolio_budget,
            },
            "candidates": candidates_for_catalog,
            "existing_sites": existing_for_catalog,
            "demand_nodes": nodes_for_catalog,
            "warnings": [
                "Đây là pilot 9 phường, không đại diện toàn TP.HCM.",
                (
                    "Candidate và demand là dữ liệu tổng hợp; demand là tổng phiên kỳ vọng "
                    "trong một tuần mẫu."
                ),
                (
                    "Độ phủ dùng access-time proxy profile normal, không phải thời gian đi "
                    "đường thực tế."
                ),
                "Ngày hiệu lực boundary và crosswalk lịch sử chưa được xác minh trong nguồn M1.",
                "Điều kiện đất, lưới, cấp phép, đường vào và tương thích đầu nối còn cần xác minh.",
            ],
        }
        return {
            "manifest": manifest,
            "scenario": scenario,
            "package": package,
            "access_model": access_model,
            "boundary_metadata": boundary_metadata,
            "boundary_geometry": boundary_feature["geometry"],
            "candidates": candidates,
            "existing_sites": existing,
            "demand_nodes": demand_nodes,
            "eligibility": eligibility,
            "costs": costs,
            "constraints": constraints,
            "access_by_target": access_by_target,
            "nearest_existing": nearest_existing,
            "demand_intervals": intervals_by_profile,
            "demo_catalog": demo_catalog,
        }

    def _build_dataset(
        self, bundle: Mapping[str, Any], config: PlanningRunConfig
    ) -> Mapping[str, Any]:
        scenario_key = config.demand_scenario
        if scenario_key not in DEMAND_SOURCE_PROFILES:
            raise PlanningDataError(f"Unsupported M1 demand scenario '{scenario_key}'.")
        node_ids = set(bundle["demand_nodes"])
        source_id = f"{SNAPSHOT_ID}:access_matrix.csv:{ACCESS_PROFILE}:{config.coverage_minutes}min"
        candidates = []
        for candidate_id, row in bundle["candidates"].items():
            access = bundle["access_by_target"].get(candidate_id, {})
            self._require(
                set(access) == node_ids,
                f"The M1 access matrix is incomplete for candidate '{candidate_id}'.",
            )
            point = {"lat": float(row["lat"]), "lon": float(row["lon"])}
            facts = self._candidate_constraints(bundle, config, candidate_id, row)
            candidate_cost = self._candidate_cost(bundle, config, candidate_id)
            grid_row = bundle["constraints"][candidate_id].get("grid_capacity", {})
            grid_capacity = self._optional_float(grid_row.get("value"))
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    **point,
                    "covered_demand_cell_ids": sorted(
                        node_id
                        for node_id, minutes in access.items()
                        if minutes <= config.coverage_minutes
                    ),
                    "coverage_source_ids": [source_id],
                    "coverage_status": "proxy",
                    "coverage_is_synthetic": True,
                    "coverage_source_ref": "access_matrix.csv#access_profile=normal",
                    "constraints": facts,
                    "grid_capacity_kw": {
                        "value": grid_capacity,
                        "unit": "kW",
                        "status": "unknown"
                        if grid_capacity is None
                        else self._status_from_source(grid_row.get("source_type")),
                        "source_id": self._constraint_source(candidate_id, "grid_capacity"),
                    },
                    "estimated_cost": candidate_cost,
                    "network_features": {},
                    "provenance": [
                        {
                            "field": "candidate.location",
                            "source_id": f"{SNAPSHOT_ID}:candidate_sites.csv:{candidate_id}",
                            "source_ref": row.get("source_ref"),
                            "status": "synthetic",
                            "is_synthetic": True,
                            "observed_at": None,
                            "note": (
                                "Vị trí candidate tổng hợp từ ngữ cảnh POI/giao thông; "
                                "chưa phải parcel đã xác nhận."
                            ),
                        },
                        {
                            "field": "candidate.type",
                            "source_id": f"{SNAPSHOT_ID}:candidate_sites.csv:{candidate_id}",
                            "source_ref": row.get("source_ref"),
                            "status": "synthetic",
                            "is_synthetic": True,
                            "observed_at": None,
                            "note": (
                                "Parcel hypothesis; cần khảo sát và xác nhận "
                                "ranh giới/quyền sử dụng."
                            ),
                        },
                    ],
                }
            )

        access_minutes_by_node = bundle["nearest_existing"]
        existing_covered = sorted(
            node_id
            for node_id, minutes in access_minutes_by_node.items()
            if minutes <= config.coverage_minutes
        )
        demand_estimates = self._demand_estimates(bundle, scenario_key)
        return {
            "snapshot": {
                "city_id": CITY_ID,
                "boundary_version": BOUNDARY_VERSION,
                "pilot_extent_id": PILOT_EXTENT_ID,
                "data_snapshot_id": config.data_snapshot_id,
                "boundary_crs": "EPSG:4326",
                "boundary_geometry": bundle["boundary_geometry"],
                "boundary_source_id": bundle["boundary_metadata"].get("boundary_id"),
            },
            "candidates": candidates,
            "demand_estimates": demand_estimates,
            "existing_covered_demand_cell_ids": existing_covered,
            "existing_coverage_source_ids": [source_id],
            "existing_coverage_status": "proxy",
            "existing_coverage_is_synthetic": True,
            "existing_coverage_source_ref": "access_matrix.csv#access_profile=normal",
            "warnings": list(bundle["demo_catalog"]["warnings"]),
        }

    def _candidate_constraints(
        self,
        bundle: Mapping[str, Any],
        config: PlanningRunConfig,
        candidate_id: str,
        candidate: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        raw = bundle["constraints"][candidate_id]
        translations = {
            "new_site_fixture_spacing": "candidate_spacing",
            "land_site_control": "site_rights",
            "grid_capacity": "grid_capacity",
            "permit_safety": "safety_permit",
            "physical_road_access": "road_access",
        }
        result = [
            self._constraint_fact(candidate_id, raw[source], target)
            for source, target in translations.items()
        ]
        result.extend(
            [
                {
                    "id": "candidate_type",
                    "status": "conditional",
                    "reason": (
                        "Ứng viên là giả thuyết vị trí; chưa xác nhận parcel hoặc quyền triển khai."
                    ),
                    "source_ids": [f"{SNAPSHOT_ID}:candidate_sites.csv:{candidate_id}"],
                    "source_ref": candidate.get("source_ref"),
                    "evidence_status": "synthetic",
                    "confirmed_infeasible": False,
                },
                {
                    "id": "site_access",
                    "status": "unknown",
                    "reason": "M1 chưa có bằng chứng xác minh lối ra vào thực tế của site.",
                    "source_ids": [],
                    "source_ref": "candidate_sites.csv#access_feasible",
                    "evidence_status": "unknown",
                    "confirmed_infeasible": False,
                },
            ]
        )
        expected = bundle["package"].get("charger_option", {})
        requested = [dict(option) for option in config.charger_options]
        supported = len(requested) == 1 and all(
            requested[0].get(key) == expected.get(key)
            for key in ("charger_type", "port_count", "power_kw_per_port")
        )
        option_source = f"{SNAPSHOT_ID}:technical_constraints_package.json:charger_option"
        connector_fact = self._constraint_fact(
            candidate_id, raw["connector_compatibility"], "charger_configuration"
        )
        if not supported:
            connector_fact.update(
                status="conditional",
                reason=(
                    "Cấu hình chưa có trong package M1; cần đánh giá lại cost và "
                    "tương thích kỹ thuật."
                ),
                source_ids=[option_source, *connector_fact["source_ids"]],
                source_ref="technical_constraints_package.json#/charger_option;candidate_constraints.csv#connector_compatibility",
                evidence_status="unknown",
            )
        else:
            connector_fact["source_ids"] = [option_source, *connector_fact["source_ids"]]
            connector_fact["source_ref"] = (
                "technical_constraints_package.json#/charger_option;"
                "candidate_constraints.csv#connector_compatibility"
            )
            connector_fact["reason"] = (
                "Cấu hình khớp kịch bản M1; tương thích đầu nối thực tế vẫn chưa xác minh."
            )
        result.append(connector_fact)
        return result

    def _candidate_cost(
        self, bundle: Mapping[str, Any], config: PlanningRunConfig, candidate_id: str
    ) -> dict[str, Any]:
        row = bundle["costs"][candidate_id]
        expected = bundle["package"].get("charger_option", {})
        requested = [dict(option) for option in config.charger_options]
        matches = len(requested) == 1 and all(
            requested[0].get(key) == expected.get(key)
            for key in ("charger_type", "port_count", "power_kw_per_port")
        )
        source_id = f"{SNAPSHOT_ID}:candidate_cost_assumptions.csv:{candidate_id}:base_cost"
        value = self._optional_float(row.get("total_capex_vnd")) if matches else None
        return {
            "value": value,
            "unit": "VND",
            "status": "synthetic" if value is not None else "unknown",
            "source_id": source_id if value is not None else None,
            "source_ref": "candidate_cost_assumptions.csv#cost_profile=base_cost"
            if value is not None
            else None,
            "note": (
                "CAPEX minh họa theo base_cost cho DC 4 x 80 kW; không phải báo giá thị trường."
                if value is not None
                else "Không có ước tính CAPEX phù hợp với cấu hình bộ sạc đã chọn."
            ),
        }

    def _demand_estimates(self, bundle: Mapping[str, Any], profile: str) -> list[dict[str, Any]]:
        rows = bundle["demand_intervals"][profile]
        totals = {node_id: 0.0 for node_id in bundle["demand_nodes"]}
        starts: list[datetime] = []
        interval_minutes: int | None = None
        for row in rows:
            node_id = row.get("demand_node_id") or row.get("cell_id")
            value = self._optional_float(row.get("expected_sessions"))
            start_text = row.get("interval_start", "")
            try:
                start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise PlanningDataError(
                    "M1 demand intervals contain an invalid timestamp."
                ) from exc
            self._require(
                node_id in totals and value is not None and value >= 0,
                "M1 demand intervals contain an invalid node ID or expected session value.",
            )
            interval = self._optional_int(row.get("interval_minutes"))
            self._require(
                interval is not None and interval > 0,
                "M1 demand intervals contain an invalid duration.",
            )
            if interval_minutes is None:
                interval_minutes = interval
            self._require(
                interval == interval_minutes, "M1 demand interval durations are inconsistent."
            )
            starts.append(start)
            totals[node_id] += value
        self._require(
            len(starts) > 0 and interval_minutes is not None, "M1 demand series is empty."
        )
        start = min(starts)
        end = max(starts) + timedelta(minutes=interval_minutes)
        scenario_id = f"hcmc-technical-opportunity-demo-{profile}"
        source_id = f"{SNAPSHOT_ID}:demand_intervals.csv:{scenario_id}"
        return [
            {
                "demand_cell_id": node_id,
                "target": "expected_sessions",
                "value": round(value, 6),
                "unit": "sessions_per_week",
                "status": "synthetic",
                "source_id": source_id,
                "source_ref": "demand_intervals.csv#expected_sessions",
                "model_version": "hcmc-demo-synthetic-demand-v3",
                "data_snapshot_id": SNAPSHOT_ID,
                "scenario": scenario_id,
                "time_window": {"start": start.isoformat(), "end": end.isoformat()},
            }
            for node_id, value in sorted(totals.items())
        ]

    @staticmethod
    def _constraint_source(candidate_id: str, constraint_id: str) -> str:
        return f"{SNAPSHOT_ID}:candidate_constraints.csv:{candidate_id}:{constraint_id}"

    @staticmethod
    def _constraint_fact(
        candidate_id: str, row: Mapping[str, str], target_id: str
    ) -> dict[str, Any]:
        status = row.get("status", "unknown")
        if status not in {"pass", "fail", "conditional", "unknown", "not_applicable"}:
            status = "unknown"
        evidence_status = FilePlanningDataRepository._status_from_source(row.get("source_type"))
        source_id = FilePlanningDataRepository._constraint_source(
            candidate_id, row.get("constraint_id", target_id)
        )
        source_ids = [source_id]
        confirmed = status == "fail" and row.get("source_type") in {"observed", "scenario"}
        reason_codes = {
            "meets_demo_spacing": (
                "Đáp ứng ngưỡng giãn cách fixture trong quy tắc M1; đây là kiểm tra demo."
            ),
            "site_control_unverified": "Quyền kiểm soát đất/site chưa được xác minh.",
            "grid_capacity_unverified": "Chưa có xác nhận công suất khả dụng từ đơn vị điện lực.",
            "permit_safety_unverified": "Chưa có hồ sơ cấp phép và an toàn được xác minh.",
            "road_access_unverified": "Chưa xác minh khả năng tiếp cận vật lý từ đường.",
            "connector_unverified": "Chưa xác minh tương thích đầu nối tại site.",
            "fits_demo_budget_individually": (
                "CAPEX base_cost minh họa nằm trong budget demo cho một candidate."
            ),
        }
        return {
            "id": target_id,
            "status": status,
            "reason": reason_codes.get(
                row.get("reason_code", ""), row.get("reason_code", "M1 constraint evidence.")
            ),
            "source_ids": source_ids,
            "source_ref": row.get("source_ref"),
            "evidence_status": evidence_status,
            "confirmed_infeasible": confirmed,
        }

    @staticmethod
    def _status_from_source(source_type: str | None) -> str:
        return {
            "observed": "observed",
            "proxy": "proxy",
            "scenario": "scenario",
            "synthetic": "synthetic",
            "unknown": "unknown",
            "not_applicable": "not_applicable",
        }.get((source_type or "").lower(), "unknown")

    def _read_json(
        self, name: str, *, manifest: Mapping[str, Any] | None = None, verify: bool = True
    ) -> dict[str, Any]:
        path = self._verified_path(name, manifest, verify=verify)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PlanningDataError(f"M1 snapshot file '{name}' is missing or invalid.") from exc
        except UnicodeError as exc:
            raise PlanningDataError(f"M1 snapshot file '{name}' is not valid UTF-8.") from exc
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                raise PlanningDataError(
                    f"M1 snapshot file '{name}' is missing or invalid."
                ) from exc
            raise PlanningInfrastructureError(
                f"M1 snapshot file '{name}' could not be read."
            ) from exc
        if not isinstance(payload, dict):
            raise PlanningDataError(f"M1 snapshot file '{name}' must contain a JSON object.")
        return payload

    def _read_csv(self, name: str, manifest: Mapping[str, Any]) -> list[dict[str, str]]:
        path = self._verified_path(name, manifest, verify=True)
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except UnicodeError as exc:
            raise PlanningDataError(f"M1 snapshot file '{name}' is not valid UTF-8.") from exc
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                raise PlanningDataError(f"M1 snapshot file '{name}' is missing.") from exc
            raise PlanningInfrastructureError(
                f"M1 snapshot file '{name}' could not be read."
            ) from exc
        if not rows:
            raise PlanningDataError(f"M1 snapshot file '{name}' is empty.")
        return rows

    def _verified_path(
        self, name: str, manifest: Mapping[str, Any] | None, *, verify: bool
    ) -> Path:
        path = self._directory / name
        if not path.is_file():
            raise PlanningDataError(f"Required M1 snapshot file '{name}' is missing.")
        if verify and manifest is not None:
            file_entry = manifest.get("files", {}).get(name)
            if not isinstance(file_entry, Mapping) or not isinstance(file_entry.get("sha256"), str):
                raise PlanningDataError(f"M1 manifest does not declare a hash for '{name}'.")
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                if isinstance(exc, FileNotFoundError):
                    raise PlanningDataError(f"M1 snapshot file '{name}' is missing.") from exc
                raise PlanningInfrastructureError(
                    f"M1 snapshot file '{name}' could not be hashed."
                ) from exc
            if actual != file_entry["sha256"]:
                raise PlanningDataError(
                    f"M1 snapshot file '{name}' does not match its manifest hash."
                )
        return path

    @staticmethod
    def _first_feature(collection: Mapping[str, Any], label: str) -> Mapping[str, Any]:
        features = collection.get("features")
        if not isinstance(features, list) or not features or not isinstance(features[0], Mapping):
            raise PlanningDataError(f"M1 {label} GeoJSON has no feature.")
        feature = features[0]
        if not isinstance(feature.get("geometry"), Mapping):
            raise PlanningDataError(f"M1 {label} GeoJSON has no geometry.")
        return feature

    @staticmethod
    def _index_rows(rows: list[dict[str, str]], key: str, name: str) -> dict[str, dict[str, str]]:
        result = {row.get(key, ""): row for row in rows}
        if "" in result or len(result) != len(rows):
            raise PlanningDataError(f"M1 file '{name}' has blank or duplicate IDs.")
        return result

    @staticmethod
    def _valid_point(row: Mapping[str, str], label: str) -> None:
        try:
            lat, lon = float(row["lat"]), float(row["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanningDataError(f"M1 {label} does not have valid WGS84 coordinates.") from exc
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise PlanningDataError(f"M1 {label} has coordinates outside WGS84 bounds.")

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if result == result and abs(result) != float("inf") else None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        number = FilePlanningDataRepository._optional_float(value)
        return int(number) if number is not None and number.is_integer() else None

    @staticmethod
    def _as_bool(value: Any) -> bool:
        return str(value).strip().lower() == "true"

    @staticmethod
    def _require(condition: bool, message: str) -> None:
        if not condition:
            raise PlanningDataError(message)
