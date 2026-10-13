"""Pure, deterministic M2B technical site screening engine.

The engine consumes a versioned M1 snapshot and the internal M2A demand payload. It has no
FastAPI, Pydantic, database, or network dependencies; the application service adapts its mapping
output to the HTTP contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from backend.app.planning.domain import PlanningRunConfig

COMPONENTS = (
    "demand_potential",
    "marginal_coverage",
    "grid_site_readiness",
    "network_segment_fit",
    "network_gap_fit",
)
HARD_CONSTRAINTS = (
    "inside_boundary",
    "site_access",
    "safety_permit",
    "grid_capacity",
    "road_access",
    "charger_configuration",
    "candidate_type",
    "site_rights",
)
DATA_STATUSES = {"observed", "proxy", "synthetic", "scenario", "unknown", "not_applicable"}
CONSTRAINT_STATUSES = {"pass", "fail", "conditional", "unknown", "not_applicable"}
NETWORK_FEATURE_WEIGHTS = (
    ("road_accessibility", 0.30),
    ("poi_dwell", 0.25),
    ("fleet_activity", 0.25),
    ("charger_mix_fit", 0.20),
)


@dataclass(frozen=True, slots=True)
class TechnicalScoringConfig:
    """Versioned technical profile. Weights are demo defaults, not investor or policy rules."""

    version: str = "technical-demo-v1"
    weights: tuple[tuple[str, float], ...] = (
        ("demand_potential", 30.0),
        ("marginal_coverage", 25.0),
        ("grid_site_readiness", 20.0),
        ("network_segment_fit", 15.0),
        ("network_gap_fit", 10.0),
    )
    minimum_evidence_coverage: float = 0.60
    network_feature_weights: tuple[tuple[str, float], ...] = NETWORK_FEATURE_WEIGHTS

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("scoring config version is required")
        weights = dict(self.weights)
        if set(weights) != set(COMPONENTS) or len(weights) != len(self.weights):
            raise ValueError("scoring config must define each component exactly once")
        if any(not isfinite(value) or value < 0 for value in weights.values()):
            raise ValueError("component weights must be finite and non-negative")
        if abs(sum(weights.values()) - 100.0) > 1e-6:
            raise ValueError("component weights must total 100")
        if not 0 <= self.minimum_evidence_coverage <= 1:
            raise ValueError("minimum_evidence_coverage must be between 0 and 1")
        network_weights = dict(self.network_feature_weights)
        if len(network_weights) != len(self.network_feature_weights) or any(
            not isfinite(value) or value < 0 for value in network_weights.values()
        ):
            raise ValueError("network feature weights must be unique, finite, and non-negative")
        if network_weights and abs(sum(network_weights.values()) - 1.0) > 1e-6:
            raise ValueError("network feature weights must total 1")


@dataclass(frozen=True, slots=True)
class SensitivityCase:
    """One deterministic rerun with alternative inputs or technical scoring weights."""

    case_id: str
    config: PlanningRunConfig | None = None
    dataset: Mapping[str, Any] | None = None
    scoring: TechnicalScoringConfig | None = None


@dataclass(frozen=True, slots=True)
class _DemandRecord:
    subject_type: str
    subject_id: str
    target: str
    value: float | None
    unit: str
    status: str
    source_id: str | None
    model_version: str | None
    data_snapshot_id: str | None
    scenario: str
    time_window: Mapping[str, Any]
    uncertainty: Mapping[str, Any] | None


class TechnicalOpportunityEngine:
    """Rank candidates for one-site comparison using a versioned technical profile."""

    algorithm_version = "m2b-technical-screen-0.1.0"

    def __init__(self, scoring: TechnicalScoringConfig | None = None) -> None:
        self.scoring = scoring or TechnicalScoringConfig()
        self.config_version = self.scoring.version

    def recommend(self, config: PlanningRunConfig, dataset: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return the M2 output mapping expected by ``PlanningApplicationService``."""
        if config.profile != "technical_opportunity":
            return _empty_result(
                "invalid_input", f"Unsupported M2 scoring profile: {config.profile}."
            )
        if not config.candidate_ids:
            return _empty_result("invalid_input", "At least one candidate ID is required.")

        _snapshot, boundary, boundary_source, warning = _resolve_snapshot(config, dataset)
        if warning:
            return _empty_result("invalid_input", warning)

        candidates, warning = _resolve_candidates(config, dataset)
        if warning:
            return _empty_result("invalid_input", warning)

        demand_records, warning = _resolve_demand_records(config, dataset)
        if warning:
            return _empty_result("invalid_input", warning)

        existing_cells, existing_sources, existing_is_known, existing_status = _existing_coverage(
            dataset
        )
        cell_records = {
            item.subject_id: item for item in demand_records if item.subject_type == "demand_cell"
        }
        candidate_records = {
            item.subject_id: item for item in demand_records if item.subject_type == "candidate"
        }
        cell_context = bool(cell_records)
        all_cell_values_known = bool(cell_records) and all(
            item.value is not None for item in cell_records.values()
        )
        total_cell_demand = (
            sum(item.value or 0.0 for item in cell_records.values())
            if all_cell_values_known
            else None
        )

        evaluations: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for candidate in candidates:
            point = _candidate_point(candidate)
            candidate_id = str(candidate["candidate_id"])
            constraint_items = _constraints_for_candidate(
                candidate,
                point,
                boundary,
                boundary_source,
            )
            failing = [item for item in constraint_items if item["status"] == "fail"]
            if failing:
                excluded.append(
                    {
                        "candidate_id": candidate_id,
                        "constraints": [
                            {"id": item["id"], "status": "fail", "reason": item["reason"]}
                            for item in failing
                        ],
                    }
                )
                continue

            covered_ids = _string_ids(candidate.get("covered_demand_cell_ids"))
            demand, demand_sources, demand_status, demand_coverage, demand_note = _candidate_demand(
                candidate,
                candidate_records,
                cell_records,
                cell_context,
                covered_ids,
            )
            demand_unit = next((record.unit for record in demand_records), "demand_unit")
            coverage = _coverage_metrics(
                candidate,
                covered_ids,
                cell_records,
                cell_context,
                existing_cells,
                existing_sources,
                existing_is_known,
                existing_status,
                total_cell_demand,
                all_cell_values_known,
            )
            capacity = _capacity_metrics(config, candidate)
            readiness = _readiness_component(constraint_items, capacity)
            segment_fit = _network_fit_component(candidate, self.scoring.network_feature_weights)
            evaluations.append(
                {
                    "candidate": candidate,
                    "candidate_id": candidate_id,
                    "point": point,
                    "constraints": constraint_items,
                    "demand_value": demand,
                    "demand_status": demand_status,
                    "demand_sources": demand_sources,
                    "demand_coverage": demand_coverage,
                    "demand_note": demand_note,
                    "demand_unit": demand_unit,
                    "coverage": coverage,
                    "capacity": capacity,
                    "readiness": readiness,
                    "segment_fit": segment_fit,
                }
            )

        _add_demand_scores(evaluations)
        weights = dict(self.scoring.weights)
        for item in evaluations:
            item["components"] = {
                "demand_potential": item["demand_component"],
                "marginal_coverage": item["coverage"]["marginal_component"],
                "grid_site_readiness": item["readiness"],
                "network_segment_fit": item["segment_fit"],
                "network_gap_fit": item["coverage"]["network_gap_component"],
            }
            item["evidence_coverage"] = (
                sum(
                    weights[name] * component["evidence_fraction"]
                    for name, component in item["components"].items()
                    if component["score"] is not None
                )
                / 100.0
            )
            item["known_components"] = tuple(
                name for name in COMPONENTS if item["components"][name]["score"] is not None
            )

        recommendations, unranked = self._rank(evaluations, weights)
        warnings = _run_warnings(evaluations)
        all_requested_excluded = bool(config.candidate_ids) and len(excluded) == len(
            config.candidate_ids
        )
        if all_requested_excluded:
            status = "no_feasible_candidates"
        elif (
            unranked
            or warnings
            or any(
                any(
                    fact["status"] in {"unknown", "conditional", "not_applicable"}
                    for fact in item["constraints"]
                )
                for item in evaluations
            )
        ):
            status = "completed_with_unknowns"
        else:
            status = "completed"
        return {
            "status": status,
            "recommendations": recommendations,
            "unranked_candidates": unranked,
            "excluded_candidates": excluded,
            "warnings": warnings,
        }

    def compare_sensitivity(
        self,
        config: PlanningRunConfig,
        dataset: Mapping[str, Any],
        cases: Sequence[SensitivityCase],
    ) -> Mapping[str, Any]:
        """Rerun the pure engine and report score/rank movement for named alternatives.

        Cases may change the demand/candidate snapshot, run configuration, or versioned technical
        weights, but must retain the same candidate set so rank movement remains interpretable.
        Returned deltas are scenario comparisons, not probabilities or confidence intervals.
        """
        if not cases:
            raise ValueError("at least one sensitivity case is required")
        case_ids = [case.case_id.strip() for case in cases]
        if any(not case_id for case_id in case_ids) or len(set(case_ids)) != len(case_ids):
            raise ValueError("sensitivity case IDs must be non-empty and unique")

        baseline = self.recommend(config, dataset)
        baseline_states = _sensitivity_states(baseline)
        comparisons = []
        requested_ids = set(config.candidate_ids)
        for case, case_id in zip(cases, case_ids, strict=True):
            case_config = case.config or config
            if set(case_config.candidate_ids) != requested_ids:
                raise ValueError("sensitivity cases must use the same candidate set as baseline")
            case_engine = TechnicalOpportunityEngine(case.scoring or self.scoring)
            result = case_engine.recommend(
                case_config,
                case.dataset if case.dataset is not None else dataset,
            )
            case_states = _sensitivity_states(result)
            movements = []
            for candidate_id in config.candidate_ids:
                before = baseline_states.get(candidate_id, {"state": "not_returned"})
                after = case_states.get(candidate_id, {"state": "not_returned"})
                before_rank = before.get("rank")
                after_rank = after.get("rank")
                before_score = before.get("score")
                after_score = after.get("score")
                movements.append(
                    {
                        "candidate_id": candidate_id,
                        "baseline_state": before["state"],
                        "case_state": after["state"],
                        "baseline_rank": before_rank,
                        "case_rank": after_rank,
                        "rank_movement": (
                            before_rank - after_rank
                            if before_rank is not None and after_rank is not None
                            else None
                        ),
                        "baseline_score": before_score,
                        "case_score": after_score,
                        "score_delta": (
                            round(after_score - before_score, 4)
                            if before_score is not None and after_score is not None
                            else None
                        ),
                    }
                )
            comparisons.append(
                {
                    "case_id": case_id,
                    "config_version": case_engine.config_version,
                    "status": result["status"],
                    "recommendation_order": [
                        item["candidate_id"] for item in result["recommendations"]
                    ],
                    "candidate_movements": movements,
                }
            )

        return {
            "algorithm_version": self.algorithm_version,
            "baseline": {
                "config_version": self.config_version,
                "status": baseline["status"],
                "recommendation_order": [
                    item["candidate_id"] for item in baseline["recommendations"]
                ],
            },
            "comparisons": comparisons,
            "interpretation": (
                "Rank movement is baseline rank minus case rank, so positive means improved; "
                "score deltas and scenario comparisons are not probabilities."
            ),
        }

    def _rank(
        self, evaluations: Sequence[dict[str, Any]], weights: Mapping[str, float]
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        if not evaluations:
            return [], []

        for item in evaluations:
            known_weight = sum(weights[name] for name in item["known_components"])
            item["known_weight"] = known_weight
            item["score"] = (
                sum(
                    weights[name] * item["components"][name]["score"]
                    for name in item["known_components"]
                )
                / known_weight
                if known_weight > 0
                else None
            )
            item["comparison_signature"] = (
                item["known_components"],
                tuple(
                    round(item["components"][name]["evidence_fraction"], 6)
                    for name in item["known_components"]
                ),
                round(item["evidence_coverage"], 6),
            )

        comparable = [
            item
            for item in evaluations
            if item["score"] is not None
            and item["evidence_coverage"] >= self.scoring.minimum_evidence_coverage
        ]
        selected_signature: tuple[Any, ...] | None = None
        if comparable:
            highest_coverage = max(item["evidence_coverage"] for item in comparable)
            top = [
                item
                for item in comparable
                if abs(item["evidence_coverage"] - highest_coverage) <= 1e-9
            ]
            signatures = {item["comparison_signature"] for item in top}
            if len(signatures) == 1:
                selected_signature = next(iter(signatures))

        ranked = [item for item in comparable if item["comparison_signature"] == selected_signature]
        unranked: list[dict[str, str]] = []
        for item in evaluations:
            if item not in ranked:
                if item["score"] is None:
                    reason = (
                        "Not enough supported components to calculate a comparable technical score."
                    )
                elif item["evidence_coverage"] < self.scoring.minimum_evidence_coverage:
                    reason = (
                        "Evidence coverage is below the configured minimum of "
                        f"{self.scoring.minimum_evidence_coverage:.0%}."
                    )
                else:
                    reason = (
                        "Evidence dimensions or coverage differ from the highest-coverage group; "
                        "ranking would not be comparable."
                    )
                unranked.append({"candidate_id": item["candidate_id"], "reason": reason})

        ranked.sort(key=lambda item: (-item["score"], item["candidate_id"]))
        result = [
            self._recommendation(item, rank=index, weights=weights)
            for index, item in enumerate(ranked, start=1)
        ]
        return result, unranked

    def _recommendation(
        self, item: Mapping[str, Any], *, rank: int, weights: Mapping[str, float]
    ) -> dict[str, Any]:
        components: Mapping[str, Mapping[str, Any]] = item["components"]
        known_weight = item["known_weight"]
        score_breakdown = []
        for component_id in COMPONENTS:
            evidence = components[component_id]
            score = evidence["score"]
            score_breakdown.append(
                {
                    "component_id": component_id,
                    "score": score,
                    "weight_percent": weights[component_id],
                    "contribution_points": (
                        weights[component_id] * score / known_weight if score is not None else None
                    ),
                    "status": evidence["status"],
                    "reason": evidence["reason"],
                }
            )

        candidate: Mapping[str, Any] = item["candidate"]
        constraints = item["constraints"]
        eligibility = (
            "conditional"
            if any(
                fact["status"] in {"unknown", "conditional", "not_applicable"}
                for fact in constraints
            )
            else "eligible"
        )
        metrics = {
            "demand_potential": _metric(
                item["demand_value"],
                item["demand_unit"],
                item["demand_status"],
                item["demand_coverage"],
                item["demand_sources"],
                item["demand_note"],
            ),
            "coverage_gain": item["coverage"]["coverage_gain"],
            "coverage_gap": item["coverage"]["coverage_gap"],
            "competition": item["coverage"]["competition"],
            "network_fit": item["coverage"]["network_fit"],
            "network_gap_fit": item["coverage"]["network_gap_metric"],
            "recommended_capacity": item["capacity"]["recommended_capacity"],
            "capacity_fit": item["capacity"]["capacity_fit"],
            "overload_risk": item["capacity"]["overload_risk"],
            "estimated_cost": _metric(
                None,
                "VND",
                "not_applicable",
                0.0,
                note="Finance is outside the technical opportunity profile.",
            ),
        }
        provenance = _candidate_provenance(candidate)
        provenance.extend(_constraint_provenance(constraints))
        provenance.extend(item["demand_sources"])
        provenance.extend(item["coverage"]["provenance"])
        provenance.extend(item["capacity"]["provenance"])
        provenance = _dedupe_provenance(provenance)
        return {
            "rank": rank,
            "candidate_id": item["candidate_id"],
            "location": {"lat": item["point"][0], "lon": item["point"][1]},
            "eligibility": eligibility,
            "technical_score": round(float(item["score"]), 4),
            "evidence_coverage": round(float(item["evidence_coverage"]), 6),
            "metrics": metrics,
            "constraints": [
                {"id": fact["id"], "status": fact["status"], "reason": fact["reason"]}
                for fact in constraints
            ],
            "score_breakdown": score_breakdown,
            "provenance": provenance,
        }


def _empty_result(status: str, warning: str) -> dict[str, Any]:
    return {
        "status": status,
        "recommendations": [],
        "unranked_candidates": [],
        "excluded_candidates": [],
        "warnings": [warning],
    }


def _sensitivity_states(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for item in result["recommendations"]:
        states[item["candidate_id"]] = {
            "state": "ranked",
            "rank": item["rank"],
            "score": float(item["technical_score"]),
        }
    for item in result["unranked_candidates"]:
        states[item["candidate_id"]] = {"state": "unranked", "rank": None, "score": None}
    for item in result["excluded_candidates"]:
        states[item["candidate_id"]] = {"state": "excluded", "rank": None, "score": None}
    return states


def _resolve_snapshot(
    config: PlanningRunConfig, dataset: Mapping[str, Any]
) -> tuple[Mapping[str, Any], Mapping[str, Any], str, str | None]:
    snapshot = dataset.get("snapshot")
    if not isinstance(snapshot, Mapping):
        return {}, {}, "", "The M1 dataset is missing its versioned snapshot metadata."
    required = {
        "city_id": config.city_id,
        "boundary_version": config.boundary_version,
        "pilot_extent_id": config.pilot_extent_id,
        "data_snapshot_id": config.data_snapshot_id,
        "boundary_crs": "EPSG:4326",
    }
    for key, expected in required.items():
        if snapshot.get(key) != expected:
            return snapshot, {}, "", f"Snapshot {key} does not match the requested planning run."
    boundary = snapshot.get("boundary_geometry")
    if isinstance(boundary, Mapping) and boundary.get("type") == "Feature":
        boundary = boundary.get("geometry")
    if not isinstance(boundary, Mapping) or boundary.get("type") not in {"Polygon", "MultiPolygon"}:
        return snapshot, {}, "", "The pinned boundary geometry is missing or invalid."
    source_id = snapshot.get("boundary_source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        return snapshot, {}, "", "The pinned boundary source_id is required."
    if not _valid_geojson_geometry(boundary):
        return snapshot, {}, "", "The pinned boundary geometry has invalid coordinates."
    return snapshot, boundary, source_id, None


def _valid_geojson_geometry(geometry: Mapping[str, Any]) -> bool:
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Polygon":
        polygons = [coordinates]
    else:
        polygons = coordinates
    if not isinstance(polygons, Sequence) or isinstance(polygons, (str, bytes)) or not polygons:
        return False
    for polygon in polygons:
        if not isinstance(polygon, Sequence) or not polygon:
            return False
        for ring in polygon:
            if not isinstance(ring, Sequence) or len(ring) < 4:
                return False
            points = [_geo_point(value) for value in ring]
            if any(point is None for point in points) or points[0] != points[-1]:
                return False
    return True


def _geo_point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
        return None
    lon, lat = value[0], value[1]
    if not _finite_number(lon) or not _finite_number(lat):
        return None
    if not -180 <= float(lon) <= 180 or not -90 <= float(lat) <= 90:
        return None
    return float(lon), float(lat)


def _point_in_ring(point: tuple[float, float], ring: Sequence[Any]) -> bool:
    x, y = point
    inside = False
    points = [_geo_point(value) for value in ring]
    clean = [value for value in points if value is not None]
    for start, end in zip(clean, clean[1:], strict=False):
        x1, y1 = start
        x2, y2 = end
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if (
            abs(cross) <= 1e-12
            and min(x1, x2) - 1e-12 <= x <= max(x1, x2) + 1e-12
            and min(y1, y2) - 1e-12 <= y <= max(y1, y2) + 1e-12
        ):
            return True
        crosses = (y1 > y) != (y2 > y)
        if crosses and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _inside_boundary(point: tuple[float, float], geometry: Mapping[str, Any]) -> bool:
    polygons = (
        [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    )
    for polygon in polygons:
        if not _point_in_ring(point, polygon[0]):
            continue
        if not any(_point_in_ring(point, hole) for hole in polygon[1:]):
            return True
    return False


def _resolve_candidates(
    config: PlanningRunConfig, dataset: Mapping[str, Any]
) -> tuple[list[Mapping[str, Any]], str | None]:
    raw = dataset.get("candidates")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return [], "The M1 dataset must provide a candidate list."
    if any(not isinstance(item, Mapping) for item in raw):
        return [], "The M1 candidate list contains an invalid record."
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip() or candidate_id in by_id:
            return [], "Candidate IDs must be non-empty and unique in the M1 snapshot."
        point = _candidate_point(item)
        if point is None:
            return [], f"Candidate '{candidate_id}' has invalid WGS84 coordinates."
        by_id[candidate_id] = item
    requested = set(config.candidate_ids)
    missing = requested - set(by_id)
    if missing:
        return (
            [],
            f"Candidate IDs are missing from the selected snapshot: {', '.join(sorted(missing))}.",
        )
    return [by_id[candidate_id] for candidate_id in config.candidate_ids], None


def _candidate_point(candidate: Mapping[str, Any]) -> tuple[float, float] | None:
    lat = candidate.get("lat", candidate.get("latitude"))
    lon = candidate.get("lon", candidate.get("longitude"))
    if not _finite_number(lat) or not _finite_number(lon):
        return None
    lat, lon = float(lat), float(lon)
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return lat, lon


def _constraints_for_candidate(
    candidate: Mapping[str, Any],
    point: tuple[float, float],
    boundary: Mapping[str, Any],
    boundary_source: str,
) -> list[dict[str, Any]]:
    raw = candidate.get("constraints", ())
    if isinstance(raw, Mapping):
        raw = [
            dict(value, id=key) if isinstance(value, Mapping) else {"id": key, "status": value}
            for key, value in raw.items()
        ]
    facts: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for fact in raw:
            if not isinstance(fact, Mapping):
                continue
            key = fact.get("id", fact.get("constraint_id"))
            if isinstance(key, str) and key in HARD_CONSTRAINTS:
                facts[key] = fact

    inside = _inside_boundary((point[1], point[0]), boundary)
    result: list[dict[str, Any]] = [
        {
            "id": "inside_boundary",
            "status": "pass" if inside else "fail",
            "reason": (
                "Candidate lies inside the pinned study boundary."
                if inside
                else "Candidate lies outside the pinned study boundary."
            ),
            "source_ids": (boundary_source,),
            "evidence_status": "observed",
            "confirmed_infeasible": not inside,
        }
    ]
    for constraint_id in HARD_CONSTRAINTS[1:]:
        fact = facts.get(constraint_id)
        if fact is None:
            result.append(
                {
                    "id": constraint_id,
                    "status": "unknown",
                    "reason": "No verified evidence was provided for this hard constraint.",
                    "source_ids": (),
                    "evidence_status": "unknown",
                    "confirmed_infeasible": False,
                }
            )
            continue
        status = fact.get("status", "unknown")
        if status not in CONSTRAINT_STATUSES:
            status = "unknown"
        sources = _source_ids(fact.get("source_ids", fact.get("source_id")))
        confirmed = fact.get("confirmed_infeasible") is True and bool(sources)
        if status == "fail" and not confirmed:
            status = "conditional"
        if confirmed:
            status = "fail"
        if status == "pass" and not sources:
            status = "unknown"
        evidence_status = fact.get("evidence_status", fact.get("data_status", "observed"))
        if evidence_status not in DATA_STATUSES:
            evidence_status = "unknown"
        reason = fact.get("reason")
        if fact.get("status") == "pass" and not sources:
            reason = "Pass finding has no source ID, so this constraint remains unknown."
        if not isinstance(reason, str) or not reason.strip():
            reason = {
                "pass": "Constraint has a source-backed pass finding.",
                "fail": "A source confirms this candidate is infeasible.",
                "conditional": "Constraint requires further review.",
                "not_applicable": "Constraint is not applicable according to the supplied rule.",
            }.get(status, "Constraint evidence is unknown.")
        result.append(
            {
                "id": constraint_id,
                "status": status,
                "reason": reason,
                "source_ids": sources,
                "evidence_status": evidence_status,
                "confirmed_infeasible": confirmed,
            }
        )
    return result


def _resolve_demand_records(
    config: PlanningRunConfig, dataset: Mapping[str, Any]
) -> tuple[list[_DemandRecord], str | None]:
    raw = dataset.get("demand_estimates", ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return [], "demand_estimates must be a list of M2A demand payloads."
    records: list[_DemandRecord] = []
    keys: set[tuple[str, str, str, str, str, str]] = set()
    contexts: set[tuple[str, str, str, str, str]] = set()
    granularities: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            return [], "demand_estimates contains an invalid record."
        candidate_id = item.get("candidate_id")
        cell_id = item.get("demand_cell_id")
        if bool(candidate_id) == bool(cell_id):
            return [], "Each demand estimate must identify exactly one candidate or demand cell."
        subject_type, subject_id = (
            ("candidate", candidate_id) if candidate_id else ("demand_cell", cell_id)
        )
        if not isinstance(subject_id, str) or not subject_id.strip():
            return [], "Demand estimate subject IDs must be non-empty strings."
        target, unit, scenario = item.get("target"), item.get("unit"), item.get("scenario")
        if not all(isinstance(value, str) and value.strip() for value in (target, unit, scenario)):
            return [], "Demand estimate target, unit, and scenario are required."
        status = item.get("status")
        if status not in DATA_STATUSES:
            return [], "Demand estimate has an unsupported evidence status."
        value = item.get("value")
        if value is not None and (not _finite_number(value) or float(value) < 0):
            return [], "Demand estimate values must be finite and non-negative."
        if value is None and status not in {"unknown", "not_applicable"}:
            return [], "A missing demand estimate must have unknown or not_applicable status."
        if value is not None and status in {"unknown", "not_applicable"}:
            return [], "Known demand values require an evidence status."
        source_id = item.get("source_id")
        if value is not None and (not isinstance(source_id, str) or not source_id.strip()):
            return [], "Known demand estimates require source_id."
        snapshot_id = item.get("data_snapshot_id")
        if snapshot_id not in (None, config.data_snapshot_id):
            return [], "Demand estimate data_snapshot_id does not match the planning run."
        window = item.get("time_window")
        if not isinstance(window, Mapping) or not window.get("start") or not window.get("end"):
            return [], "Demand estimate time_window.start and time_window.end are required."
        start, end = str(window["start"]), str(window["end"])
        if start >= end:
            return [], "Demand estimate time window end must be after start."
        key = (subject_type, subject_id, target, unit, start, end)
        if key in keys:
            return [], "Demand estimates must be unique per subject/target/unit/time window."
        keys.add(key)
        contexts.add((target, unit, scenario, start, end))
        granularities.add(subject_type)
        uncertainty = item.get("uncertainty")
        if uncertainty is not None:
            if not isinstance(uncertainty, Mapping):
                return [], "Demand uncertainty must be an object when provided."
            low, high = uncertainty.get("low"), uncertainty.get("high")
            method = uncertainty.get("method")
            if (
                not _finite_number(low)
                or not _finite_number(high)
                or float(low) < 0
                or float(high) < float(low)
                or not isinstance(method, str)
                or not method.strip()
            ):
                return [], "Demand uncertainty requires a valid low, high, and method."
            if value is not None and not float(low) <= float(value) <= float(high):
                return [], "Demand value must fall within its uncertainty range."
        records.append(
            _DemandRecord(
                subject_type=subject_type,
                subject_id=subject_id,
                target=target,
                value=float(value) if value is not None else None,
                unit=unit,
                status=status,
                source_id=source_id,
                model_version=item.get("model_version"),
                data_snapshot_id=snapshot_id,
                scenario=scenario,
                time_window={"start": start, "end": end},
                uncertainty=uncertainty,
            )
        )
    if len(contexts) > 1:
        return [], "Demand records use different targets, units, scenarios, or time windows."
    if len(granularities) > 1:
        return [], "Candidate-level and demand-cell estimates cannot be mixed in one run."
    if granularities == {"candidate"}:
        requested = set(config.candidate_ids)
        if any(item.subject_id not in requested for item in records):
            return [], "Candidate-level demand estimate references an unrequested candidate."
    return records, None


def _candidate_demand(
    candidate: Mapping[str, Any],
    candidate_records: Mapping[str, _DemandRecord],
    cell_records: Mapping[str, _DemandRecord],
    cell_context: bool,
    covered_ids: tuple[str, ...] | None,
) -> tuple[float | None, list[dict[str, Any]], str, float, str | None]:
    candidate_id = str(candidate["candidate_id"])
    direct = candidate_records.get(candidate_id)
    if direct is not None:
        sources = [_demand_provenance(direct, "metrics.demand_potential")]
        return direct.value, sources, direct.status, 1.0 if direct.value is not None else 0.0, None
    if not cell_context or covered_ids is None or not covered_ids:
        return (
            None,
            [],
            "unknown",
            0.0,
            "Candidate demand is unavailable for this target and time window.",
        )
    matched = [cell_records[cell_id] for cell_id in covered_ids if cell_id in cell_records]
    sources = [_demand_provenance(record, "metrics.demand_potential") for record in matched]
    complete = len(matched) == len(covered_ids) and all(item.value is not None for item in matched)
    if not complete:
        return (
            None,
            sources,
            "unknown",
            len([item for item in matched if item.value is not None]) / len(covered_ids),
            "Catchment demand has missing cells; the sum is not reported as complete.",
        )
    value = sum(item.value or 0.0 for item in matched)
    status = _combined_status(item.status for item in matched)
    return (
        value,
        sources,
        status,
        1.0,
        "Sum of compatible demand-cell estimates in the candidate catchment.",
    )


def _coverage_metrics(
    candidate: Mapping[str, Any],
    covered_ids: tuple[str, ...] | None,
    cell_records: Mapping[str, _DemandRecord],
    cell_context: bool,
    existing_cells: set[str],
    existing_sources: tuple[str, ...],
    existing_is_known: bool,
    existing_status: str,
    total_cell_demand: float | None,
    all_cell_values_known: bool,
) -> dict[str, Any]:
    candidate_coverage_status = candidate.get("coverage_status", "unknown")
    candidate_coverage_sources = _source_ids(candidate.get("coverage_source_ids"))
    if (
        not cell_context
        or covered_ids is None
        or not existing_is_known
        or candidate_coverage_status not in DATA_STATUSES - {"unknown", "not_applicable"}
        or not candidate_coverage_sources
    ):
        unknown = _metric(
            None,
            "percent",
            "unknown",
            0.0,
            note="Versioned demand-cell coverage evidence is required.",
        )
        return {
            "coverage_gain": unknown,
            "coverage_gap": _metric(None, "demand_unit", "unknown", 0.0),
            "competition": unknown,
            "network_fit": _metric(None, "score_0_100", "unknown", 0.0),
            "network_gap_metric": unknown,
            "marginal_component": _component(
                None, "unknown", 0.0, "Coverage evidence is unavailable."
            ),
            "network_gap_component": _component(
                None, "unknown", 0.0, "Network gap evidence is unavailable."
            ),
            "provenance": [],
        }

    source_ids = tuple(dict.fromkeys((*candidate_coverage_sources, *existing_sources)))
    matched = [cell_records[cell_id] for cell_id in covered_ids if cell_id in cell_records]
    complete_candidate = len(matched) == len(covered_ids) and all(
        item.value is not None for item in matched
    )
    complete_total = all_cell_values_known and total_cell_demand is not None
    if not complete_candidate or not complete_total or total_cell_demand <= 0:
        status = _combined_status(item.status for item in matched if item.value is not None)
        note = (
            "Complete demand-cell values are required to calculate marginal coverage "
            "and competition."
        )
        unknown = _metric(
            None,
            "percent",
            "unknown",
            len([x for x in matched if x.value is not None]) / max(len(covered_ids), 1),
            source_ids,
            note,
        )
        return {
            "coverage_gain": unknown,
            "coverage_gap": _metric(None, "demand_unit", "unknown", 0.0, source_ids, note),
            "competition": unknown,
            "network_fit": _metric(None, "score_0_100", "unknown", 0.0, source_ids, note),
            "network_gap_metric": unknown,
            "marginal_component": _component(None, status, 0.0, note, source_ids),
            "network_gap_component": _component(None, status, 0.0, note, source_ids),
            "provenance": [],
        }

    cell_values = {cell_id: cell_records[cell_id].value or 0.0 for cell_id in cell_records}
    all_ids = set(cell_values)
    gained_ids = set(covered_ids) - existing_cells
    gained_demand = sum(cell_values[cell_id] for cell_id in gained_ids if cell_id in cell_values)
    catchment_demand = sum(cell_values[cell_id] for cell_id in covered_ids)
    competition_demand = sum(cell_values[cell_id] for cell_id in set(covered_ids) & existing_cells)
    residual_demand = sum(cell_values[cell_id] for cell_id in all_ids - existing_cells)
    coverage_gain = 100.0 * gained_demand / total_cell_demand
    competition = 100.0 * competition_demand / catchment_demand if catchment_demand > 0 else None
    gap_fit = 100.0 - competition if competition is not None else None
    cell_status = _combined_status(
        [item.status for item in cell_records.values()]
        + [candidate_coverage_status, existing_status]
    )
    provenance = [_demand_provenance(item, "metrics.coverage_gain") for item in matched]
    provenance.extend(
        {
            "field": "metrics.coverage_gain",
            "source_id": source_id,
            "source_ref": None,
            "status": candidate_coverage_status,
            "is_synthetic": candidate_coverage_status == "synthetic",
            "observed_at": None,
            "note": "M1 candidate catchment coverage evidence.",
        }
        for source_id in candidate_coverage_sources
    )
    provenance.extend(
        {
            "field": "metrics.coverage_gain",
            "source_id": source_id,
            "source_ref": None,
            "status": existing_status,
            "is_synthetic": existing_status == "synthetic",
            "observed_at": None,
            "note": "M1 versioned existing-site coverage evidence.",
        }
        for source_id in existing_sources
    )
    coverage_metric = _metric(coverage_gain, "percent_total_demand", cell_status, 1.0, source_ids)
    competition_metric = _metric(
        competition,
        "percent_candidate_catchment_demand",
        cell_status if competition is not None else "unknown",
        1.0 if competition is not None else 0.0,
        source_ids,
        (
            "Demand already reachable from existing sites; this is a competition proxy, "
            "not revenue loss."
        ),
    )
    gap_metric = _metric(residual_demand, _cell_unit(cell_records), cell_status, 1.0, source_ids)
    network_metric = _metric(
        gap_fit,
        "score_0_100",
        cell_status if gap_fit is not None else "unknown",
        1.0 if gap_fit is not None else 0.0,
        source_ids,
    )
    return {
        "coverage_gain": coverage_metric,
        "coverage_gap": gap_metric,
        "competition": competition_metric,
        "network_fit": network_metric,
        "network_gap_metric": network_metric,
        "marginal_component": _component(
            coverage_gain,
            cell_status,
            1.0,
            "Share of all known study-area demand added after existing-site coverage.",
            source_ids,
        ),
        "network_gap_component": _component(
            gap_fit,
            cell_status if gap_fit is not None else "unknown",
            1.0 if gap_fit is not None else 0.0,
            (
                "Higher values indicate a larger share of catchment demand remains "
                "uncovered by existing sites."
            ),
            source_ids,
        ),
        "provenance": provenance,
    }


def _capacity_metrics(config: PlanningRunConfig, candidate: Mapping[str, Any]) -> dict[str, Any]:
    charger_options = config.charger_options
    proposed_kw = 0.0
    for option in charger_options:
        count = option.get("port_count")
        power = option.get("power_kw_per_port")
        if (
            _finite_number(count)
            and _finite_number(power)
            and float(count) > 0
            and float(power) > 0
        ):
            proposed_kw += float(count) * float(power)
    recommended = _metric(
        proposed_kw if proposed_kw > 0 else None,
        "kW",
        "scenario" if proposed_kw > 0 else "unknown",
        1.0 if proposed_kw > 0 else 0.0,
        note=(
            "Scenario charger configuration; not utility approval or confirmed connection capacity."
        ),
    )
    grid = candidate.get("grid_capacity_kw")
    if (
        not isinstance(grid, Mapping)
        or grid.get("value") is None
        or not _finite_number(grid.get("value"))
    ):
        return {
            "recommended_capacity": recommended,
            "capacity_fit": _metric(
                None, "percent", "unknown", 0.0, note="Grid capacity evidence is unavailable."
            ),
            "overload_risk": _metric(
                None, "category", "unknown", 0.0, note="Grid capacity evidence is unavailable."
            ),
            "score": None,
            "evidence_fraction": 0.0,
            "status": "unknown",
            "source_ids": (),
            "provenance": [],
        }
    value = float(grid["value"])
    if value < 0:
        return {
            "recommended_capacity": recommended,
            "capacity_fit": _metric(None, "percent", "unknown", 0.0),
            "overload_risk": _metric(None, "category", "unknown", 0.0),
            "score": None,
            "evidence_fraction": 0.0,
            "status": "unknown",
            "source_ids": (),
            "provenance": [],
        }
    status = grid.get("status", "observed")
    if status not in DATA_STATUSES - {"unknown", "not_applicable"}:
        status = "unknown"
    sources = _source_ids(grid.get("source_ids", grid.get("source_id")))
    if not sources:
        status = "unknown"
    if status == "unknown":
        return {
            "recommended_capacity": recommended,
            "capacity_fit": _metric(
                None, "percent", "unknown", 0.0, note="Grid capacity has no valid source_id."
            ),
            "overload_risk": _metric(None, "category", "unknown", 0.0),
            "score": None,
            "evidence_fraction": 0.0,
            "status": "unknown",
            "source_ids": (),
            "provenance": [],
        }
    fit = min(100.0, 100.0 * value / proposed_kw) if proposed_kw > 0 else None
    shortfall = proposed_kw - value
    capacity_fit = _metric(
        fit,
        "percent",
        status if fit is not None else "unknown",
        1.0 if fit is not None else 0.0,
        sources,
    )
    risk_value = "potential_capacity_shortfall" if shortfall > 0 else "within_reported_capacity"
    overload = _metric(
        risk_value,
        "category",
        "scenario",
        1.0,
        sources,
        "Deterministic comparison with reported capacity; not a probability or utility approval.",
    )
    provenance = [
        {
            "field": "metrics.capacity_fit",
            "source_id": source,
            "source_ref": None,
            "status": status,
            "is_synthetic": status == "synthetic",
            "observed_at": None,
            "note": "Reported candidate grid capacity.",
        }
        for source in sources
    ]
    return {
        "recommended_capacity": recommended,
        "capacity_fit": capacity_fit,
        "overload_risk": overload,
        "score": fit,
        "evidence_fraction": 1.0 if fit is not None else 0.0,
        "status": status if fit is not None else "unknown",
        "source_ids": sources,
        "provenance": provenance,
    }


def _readiness_component(
    constraints: Sequence[Mapping[str, Any]], capacity: Mapping[str, Any]
) -> dict[str, Any]:
    readiness_facts = [item for item in constraints if item["id"] != "inside_boundary"]
    known = [item for item in readiness_facts if item["status"] == "pass"]
    scores = [100.0 for _ in known]
    sources = [source for item in known for source in item["source_ids"]]
    statuses = [item["evidence_status"] for item in known]
    if capacity["score"] is not None:
        scores.append(float(capacity["score"]))
        sources.extend(capacity["source_ids"])
        statuses.append(capacity["status"])
    if not scores:
        return _component(
            None, "unknown", 0.0, "No source-backed site/grid readiness evidence is available."
        )
    fraction = min(
        1.0, (len(known) + (1 if capacity["score"] is not None else 0)) / (len(readiness_facts) + 1)
    )
    status = _combined_status(statuses)
    return _component(
        sum(scores) / len(scores),
        status,
        fraction,
        (
            "Average of source-backed passing readiness gates and reported grid-capacity fit; "
            "unknown gates are excluded."
        ),
        tuple(dict.fromkeys(sources)),
    )


def _network_fit_component(
    candidate: Mapping[str, Any], feature_weights: Sequence[tuple[str, float]]
) -> dict[str, Any]:
    raw = candidate.get("network_features")
    if not isinstance(raw, Mapping):
        return _component(None, "unknown", 0.0, "No network-segment feature evidence was provided.")
    scores: list[tuple[float, float, str, tuple[str, ...]]] = []
    for name, weight in feature_weights:
        feature = raw.get(name)
        if not isinstance(feature, Mapping):
            continue
        value = feature.get("value")
        status = feature.get("status")
        if (
            not _finite_number(value)
            or not 0 <= float(value) <= 100
            or status not in DATA_STATUSES - {"unknown", "not_applicable"}
        ):
            continue
        sources = _source_ids(feature.get("source_ids", feature.get("source_id")))
        if not sources:
            continue
        scores.append((float(value), weight, status, sources))
    if not scores:
        return _component(
            None, "unknown", 0.0, "No source-backed network-segment features are available."
        )
    known_weight = sum(weight for _, weight, _, _ in scores)
    score = sum(value * weight for value, weight, _, _ in scores) / known_weight
    return _component(
        score,
        _combined_status(status for _, _, status, _ in scores),
        known_weight,
        (
            "Weighted mean of available 0-100 road-accessibility, POI/dwell, fleet, and "
            "charger-mix features."
        ),
        tuple(dict.fromkeys(source for _, _, _, sources in scores for source in sources)),
    )


def _add_demand_scores(evaluations: list[dict[str, Any]]) -> None:
    known = [item for item in evaluations if item["demand_value"] is not None]
    if not known:
        for item in evaluations:
            item["demand_component"] = _component(
                None,
                "unknown",
                item["demand_coverage"],
                item["demand_note"] or "Demand evidence is unavailable.",
                tuple(
                    source["source_id"] for source in item["demand_sources"] if source["source_id"]
                ),
            )
        return
    values = [item["demand_value"] for item in known]
    low, high = min(values), max(values)
    for item in evaluations:
        value = item["demand_value"]
        if value is None:
            item["demand_component"] = _component(
                None,
                "unknown",
                item["demand_coverage"],
                item["demand_note"] or "Demand evidence is unavailable.",
                tuple(
                    source["source_id"] for source in item["demand_sources"] if source["source_id"]
                ),
            )
            continue
        score = 50.0 if high == low else 100.0 * (value - low) / (high - low)
        item["demand_component"] = _component(
            score,
            item["demand_status"],
            item["demand_coverage"],
            (
                "Relative demand potential within this candidate set; it is not a market "
                "forecast or probability."
            ),
            tuple(source["source_id"] for source in item["demand_sources"] if source["source_id"]),
        )


def _existing_coverage(dataset: Mapping[str, Any]) -> tuple[set[str], tuple[str, ...], bool, str]:
    raw = dataset.get("existing_covered_demand_cell_ids")
    if raw is None:
        return set(), (), False, "unknown"
    ids = _string_ids(raw)
    if ids is None:
        return set(), (), False, "unknown"
    sources = _source_ids(dataset.get("existing_coverage_source_ids"))
    status = dataset.get("existing_coverage_status", "unknown")
    if not sources or status not in DATA_STATUSES - {"unknown", "not_applicable"}:
        return set(), (), False, "unknown"
    return set(ids), sources, True, status


def _string_ids(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    if any(not isinstance(item, str) or not item.strip() for item in value) or len(value) != len(
        set(value)
    ):
        return None
    return tuple(value)


def _metric(
    value: float | str | None,
    unit: str,
    status: str,
    coverage: float,
    source_ids: Sequence[str] = (),
    note: str | None = None,
) -> dict[str, Any]:
    if value is None and status not in {"unknown", "not_applicable"}:
        status = "unknown"
    if value is not None and status in {"unknown", "not_applicable"}:
        value = None
    result: dict[str, Any] = {
        "value": round(float(value), 6)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else value,
        "unit": unit,
        "status": status if status in DATA_STATUSES else "unknown",
    }
    return result


def _component(
    score: float | None,
    status: str,
    evidence_fraction: float,
    reason: str,
    source_ids: Sequence[str] = (),
) -> dict[str, Any]:
    if score is None or status in {"unknown", "not_applicable"}:
        return {
            "score": None,
            "status": status if status == "not_applicable" else "unknown",
            "evidence_fraction": max(0.0, min(1.0, evidence_fraction)),
            "reason": reason,
            "source_ids": tuple(source_ids),
        }
    return {
        "score": max(0.0, min(100.0, float(score))),
        "status": status,
        "evidence_fraction": max(0.0, min(1.0, evidence_fraction)),
        "reason": reason,
        "source_ids": tuple(source_ids),
    }


def _candidate_provenance(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    raw = candidate.get("provenance", ())
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            status = item.get("status", "unknown")
            if status not in DATA_STATUSES:
                status = "unknown"
            result.append(
                {
                    "field": str(item.get("field", "candidate")),
                    "source_id": item.get("source_id"),
                    "source_ref": item.get("source_ref"),
                    "status": status,
                    "is_synthetic": bool(item.get("is_synthetic", status == "synthetic")),
                    "observed_at": item.get("observed_at"),
                    "note": item.get("note"),
                }
            )
    for source in _source_ids(candidate.get("source_ids")):
        result.append(
            {
                "field": "candidate",
                "source_id": source,
                "source_ref": None,
                "status": candidate.get("status", "observed")
                if candidate.get("status") in DATA_STATUSES
                else "unknown",
                "is_synthetic": candidate.get("status") == "synthetic",
                "observed_at": None,
                "note": None,
            }
        )
    return result


def _constraint_provenance(constraints: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "field": f"constraints.{item['id']}",
            "source_id": source,
            "source_ref": None,
            "status": item["evidence_status"],
            "is_synthetic": item["evidence_status"] == "synthetic",
            "observed_at": None,
            "note": item["reason"],
        }
        for item in constraints
        for source in item["source_ids"]
    ]


def _demand_provenance(record: _DemandRecord, field: str) -> dict[str, Any]:
    note = f"{record.target} ({record.unit}), scenario={record.scenario}"
    if record.model_version:
        note += f", model_version={record.model_version}"
    if record.uncertainty:
        note += f", uncertainty={record.uncertainty.get('method')}"
    return {
        "field": field,
        "source_id": record.source_id,
        "source_ref": None,
        "status": record.status,
        "is_synthetic": record.status == "synthetic",
        "observed_at": None,
        "note": note,
    }


def _dedupe_provenance(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        key = (item.get("field"), item.get("source_id"), item.get("status"), item.get("note"))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def _combined_status(statuses: Sequence[str] | Any) -> str:
    values = tuple(statuses)
    for status in ("synthetic", "scenario", "proxy", "observed"):
        if status in values:
            return status
    return "unknown"


def _source_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(
            dict.fromkeys(item for item in value if isinstance(item, str) and item.strip())
        )
    return ()


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))
    )


def _cell_unit(records: Mapping[str, _DemandRecord]) -> str:
    return next(iter(records.values())).unit if records else "demand_unit"


def _run_warnings(evaluations: Sequence[Mapping[str, Any]]) -> list[str]:
    statuses: set[str] = set()
    for item in evaluations:
        statuses.add(item["demand_status"])
        if item["capacity"]["recommended_capacity"]["value"] is not None:
            statuses.add("scenario")
        statuses.update(fact["evidence_status"] for fact in item["constraints"])
        statuses.update(fact["status"] for fact in item["constraints"])
        statuses.update(item["components"][name]["status"] for name in COMPONENTS)
        statuses.update(source["status"] for source in item["demand_sources"])
        statuses.update(source["status"] for source in _candidate_provenance(item["candidate"]))
    warnings = []
    if "synthetic" in statuses:
        warnings.append(
            "Synthetic input is for demonstration only and is not HCMC operating evidence."
        )
    if "scenario" in statuses:
        warnings.append(
            "Scenario-derived values are assumptions, not probability estimates "
            "or utility approval."
        )
    if "proxy" in statuses:
        warnings.append("One or more inputs are proxies; review their provenance before decisions.")
    if "unknown" in statuses or "not_applicable" in statuses or "conditional" in statuses:
        warnings.append(
            "Unknown or conditional evidence remains; candidate rankings are "
            "screening results only."
        )
    return warnings
