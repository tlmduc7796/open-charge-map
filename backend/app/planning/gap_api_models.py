"""Pydantic contract for the gap-screening endpoints (snake_case like the rest of /planning)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GapDivision = Literal["grid", "route"]


class GapRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str | None = Field(default=None, description="Gap snapshot; null = current.")
    division: GapDivision = Field(
        default="route", description="route = street blocks bounded by roads, grid = 300 m cells"
    )
    w_flow: float = Field(default=0.5, ge=0.0, le=1.0, description="w1; w2 = 1 - w1")
    lambda_m: float = Field(default=1000.0, ge=50.0, le=10_000.0)
    normalization: Literal["minmax", "percentile"] = "minmax"
    rent_mode: Literal["none", "filter", "divide"] = "divide"
    rent_max_kvnd: float = Field(default=600.0, ge=0.0)
    epsilon: float = Field(default=0.1, gt=0.0, le=1.0)
    own_min_distance_m: float = Field(default=500.0, ge=0.0, le=5_000.0)
    own_mode: Literal["flag", "exclude"] = "flag"
    top_n: int = Field(default=5, ge=1, le=30)
    min_separation_m: float = Field(default=1000.0, ge=0.0, le=5_000.0)
    supply_basis: Literal["ports", "power"] = "ports"
    reference_power_kw: float = Field(default=60.0, gt=0.0, le=1_000.0)
    min_demand: float = Field(default=0.1, ge=0.0, le=1.0)
    with_sensitivity: bool = True


class GapPortGroup(BaseModel):
    charger_type: Literal["AC", "DC"]
    connector_type: str
    port_count: int
    power_kw_per_port: float


class GapStationItem(BaseModel):
    station_id: str
    operator_id: str
    operator_name: str
    relationship: Literal["OWNED", "OTHER_NETWORK"]
    unit_id: str
    unit_name: str
    lat: float
    lon: float
    site_type: str
    opening_hours: str
    port_count: int
    dc_port_count: int
    ac_port_count: int
    total_power_kw: float
    max_port_power_kw: float
    port_groups: list[GapPortGroup]
    data_status: Literal["synthetic"] = "synthetic"


class GapCellItem(BaseModel):
    cell_id: str
    unit_id: str
    unit_name: str
    lat: float
    lon: float
    bounds: tuple[float, float, float, float] = Field(
        description="Bounding box: lat_min, lon_min, lat_max, lon_max"
    )
    polygon: list[list[tuple[float, float]]] | None = Field(
        default=None, description="Street block outline as [lat, lon] rings (outer ring first)"
    )
    area_m2: float | None = None
    subdivided: bool = Field(
        default=False, description="Piece of an oversized open area, cut by a straight line"
    )
    road_name: str | None = Field(default=None, description="Route division: longest road in cell")
    road_names: list[str] | None = Field(default=None, description="Up to 3 roads, longest first")
    road_type: str | None = None
    width_m: float | None = Field(default=None, description="Widest road surface in the cell")
    lanes: int | None = None
    road_length_m: float | None = Field(default=None, description="Road length inside the cell")
    poi_count: float
    poi_weighted: float
    flow_vph: float
    rent_kvnd_m2_month: float | None


class GapRoadItem(BaseModel):
    road_id: str
    name: str
    road_type: str
    lanes: int | None = None
    length_m: float
    flow_vph: float = Field(description="Simulated peak-hour vehicles per hour on this road")
    coordinates: list[tuple[float, float]] = Field(description="Polyline as [lat, lon] points")


class GapOperatorSummary(BaseModel):
    operator_name: str
    relationship: str
    stations: int
    ports: int
    dc_ports: int
    ac_ports: int
    total_power_kw: float


class GapStationSummary(BaseModel):
    stations: int
    ports: int
    total_power_kw: float
    by_operator: dict[str, GapOperatorSummary]
    ports_by_power_class: dict[str, int]
    stations_by_ward: dict[str, int]


class GapSnapshotResponse(BaseModel):
    contract_version: Literal["gap-0.1"] = "gap-0.1"
    snapshot_id: str
    division: GapDivision
    prepared_on: str
    data_labels: dict[str, str]
    defaults: GapRunRequest
    cells: list[GapCellItem]
    roads: list[GapRoadItem]
    stations: list[GapStationItem]
    station_summary: GapStationSummary


class GapCellResult(BaseModel):
    cell_id: str
    flow_norm: float
    poi_norm: float
    demand: float
    supply: float
    supply_own: float
    supply_competitor: float
    gap: float
    rent_norm: float | None
    rent_missing: bool
    score: float
    d_own_m: float | None
    d_competitor_m: float | None
    own_overlap: bool
    excluded_reason: Literal["rent_above_limit", "own_station_nearby", "demand_below_floor"] | None
    rank: int | None


class GapNearestStation(BaseModel):
    station_id: str
    operator_name: str
    port_count: int
    total_power_kw: float
    max_port_power_kw: float
    distance_m: float


class GapSupplyContributor(BaseModel):
    station_id: str
    operator_name: str
    relationship: str
    port_count: int
    total_power_kw: float
    distance_m: float
    contribution: float


class GapNearby(BaseModel):
    radius_m: float
    cell_count: int
    flow_mean_vph: float
    flow_max_vph: float
    flow_max_roads: list[str] | None = None
    flow_percentile: float
    rent_mean_kvnd: float | None
    rent_min_kvnd: float | None
    rent_max_kvnd: float | None
    rent_percentile: float | None


class GapCandidate(GapCellResult):
    selection_order: int
    unit_id: str
    unit_name: str
    lat: float
    lon: float
    flow_vph: float
    poi_count: float
    poi_weighted: float
    rent_kvnd_m2_month: float | None
    road_name: str | None = None
    road_names: list[str] | None = None
    road_type: str | None = None
    width_m: float | None = None
    lanes: int | None = None
    road_length_m: float | None = None
    area_m2: float | None = None
    subdivided: bool = False
    cluster_cell_ids: list[str]
    cluster_size: int
    nearby: GapNearby
    nearest_own: GapNearestStation | None
    nearest_competitor: GapNearestStation | None
    top_supply_stations: list[GapSupplyContributor]
    stability: float | None
    stability_label: Literal["stable", "sensitive"] | None
    legal_status: Literal["unknown"] = "unknown"
    pending_legal_checks: list[str]


class GapRunSummary(BaseModel):
    cell_count: int
    eligible_cell_count: int
    excluded_by_reason: dict[str, int]
    own_overlap_cell_count: int
    rent_missing_cell_count: int
    sensitivity_variant_count: int
    max_gap: float
    max_score: float


class GapRunResponse(BaseModel):
    contract_version: Literal["gap-0.1"] = "gap-0.1"
    snapshot_id: str
    params: GapRunRequest
    cells: list[GapCellResult]
    candidates: list[GapCandidate]
    summary: GapRunSummary
    warnings: list[str]
