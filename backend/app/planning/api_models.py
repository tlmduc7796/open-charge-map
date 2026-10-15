"""Snake-case HTTP models for the station-planning contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DataStatus = Literal[
    "observed",
    "proxy",
    "synthetic",
    "scenario",
    "unknown",
    "not_applicable",
]


def _parse_iso_datetime(value: Any) -> Any:
    """Allow ISO JSON timestamps while keeping strict validation for other field types."""
    if not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value


ConstraintStatus = Literal["pass", "fail", "conditional", "unknown", "not_applicable"]
PlanningProfile = Literal["technical_opportunity", "public_policy", "investor_economic"]
PlanningRunStatus = Literal[
    "completed",
    "completed_with_unknowns",
    "invalid_input",
    "no_feasible_candidates",
    "failed",
]


class PlanningModel(BaseModel):
    """Planning models use contract snake_case, independent of the legacy camelCase API base."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        strict=True,
        allow_inf_nan=False,
    )


class StudyAreaInput(PlanningModel):
    city_id: str = Field(min_length=1)
    boundary_version: str = Field(min_length=1)
    pilot_extent_id: str = Field(min_length=1)


class RunInput(PlanningModel):
    as_of: datetime
    horizon_years: int = Field(ge=1)
    data_snapshot_id: str = Field(min_length=1)
    seed: int
    config_version: str | None = Field(min_length=1)
    demand_scenario: Literal["low", "base", "high"] = "base"

    @field_validator("as_of", mode="before")
    @classmethod
    def parse_as_of(cls, value: Any) -> Any:
        return _parse_iso_datetime(value)

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        return value


class CandidateSourceInput(PlanningModel):
    mode: Literal["provided"]
    candidate_ids: list[str]

    @field_validator("candidate_ids")
    @classmethod
    def candidate_ids_are_unique(cls, values: list[str]) -> list[str]:
        if any(not value for value in values):
            raise ValueError("candidate_ids must not contain blank IDs")
        if len(set(values)) != len(values):
            raise ValueError("candidate_ids must not contain duplicates")
        return values


class ChargerOptionInput(PlanningModel):
    charger_type: Literal["AC", "DC"]
    port_count: int = Field(ge=1)
    power_kw_per_port: float = Field(gt=0)


class TechnicalInput(PlanningModel):
    coverage_minutes: int = Field(gt=0)
    charger_options: list[ChargerOptionInput] = Field(min_length=1)
    budget_vnd: float | None = Field(default=None, ge=0)


class PlanningRecommendationRequest(PlanningModel):
    contract_version: Literal["0.1"]
    study_area: StudyAreaInput
    run: RunInput
    candidate_source: CandidateSourceInput
    profile: PlanningProfile
    technical: TechnicalInput
    policy_package: dict[str, Any] | None = None
    finance_package: dict[str, Any] | None = None


class ScenarioEcho(PlanningModel):
    profile: PlanningProfile
    as_of: datetime
    horizon_years: int
    seed: int
    data_snapshot_id: str
    demand_scenario: Literal["low", "base", "high"] = "base"
    algorithm_version: str | None
    config_version: str | None
    policy_package_id: str | None
    policy_package_version: str | None
    finance_package_id: str | None
    finance_package_version: str | None


class LocationOutput(PlanningModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class MetricOutput(PlanningModel):
    value: int | float | str | None
    unit: str = Field(min_length=1)
    status: DataStatus

    @model_validator(mode="after")
    def null_unknown_values(self) -> MetricOutput:
        if self.status in {"unknown", "not_applicable"} and self.value is not None:
            raise ValueError("unknown and not_applicable metrics must have null value")
        return self


class ConstraintOutput(PlanningModel):
    id: str = Field(min_length=1)
    status: ConstraintStatus
    reason: str = Field(min_length=1)


class ScoreBreakdownOutput(PlanningModel):
    component_id: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0, le=100)
    weight_percent: float | None = Field(default=None, ge=0, le=100)
    contribution_points: float | None = None
    status: DataStatus
    reason: str = Field(min_length=1)


class ProvenanceOutput(PlanningModel):
    field: str = Field(min_length=1)
    source_id: str | None
    source_ref: str | None
    status: DataStatus
    is_synthetic: bool
    observed_at: datetime | None
    note: str | None

    @field_validator("observed_at", mode="before")
    @classmethod
    def parse_observed_at(cls, value: Any) -> Any:
        return _parse_iso_datetime(value)

    @field_validator("observed_at")
    @classmethod
    def observed_at_requires_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("observed_at must include a timezone")
        return value


class RecommendationOutput(PlanningModel):
    rank: int = Field(ge=1)
    candidate_id: str = Field(min_length=1)
    location: LocationOutput
    eligibility: Literal["eligible", "conditional"]
    technical_score: float = Field(ge=0, le=100)
    evidence_coverage: float = Field(ge=0, le=1)
    metrics: dict[str, MetricOutput]
    constraints: list[ConstraintOutput]
    score_breakdown: list[ScoreBreakdownOutput]
    provenance: list[ProvenanceOutput]


class UnrankedCandidateOutput(PlanningModel):
    candidate_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ExcludedCandidateOutput(PlanningModel):
    candidate_id: str = Field(min_length=1)
    constraints: list[ConstraintOutput] = Field(min_length=1)

    @field_validator("constraints")
    @classmethod
    def all_exclusion_constraints_fail(
        cls, values: list[ConstraintOutput]
    ) -> list[ConstraintOutput]:
        if any(item.status != "fail" for item in values):
            raise ValueError("excluded candidates require confirmed failing constraints")
        return values


class PlanningRecommendationResponse(PlanningModel):
    contract_version: Literal["0.1"]
    run_id: str = Field(min_length=1)
    status: PlanningRunStatus
    scenario: ScenarioEcho
    recommendations: list[RecommendationOutput]
    unranked_candidates: list[UnrankedCandidateOutput]
    excluded_candidates: list[ExcludedCandidateOutput]
    warnings: list[str]

    @model_validator(mode="after")
    def recommendations_have_contiguous_ranks(self) -> PlanningRecommendationResponse:
        ranks = [item.rank for item in self.recommendations]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("recommendation ranks must be contiguous from 1")
        candidate_ids = [item.candidate_id for item in self.recommendations]
        candidate_ids.extend(item.candidate_id for item in self.unranked_candidates)
        candidate_ids.extend(item.candidate_id for item in self.excluded_candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("a candidate may appear in only one result group")
        if self.status == "invalid_input" and (candidate_ids or not self.warnings):
            raise ValueError("invalid_input runs require a warning and no evaluated candidates")
        if self.status == "failed" and not self.warnings:
            raise ValueError("failed runs require a warning that explains the failure")
        if self.status == "no_feasible_candidates" and (
            self.recommendations or self.unranked_candidates or not self.excluded_candidates
        ):
            raise ValueError("no_feasible_candidates requires only excluded candidates")
        return self


class PlanningDemoLocation(PlanningModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PlanningDemoCandidate(PlanningModel):
    candidate_id: str = Field(min_length=1)
    unit_id: str | None = None
    unit_name: str | None = None
    label: str = Field(min_length=1)
    candidate_type: str = Field(min_length=1)
    eligibility: Literal["eligible", "conditional"]
    is_synthetic: bool
    location: PlanningDemoLocation
    source_ref: str | None


class PlanningDemoSite(PlanningModel):
    site_id: str = Field(min_length=1)
    unit_id: str | None = None
    unit_name: str | None = None
    label: str = Field(min_length=1)
    site_type: str = Field(min_length=1)
    charger_type: str = Field(min_length=1)
    port_count: int | None
    power_kw: float | None
    is_synthetic: bool
    location: PlanningDemoLocation
    source_ref: str | None


class PlanningDemoWeeklyDemand(PlanningModel):
    low: float = Field(ge=0, allow_inf_nan=False)
    base: float = Field(ge=0, allow_inf_nan=False)
    high: float = Field(ge=0, allow_inf_nan=False)


class PlanningDemoDemandNode(PlanningModel):
    demand_node_id: str = Field(min_length=1)
    unit_id: str = Field(min_length=1)
    location: PlanningDemoLocation
    nearest_existing_access_minutes_proxy: float = Field(ge=0)
    is_synthetic: bool
    weekly_expected_sessions: PlanningDemoWeeklyDemand


class PlanningDemoPeakLoad(PlanningModel):
    interval_start: datetime
    sessions_by_node: dict[str, float]

    @field_validator("interval_start", mode="before")
    @classmethod
    def parse_interval_start(cls, value: Any) -> Any:
        return _parse_iso_datetime(value)


class PlanningDemoLoadSimulation(PlanningModel):
    version: Literal["peak-load-demo-v1"]
    interval_minutes: float = Field(gt=0)
    nearby_drive_minutes: float = Field(gt=0)
    circuity_factor: float = Field(gt=0)
    speed_kmh: float = Field(gt=0)
    fixed_access_minutes: float = Field(ge=0)
    energy_per_session_kwh: float = Field(gt=0)
    grid_delivery_efficiency: float = Field(gt=0, le=1)
    minimum_service_minutes: float = Field(gt=0)
    comfortable_utilization: float = Field(gt=0, le=1)
    peak_by_scenario: dict[Literal["low", "base", "high"], PlanningDemoPeakLoad]


class PlanningDemoSnapshotResponse(PlanningModel):
    contract_version: Literal["0.1"]
    study_area: StudyAreaInput
    snapshot: dict[str, Any]
    defaults: dict[str, Any]
    candidates: list[PlanningDemoCandidate]
    existing_sites: list[PlanningDemoSite]
    demand_nodes: list[PlanningDemoDemandNode]
    load_simulation: PlanningDemoLoadSimulation | None = None
    warnings: list[str]
