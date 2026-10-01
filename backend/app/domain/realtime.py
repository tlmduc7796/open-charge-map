"""Telemetry contracts and deterministic discrete-event wait simulation.

This module deliberately does not turn an app user's intent into a confirmed
arrival.  ``PlannedArrival`` remains the probabilistic input for the aggregate
queue estimator.  DES is enabled only for an observed station snapshot with
per-port state and resolvable session durations.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock
from typing import Literal, Protocol

from pydantic import Field, model_validator

from backend.app.domain.models import DomainModel


class ChargingPortTelemetry(DomainModel):
    """One physical port at the instant a station provider observed it."""

    port_id: str = Field(min_length=1)
    connector_types: tuple[str, ...] = Field(min_length=1)
    state: Literal["available", "charging", "offline"]
    session_id: str | None = None
    reported_remaining_port_release_min: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_session_state(self) -> ChargingPortTelemetry:
        if self.state == "charging" and not self.session_id:
            raise ValueError("a charging port requires session_id")
        if self.state != "charging" and (
            self.session_id is not None or self.reported_remaining_port_release_min is not None
        ):
            raise ValueError("only a charging port may carry session duration data")
        return self


class QueueVehicleTelemetry(DomainModel):
    """A vehicle physically confirmed in the station's queue.

    Future app intents do not belong here.  They remain probabilistic planned
    arrivals until a station/camera observation confirms presence.
    """

    queue_id: str = Field(min_length=1)
    queue_position: int = Field(gt=0)
    entered_queue_at: datetime
    compatible_connector_types: tuple[str, ...] = Field(min_length=1)
    expected_charge_duration_min: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_entered_queue_at(self) -> QueueVehicleTelemetry:
        if self.entered_queue_at.tzinfo is None:
            raise ValueError("entered_queue_at requires timezone")
        return self


class StationTelemetrySnapshot(DomainModel):
    """Validated state that can be fed by a simulator or a station adapter."""

    station_id: str = Field(min_length=1)
    observed_at: datetime
    ports: tuple[ChargingPortTelemetry, ...] = Field(min_length=1)
    queue: tuple[QueueVehicleTelemetry, ...] = ()
    data_source: Literal["simulated", "station_api", "camera_vision", "combined"]

    @model_validator(mode="after")
    def validate_snapshot(self) -> StationTelemetrySnapshot:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at requires timezone")
        port_ids = [port.port_id for port in self.ports]
        queue_positions = [vehicle.queue_position for vehicle in self.queue]
        queue_ids = [vehicle.queue_id for vehicle in self.queue]
        if len(port_ids) != len(set(port_ids)):
            raise ValueError("port_id values must be unique per snapshot")
        if len(queue_positions) != len(set(queue_positions)):
            raise ValueError("queue_position values must be unique per snapshot")
        if len(queue_ids) != len(set(queue_ids)):
            raise ValueError("queue_id values must be unique per snapshot")
        return self


class ResidualDurationPredictor(Protocol):
    """Future ML/DL adapter: estimates remaining minutes until port release."""

    def predict_remaining_port_release_min(self, port: ChargingPortTelemetry) -> float:
        """Return a strictly positive remaining duration until the EV unplugs."""


class ResidualDurationService:
    """Prefer provider port-release telemetry; use an approved RDM only when it exists."""

    def __init__(self, predictor: ResidualDurationPredictor | None = None) -> None:
        self._predictor = predictor

    def resolve(self, port: ChargingPortTelemetry) -> tuple[float, str]:
        if port.state != "charging":
            raise ValueError("only charging ports have a residual duration")
        if port.reported_remaining_port_release_min is not None:
            return port.reported_remaining_port_release_min, "PROVIDER_REPORTED_PORT_RELEASE"
        if self._predictor is None:
            raise ValueError(
                "charging port has no reported duration and no approved residual-duration model"
            )
        duration = self._predictor.predict_remaining_port_release_min(port)
        if duration <= 0:
            raise ValueError("residual-duration model returned a non-positive duration")
        return duration, "PORT_RELEASE_DURATION_MODEL"


class DESWaitRequest(DomainModel):
    evaluation_at: datetime
    compatible_connector_types: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evaluation_at(self) -> DESWaitRequest:
        if self.evaluation_at.tzinfo is None:
            raise ValueError("evaluation_at requires timezone")
        return self


class DESWaitResult(DomainModel):
    station_id: str
    evaluation_at: datetime
    snapshot_observed_at: datetime
    method: Literal["discrete_event_simulation"] = "discrete_event_simulation"
    operational_ports: int = Field(ge=0)
    confirmed_queue_length: int = Field(ge=0)
    estimated_wait_min: float | None = Field(default=None, ge=0)
    predicted_charge_start_at: datetime | None = None
    duration_sources: tuple[str, ...]
    flags: tuple[str, ...]


class DiscreteEventWaitSimulator:
    """Schedules physical ports and confirmed queue entries without randomness."""

    def __init__(self, durations: ResidualDurationService) -> None:
        self._durations = durations

    def estimate(
        self,
        snapshot: StationTelemetrySnapshot,
        request: DESWaitRequest,
    ) -> DESWaitResult:
        if request.evaluation_at < snapshot.observed_at:
            raise ValueError("evaluation_at cannot precede the telemetry snapshot")

        duration_sources: list[str] = []
        slots: list[tuple[datetime, ChargingPortTelemetry]] = []
        for port in snapshot.ports:
            if port.state == "offline":
                continue
            if port.state == "available":
                slots.append((request.evaluation_at, port))
                continue
            duration, source = self._durations.resolve(port)
            duration_sources.append(source)
            free_at = max(
                request.evaluation_at,
                snapshot.observed_at + timedelta(minutes=duration),
            )
            slots.append((free_at, port))

        flags = ["CONFIRMED_QUEUE_ONLY", "UNOBSERVED_ARRIVALS_EXCLUDED"]
        if request.evaluation_at > snapshot.observed_at:
            flags.append("SNAPSHOT_ADVANCED_WITHOUT_NEW_TELEMETRY")
        if not slots:
            return DESWaitResult(
                station_id=snapshot.station_id,
                evaluation_at=request.evaluation_at,
                snapshot_observed_at=snapshot.observed_at,
                operational_ports=0,
                confirmed_queue_length=len(snapshot.queue),
                estimated_wait_min=None,
                predicted_charge_start_at=None,
                duration_sources=tuple(dict.fromkeys(duration_sources)),
                flags=tuple([*flags, "NO_OPERATIONAL_PORTS"]),
            )

        for vehicle in sorted(snapshot.queue, key=lambda entry: entry.queue_position):
            index = self._earliest_compatible_slot(
                slots, vehicle.compatible_connector_types
            )
            if index is None:
                return self._incompatible_result(
                    snapshot, request, duration_sources, flags, "QUEUE_CONNECTOR_UNSUPPORTED"
                )
            free_at, port = slots[index]
            slots[index] = (
                free_at + timedelta(minutes=vehicle.expected_charge_duration_min),
                port,
            )
            duration_sources.append("QUEUE_DURATION_ESTIMATE")

        index = self._earliest_compatible_slot(slots, request.compatible_connector_types)
        if index is None:
            return self._incompatible_result(
                snapshot, request, duration_sources, flags, "REQUESTED_CONNECTOR_UNSUPPORTED"
            )
        start_at, _ = slots[index]
        return DESWaitResult(
            station_id=snapshot.station_id,
            evaluation_at=request.evaluation_at,
            snapshot_observed_at=snapshot.observed_at,
            operational_ports=len(slots),
            confirmed_queue_length=len(snapshot.queue),
            estimated_wait_min=max(
                0.0, (start_at - request.evaluation_at).total_seconds() / 60
            ),
            predicted_charge_start_at=start_at,
            duration_sources=tuple(dict.fromkeys(duration_sources)),
            flags=tuple(flags),
        )

    @staticmethod
    def _earliest_compatible_slot(
        slots: list[tuple[datetime, ChargingPortTelemetry]], connector_types: tuple[str, ...]
    ) -> int | None:
        eligible = [
            (free_at, port.port_id, index)
            for index, (free_at, port) in enumerate(slots)
            if set(port.connector_types).intersection(connector_types)
        ]
        return min(eligible)[2] if eligible else None

    @staticmethod
    def _incompatible_result(
        snapshot: StationTelemetrySnapshot,
        request: DESWaitRequest,
        duration_sources: list[str],
        flags: list[str],
        reason: str,
    ) -> DESWaitResult:
        return DESWaitResult(
            station_id=snapshot.station_id,
            evaluation_at=request.evaluation_at,
            snapshot_observed_at=snapshot.observed_at,
            operational_ports=sum(port.state != "offline" for port in snapshot.ports),
            confirmed_queue_length=len(snapshot.queue),
            estimated_wait_min=None,
            predicted_charge_start_at=None,
            duration_sources=tuple(dict.fromkeys(duration_sources)),
            flags=tuple([*flags, reason]),
        )


class RealtimeTelemetryStore:
    """Small resettable adapter boundary for the simulator and future ingestion."""

    def __init__(self) -> None:
        self._snapshots: dict[str, StationTelemetrySnapshot] = {}
        self._lock = RLock()

    def upsert(self, snapshot: StationTelemetrySnapshot) -> StationTelemetrySnapshot:
        with self._lock:
            previous = self._snapshots.get(snapshot.station_id)
            if previous is not None and snapshot.observed_at < previous.observed_at:
                raise ValueError("telemetry snapshot is older than the stored snapshot")
            self._snapshots[snapshot.station_id] = snapshot
            return snapshot

    def get(self, station_id: str) -> StationTelemetrySnapshot:
        with self._lock:
            return self._snapshots[station_id]

    def reset(self) -> None:
        with self._lock:
            self._snapshots.clear()
