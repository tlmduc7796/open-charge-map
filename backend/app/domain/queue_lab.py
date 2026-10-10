"""Stateless Queue Lab simulations for deterministic and synthetic-duration DES.

This is an explicitly simulated teaching/demo surface.  It is not connected to
station telemetry, occupancy forecasting, ACN-Data, or an RDM artifact.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from backend.app.domain.models import DomainModel


class SyntheticDuration(DomainModel):
    kind: Literal["fixed", "uniform"] = "fixed"
    value_min: float | None = Field(default=None, gt=0)
    min_min: float | None = Field(default=None, gt=0)
    max_min: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_distribution(self) -> SyntheticDuration:
        if self.kind == "fixed":
            if self.value_min is None or self.min_min is not None or self.max_min is not None:
                raise ValueError("fixed duration requires value_min only")
        elif (
            self.min_min is None
            or self.max_min is None
            or self.value_min is not None
            or self.min_min > self.max_min
        ):
            raise ValueError("uniform duration requires min_min and max_min only")
        return self

    def sample(self, rng: random.Random) -> float:
        if self.kind == "fixed":
            assert self.value_min is not None
            return self.value_min
        assert self.min_min is not None and self.max_min is not None
        return rng.uniform(self.min_min, self.max_min)


class QueueLabPort(DomainModel):
    port_id: str = Field(min_length=1)
    connector_types: tuple[str, ...] = Field(min_length=1)
    state: Literal["available", "charging", "offline"]
    remaining_port_release: SyntheticDuration | None = None

    @model_validator(mode="after")
    def validate_duration_for_state(self) -> QueueLabPort:
        if self.state == "charging" and self.remaining_port_release is None:
            raise ValueError("a charging port requires remaining_port_release")
        if self.state != "charging" and self.remaining_port_release is not None:
            raise ValueError("only a charging port may have a release duration")
        return self


class QueueLabVehicle(DomainModel):
    vehicle_id: str = Field(min_length=1)
    queue_position: int = Field(gt=0)
    connector_types: tuple[str, ...] = Field(min_length=1)
    charging_duration: SyntheticDuration


class QueueLabSimulationRequest(DomainModel):
    evaluation_at: datetime
    ports: tuple[QueueLabPort, ...] = Field(min_length=1)
    confirmed_queue: tuple[QueueLabVehicle, ...] = ()
    requester_connector_types: tuple[str, ...] = Field(min_length=1)
    requester_charge_duration: SyntheticDuration
    trials: int = Field(default=1000, ge=1, le=10000)
    seed: int = Field(default=42, ge=0)
    wait_threshold_min: float = Field(default=30, ge=0)

    @model_validator(mode="after")
    def validate_request(self) -> QueueLabSimulationRequest:
        if self.evaluation_at.tzinfo is None:
            raise ValueError("evaluation_at requires timezone")
        port_ids = [item.port_id for item in self.ports]
        positions = [item.queue_position for item in self.confirmed_queue]
        vehicle_ids = [item.vehicle_id for item in self.confirmed_queue]
        if len(port_ids) != len(set(port_ids)):
            raise ValueError("port_id values must be unique")
        if len(positions) != len(set(positions)):
            raise ValueError("queue_position values must be unique")
        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ValueError("queue vehicle_id values must be unique")
        return self


class QueueLabTimelineEntry(DomainModel):
    port_id: str
    vehicle_id: str
    kind: Literal["active_session", "confirmed_queue", "requester"]
    start_at: datetime
    end_at: datetime


class QueueLabMonteCarloSummary(DomainModel):
    trials: int
    seed: int
    p10_wait_min: float | None = None
    p50_wait_min: float | None = None
    p90_wait_min: float | None = None
    probability_wait_over_threshold: float | None = None
    wait_threshold_min: float


class QueueLabSimulationResult(DomainModel):
    estimated_start_at: datetime | None = Field(
        default=None,
        description=(
            "Start time from one deterministic sample using the request seed; it is "
            "not the Monte Carlo mean or a live station estimate."
        ),
    )
    estimated_wait_min: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Wait from the single seeded timeline sample; use monte_carlo percentiles "
            "for the synthetic duration distribution."
        ),
    )
    timeline: tuple[QueueLabTimelineEntry, ...] = ()
    monte_carlo: QueueLabMonteCarloSummary
    caveats: tuple[str, ...]


def _fixed_duration(minutes: float) -> SyntheticDuration:
    return SyntheticDuration(kind="fixed", value_min=minutes)


def demo_request() -> QueueLabSimulationRequest:
    """Known scenario: requester waits 28 minutes because only port A is compatible."""
    return QueueLabSimulationRequest(
        evaluation_at=datetime.fromisoformat("2026-10-01T10:00:00+07:00"),
        ports=(
            QueueLabPort(
                port_id="A",
                connector_types=("CCS2",),
                state="charging",
                remaining_port_release=_fixed_duration(8),
            ),
            QueueLabPort(
                port_id="B",
                connector_types=("CHAdeMO",),
                state="charging",
                remaining_port_release=_fixed_duration(20),
            ),
        ),
        confirmed_queue=(
            QueueLabVehicle(
                vehicle_id="QUEUE_1",
                queue_position=1,
                connector_types=("CCS2",),
                charging_duration=_fixed_duration(20),
            ),
        ),
        requester_connector_types=("CCS2",),
        requester_charge_duration=_fixed_duration(30),
    )


def _compatible(port: QueueLabPort, connectors: tuple[str, ...]) -> bool:
    return bool(set(port.connector_types).intersection(connectors))


def _schedule(
    request: QueueLabSimulationRequest,
    rng: random.Random,
    *,
    include_timeline: bool,
) -> tuple[datetime | None, tuple[QueueLabTimelineEntry, ...], list[str]]:
    slots: list[tuple[datetime, QueueLabPort]] = []
    timeline: list[QueueLabTimelineEntry] = []
    caveats = [
        "SIMULATED_DURATION_INPUTS",
        "SEEDED_TIMELINE_IS_ONE_SAMPLE",
        "CONFIRMED_QUEUE_ONLY",
        "CONNECTOR_COMPATIBILITY_APPLIED",
        "NOT_LIVE_STATION_TELEMETRY",
    ]
    for port in request.ports:
        if port.state == "offline":
            continue
        if port.state == "available":
            slots.append((request.evaluation_at, port))
            continue
        assert port.remaining_port_release is not None
        release_at = request.evaluation_at + timedelta(
            minutes=port.remaining_port_release.sample(rng)
        )
        slots.append((release_at, port))
        if include_timeline:
            timeline.append(
                QueueLabTimelineEntry(
                    port_id=port.port_id,
                    vehicle_id=f"ACTIVE_{port.port_id}",
                    kind="active_session",
                    start_at=request.evaluation_at,
                    end_at=release_at,
                )
            )
    for vehicle in sorted(request.confirmed_queue, key=lambda item: item.queue_position):
        candidates = [
            (free_at, port.port_id, index)
            for index, (free_at, port) in enumerate(slots)
            if _compatible(port, vehicle.connector_types)
        ]
        if not candidates:
            return None, tuple(timeline), [*caveats, "QUEUE_CONNECTOR_UNSUPPORTED"]
        _, _, index = min(candidates)
        start_at, port = slots[index]
        end_at = start_at + timedelta(minutes=vehicle.charging_duration.sample(rng))
        slots[index] = (end_at, port)
        if include_timeline:
            timeline.append(
                QueueLabTimelineEntry(
                    port_id=port.port_id,
                    vehicle_id=vehicle.vehicle_id,
                    kind="confirmed_queue",
                    start_at=start_at,
                    end_at=end_at,
                )
            )
    requester_candidates = [
        (free_at, port.port_id, index)
        for index, (free_at, port) in enumerate(slots)
        if _compatible(port, request.requester_connector_types)
    ]
    if not requester_candidates:
        return None, tuple(timeline), [*caveats, "REQUESTED_CONNECTOR_UNSUPPORTED"]
    _, _, index = min(requester_candidates)
    start_at, port = slots[index]
    if include_timeline:
        timeline.append(
            QueueLabTimelineEntry(
                port_id=port.port_id,
                vehicle_id="DEMO_REQUESTER",
                kind="requester",
                start_at=start_at,
                end_at=start_at + timedelta(minutes=request.requester_charge_duration.sample(rng)),
            )
        )
    return (
        start_at,
        tuple(sorted(timeline, key=lambda entry: (entry.start_at, entry.port_id))),
        caveats,
    )


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def simulate_queue_lab(request: QueueLabSimulationRequest) -> QueueLabSimulationResult:
    deterministic_start, timeline, caveats = _schedule(
        request, random.Random(request.seed), include_timeline=True
    )
    if deterministic_start is None:
        return QueueLabSimulationResult(
            estimated_start_at=None,
            estimated_wait_min=None,
            timeline=timeline,
            monte_carlo=QueueLabMonteCarloSummary(
                trials=request.trials,
                seed=request.seed,
                wait_threshold_min=request.wait_threshold_min,
            ),
            caveats=tuple(caveats),
        )
    waits: list[float] = []
    rng = random.Random(request.seed)
    for _ in range(request.trials):
        start_at, _, trial_caveats = _schedule(request, rng, include_timeline=False)
        if start_at is None:
            return QueueLabSimulationResult(
                estimated_start_at=deterministic_start,
                estimated_wait_min=(deterministic_start - request.evaluation_at).total_seconds()
                / 60,
                timeline=timeline,
                monte_carlo=QueueLabMonteCarloSummary(
                    trials=request.trials,
                    seed=request.seed,
                    wait_threshold_min=request.wait_threshold_min,
                ),
                caveats=tuple(trial_caveats),
            )
        waits.append((start_at - request.evaluation_at).total_seconds() / 60)
    return QueueLabSimulationResult(
        estimated_start_at=deterministic_start,
        estimated_wait_min=(deterministic_start - request.evaluation_at).total_seconds() / 60,
        timeline=timeline,
        monte_carlo=QueueLabMonteCarloSummary(
            trials=request.trials,
            seed=request.seed,
            p10_wait_min=round(_quantile(waits, 0.10), 4),
            p50_wait_min=round(_quantile(waits, 0.50), 4),
            p90_wait_min=round(_quantile(waits, 0.90), 4),
            probability_wait_over_threshold=round(
                sum(value > request.wait_threshold_min for value in waits) / len(waits), 6
            ),
            wait_threshold_min=request.wait_threshold_min,
        ),
        caveats=tuple(caveats),
    )
