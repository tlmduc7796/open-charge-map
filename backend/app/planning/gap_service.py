"""Load the pinned gap snapshot and serve snapshot/run requests."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

from backend.app.planning.domain import PlanningDataError
from backend.app.planning.gap_analysis import (
    GapCell,
    GapParams,
    GapStation,
    distance_matrix,
    run_gap_analysis,
)
from backend.app.planning.gap_api_models import (
    GapDivision,
    GapRunRequest,
    GapRunResponse,
    GapSnapshotResponse,
)

GAP_SNAPSHOT_ID = "hcmc-nine-wards-gap-v1"
_DEFAULT_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "data_platform" / "station_planning" / "gap_v1"
)
_REQUIRED_FILES = (
    "grid_cells.csv",
    "route_blocks.csv",
    "route_roads.csv",
    "gap_stations.csv",
    "gap_station_ports.csv",
    "station_summary.json",
    "analysis_defaults.json",
)
_DIVISION_LABELS = {"grid": "ô lưới", "route": "khối đường"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _optional_float(value: str) -> float | None:
    return float(value) if value.strip() else None


def _optional_int(value: str) -> int | None:
    return int(float(value)) if value.strip() else None


def _grid_units(rows: list[dict[str, str]]) -> tuple[list[GapCell], list[dict[str, Any]]]:
    cells, items = [], []
    for row in rows:
        cell = GapCell(
            cell_id=row["cell_id"], unit_id=row["unit_id"], unit_name=row["unit_name"],
            lat=float(row["center_lat"]), lon=float(row["center_lon"]),
            poi_count=float(row["poi_count"]), poi_weighted=float(row["poi_weighted"]),
            flow_vph=float(row["flow_vph"]),
            rent_kvnd_m2_month=_optional_float(row["rent_kvnd_m2_month"]),
        )
        cells.append(cell)
        items.append(
            {
                **_base_item(cell),
                "bounds": (
                    float(row["lat_min"]), float(row["lon_min"]),
                    float(row["lat_max"]), float(row["lon_max"]),
                ),
            }
        )
    return cells, items


def _route_units(rows: list[dict[str, str]]) -> tuple[list[GapCell], list[dict[str, Any]]]:
    cells, items = [], []
    for row in rows:
        names = tuple(name for name in row["road_names"].split(" | ") if name)
        cell = GapCell(
            cell_id=row["cell_id"], unit_id=row["unit_id"], unit_name=row["unit_name"],
            lat=float(row["center_lat"]), lon=float(row["center_lon"]),
            poi_count=float(row["poi_count"]), poi_weighted=float(row["poi_weighted"]),
            flow_vph=float(row["flow_vph"]),
            rent_kvnd_m2_month=_optional_float(row["rent_kvnd_m2_month"]),
            road_name=names[0] if names else None, road_names=names,
            road_type=row["road_type"] or None, lanes=_optional_int(row["lanes"]),
            road_length_m=float(row["road_length_m"]), area_m2=float(row["area_m2"]),
            subdivided=row["subdivided"] == "true",
        )
        cells.append(cell)
        items.append(
            {
                **_base_item(cell),
                "bounds": (
                    float(row["lat_min"]), float(row["lon_min"]),
                    float(row["lat_max"]), float(row["lon_max"]),
                ),
                "polygon": [
                    [tuple(point) for point in ring] for ring in json.loads(row["polygon"])
                ],
                "road_name": cell.road_name, "road_names": list(names) or None,
                "road_type": cell.road_type, "lanes": cell.lanes,
                "road_length_m": cell.road_length_m, "area_m2": cell.area_m2,
                "subdivided": cell.subdivided,
            }
        )
    return cells, items


def _base_item(cell: GapCell) -> dict[str, Any]:
    return {
        "cell_id": cell.cell_id, "unit_id": cell.unit_id, "unit_name": cell.unit_name,
        "lat": cell.lat, "lon": cell.lon, "poi_count": cell.poi_count,
        "poi_weighted": cell.poi_weighted, "flow_vph": cell.flow_vph,
        "rent_kvnd_m2_month": cell.rent_kvnd_m2_month,
    }


class GapAnalysisService:
    """Read-only; the snapshot is immutable and loaded once on first use."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory or _DEFAULT_DIRECTORY
        self._lock = Lock()
        self._bundle: dict[str, Any] | None = None

    def snapshot(self, division: GapDivision = "route") -> GapSnapshotResponse:
        bundle = self._load()
        return GapSnapshotResponse.model_validate(
            {
                "snapshot_id": GAP_SNAPSHOT_ID,
                "division": division,
                "prepared_on": bundle["prepared_on"],
                "data_labels": bundle["data_labels"],
                "defaults": bundle["defaults"],
                "cells": bundle["divisions"][division]["items"],
                "roads": bundle["roads"],
                "stations": bundle["station_items"],
                "station_summary": bundle["station_summary"],
            }
        )

    def run(self, request: GapRunRequest) -> GapRunResponse:
        bundle = self._load()
        if request.snapshot_id not in {None, GAP_SNAPSHOT_ID}:
            raise PlanningDataError(f"Gap snapshot '{request.snapshot_id}' is not available.")
        division = bundle["divisions"][request.division]
        params = GapParams(
            w_flow=request.w_flow, lambda_m=request.lambda_m, normalization=request.normalization,
            rent_mode=request.rent_mode, rent_max_kvnd=request.rent_max_kvnd,
            epsilon=request.epsilon, own_min_distance_m=request.own_min_distance_m,
            own_mode=request.own_mode, top_n=request.top_n,
            min_separation_m=request.min_separation_m, supply_basis=request.supply_basis,
            reference_power_kw=request.reference_power_kw, min_demand=request.min_demand,
        )
        result = run_gap_analysis(
            division["cells"], bundle["stations"], params, distances=division["distances"],
            with_sensitivity=request.with_sensitivity,
        )
        warnings = list(bundle["warnings"])
        if request.rent_mode == "none":
            warnings.append("Bước điều chỉnh giá thuê đang tắt: Điểm = Gap.")
        if result["summary"]["rent_missing_cell_count"]:
            warnings.append("Một số đơn vị thiếu giá thuê nên bỏ qua bước điều chỉnh giá thuê.")
        if not result["candidates"]:
            warnings.append(
                f"Không có {_DIVISION_LABELS[request.division]} nào đủ điều kiện với tham số này."
            )
        return GapRunResponse(
            snapshot_id=GAP_SNAPSHOT_ID,
            params=request,
            cells=result["cells"],
            candidates=result["candidates"],
            summary=result["summary"],
            warnings=warnings,
        )

    def _load(self) -> dict[str, Any]:
        if self._bundle is not None:
            return self._bundle
        with self._lock:
            if self._bundle is None:
                self._bundle = self._read_snapshot()
        return self._bundle

    def _read_snapshot(self) -> dict[str, Any]:
        manifest_path = self._directory / "manifest.json"
        if not manifest_path.is_file():
            raise PlanningDataError("The gap snapshot is not generated yet (missing manifest).")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("snapshot_id") != GAP_SNAPSHOT_ID:
            raise PlanningDataError("The gap directory does not contain the pinned snapshot.")
        for name in _REQUIRED_FILES:
            path = self._directory / name
            if not path.is_file():
                raise PlanningDataError(f"Gap snapshot file is missing: {name}.")
            if manifest.get("files", {}).get(name) != _sha256(path):
                raise PlanningDataError(f"Gap snapshot file does not match its manifest: {name}.")

        station_rows = _read_csv(self._directory / "gap_stations.csv")
        port_rows = _read_csv(self._directory / "gap_station_ports.csv")
        stations = [
            GapStation(
                station_id=row["station_id"], operator_id=row["operator_id"],
                operator_name=row["operator_name"], relationship=row["relationship"],
                unit_id=row["unit_id"], unit_name=row["unit_name"],
                lat=float(row["lat"]), lon=float(row["lon"]), site_type=row["site_type"],
                opening_hours=row["opening_hours"], port_count=int(row["port_count"]),
                dc_port_count=int(row["dc_port_count"]), ac_port_count=int(row["ac_port_count"]),
                total_power_kw=float(row["total_power_kw"]),
                max_port_power_kw=float(row["max_port_power_kw"]),
            )
            for row in station_rows
        ]
        if not stations:
            raise PlanningDataError("The gap snapshot has no stations.")
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in port_rows:
            groups.setdefault(row["station_id"], []).append(
                {
                    "charger_type": row["charger_type"], "connector_type": row["connector_type"],
                    "port_count": int(row["port_count"]),
                    "power_kw_per_port": float(row["power_kw_per_port"]),
                }
            )
        for station in stations:
            declared = sum(group["port_count"] for group in groups.get(station.station_id, []))
            if declared != station.port_count:
                raise PlanningDataError(
                    f"Port groups of {station.station_id} do not add up to its port count."
                )
        station_items = [
            {
                **{key: getattr(station, key) for key in (
                    "station_id", "operator_id", "operator_name", "relationship", "unit_id",
                    "unit_name", "lat", "lon", "site_type", "opening_hours", "port_count",
                    "dc_port_count", "ac_port_count", "total_power_kw", "max_port_power_kw")},
                "port_groups": groups.get(station.station_id, []),
            }
            for station in stations
        ]

        divisions: dict[str, dict[str, Any]] = {}
        for name, filename, loader in (
            ("grid", "grid_cells.csv", _grid_units),
            ("route", "route_blocks.csv", _route_units),
        ):
            cells, items = loader(_read_csv(self._directory / filename))
            if not cells:
                raise PlanningDataError(f"The gap snapshot has no units in {filename}.")
            divisions[name] = {
                "cells": cells, "items": items, "distances": distance_matrix(cells, stations),
            }
        roads = [
            {
                "road_id": row["road_id"], "name": row["road_name"], "road_type": row["road_type"],
                "lanes": _optional_int(row["lanes"]), "length_m": float(row["length_m"]),
                "flow_vph": float(row["flow_vph"]),
                "coordinates": [tuple(point) for point in json.loads(row["coordinates"])],
            }
            for row in _read_csv(self._directory / "route_roads.csv")
        ]
        if not roads:
            raise PlanningDataError("The gap snapshot has no road flows (route_roads.csv).")
        return {
            "stations": stations,
            "station_items": station_items,
            "roads": roads,
            "divisions": divisions,
            "prepared_on": manifest["prepared_on"],
            "data_labels": manifest["data_labels"],
            "defaults": json.loads((self._directory / "analysis_defaults.json").read_text("utf-8")),
            "station_summary": json.loads(
                (self._directory / "station_summary.json").read_text("utf-8")
            ),
            "warnings": [
                "Lưu lượng xe, giá thuê và danh sách trạm (của mình và đối thủ) là dữ liệu mô "
                "phỏng; POI lấy từ dữ liệu đã thu thập.",
                "Pháp lý của mọi đơn vị là chưa xác minh.",
            ],
        }
