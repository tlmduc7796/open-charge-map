"""In-memory, resettable demo state for events and planned-arrival lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from backend.app.domain.models import PlannedArrival, PortRuntimeStatus, StationStatus
from backend.app.domain.numeric import database_numeric_values_match
from backend.app.domain.phase7_models import DemoEvent, PlannedArrivalCreateRequest
from backend.app.domain.realtime import StationTelemetrySnapshot
from backend.app.domain.repositories import (
    DemoEventRepository,
    PlannedArrivalRepository,
    StationStatusRepository,
)


class TelemetrySnapshotReader(Protocol):
    def get(self, station_id: str) -> StationTelemetrySnapshot: ...

    def all(self) -> tuple[StationTelemetrySnapshot, ...]: ...

    def get_many(self, station_ids: tuple[str, ...]) -> tuple[StationTelemetrySnapshot, ...]: ...


def planned_arrival_matches_request(
    arrival: PlannedArrival, request: PlannedArrivalCreateRequest
) -> bool:
    return (
        arrival.journey_id
        == (str(request.journey_id) if request.journey_id is not None else None)
        and arrival.station_id == request.station_id
        and arrival.vehicle_id == request.vehicle_id
        and arrival.eta_at == request.eta_at
        and arrival.eta_window_start == request.eta_window_start
        and arrival.eta_window_end == request.eta_window_end
        and database_numeric_values_match(
            arrival.expected_energy_kwh,
            request.expected_energy_kwh,
            decimal_places=3,
        )
        and database_numeric_values_match(
            arrival.expected_charge_duration_min,
            request.expected_charge_duration_min,
            decimal_places=3,
        )
        and database_numeric_values_match(
            arrival.arrival_probability,
            request.arrival_probability,
            decimal_places=6,
        )
        and arrival.expires_at == request.expires_at
        and arrival.route_id == request.route_id
    )


class RuntimeStateStore:
    def __init__(
        self,
        statuses: StationStatusRepository,
        events: DemoEventRepository,
        *,
        telemetry: TelemetrySnapshotReader | None = None,
        telemetry_max_age_s: float = 300,
        enforce_freshness: bool = True,
    ) -> None:
        if telemetry_max_age_s <= 0:
            raise ValueError("telemetry maximum age must be positive")
        self._status_repository = statuses
        self._telemetry = telemetry
        self._telemetry_max_age_s = telemetry_max_age_s
        self._enforce_freshness = enforce_freshness
        self._base = {status.station_id: status for status in statuses.all()}
        self._events = events
        self._active_event_ids: list[str] = []
        self._statuses = dict(self._base)
        self._lock = RLock()

    def all(self) -> tuple[StationStatus, ...]:
        with self._lock:
            statuses = dict(self._statuses)
        if self._telemetry is None:
            return tuple(self._with_staleness(status) for status in statuses.values())
        now = datetime.now(UTC)
        for snapshot in self._telemetry.all():
            base_status = statuses.get(snapshot.station_id)
            if base_status is None:
                continue
            age_s = (now - snapshot.observed_at.astimezone(UTC)).total_seconds()
            if age_s < 0 or age_s > self._telemetry_max_age_s:
                continue
            statuses[snapshot.station_id] = self._snapshot_status(
                snapshot, base_status.total_ports
            )
        return tuple(self._with_staleness(status) for status in statuses.values())

    def get(self, station_id: str) -> StationStatus:
        with self._lock:
            base_status = self._statuses[station_id]
        if self._telemetry is None:
            return self._with_staleness(base_status)
        try:
            snapshot = self._telemetry.get(station_id)
        except KeyError:
            return self._with_staleness(base_status)
        age_s = (datetime.now(UTC) - snapshot.observed_at.astimezone(UTC)).total_seconds()
        if age_s < 0 or age_s > self._telemetry_max_age_s:
            return self._with_staleness(base_status)
        return self._snapshot_status(snapshot, base_status.total_ports)

    def get_many(self, station_ids: tuple[str, ...]) -> tuple[StationStatus, ...]:
        """Load and compose statuses for one bounded station set."""
        requested_ids = set(station_ids)
        status_reader = getattr(self._status_repository, "get_many", None)
        base_statuses = (
            status_reader(station_ids)
            if status_reader is not None
            else tuple(
                status for status in self._status_repository.all()
                if status.station_id in requested_ids
            )
        )
        statuses = {status.station_id: status for status in base_statuses}
        if self._telemetry is not None:
            snapshot_reader = getattr(self._telemetry, "get_many", None)
            snapshots = (
                snapshot_reader(station_ids)
                if snapshot_reader is not None
                else tuple(
                    snapshot for snapshot in self._telemetry.all()
                    if snapshot.station_id in requested_ids
                )
            )
            now = datetime.now(UTC)
            for snapshot in snapshots:
                base_status = statuses.get(snapshot.station_id)
                if base_status is None:
                    continue
                age_s = (now - snapshot.observed_at.astimezone(UTC)).total_seconds()
                if 0 <= age_s <= self._telemetry_max_age_s:
                    statuses[snapshot.station_id] = self._snapshot_status(
                        snapshot, base_status.total_ports
                    )
        return tuple(
            self._with_staleness(statuses[item])
            for item in station_ids
            if item in statuses
        )

    def _with_staleness(self, status: StationStatus) -> StationStatus:
        if not self._enforce_freshness:
            return status.model_copy(update={"is_stale": False})
        now = datetime.now(UTC)
        age_s = (now - status.timestamp.astimezone(UTC)).total_seconds()
        updates: dict[str, object] = {
            "is_stale": status.data_source == "simulated"
            or age_s < 0
            or age_s > self._telemetry_max_age_s
        }
        if status.port_runtime_statuses is not None:
            fresh_port_states = tuple(
                port.model_copy(update={"state": "unknown"})
                if port.observed_at is None
                or (port_age_s := (now - port.observed_at.astimezone(UTC)).total_seconds()) < 0
                or port_age_s > self._telemetry_max_age_s
                else port
                for port in status.port_runtime_statuses
            )
            updates["port_runtime_statuses"] = fresh_port_states
            operational = sum(
                port.state in {"available", "charging"} for port in fresh_port_states
            )
            occupied = sum(port.state == "charging" for port in fresh_port_states)
            offline = sum(
                port.state in {"offline", "out_of_service"}
                for port in fresh_port_states
            )
            unknown = sum(port.state == "unknown" for port in fresh_port_states)
            updates.update(
                {
                    "total_ports": len(fresh_port_states),
                    "operational_ports": operational,
                    "occupied_ports": occupied,
                    "available_ports": operational - occupied,
                    "offline_ports": offline,
                    "unknown_ports": unknown,
                    "occupancy_ratio": occupied / operational if operational else None,
                }
            )
        return status.model_copy(update=updates)

    def _snapshot_status(
        self, snapshot: StationTelemetrySnapshot, total_ports: int
    ) -> StationStatus:
        status = self._status_from_snapshot(snapshot, total_ports)
        if self._enforce_freshness and snapshot.data_source == "simulated":
            return status.model_copy(update={"is_stale": True})
        return status

    @staticmethod
    def _status_from_snapshot(
        snapshot: StationTelemetrySnapshot, total_ports: int
    ) -> StationStatus:
        if len(snapshot.ports) != total_ports:
            raise ValueError("telemetry snapshot must include every station port")
        operational_ports = sum(port.is_operational for port in snapshot.ports)
        occupied_ports = sum(port.state == "charging" for port in snapshot.ports)
        offline_ports = sum(port.is_out_of_service for port in snapshot.ports)
        unknown_ports = sum(port.state == "unknown" for port in snapshot.ports)
        available_ports = operational_ports - occupied_ports
        return StationStatus(
            station_id=snapshot.station_id,
            timestamp=snapshot.observed_at,
            total_ports=total_ports,
            operational_ports=operational_ports,
            occupied_ports=occupied_ports,
            available_ports=available_ports,
            offline_ports=offline_ports,
            unknown_ports=unknown_ports,
            occupancy_ratio=(
                occupied_ports / operational_ports if operational_ports else None
            ),
            queue_length=len(snapshot.queue) if snapshot.queue is not None else None,
            avg_session_duration_min=snapshot.avg_session_duration_min,
            data_source=snapshot.data_source,
            port_runtime_statuses=tuple(
                PortRuntimeStatus(
                    connector_types=port.connector_types,
                    state=port.state,
                    observed_at=snapshot.observed_at,
                )
                for port in snapshot.ports
            ),
            queue_connector_types=(
                tuple(
                    vehicle.compatible_connector_types
                    for vehicle in snapshot.queue
                )
                if snapshot.queue is not None
                else None
            ),
        )

    def active_event_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._active_event_ids)

    def refresh(self) -> None:
        """Reload persisted statuses and reapply in-memory demo overlays."""
        statuses = self._status_repository.all()
        with self._lock:
            self._base = {status.station_id: status for status in statuses}
            self._rebuild()

    def apply(self, event_id: str) -> StationStatus:
        with self._lock:
            event = self._events.get(event_id)
            if event_id not in self._active_event_ids:
                self._active_event_ids.append(event_id)
                self._statuses[event.station_id] = self._apply_effect(
                    self._statuses[event.station_id], event
                )
            return self._statuses[event.station_id]

    def reset(self, event_id: str | None = None) -> None:
        statuses = self._status_repository.all()
        with self._lock:
            if event_id is None:
                self._active_event_ids.clear()
            else:
                self._active_event_ids = [
                    active for active in self._active_event_ids if active != event_id
                ]
            self._base = {status.station_id: status for status in statuses}
            self._rebuild()

    def _rebuild(self) -> None:
        self._statuses = dict(self._base)
        for event_id in self._active_event_ids:
            event = self._events.get(event_id)
            self._statuses[event.station_id] = self._apply_effect(
                self._statuses[event.station_id], event
            )

    @staticmethod
    def _apply_effect(status: StationStatus, event: DemoEvent) -> StationStatus:
        if status.queue_length is None or status.avg_session_duration_min is None:
            raise ValueError("demo events require queue and session-duration telemetry")
        offline_ports = min(
            status.total_ports - status.unknown_ports,
            max(0, status.offline_ports + event.effects.offline_ports_delta),
        )
        operational_ports = status.total_ports - offline_ports - status.unknown_ports
        occupied_ports = min(
            operational_ports,
            max(0, status.occupied_ports + event.effects.occupied_ports_delta),
        )
        available_ports = operational_ports - occupied_ports
        queue_length = max(0, status.queue_length + event.effects.queue_length_delta)
        occupancy_ratio = (
            occupied_ports / operational_ports if operational_ports > 0 else None
        )
        return StationStatus(
            station_id=status.station_id,
            timestamp=event.start_at,
            total_ports=status.total_ports,
            operational_ports=operational_ports,
            occupied_ports=occupied_ports,
            available_ports=available_ports,
            offline_ports=offline_ports,
            unknown_ports=status.unknown_ports,
            occupancy_ratio=occupancy_ratio,
            queue_length=queue_length,
            avg_session_duration_min=status.avg_session_duration_min,
            data_source="runtime",
        )


class PlannedArrivalStore:
    def __init__(self, arrivals: PlannedArrivalRepository) -> None:
        self._base = {arrival.arrival_id: arrival for arrival in arrivals.all()}
        self._arrivals = dict(self._base)
        self._lock = RLock()

    def all(self) -> tuple[PlannedArrival, ...]:
        with self._lock:
            return tuple(self._arrivals.values())

    def get(self, arrival_id: str) -> PlannedArrival:
        with self._lock:
            return self._arrivals[arrival_id]

    def active_for_stations(
        self, station_ids: tuple[str, ...]
    ) -> tuple[PlannedArrival, ...]:
        station_id_set = set(station_ids)
        with self._lock:
            return tuple(
                arrival
                for arrival in self._arrivals.values()
                if arrival.status == "planned"
                and arrival.expires_at > datetime.now(UTC)
                and arrival.station_id in station_id_set
            )

    def active_for_journey(self, journey_id: str) -> PlannedArrival | None:
        now = datetime.now(UTC)
        with self._lock:
            matches = (
                arrival
                for arrival in self._arrivals.values()
                if arrival.journey_id == journey_id
                and arrival.status == "planned"
                and arrival.expires_at > now
            )
            return max(matches, key=lambda arrival: arrival.created_at, default=None)

    def register(
        self,
        request: PlannedArrivalCreateRequest,
        *,
        created_at: datetime,
    ) -> PlannedArrival:
        arrival_id = request.arrival_id
        with self._lock:
            if arrival_id in self._arrivals:
                existing = self._arrivals[arrival_id]
                if planned_arrival_matches_request(existing, request):
                    return existing
                raise ValueError(f"arrival_id already exists: {arrival_id}")
            arrival = PlannedArrival(
                arrival_id=arrival_id,
                journey_id=(str(request.journey_id) if request.journey_id else None),
                station_id=request.station_id,
                vehicle_id=request.vehicle_id,
                created_at=created_at,
                eta_at=request.eta_at,
                eta_window_start=request.eta_window_start,
                eta_window_end=request.eta_window_end,
                expected_energy_kwh=request.expected_energy_kwh,
                expected_charge_duration_min=request.expected_charge_duration_min,
                arrival_probability=request.arrival_probability,
                expires_at=request.expires_at,
                route_id=request.route_id,
                status="planned",
                data_source="runtime",
            )
            self._arrivals[arrival_id] = arrival
            return arrival

    def cancel(self, arrival_id: str) -> PlannedArrival:
        with self._lock:
            arrival = self._arrivals[arrival_id]
            if arrival.status == "cancelled":
                return arrival
            if arrival.status != "planned":
                raise ValueError(
                    f"planned arrival {arrival_id} cannot transition from {arrival.status}"
                )
            updated = arrival.model_copy(update={"status": "cancelled"})
            self._arrivals[arrival_id] = updated
            return updated

    def mark_arrived(self, arrival_id: str) -> PlannedArrival:
        with self._lock:
            arrival = self._arrivals[arrival_id]
            if arrival.status != "planned":
                raise ValueError(
                    f"planned arrival {arrival_id} cannot transition from {arrival.status}"
                )
            updated = arrival.model_copy(update={"status": "arrived"})
            self._arrivals[arrival_id] = updated
            return updated

    def expire(self, evaluation_at: datetime) -> tuple[PlannedArrival, ...]:
        expired: list[PlannedArrival] = []
        with self._lock:
            for arrival_id, arrival in tuple(self._arrivals.items()):
                if arrival.status == "planned" and arrival.expires_at <= evaluation_at:
                    updated = arrival.model_copy(update={"status": "expired"})
                    self._arrivals[arrival_id] = updated
                    expired.append(updated)
        return tuple(expired)

    def reset(self) -> None:
        with self._lock:
            self._arrivals = dict(self._base)
