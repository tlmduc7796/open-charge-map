"""Pure trip lifecycle rules shared by the future PostgreSQL trip service."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from backend.app.domain.models import DomainModel

TripPhase = Literal[
    "to_station", "at_station", "to_destination", "arrived", "cancelled"
]


class TripState(DomainModel):
    phase: TripPhase
    route_version: int = Field(ge=0)
    last_position_at: datetime | None = None
    last_reroute_at: datetime | None = None
    declined_station_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def timestamps_require_timezone(self) -> TripState:
        values = (self.last_position_at, self.last_reroute_at)
        if any(value is not None and value.tzinfo is None for value in values):
            raise ValueError("trip timestamps require timezone")
        return self


def apply_position(
    state: TripState,
    *,
    recorded_at: datetime,
    near_station: bool,
    near_destination: bool,
) -> tuple[TripState, bool]:
    if recorded_at.tzinfo is None:
        raise ValueError("position timestamp requires timezone")
    if state.last_position_at is not None and recorded_at <= state.last_position_at:
        return state, False
    phase = state.phase
    if phase == "to_station" and near_station:
        phase = "at_station"
    elif phase == "to_destination" and near_destination:
        phase = "arrived"
    return state.model_copy(
        update={"phase": phase, "last_position_at": recorded_at}
    ), True


def depart_station(state: TripState) -> TripState:
    if state.phase != "at_station":
        raise ValueError(f"cannot depart station from phase {state.phase}")
    return state.model_copy(update={"phase": "to_destination"})


def cancel_trip(state: TripState) -> TripState:
    if state.phase in {"arrived", "cancelled"}:
        raise ValueError(f"cannot cancel trip from phase {state.phase}")
    return state.model_copy(update={"phase": "cancelled"})


def register_reroute(
    state: TripState,
    *,
    evaluated_at: datetime,
    route_changed: bool,
    cooldown: timedelta,
) -> tuple[TripState, bool]:
    if evaluated_at.tzinfo is None:
        raise ValueError("reroute timestamp requires timezone")
    if cooldown.total_seconds() < 0:
        raise ValueError("reroute cooldown cannot be negative")
    if (
        state.last_reroute_at is not None
        and evaluated_at - state.last_reroute_at < cooldown
    ):
        return state, False
    if not route_changed:
        return state, False
    return state.model_copy(
        update={
            "route_version": state.route_version + 1,
            "last_reroute_at": evaluated_at,
        }
    ), True
