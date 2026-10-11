"""File-backed repositories with fail-fast schema and cross-file validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from backend.app.domain.models import (
    QueueAssumptions,
    Station,
    StationCollection,
    StationStatus,
    Vehicle,
)


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


class StationRepository:
    def __init__(self, stations: tuple[Station, ...]) -> None:
        self._stations = stations
        self._by_id = {station.station_id: station for station in stations}

    @classmethod
    def from_file(cls, path: Path) -> StationRepository:
        collection = StationCollection.model_validate(_read_json(path))
        return cls(collection.features)

    def all(self) -> tuple[Station, ...]:
        return self._stations

    def get(self, station_id: str) -> Station:
        return self._by_id[station_id]

    def within_bbox(
        self, min_lon: float, min_lat: float, max_lon: float, max_lat: float
    ) -> tuple[Station, ...]:
        return tuple(
            station
            for station in self._stations
            if min_lon <= station.geometry.coordinates[0] <= max_lon
            and min_lat <= station.geometry.coordinates[1] <= max_lat
        )

    def nearby(
        self, longitude: float, latitude: float, radius_m: float
    ) -> tuple[Station, ...]:
        from backend.app.domain.routing import _haversine_m

        return tuple(
            station
            for station in self._stations
            if _haversine_m(
                latitude,
                longitude,
                station.geometry.coordinates[1],
                station.geometry.coordinates[0],
            )
            <= radius_m
        )

    def candidates(
        self,
        origin_lon: float,
        origin_lat: float,
        destination_lon: float,
        destination_lat: float,
        corridor_m: float,
    ) -> tuple[Station, ...]:
        """Keep fixture mode deterministic while matching the database repository API."""
        return self._stations


class VehicleRepository:
    def __init__(self, vehicles: tuple[Vehicle, ...]) -> None:
        self._vehicles = vehicles
        self._by_id = {vehicle.vehicle_id: vehicle for vehicle in vehicles}
        if len(self._by_id) != len(vehicles):
            raise ValueError("vehicle_id values must be unique")

    @classmethod
    def from_file(cls, path: Path) -> VehicleRepository:
        vehicles = TypeAdapter(tuple[Vehicle, ...]).validate_python(_read_json(path))
        return cls(vehicles)

    def all(self) -> tuple[Vehicle, ...]:
        return self._vehicles

    def get(self, vehicle_id: str) -> Vehicle:
        return self._by_id[vehicle_id]


class StationStatusRepository:
    def __init__(self, statuses: tuple[StationStatus, ...]) -> None:
        self._statuses = statuses
        self._by_id = {status.station_id: status for status in statuses}
        if len(self._by_id) != len(statuses):
            raise ValueError("station status values must have unique station_id")

    @classmethod
    def from_file(cls, path: Path) -> StationStatusRepository:
        statuses = TypeAdapter(tuple[StationStatus, ...]).validate_python(_read_json(path))
        return cls(statuses)

    def all(self) -> tuple[StationStatus, ...]:
        return self._statuses

    def get(self, station_id: str) -> StationStatus:
        return self._by_id[station_id]


class QueueAssumptionsRepository:
    def __init__(self, assumptions: QueueAssumptions) -> None:
        self.assumptions = assumptions
        self._station_rates = {
            rate.station_id: rate.baseline_arrival_rate_per_hour
            for rate in assumptions.station_rates
        }

    @classmethod
    def from_file(cls, path: Path) -> QueueAssumptionsRepository:
        return cls(QueueAssumptions.model_validate(_read_json(path)))

    def baseline_rate(self, station_id: str) -> float:
        return self._station_rates[station_id]

    def baseline_source(self, station_id: str) -> str:
        self.baseline_rate(station_id)
        return self.assumptions.data_source


@dataclass(frozen=True)
class DomainData:
    stations: StationRepository
    vehicles: VehicleRepository
    station_statuses: StationStatusRepository
    queue_assumptions: QueueAssumptionsRepository


def load_domain_data(data_dir: Path) -> DomainData:
    """Load the file-backed catalog and reject inconsistent station coverage/capacity."""
    stations = StationRepository.from_file(data_dir / "static" / "stations.geojson")
    vehicles = VehicleRepository.from_file(data_dir / "demo" / "vehicles.json")
    statuses = StationStatusRepository.from_file(
        data_dir / "runtime" / "station_status.json"
    )
    queue_assumptions = QueueAssumptionsRepository.from_file(
        data_dir / "demo" / "queue_assumptions.json"
    )

    station_ids = {station.station_id for station in stations.all()}
    status_ids = {status.station_id for status in statuses.all()}
    if station_ids != status_ids:
        missing = sorted(station_ids - status_ids)
        unknown = sorted(status_ids - station_ids)
        raise ValueError(
            f"station status coverage mismatch: missing={missing}, unknown={unknown}"
        )

    for station in stations.all():
        status = statuses.get(station.station_id)
        if station.properties.total_ports != status.total_ports:
            raise ValueError(f"total_ports mismatch for station {station.station_id}")

    queue_station_ids = {
        rate.station_id for rate in queue_assumptions.assumptions.station_rates
    }
    if queue_station_ids != station_ids:
        missing = sorted(station_ids - queue_station_ids)
        unknown = sorted(queue_station_ids - station_ids)
        raise ValueError(
            f"queue assumption coverage mismatch: missing={missing}, unknown={unknown}"
        )

    return DomainData(
        stations=stations,
        vehicles=vehicles,
        station_statuses=statuses,
        queue_assumptions=queue_assumptions,
    )
