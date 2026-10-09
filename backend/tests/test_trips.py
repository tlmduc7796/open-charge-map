from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.domain.trips import (
    TripState,
    apply_position,
    cancel_trip,
    depart_station,
    register_reroute,
)

T0 = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)


def test_old_position_is_ignored_without_regressing_phase() -> None:
    state = TripState(
        phase="at_station", route_version=0, last_position_at=T0
    )

    updated, accepted = apply_position(
        state,
        recorded_at=T0 - timedelta(seconds=1),
        near_station=False,
        near_destination=False,
    )

    assert accepted is False
    assert updated == state


def test_trip_phase_progresses_forward_to_arrived() -> None:
    state = TripState(phase="to_station", route_version=0)
    at_station, _ = apply_position(
        state,
        recorded_at=T0,
        near_station=True,
        near_destination=False,
    )
    to_destination = depart_station(at_station)
    arrived, _ = apply_position(
        to_destination,
        recorded_at=T0 + timedelta(minutes=30),
        near_station=False,
        near_destination=True,
    )

    assert at_station.phase == "at_station"
    assert to_destination.phase == "to_destination"
    assert arrived.phase == "arrived"


def test_reroute_version_changes_only_after_cooldown_and_route_change() -> None:
    state = TripState(phase="to_station", route_version=2, last_reroute_at=T0)
    cooldown = timedelta(seconds=60)

    too_soon, changed = register_reroute(
        state,
        evaluated_at=T0 + timedelta(seconds=30),
        route_changed=True,
        cooldown=cooldown,
    )
    unchanged, changed_without_route = register_reroute(
        state,
        evaluated_at=T0 + cooldown,
        route_changed=False,
        cooldown=cooldown,
    )
    rerouted, changed_after_cooldown = register_reroute(
        state,
        evaluated_at=T0 + cooldown,
        route_changed=True,
        cooldown=cooldown,
    )

    assert changed is False and too_soon.route_version == 2
    assert changed_without_route is False and unchanged.route_version == 2
    assert changed_after_cooldown is True and rerouted.route_version == 3


def test_terminal_trip_cannot_be_cancelled() -> None:
    with pytest.raises(ValueError, match="cannot cancel"):
        cancel_trip(TripState(phase="arrived", route_version=0))
