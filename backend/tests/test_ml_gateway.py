from datetime import datetime

import pytest

from backend.app.config import load_settings
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.ml_gateway import DEFAULT_OCCUPANCY_RATIO, DefaultMlGateway
from backend.app.domain.models import StationStatus, WaitDistribution
from backend.app.domain.repositories import DomainData, load_domain_data
from backend.app.domain.wait_estimation import WaitEstimator


@pytest.fixture(scope="module")
def domain_data() -> DomainData:
    return load_domain_data(load_settings().data_dir)


@pytest.fixture(scope="module")
def status(domain_data: DomainData) -> StationStatus:
    return domain_data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")


class FixedHerdingGateway(DefaultMlGateway):
    def __init__(self, extra_ports: float) -> None:
        self.extra_ports = extra_ports

    def adjust_for_herding(
        self, station_id: str, predicted_occupied_ports: float, *, horizon_min: int
    ) -> float:
        return predicted_occupied_ports + self.extra_ports


def test_default_gateway_values_are_fixed_and_labelled() -> None:
    gateway = DefaultMlGateway()

    assert gateway.predict_occupancy_ratio("ST", None, 15) == DEFAULT_OCCUPANCY_RATIO
    assert gateway.adjust_for_herding("ST", 1.5, horizon_min=15) == 1.5
    waiting = gateway.wait_distribution("ST", point_estimate_min=12)
    assert waiting == WaitDistribution(
        p_wait=1.0, expected_wait_min=12, p90_wait_min=12, source="default"
    )
    idle = gateway.wait_distribution("ST", point_estimate_min=0)
    assert (idle.p_wait, idle.expected_wait_min, idle.p90_wait_min) == (0.0, 0.0, 0.0)


def test_forecast_uses_default_ratio_regardless_of_station_state(
    status: StationStatus,
) -> None:
    service = OccupancyForecastService(ml_gateway=DefaultMlGateway())

    result = service.forecast_occupancy(status, horizon_min=20)

    assert result.prediction_source == "default"
    assert result.predicted_occupancy_ratio == DEFAULT_OCCUPANCY_RATIO
    assert result.predicted_occupied_ports == pytest.approx(
        DEFAULT_OCCUPANCY_RATIO * status.operational_ports
    )
    assert "ML_DEFAULT_VALUE" in result.flags
    assert "PERSISTENCE_FALLBACK" not in result.flags
    assert service.model_loaded is False
    assert service.prediction_source == "default"


def test_offline_station_is_not_given_a_default_occupancy(status: StationStatus) -> None:
    offline = StationStatus.model_validate(
        {
            **status.model_dump(),
            "operational_ports": 0,
            "occupied_ports": 0,
            "available_ports": 0,
            "offline_ports": status.total_ports,
            "unknown_ports": 0,
            "occupancy_ratio": None,
            "queue_length": None,
            "avg_session_duration_min": None,
        }
    )

    result = OccupancyForecastService(ml_gateway=DefaultMlGateway()).forecast_occupancy(
        offline, horizon_min=10
    )

    assert result.predicted_occupancy_ratio is None
    assert result.predicted_occupied_ports == 0
    assert "STATION_OFFLINE" in result.flags


def test_herding_correction_is_applied_and_clamped_to_capacity(
    status: StationStatus,
) -> None:
    result = OccupancyForecastService(
        ml_gateway=FixedHerdingGateway(extra_ports=1_000)
    ).forecast_occupancy(status, horizon_min=10)

    assert result.predicted_occupied_ports == status.operational_ports
    assert result.predicted_occupancy_ratio == 1.0


def test_service_without_gateway_keeps_persistence_fallback(status: StationStatus) -> None:
    service = OccupancyForecastService()

    assert service.forecast_occupancy(status, horizon_min=10).prediction_source == (
        "persistence"
    )
    assert service.prediction_source == "persistence"


def test_wait_estimate_carries_gateway_distribution(
    domain_data: DomainData, status: StationStatus
) -> None:
    gateway = DefaultMlGateway()
    forecast = OccupancyForecastService(ml_gateway=gateway).forecast_occupancy(
        status, horizon_min=5
    )
    estimator = WaitEstimator(
        domain_data.queue_assumptions, scoring_wait_cap_min=120, ml_gateway=gateway
    )

    result = estimator.estimate_wait(
        status,
        forecast,
        evaluation_at=datetime.fromisoformat("2026-09-25T18:00:00+07:00"),
    )

    assert result.wait_distribution is not None
    assert result.wait_distribution.source == "default"
    assert result.wait_distribution.expected_wait_min == result.estimated_wait_min
    assert result.wait_distribution.p90_wait_min == result.estimated_wait_min


def test_wait_estimate_without_gateway_has_no_distribution(
    domain_data: DomainData, status: StationStatus
) -> None:
    forecast = OccupancyForecastService().forecast_occupancy(status, horizon_min=5)

    result = WaitEstimator(
        domain_data.queue_assumptions, scoring_wait_cap_min=120
    ).estimate_wait(
        status,
        forecast,
        evaluation_at=datetime.fromisoformat("2026-09-25T18:00:00+07:00"),
    )

    assert result.wait_distribution is None
