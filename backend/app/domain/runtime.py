"""In-memory, resettable demo state for events and planned-arrival lifecycle."""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from uuid import uuid4

from backend.app.domain.models import PlannedArrival, StationStatus
from backend.app.domain.phase7_models import DemoEvent, PlannedArrivalCreateRequest
from backend.app.domain.repositories import (
    DemoEventRepository,
    PlannedArrivalRepository,
    StationStatusRepository,
)


class RuntimeStateStore:
    def __init__(
        self,
        statuses: StationStatusRepository,
        events: DemoEventRepository,
    ) -> None:
        self._base = {status.station_id: status for status in statuses.all()}
        self._events = events
        self._active_event_ids: list[str] = []
        self._statuses = dict(self._base)
        self._lock = RLock()

    def all(self) -> tuple[StationStatus, ...]:
        with self._lock:
            return tuple(self._statuses.values())

    def get(self, station_id: str) -> StationStatus:
        with self._lock:
            return self._statuses[station_id]

    def active_event_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._active_event_ids)

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
        with self._lock:
            if event_id is None:
                self._active_event_ids.clear()
            else:
                self._active_event_ids = [
                    active for active in self._active_event_ids if active != event_id
                ]
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
        offline_ports = min(
            status.total_ports,
            max(0, status.offline_ports + event.effects.offline_ports_delta),
        )
        operational_ports = status.total_ports - offline_ports
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

    def register(
        self,
        request: PlannedArrivalCreateRequest,
        *,
        created_at: datetime,
    ) -> PlannedArrival:
        arrival_id = request.arrival_id or f"ARR_{uuid4().hex[:12].upper()}"
        with self._lock:
            if arrival_id in self._arrivals:
                raise ValueError(f"arrival_id already exists: {arrival_id}")
            arrival = PlannedArrival(
                arrival_id=arrival_id,
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
            updated = arrival.model_copy(update={"status": "cancelled"})
            self._arrivals[arrival_id] = updated
            return updated

    def mark_arrived(self, arrival_id: str) -> PlannedArrival:
        with self._lock:
            arrival = self._arrivals[arrival_id]
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
