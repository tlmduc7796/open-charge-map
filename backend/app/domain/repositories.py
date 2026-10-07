"""File-backed repositories with fail-fast schema and cross-file validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from backend.app.domain.models import (
    PlannedArrival,
    QueueAssumptions,
    Station,
    StationCollection,
    StationStatus,
    Vehicle,
)
from backend.app.domain.phase7_models import DemoEvent, DemoScenario, RouteRecord


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


class PlannedArrivalRepository:
    def __init__(self, arrivals: tuple[PlannedArrival, ...]) -> None:
        self._arrivals = arrivals
        arrival_ids = [arrival.arrival_id for arrival in arrivals]
        if len(arrival_ids) != len(set(arrival_ids)):
            raise ValueError("planned arrivals must have unique arrival_id")

    @classmethod
    def from_file(cls, path: Path) -> PlannedArrivalRepository:
        arrivals = TypeAdapter(tuple[PlannedArrival, ...]).validate_python(_read_json(path))
        return cls(arrivals)

    def all(self) -> tuple[PlannedArrival, ...]:
        return self._arrivals


class QueueAssumptionsRepository:
    def __init__(self, assumptions: QueueAssumptions) -> None:
        self.assumptions = assumptions
        self._station_rates = {
            rate.station_id: rate.baseline_arrival_rate_per_hour
            for rate in assumptions.station_rates
        }
        self._scenario_overrides = {
            (override.scenario_id, override.station_id): (
                override.baseline_arrival_rate_per_hour
            )
            for override in assumptions.scenario_overrides
        }

    @classmethod
    def from_file(cls, path: Path) -> QueueAssumptionsRepository:
        return cls(QueueAssumptions.model_validate(_read_json(path)))

    def baseline_rate(self, station_id: str, scenario_id: str | None = None) -> float:
        if scenario_id is not None:
            override = self._scenario_overrides.get((scenario_id, station_id))
            if override is not None:
                return override
        return self._station_rates[station_id]

    def has_override(self, scenario_id: str, station_id: str) -> bool:
        return (scenario_id, station_id) in self._scenario_overrides


class RouteRepository:
    def __init__(self, routes: tuple[RouteRecord, ...]) -> None:
        self._routes = routes
        self._by_id = {route.route_id: route for route in routes}
        if len(self._by_id) != len(routes):
            raise ValueError("routes must have unique route_id")

    @classmethod
    def from_directory(cls, path: Path) -> RouteRepository:
        routes = tuple(
            RouteRecord.model_validate(_read_json(route_path))
            for route_path in sorted(path.glob("*.json"))
        )
        if not routes:
            raise ValueError("at least one route cache is required")
        return cls(routes)

    def all(self) -> tuple[RouteRecord, ...]:
        return self._routes

    def get(self, route_id: str) -> RouteRecord:
        return self._by_id[route_id]

    def find_by_station(self, station_id: str) -> RouteRecord | None:
        return next(
            (
                route
                for route in self._routes
                if any(waypoint.station_id == station_id for waypoint in route.waypoints)
            ),
            None,
        )


class DemoEventRepository:
    def __init__(self, events: tuple[DemoEvent, ...]) -> None:
        self._events = events
        self._by_id = {event.event_id: event for event in events}
        if len(self._by_id) != len(events):
            raise ValueError("demo events must have unique event_id")

    @classmethod
    def from_file(cls, path: Path) -> DemoEventRepository:
        events = TypeAdapter(tuple[DemoEvent, ...]).validate_python(_read_json(path))
        return cls(events)

    def all(self) -> tuple[DemoEvent, ...]:
        return self._events

    def get(self, event_id: str) -> DemoEvent:
        return self._by_id[event_id]


class DemoScenarioRepository:
    def __init__(self, scenarios: tuple[DemoScenario, ...]) -> None:
        self._scenarios = scenarios
        self._by_id = {scenario.scenario_id: scenario for scenario in scenarios}
        if len(self._by_id) != len(scenarios):
            raise ValueError("demo scenarios must have unique scenario_id")

    @classmethod
    def from_file(cls, path: Path) -> DemoScenarioRepository:
        scenarios = TypeAdapter(tuple[DemoScenario, ...]).validate_python(_read_json(path))
        return cls(scenarios)

    def all(self) -> tuple[DemoScenario, ...]:
        return self._scenarios

    def get(self, scenario_id: str) -> DemoScenario:
        return self._by_id[scenario_id]


@dataclass(frozen=True)
class DomainData:
    stations: StationRepository
    vehicles: VehicleRepository
    station_statuses: StationStatusRepository
    planned_arrivals: PlannedArrivalRepository
    queue_assumptions: QueueAssumptionsRepository
    routes: RouteRepository
    demo_events: DemoEventRepository
    demo_scenarios: DemoScenarioRepository


def load_domain_data(data_dir: Path) -> DomainData:
    """Load Phase 05 inputs and reject inconsistent station coverage/capacity."""
    stations = StationRepository.from_file(data_dir / "static" / "stations.geojson")
    vehicles = VehicleRepository.from_file(data_dir / "demo" / "vehicles.json")
    statuses = StationStatusRepository.from_file(
        data_dir / "runtime" / "station_status.json"
    )
    planned_arrivals = PlannedArrivalRepository.from_file(
        data_dir / "runtime" / "planned_arrivals.json"
    )
    queue_assumptions = QueueAssumptionsRepository.from_file(
        data_dir / "demo" / "queue_assumptions.json"
    )
    routes = RouteRepository.from_directory(data_dir / "routes")
    demo_events = DemoEventRepository.from_file(data_dir / "demo" / "demo_events.json")
    demo_scenarios = DemoScenarioRepository.from_file(
        data_dir / "demo" / "demo_scenarios.json"
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

    invalid_override_stations = sorted(
        {
            override.station_id
            for override in queue_assumptions.assumptions.scenario_overrides
            if override.station_id not in station_ids
        }
    )
    if invalid_override_stations:
        raise ValueError(
            f"queue overrides reference unknown stations: {invalid_override_stations}"
        )

    invalid_arrival_stations = sorted(
        {
            arrival.station_id
            for arrival in planned_arrivals.all()
            if arrival.station_id not in station_ids
        }
    )
    if invalid_arrival_stations:
        raise ValueError(
            f"planned arrivals reference unknown stations: {invalid_arrival_stations}"
        )

    invalid_arrival_vehicles = sorted(
        {
            arrival.vehicle_id
            for arrival in planned_arrivals.all()
            if arrival.vehicle_id is not None
            and arrival.vehicle_id not in {vehicle.vehicle_id for vehicle in vehicles.all()}
        }
    )
    if invalid_arrival_vehicles:
        raise ValueError(
            f"planned arrivals reference unknown vehicles: {invalid_arrival_vehicles}"
        )

    invalid_route_stations = sorted(
        {
            waypoint.station_id
            for route in routes.all()
            for waypoint in route.waypoints
            if waypoint.station_id is not None and waypoint.station_id not in station_ids
        }
    )
    if invalid_route_stations:
        raise ValueError(f"routes reference unknown stations: {invalid_route_stations}")

    event_ids = {event.event_id for event in demo_events.all()}
    route_ids = {route.route_id for route in routes.all()}
    vehicle_ids = {vehicle.vehicle_id for vehicle in vehicles.all()}
    invalid_event_stations = sorted(
        {
            event.station_id
            for event in demo_events.all()
            if event.station_id not in station_ids
        }
    )
    if invalid_event_stations:
        raise ValueError(
            f"demo events reference unknown stations: {invalid_event_stations}"
        )
    for scenario in demo_scenarios.all():
        if scenario.vehicle_id not in vehicle_ids:
            raise ValueError(f"scenario references unknown vehicle: {scenario.vehicle_id}")
        unknown_events = sorted(set(scenario.event_ids) - event_ids)
        unknown_routes = sorted(set(scenario.route_ids) - route_ids)
        if unknown_events or unknown_routes:
            raise ValueError(
                f"scenario {scenario.scenario_id} references unknown data: "
                f"events={unknown_events}, routes={unknown_routes}"
            )

    return DomainData(
        stations=stations,
        vehicles=vehicles,
        station_statuses=statuses,
        planned_arrivals=planned_arrivals,
        queue_assumptions=queue_assumptions,
        routes=routes,
        demo_events=demo_events,
        demo_scenarios=demo_scenarios,
    )
