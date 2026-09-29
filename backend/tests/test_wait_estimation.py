from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.app.config import load_settings
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.models import StationStatus
from backend.app.domain.repositories import DomainData, load_domain_data
from backend.app.domain.wait_estimation import WaitEstimator


@pytest.fixture(scope="module")
def domain_data() -> DomainData:
    return load_domain_data(load_settings().data_dir)


@pytest.fixture(scope="module")
def estimator(domain_data: DomainData) -> WaitEstimator:
    return WaitEstimator(domain_data.queue_assumptions, scoring_wait_cap_min=120)


def _status(base: StationStatus, **updates: object) -> StationStatus:
    return StationStatus.model_validate({**base.model_dump(), **updates})


def _estimate(
    estimator: WaitEstimator,
    status: StationStatus,
    *,
    evaluation_at: str = "2026-09-25T18:00:00+07:00",
):
    forecast = OccupancyForecastService().forecast_occupancy(status, horizon_min=5)
    return estimator.estimate_wait(
        status,
        forecast,
        evaluation_at=datetime.fromisoformat(evaluation_at),
    )


def test_available_ports_produce_near_zero_wait(
    domain_data: DomainData, estimator: WaitEstimator
) -> None:
    status = domain_data.station_statuses.get("ST_EVO_AUDI_HCM")

    result = _estimate(estimator, status)

    assert result.current_state_wait_min == 0
    assert result.estimated_wait_min == 0


def test_empty_single_port_station_has_no_immediate_wait(
    domain_data: DomainData, estimator: WaitEstimator
) -> None:
    status = domain_data.station_statuses.get("ST_EVO_LAVIDA_Q7")

    result = _estimate(estimator, status)

    assert result.erlang_expected_wait_min > 0
    assert result.current_state_wait_min == 0
    assert result.estimated_wait_min == 0


def test_full_station_with_queue_has_positive_wait(
    domain_data: DomainData, estimator: WaitEstimator
) -> None:
    base = domain_data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")
    status = _status(
        base,
        occupied_ports=4,
        available_ports=0,
        occupancy_ratio=1,
        queue_length=1,
    )

    result = _estimate(estimator, status)

    assert result.current_state_wait_min == 25
    assert result.estimated_wait_min >= result.current_state_wait_min


def test_queue_increase_cannot_reduce_wait(
    domain_data: DomainData, estimator: WaitEstimator
) -> None:
    base = domain_data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")
    full = _status(base, occupied_ports=4, available_ports=0, occupancy_ratio=1, queue_length=0)
    queued = _status(full, queue_length=3)

    no_queue_wait = _estimate(estimator, full).estimated_wait_min
    queued_wait = _estimate(estimator, queued).estimated_wait_min

    assert queued_wait >= no_queue_wait


def test_port_outage_cannot_reduce_wait(
    domain_data: DomainData, estimator: WaitEstimator
) -> None:
    base = domain_data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")
    normal = _status(
        base,
        operational_ports=4,
        offline_ports=0,
        occupied_ports=4,
        available_ports=0,
        occupancy_ratio=1,
        queue_length=1,
    )
    outage = _status(
        base,
        operational_ports=2,
        offline_ports=2,
        occupied_ports=2,
        available_ports=0,
        occupancy_ratio=1,
        queue_length=1,
    )

    assert _estimate(estimator, outage).estimated_wait_min >= _estimate(
        estimator, normal
    ).estimated_wait_min


def test_invalid_capacity_is_rejected(domain_data: DomainData) -> None:
    base = domain_data.station_statuses.get("ST_EVO_LAVIDA_Q7")

    with pytest.raises(ValidationError, match="operational_ports.*offline_ports"):
        _status(base, operational_ports=0, offline_ports=0)


def test_planned_arrivals_can_be_toggled_and_trigger_overload(
    domain_data: DomainData, estimator: WaitEstimator
) -> None:
    status = domain_data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")
    forecast = OccupancyForecastService().forecast_occupancy(status, horizon_min=15)
    evaluation_at = datetime.fromisoformat("2026-09-25T18:12:00+07:00")

    without_planned = estimator.estimate_wait(
        status,
        forecast,
        evaluation_at=evaluation_at,
        planned_arrivals=domain_data.planned_arrivals.all(),
        include_planned_arrivals=False,
    )
    with_planned = estimator.estimate_wait(
        status,
        forecast,
        evaluation_at=evaluation_at,
        planned_arrivals=domain_data.planned_arrivals.all(),
        include_planned_arrivals=True,
    )

    assert without_planned.planned_arrival_rate_per_hour == 0
    assert with_planned.planned_arrival_rate_per_hour == pytest.approx(6.6)
    assert with_planned.estimated_wait_min >= without_planned.estimated_wait_min
    assert "OVERLOADED" in with_planned.flags
    assert with_planned.estimated_wait_min == 120


def test_scenario_override_applies_only_to_requested_station(
    domain_data: DomainData, estimator: WaitEstimator
) -> None:
    status = domain_data.station_statuses.get("ST_VF_LA_VELA")
    forecast = OccupancyForecastService().forecast_occupancy(status, horizon_min=5)

    result = estimator.estimate_wait(
        status,
        forecast,
        evaluation_at=datetime.fromisoformat("2026-09-25T18:00:00+07:00"),
        scenario_id="SCN_CONGESTION_REROUTE",
        include_planned_arrivals=False,
    )

    assert result.baseline_arrival_rate_per_hour == 2.8
    assert "SCENARIO_OVERRIDE_APPLIED" in result.flags


def test_offline_station_returns_finite_scoring_cap(
    domain_data: DomainData, estimator: WaitEstimator
) -> None:
    base = domain_data.station_statuses.get("ST_EVO_LAVIDA_Q7")
    status = _status(
        base,
        operational_ports=0,
        offline_ports=1,
        occupied_ports=0,
        available_ports=0,
        occupancy_ratio=None,
    )

    result = _estimate(estimator, status)

    assert result.estimated_wait_min == 120
    assert "STATION_OFFLINE" in result.flags
    assert "CAPPED_WAIT" in result.flags
