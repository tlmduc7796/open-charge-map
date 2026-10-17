"""Gap screening for charging-station survey candidates.

Pure logic, no I/O. Implements KeHoachPlannerNew/ke-hoach-khoang-trong-tram-sac.md:

1. demand      D_i    = w1 * norm(Flow_i) + w2 * norm(POI_i),  w1 + w2 = 1
2. supply      Cung_i = sum_k n_k * exp(-d_ik / lambda)       (own and competitor stations)
3. gap         Gap_i  = D_i / (1 + Cung_i)
4. rent        none | filter (rent above a limit) | divide (Gap_i / (norm(Rent_i) + epsilon))
5. own flag    d_own_i = min distance to an own station; below a threshold flag or exclude

A demand floor (`min_demand`) additionally drops cells whose D_i is almost zero: the plan's
Gap_i = D_i / (1 + Cung_i) otherwise ranks empty, undemanded cells first. Set it to 0 for the
plain formula.

A unit is a street block (`route`: the land enclosed by the real road network, an oversized open
area is cut into smaller pieces) or a square cell of a 300 m coordinate grid (`grid`). The
formulas only need a point inside the unit.
Units are ranked by score; the top N units at least `min_separation_m` apart become survey
candidates. Legal status is never
inferred: every candidate is `unknown` until evidence exists.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

NormalizationMethod = Literal["minmax", "percentile"]
RentMode = Literal["none", "filter", "divide"]
OwnMode = Literal["flag", "exclude"]
SupplyBasis = Literal["ports", "power"]

EARTH_RADIUS_M = 6_371_008.8
OWNED_RELATIONSHIP = "OWNED"
SENSITIVITY_WEIGHT_DELTA = 0.2
SENSITIVITY_LAMBDA_FACTORS = (0.5, 1.0, 1.5)
STABLE_THRESHOLD = 2 / 3
TOP_CONTRIBUTORS = 3
NEARBY_RADIUS_M = 800.0

LEGAL_PENDING_CHECKS = (
    "Quy hoạch và mục đích sử dụng tại vị trí chưa được xác minh",
    "Giấy phép xây dựng và yêu cầu PCCC chưa được kiểm tra",
    "Điều kiện kinh doanh dịch vụ sạc chưa được kiểm tra",
)


@dataclass(frozen=True)
class GapCell:
    cell_id: str
    unit_id: str
    unit_name: str
    lat: float
    lon: float
    poi_count: float
    poi_weighted: float
    flow_vph: float
    rent_kvnd_m2_month: float | None
    road_name: str | None = None
    road_names: tuple[str, ...] = ()
    road_type: str | None = None
    width_m: float | None = None
    lanes: int | None = None
    road_length_m: float | None = None
    area_m2: float | None = None
    subdivided: bool = False


@dataclass(frozen=True)
class GapStation:
    station_id: str
    operator_id: str
    operator_name: str
    relationship: str
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

    @property
    def is_own(self) -> bool:
        return self.relationship == OWNED_RELATIONSHIP


@dataclass(frozen=True)
class GapParams:
    w_flow: float = 0.5
    lambda_m: float = 1000.0
    normalization: NormalizationMethod = "minmax"
    rent_mode: RentMode = "divide"
    rent_max_kvnd: float = 600.0
    epsilon: float = 0.1
    own_min_distance_m: float = 500.0
    own_mode: OwnMode = "flag"
    top_n: int = 5
    min_separation_m: float = 1000.0
    supply_basis: SupplyBasis = "ports"
    reference_power_kw: float = 60.0
    min_demand: float = 0.1

    @property
    def w_poi(self) -> float:
        return 1.0 - self.w_flow


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def distance_matrix(cells: Sequence[GapCell], stations: Sequence[GapStation]) -> list[list[float]]:
    return [
        [haversine_m(cell.lat, cell.lon, station.lat, station.lon) for station in stations]
        for cell in cells
    ]


def normalize(values: Sequence[float], method: NormalizationMethod) -> list[float]:
    """Scale to [0, 1] over the study area. A constant series maps to 0, never to NaN."""
    if not values:
        return []
    if method == "percentile":
        order = sorted(range(len(values)), key=lambda index: values[index])
        ranks = [0.0] * len(values)
        last = max(len(values) - 1, 1)
        position = 0
        while position < len(order):
            end = position
            while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
                end += 1
            share = ((position + end) / 2) / last
            for index in order[position : end + 1]:
                ranks[index] = share
            position = end + 1
        return ranks
    low, high = min(values), max(values)
    span = high - low
    return [0.0 if span == 0 else (value - low) / span for value in values]


def station_weight(station: GapStation, params: GapParams) -> float:
    """n_k of the plan: number of ports, or nameplate kW expressed in reference-power ports."""
    if params.supply_basis == "power":
        return station.total_power_kw / params.reference_power_kw
    return float(station.port_count)


def compute_cells(
    cells: Sequence[GapCell],
    stations: Sequence[GapStation],
    distances: Sequence[Sequence[float]],
    params: GapParams,
) -> list[dict[str, Any]]:
    """Steps 1-5 for every cell. Returns one row per cell, in `cells` order."""
    flow_norm = normalize([cell.flow_vph for cell in cells], params.normalization)
    poi_norm = normalize([cell.poi_weighted for cell in cells], params.normalization)
    known_rent = [c.rent_kvnd_m2_month for c in cells if c.rent_kvnd_m2_month is not None]
    rent_scaled = dict(
        zip(
            [c.cell_id for c in cells if c.rent_kvnd_m2_month is not None],
            normalize(known_rent, params.normalization),
            strict=True,
        )
    )
    weights = [station_weight(station, params) for station in stations]
    rows: list[dict[str, Any]] = []
    for index, cell in enumerate(cells):
        demand = params.w_flow * flow_norm[index] + params.w_poi * poi_norm[index]
        supply_own = supply_other = 0.0
        d_own = d_other = None
        for station_index, station in enumerate(stations):
            distance = distances[index][station_index]
            contribution = weights[station_index] * math.exp(-distance / params.lambda_m)
            if station.is_own:
                supply_own += contribution
                d_own = distance if d_own is None else min(d_own, distance)
            else:
                supply_other += contribution
                d_other = distance if d_other is None else min(d_other, distance)
        supply = supply_own + supply_other
        gap = demand / (1.0 + supply)

        rent = cell.rent_kvnd_m2_month
        rent_norm = rent_scaled.get(cell.cell_id)
        rent_missing = rent is None
        excluded_reason: str | None = None
        score = gap
        if demand < params.min_demand:
            excluded_reason = "demand_below_floor"
        if params.rent_mode == "divide" and rent_norm is not None:
            score = gap / (rent_norm + params.epsilon)
        elif (
            params.rent_mode == "filter" and rent is not None and rent > params.rent_max_kvnd
            and excluded_reason is None
        ):
            excluded_reason = "rent_above_limit"
        own_overlap = d_own is not None and d_own < params.own_min_distance_m
        if own_overlap and params.own_mode == "exclude" and excluded_reason is None:
            excluded_reason = "own_station_nearby"
        rows.append(
            {
                "cell_id": cell.cell_id,
                "flow_norm": flow_norm[index],
                "poi_norm": poi_norm[index],
                "demand": demand,
                "supply": supply,
                "supply_own": supply_own,
                "supply_competitor": supply_other,
                "gap": gap,
                "rent_norm": rent_norm,
                "rent_missing": rent_missing and params.rent_mode != "none",
                "score": score,
                "d_own_m": d_own,
                "d_competitor_m": d_other,
                "own_overlap": own_overlap,
                "excluded_reason": excluded_reason,
                "rank": None,
            }
        )
    ranked = sorted(
        (row for row in rows if row["excluded_reason"] is None),
        key=lambda row: (-row["score"], row["cell_id"]),
    )
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position
    return rows


def select_candidates(
    cells: Sequence[GapCell], rows: Sequence[dict[str, Any]], params: GapParams
) -> list[dict[str, Any]]:
    """Greedy pick of the best cells at least `min_separation_m` apart; adjacent cells cluster."""
    by_id = {cell.cell_id: cell for cell in cells}
    ranked = sorted((row for row in rows if row["rank"] is not None), key=lambda r: r["rank"])
    selected: list[dict[str, Any]] = []
    clusters: dict[str, list[str]] = {}
    for row in ranked:
        cell = by_id[row["cell_id"]]
        owner = next(
            (
                chosen
                for chosen in selected
                if haversine_m(cell.lat, cell.lon, by_id[chosen["cell_id"]].lat,
                               by_id[chosen["cell_id"]].lon) < params.min_separation_m
            ),
            None,
        )
        if owner is not None:
            clusters[owner["cell_id"]].append(row["cell_id"])
        elif len(selected) < params.top_n:
            selected.append(row)
            clusters[row["cell_id"]] = []
    return [{**row, "cluster_cell_ids": clusters[row["cell_id"]]} for row in selected]


def _sensitivity_variants(params: GapParams) -> list[GapParams]:
    weights = sorted(
        {
            round(min(max(params.w_flow + delta, 0.1), 0.9), 4)
            for delta in (-SENSITIVITY_WEIGHT_DELTA, 0.0, SENSITIVITY_WEIGHT_DELTA)
        }
    )
    return [
        replace(params, w_flow=weight, lambda_m=params.lambda_m * factor)
        for weight in weights
        for factor in SENSITIVITY_LAMBDA_FACTORS
    ]


def _stability(
    cells: Sequence[GapCell],
    stations: Sequence[GapStation],
    distances: Sequence[Sequence[float]],
    params: GapParams,
    candidates: Sequence[dict[str, Any]],
) -> tuple[dict[str, float], int]:
    by_id = {cell.cell_id: cell for cell in cells}
    variants = _sensitivity_variants(params)
    hits = {candidate["cell_id"]: 0 for candidate in candidates}
    for variant in variants:
        rows = compute_cells(cells, stations, distances, variant)
        picked = select_candidates(cells, rows, variant)
        for candidate in candidates:
            base = by_id[candidate["cell_id"]]
            if any(
                haversine_m(base.lat, base.lon, by_id[p["cell_id"]].lat, by_id[p["cell_id"]].lon)
                < params.min_separation_m
                for p in picked
            ):
                hits[candidate["cell_id"]] += 1
    total = len(variants)
    return {cell_id: count / total for cell_id, count in hits.items()}, total


def _supply_contributors(
    cell: GapCell,
    stations: Sequence[GapStation],
    distances_row: Sequence[float],
    params: GapParams,
) -> list[dict[str, Any]]:
    items = []
    for station, distance in zip(stations, distances_row, strict=True):
        weight = station_weight(station, params)
        items.append(
            {
                "station_id": station.station_id,
                "operator_name": station.operator_name,
                "relationship": station.relationship,
                "port_count": station.port_count,
                "total_power_kw": station.total_power_kw,
                "distance_m": distance,
                "contribution": weight * math.exp(-distance / params.lambda_m),
            }
        )
    items.sort(key=lambda item: -item["contribution"])
    return items[:TOP_CONTRIBUTORS]


def _nearest(
    stations: Sequence[GapStation], distances_row: Sequence[float], own: bool
) -> dict[str, Any] | None:
    best: tuple[float, GapStation] | None = None
    for station, distance in zip(stations, distances_row, strict=True):
        if station.is_own == own and (best is None or distance < best[0]):
            best = (distance, station)
    if best is None:
        return None
    distance, station = best
    return {
        "station_id": station.station_id,
        "operator_name": station.operator_name,
        "port_count": station.port_count,
        "total_power_kw": station.total_power_kw,
        "max_port_power_kw": station.max_port_power_kw,
        "distance_m": distance,
    }


def _percentile(values: Sequence[float], value: float) -> float:
    """Share of the study area (0-100) whose value is at most `value`."""
    return 100.0 * sum(1 for other in values if other <= value) / len(values) if values else 0.0


def _nearby_context(cell: GapCell, cells: Sequence[GapCell]) -> dict[str, Any]:
    """Traffic and rent of the units around a candidate (the candidate's own unit included)."""
    around = [
        other for other in cells
        if haversine_m(cell.lat, cell.lon, other.lat, other.lon) <= NEARBY_RADIUS_M
    ] or [cell]
    busiest = max(around, key=lambda other: other.flow_vph)
    rents = [other.rent_kvnd_m2_month for other in around if other.rent_kvnd_m2_month is not None]
    city_rents = [c.rent_kvnd_m2_month for c in cells if c.rent_kvnd_m2_month is not None]
    rent = cell.rent_kvnd_m2_month
    return {
        "radius_m": NEARBY_RADIUS_M,
        "cell_count": len(around),
        "flow_mean_vph": sum(other.flow_vph for other in around) / len(around),
        "flow_max_vph": busiest.flow_vph,
        "flow_max_roads": list(busiest.road_names) or None,
        "flow_percentile": _percentile([c.flow_vph for c in cells], cell.flow_vph),
        "rent_mean_kvnd": sum(rents) / len(rents) if rents else None,
        "rent_min_kvnd": min(rents) if rents else None,
        "rent_max_kvnd": max(rents) if rents else None,
        "rent_percentile": None if rent is None else _percentile(city_rents, rent),
    }


def run_gap_analysis(
    cells: Sequence[GapCell],
    stations: Sequence[GapStation],
    params: GapParams,
    *,
    distances: Sequence[Sequence[float]] | None = None,
    with_sensitivity: bool = True,
) -> dict[str, Any]:
    if not cells:
        raise ValueError("At least one cell is required.")
    matrix = distances if distances is not None else distance_matrix(cells, stations)
    rows = compute_cells(cells, stations, matrix, params)
    picked = select_candidates(cells, rows, params)
    stability: dict[str, float] = {}
    variant_count = 0
    if with_sensitivity and picked:
        stability, variant_count = _stability(cells, stations, matrix, params, picked)

    by_id = {cell.cell_id: (index, cell) for index, cell in enumerate(cells)}
    candidates = []
    for pick in picked:
        index, cell = by_id[pick["cell_id"]]
        share = stability.get(pick["cell_id"])
        candidates.append(
            {
                **pick,
                "rank": pick["rank"],
                "selection_order": len(candidates) + 1,
                "unit_id": cell.unit_id,
                "unit_name": cell.unit_name,
                "lat": cell.lat,
                "lon": cell.lon,
                "flow_vph": cell.flow_vph,
                "road_name": cell.road_name,
                "road_names": list(cell.road_names) or None,
                "road_type": cell.road_type,
                "width_m": cell.width_m,
                "lanes": cell.lanes,
                "road_length_m": cell.road_length_m,
                "area_m2": cell.area_m2,
                "subdivided": cell.subdivided,
                "poi_count": cell.poi_count,
                "poi_weighted": cell.poi_weighted,
                "rent_kvnd_m2_month": cell.rent_kvnd_m2_month,
                "cluster_size": 1 + len(pick["cluster_cell_ids"]),
                "nearby": _nearby_context(cell, cells),
                "nearest_own": _nearest(stations, matrix[index], own=True),
                "nearest_competitor": _nearest(stations, matrix[index], own=False),
                "top_supply_stations": _supply_contributors(cell, stations, matrix[index], params),
                "stability": share,
                "stability_label": (
                    None if share is None else "stable" if share >= STABLE_THRESHOLD
                    else "sensitive"
                ),
                "legal_status": "unknown",
                "pending_legal_checks": list(LEGAL_PENDING_CHECKS),
            }
        )
    eligible = [row for row in rows if row["excluded_reason"] is None]
    reasons: dict[str, int] = {}
    for row in rows:
        if row["excluded_reason"]:
            reasons[row["excluded_reason"]] = reasons.get(row["excluded_reason"], 0) + 1
    return {
        "cells": rows,
        "candidates": candidates,
        "summary": {
            "cell_count": len(rows),
            "eligible_cell_count": len(eligible),
            "excluded_by_reason": reasons,
            "own_overlap_cell_count": sum(1 for row in rows if row["own_overlap"]),
            "rent_missing_cell_count": sum(1 for row in rows if row["rent_missing"]),
            "sensitivity_variant_count": variant_count,
            "max_gap": max(row["gap"] for row in rows),
            "max_score": max((row["score"] for row in eligible), default=0.0),
        },
    }
