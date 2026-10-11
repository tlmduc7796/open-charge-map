from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.app.config import load_settings
from backend.app.domain.forecasting import MILESTONES_AFTER_ARRIVAL
from backend.app.domain.models import (
    ArrivalForecast,
    OccupancyForecastResult,
    StationStatus,
)
from backend.app.domain.repositories import DomainData, load_domain_data
from backend.app.domain.wait_estimation import WaitEstimator

EVALUATION_AT = datetime.fromisoformat("2026-09-25T18:00:00+07:00")


@pytest.fixture(scope="module")
def domain_data() -> DomainData:
    return load_domain_data(load_settings().data_dir)


@pytest.fixture(scope="module")
def four_ports(domain_data: DomainData) -> StationStatus:
    status = domain_data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")
    assert status.operational_ports == 4
    return status


def _status(base: StationStatus, **updates: object) -> StationStatus:
    return StationStatus.model_validate({**base.model_dump(), **updates})


def _arrival(
    status: StationStatus, occupied: list[float], *, lead: float = 12.0, first: int = 10
) -> ArrivalForecast:
    """`occupied[i]` busy ports at milestone `first + 5 * i`; padded with the last value."""
    padded = occupied + [occupied[-1]] * (MILESTONES_AFTER_ARRIVAL + 1 - len(occupied))
    milestones = tuple(first + 5 * index for index in range(MILESTONES_AFTER_ARRIVAL + 1))
    return ArrivalForecast(
        arrival_lead_min=lead,
        milestones_min=milestones,
        forecasts=tuple(
            OccupancyForecastResult(
                station_id=status.station_id,
                requested_horizon_min=milestone,
                used_horizon_min=milestone,
                predicted_occupancy_ratio=(
                    count / status.operational_ports if status.operational_ports else None
                ),
                predicted_occupied_ports=count,
                operational_ports=status.operational_ports,
                prediction_source="model",
                flags=(),
            )
            for milestone, count in zip(milestones, padded, strict=True)
        ),
    )


def _wait(status: StationStatus, occupied: list[float], **kwargs):
    settings = kwargs.pop("settings", {})
    return WaitEstimator(**settings).estimate_wait(
        status, _arrival(status, occupied, **kwargs), evaluation_at=EVALUATION_AT
    )


def test_both_surrounding_milestones_free_means_no_wait(four_ports: StationStatus) -> None:
    # Arrival at minute 12 between milestones 10 and 15, each with 3 free ports (1 busy).
    result = _wait(four_ports, [1, 1])

    assert result.estimated_wait_min == 0
    assert result.free_ports_at_arrival == 3
    assert result.satisfied_at_min == 0
    assert result.flags == ()


def test_wait_runs_from_the_actual_arrival_to_the_next_good_milestone(
    four_ports: StationStatus,
) -> None:
    # Milestone 10 is full, 15 has 3 free: the driver waits from minute 12 to minute 15.
    result = _wait(four_ports, [4, 1])

    assert result.free_ports_at_arrival == 0
    assert result.estimated_wait_min == pytest.approx(3.0)
    assert result.satisfied_at_min == pytest.approx(3.0)


def test_the_worse_surrounding_milestone_decides_the_state_at_arrival(
    four_ports: StationStatus,
) -> None:
    # 10: 3 free, 15: full, 20: 3 free -> not free on arrival, available at minute 20.
    result = _wait(four_ports, [1, 4, 1])

    assert result.free_ports_at_arrival == 0
    assert result.estimated_wait_min == pytest.approx(8.0)


def test_one_free_port_is_enough(four_ports: StationStatus) -> None:
    # Exactly one free port at both surrounding milestones.
    result = _wait(four_ports, [3, 3])

    assert result.free_ports_at_arrival == 1
    assert result.estimated_wait_min == 0


def test_a_full_station_waits_for_its_first_free_port(four_ports: StationStatus) -> None:
    # Full at milestone 10, one free port at 15: wait from minute 12 to minute 15.
    assert _wait(four_ports, [4, 3]).estimated_wait_min == pytest.approx(3.0)


def test_arrival_on_the_grid_uses_that_single_milestone(four_ports: StationStatus) -> None:
    free_now = _wait(four_ports, [2, 4], lead=10.0)
    waits_five = _wait(four_ports, [4, 3], lead=10.0)

    assert free_now.estimated_wait_min == 0
    assert free_now.free_ports_at_arrival == 2
    assert waits_five.estimated_wait_min == pytest.approx(5.0)


def test_fractional_occupancy_rounds_towards_fewer_free_ports(
    four_ports: StationStatus,
) -> None:
    # 3.2 busy -> 4 whole ports busy -> 0 free; 2.9 -> 3 busy -> 1 free.
    assert _wait(four_ports, [3.2, 3.2, 2.9], lead=10.0).estimated_wait_min == 10


def test_no_milestone_with_a_free_port_returns_the_30_minute_maximum(
    four_ports: StationStatus,
) -> None:
    result = _wait(four_ports, [4])

    assert result.estimated_wait_min == 30
    assert result.satisfied_at_min is None
    assert "WAIT_NO_FREE_PORT_WITHIN_30MIN" in result.flags
    assert "CAPPED_WAIT" in result.flags


def test_the_sixth_milestone_after_the_arrival_still_counts(four_ports: StationStatus) -> None:
    # Arrival at 12: milestones 15..40 follow it; 40 is the sixth.
    result = _wait(four_ports, [4, 4, 4, 4, 4, 4, 3])

    assert result.satisfied_at_min == pytest.approx(28.0)
    assert result.estimated_wait_min == pytest.approx(28.0)
    assert result.flags == ()


def test_single_port_station_is_free_when_its_port_is_free(domain_data: DomainData) -> None:
    base = domain_data.station_statuses.get("ST_EVO_LAVIDA_Q7")
    single = _status(
        base,
        total_ports=1,
        operational_ports=1,
        offline_ports=0,
        unknown_ports=0,
        occupied_ports=0,
        available_ports=1,
        occupancy_ratio=0,
    )

    assert _wait(single, [0]).estimated_wait_min == 0
    assert _wait(single, [1, 1, 0], lead=10.0).estimated_wait_min == 10


def test_queue_length_does_not_change_the_estimate(four_ports: StationStatus) -> None:
    queued = _status(four_ports, queue_length=5)

    assert _wait(queued, [4, 3]).estimated_wait_min == pytest.approx(3.0)
    assert _wait(four_ports, [4, 3]).estimated_wait_min == pytest.approx(3.0)


def test_offline_station_returns_the_maximum(domain_data: DomainData) -> None:
    base = domain_data.station_statuses.get("ST_EVO_LAVIDA_Q7")
    status = _status(
        base,
        operational_ports=0,
        offline_ports=1,
        occupied_ports=0,
        available_ports=0,
        occupancy_ratio=None,
    )

    result = _wait(status, [0])

    assert result.estimated_wait_min == 30
    assert result.free_ports_at_arrival is None
    assert "STATION_OFFLINE" in result.flags
    assert "CAPPED_WAIT" in result.flags


def test_configured_cap_below_the_maximum_applies(four_ports: StationStatus) -> None:
    capped = _wait(
        four_ports, [4, 4, 4, 4, 2], lead=10.0, settings={"scoring_wait_cap_min": 10}
    )
    unreachable = _wait(four_ports, [4], settings={"scoring_wait_cap_min": 10})

    assert capped.estimated_wait_min == 10
    assert "CAPPED_WAIT" in capped.flags
    assert unreachable.estimated_wait_min == 10


def test_cap_above_the_maximum_never_extends_the_wait(four_ports: StationStatus) -> None:
    assert _wait(four_ports, [4], settings={"scoring_wait_cap_min": 120}).estimated_wait_min == 30


def test_incomplete_arrival_forecast_is_rejected(four_ports: StationStatus) -> None:
    short = ArrivalForecast(
        arrival_lead_min=12,
        milestones_min=(10, 15),
        forecasts=_arrival(four_ports, [0]).forecasts[:2],
    )

    with pytest.raises(ValueError, match="milestones"):
        WaitEstimator().estimate_wait(four_ports, short, evaluation_at=EVALUATION_AT)


def test_forecast_of_another_station_is_rejected(
    four_ports: StationStatus, domain_data: DomainData
) -> None:
    other = domain_data.station_statuses.get("ST_EVO_LAVIDA_Q7")

    with pytest.raises(ValueError, match="same station"):
        WaitEstimator().estimate_wait(
            four_ports, _arrival(other, [0]), evaluation_at=EVALUATION_AT
        )


def test_evaluation_time_needs_a_timezone(four_ports: StationStatus) -> None:
    with pytest.raises(ValueError, match="timezone"):
        WaitEstimator().estimate_wait(
            four_ports,
            _arrival(four_ports, [0]),
            evaluation_at=datetime(2026, 9, 25, 18, 0),
        )


def test_arrival_forecast_rejects_a_misplaced_first_milestone(
    four_ports: StationStatus,
) -> None:
    with pytest.raises(ValidationError, match="at or before the arrival"):
        _arrival(four_ports, [0], lead=17.0, first=10)


def test_invalid_capacity_is_rejected(domain_data: DomainData) -> None:
    base = domain_data.station_statuses.get("ST_EVO_LAVIDA_Q7")

    with pytest.raises(ValidationError, match="operational_ports.*offline_ports"):
        _status(base, operational_ports=0, offline_ports=0)
