"""Telemetry contracts and deterministic discrete-event wait simulation.

This module deliberately does not turn an app user's intent into a confirmed
arrival.  ``PlannedArrival`` remains the probabilistic input for the aggregate
queue estimator.  DES is enabled only for an observed station snapshot with
per-port state and resolvable session durations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from threading import RLock
from typing import Literal, Protocol

from pydantic import Field, model_validator

from backend.app.domain.models import DomainModel


def validate_observation_timestamp(
    observed_at: datetime,
    *,
    now: datetime,
    max_future_skew_s: float,
) -> None:
    """Reject timestamps that could poison monotonic telemetry or history."""
    if observed_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("observation timestamps require timezone")
    if not isfinite(max_future_skew_s) or max_future_skew_s <= 0:
        raise ValueError("maximum future clock skew must be positive")
    latest_accepted = now.astimezone(UTC) + timedelta(seconds=max_future_skew_s)
    if observed_at.astimezone(UTC) > latest_accepted:
        raise ValueError("observed_at is too far in the future")


class ChargingPortTelemetry(DomainModel):
    """One physical port at the instant a station provider observed it."""

    port_id: str = Field(min_length=1, max_length=128)
    connector_types: tuple[str, ...] = Field(min_length=1, max_length=16)
    state: Literal["available", "charging", "offline", "out_of_service", "unknown"]
    session_id: str | None = None
    reported_remaining_port_release_min: float | None = Field(default=None, gt=0)

    @property
    def is_operational(self) -> bool:
        return self.state in {"available", "charging"}

    @property
    def is_out_of_service(self) -> bool:
        return self.state in {"offline", "out_of_service"}

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

    queue_id: str = Field(min_length=1, max_length=128)
    queue_position: int = Field(gt=0)
    entered_queue_at: datetime
    compatible_connector_types: tuple[str, ...] = Field(min_length=1, max_length=16)
    expected_charge_duration_min: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_entered_queue_at(self) -> QueueVehicleTelemetry:
        if self.entered_queue_at.tzinfo is None:
            raise ValueError("entered_queue_at requires timezone")
        return self


class StationTelemetrySnapshot(DomainModel):
    """Validated state that can be fed by a simulator or a station adapter."""

    station_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime
    ports: tuple[ChargingPortTelemetry, ...] = Field(min_length=1, max_length=1000)
    queue: tuple[QueueVehicleTelemetry, ...] | None = Field(default=None, max_length=2000)
    avg_session_duration_min: float | None = Field(default=None, gt=0)
    data_source: Literal["simulated", "station_api", "camera_vision", "combined"]

    @model_validator(mode="after")
    def validate_snapshot(self) -> StationTelemetrySnapshot:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at requires timezone")
        port_ids = [port.port_id for port in self.ports]
        queue_positions = [vehicle.queue_position for vehicle in self.queue or ()]
        queue_ids = [vehicle.queue_id for vehicle in self.queue or ()]
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
    unknown_ports: int = Field(default=0, ge=0)
    confirmed_queue_length: int | None = Field(default=None, ge=0)
    estimated_wait_min: float | None = Field(default=None, ge=0)
    predicted_charge_start_at: datetime | None = None
    duration_sources: tuple[str, ...]
    flags: tuple[str, ...]

    @model_validator(mode="after")
    def validate_result_timestamps(self) -> DESWaitResult:
        timestamps = (
            self.evaluation_at,
            self.snapshot_observed_at,
            self.predicted_charge_start_at,
        )
        if any(timestamp is not None and timestamp.tzinfo is None for timestamp in timestamps):
            raise ValueError("wait result timestamps must include a timezone")
        return self


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

        unknown_ports = sum(port.state == "unknown" for port in snapshot.ports)
        unavailable_reasons = []
        if unknown_ports:
            unavailable_reasons.append("PORT_STATE_UNKNOWN")
        if snapshot.queue is None:
            unavailable_reasons.append("QUEUE_STATE_UNKNOWN")
        if unavailable_reasons:
            flags = ["CONFIRMED_QUEUE_ONLY", "UNOBSERVED_ARRIVALS_EXCLUDED"]
            if request.evaluation_at > snapshot.observed_at:
                flags.append("SNAPSHOT_ADVANCED_WITHOUT_NEW_TELEMETRY")
            return DESWaitResult(
                station_id=snapshot.station_id,
                evaluation_at=request.evaluation_at,
                snapshot_observed_at=snapshot.observed_at,
                operational_ports=sum(port.is_operational for port in snapshot.ports),
                unknown_ports=unknown_ports,
                confirmed_queue_length=(
                    len(snapshot.queue) if snapshot.queue is not None else None
                ),
                estimated_wait_min=None,
                predicted_charge_start_at=None,
                duration_sources=(),
                flags=tuple([*flags, *unavailable_reasons]),
            )

        duration_sources: list[str] = []
        slots: list[tuple[datetime, ChargingPortTelemetry]] = []
        for port in snapshot.ports:
            if port.is_out_of_service:
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
                confirmed_queue_length=(
                    len(snapshot.queue) if snapshot.queue is not None else None
                ),
                estimated_wait_min=None,
                predicted_charge_start_at=None,
                duration_sources=tuple(dict.fromkeys(duration_sources)),
                flags=tuple([*flags, "NO_OPERATIONAL_PORTS"]),
            )

        for vehicle in sorted(snapshot.queue or (), key=lambda entry: entry.queue_position):
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
            confirmed_queue_length=len(snapshot.queue or ()),
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
            operational_ports=sum(port.is_operational for port in snapshot.ports),
            unknown_ports=sum(port.state == "unknown" for port in snapshot.ports),
            confirmed_queue_length=(
                len(snapshot.queue) if snapshot.queue is not None else None
            ),
            estimated_wait_min=None,
            predicted_charge_start_at=None,
            duration_sources=tuple(dict.fromkeys(duration_sources)),
            flags=tuple([*flags, reason]),
        )


class RealtimeTelemetryStore:
    """Small resettable adapter boundary for the simulator and future ingestion."""

    def __init__(self) -> None:
        self._snapshots: dict[str, StationTelemetrySnapshot] = {}
        self._history: dict[tuple[str, datetime], StationTelemetrySnapshot] = {}
        self._lock = RLock()

    def upsert(self, snapshot: StationTelemetrySnapshot) -> StationTelemetrySnapshot:
        return self.upsert_with_change(snapshot)[0]

    def upsert_with_change(
        self, snapshot: StationTelemetrySnapshot
    ) -> tuple[StationTelemetrySnapshot, bool]:
        with self._lock:
            key = (snapshot.station_id, snapshot.observed_at)
            existing = self._history.get(key)
            if existing is not None:
                if existing != snapshot:
                    raise ValueError(
                        "a different telemetry snapshot already exists at this timestamp"
                    )
                return snapshot, False
            previous = self._snapshots.get(snapshot.station_id)
            if previous is not None and snapshot.observed_at < previous.observed_at:
                raise ValueError("telemetry snapshot is older than the stored snapshot")
            self._history[key] = snapshot
            self._snapshots[snapshot.station_id] = snapshot
            return snapshot, True

    def get(self, station_id: str) -> StationTelemetrySnapshot:
        with self._lock:
            return self._snapshots[station_id]

    def all(self) -> tuple[StationTelemetrySnapshot, ...]:
        with self._lock:
            return tuple(self._snapshots.values())

    def get_many(self, station_ids: tuple[str, ...]) -> tuple[StationTelemetrySnapshot, ...]:
        with self._lock:
            return tuple(
                self._snapshots[item] for item in station_ids if item in self._snapshots
            )

    def reset(self) -> None:
        with self._lock:
            self._snapshots.clear()
            self._history.clear()
