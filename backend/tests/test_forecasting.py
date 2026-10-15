import math
from datetime import timedelta

import pytest

from backend.app.config import load_settings
from backend.app.domain.forecasting import OccupancyForecastService, available_ports
from backend.app.domain.models import OccupancyWindow, StationStatus
from backend.app.domain.repositories import load_domain_data

ALL_HORIZONS = (5, 10, 15, 20, 25, 30)


class FixedPredictor:
    model_version = "fixed-test"

    def __init__(self, prediction: float, by_horizon: dict[int, float] | None = None) -> None:
        self.prediction = prediction
        self.by_horizon = by_horizon or {}
        self.calls: list[tuple[OccupancyWindow, int]] = []

    def predict(self, window: OccupancyWindow, horizon_min: int) -> float:
        self.calls.append((window, horizon_min))
        return self.by_horizon.get(horizon_min, self.prediction)


class FailingPredictor:
    def predict(self, window: OccupancyWindow, horizon_min: int) -> float:
        raise RuntimeError("model unavailable")


class WindowProvider:
    def __init__(self, window: OccupancyWindow | None) -> None:
        self.window_value = window
        self.calls = 0
        self.as_of_values: list = []

    def window(self, station_id: str, as_of=None) -> OccupancyWindow | None:
        self.calls += 1
        self.as_of_values.append(as_of)
        return self.window_value


class ProfileProvider:
    def __init__(self, values: dict[timedelta, float], t_last) -> None:
        self.values = values
        self.t_last = t_last

    def ratio_at(self, station_id: str, at):
        return self.values.get(at - self.t_last)


@pytest.fixture(scope="module")
def deutsches_status() -> StationStatus:
    data = load_domain_data(load_settings().data_dir)
    return data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")


def _window(status: StationStatus, ratio: float = 0.75) -> OccupancyWindow:
    return OccupancyWindow(
        station_id=status.station_id,
        lags=(ratio,) * 12,
        t_last=status.timestamp,
        total_ports=status.total_ports,
        geo_features=(0.0,) * 13,
        nearest_station_occupancy=ratio,
    )


def _service(status: StationStatus, predictor, *, window=True, profile=None, age_min=0):
    provider = WindowProvider(_window(status) if window else None)
    service = OccupancyForecastService(
        predictor,
        supported_model_horizons=ALL_HORIZONS,
        window_provider=provider,
        profile_provider=profile,
        profile_tau_min=30,
        clock=lambda: status.timestamp + timedelta(minutes=age_min),
    )
    return service, provider


def test_persistence_forecast_uses_latest_occupancy(deutsches_status: StationStatus) -> None:
    result = OccupancyForecastService().forecast_occupancy(
        deutsches_status, horizon_min=10
    )

    assert result.prediction_source == "persistence"
    assert result.predicted_occupancy_ratio == 0.75
    assert result.predicted_occupied_ports == 3
    assert result.flags == ("PERSISTENCE_FALLBACK",)


def test_beyond_model_horizon_uses_requested_contract_horizon_with_fallback(
    deutsches_status: StationStatus,
) -> None:
    result = OccupancyForecastService().forecast_occupancy(
        deutsches_status, horizon_min=30
    )

    assert result.used_horizon_min == 30
    assert "BEYOND_MODEL_HORIZON" in result.flags
    assert result.prediction_source == "persistence"


def test_loaded_model_is_not_called_for_an_unsupported_contract_horizon(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(0.5)
    result = OccupancyForecastService(predictor).forecast_occupancy(
        deutsches_status, horizon_min=20
    )

    assert result.used_horizon_min == 20
    assert result.prediction_source == "persistence"
    assert "MODEL_HORIZON_UNSUPPORTED" in result.flags
    assert predictor.calls == []


def test_model_gets_the_window_aligned_horizon_and_clamped_output(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(1.2)
    service, _ = _service(deutsches_status, predictor)

    result = service.forecast_occupancy(deutsches_status, horizon_min=8)

    assert [(call[0].t_last, call[1]) for call in predictor.calls] == [
        (deutsches_status.timestamp, 10)
    ]
    assert result.used_horizon_min == 10
    assert result.predicted_occupancy_ratio == 1
    assert result.prediction_source == "model"
    assert result.model_version == "fixed-test"
    assert "HORIZON_ALIGNED_TO_MODEL" in result.flags
    assert "PREDICTION_CLAMPED" in result.flags


def test_loaded_model_without_history_provider_falls_back(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(0.5)
    service = OccupancyForecastService(predictor, supported_model_horizons=ALL_HORIZONS)

    result = service.forecast_occupancy(deutsches_status, horizon_min=5)

    assert predictor.calls == []
    assert result.prediction_source == "persistence"
    assert "HISTORY_UNAVAILABLE" in result.flags


def test_window_that_is_not_usable_falls_back_without_calling_model(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(0.5)
    service, provider = _service(deutsches_status, predictor, window=False)

    result = service.forecast_occupancy(deutsches_status, horizon_min=5)

    assert provider.calls == 1
    assert predictor.calls == []
    assert result.prediction_source == "persistence"
    assert "HISTORY_UNAVAILABLE" in result.flags


def test_model_error_falls_back_to_persistence(deutsches_status: StationStatus) -> None:
    service, _ = _service(deutsches_status, FailingPredictor())

    result = service.forecast_occupancy(deutsches_status, horizon_min=5)

    assert result.prediction_source == "persistence"
    assert result.predicted_occupancy_ratio == 0.75
    assert "MODEL_INFERENCE_FAILED" in result.flags
    assert "PERSISTENCE_FALLBACK" in result.flags


def test_window_is_read_as_of_the_status_bucket(deutsches_status: StationStatus) -> None:
    service, provider = _service(deutsches_status, FixedPredictor(0.4))

    service.forecast_occupancy(deutsches_status, horizon_min=5)

    assert provider.as_of_values == [deutsches_status.timestamp]


def test_window_provider_failure_degrades_to_persistence(
    deutsches_status: StationStatus,
) -> None:
    class Broken:
        def window(self, station_id: str, as_of=None):
            raise RuntimeError("database down")

    service = OccupancyForecastService(
        FixedPredictor(0.4),
        supported_model_horizons=ALL_HORIZONS,
        window_provider=Broken(),
    )

    result = service.forecast_occupancy(deutsches_status, horizon_min=5)

    assert result.prediction_source == "persistence"
    assert "HISTORY_UNAVAILABLE" in result.flags


def test_observation_age_extends_the_horizon_from_the_newest_bucket(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(0.4)
    service, _ = _service(deutsches_status, predictor, age_min=7)

    result = service.forecast_occupancy(deutsches_status, horizon_min=5)

    assert result.used_horizon_min == 15
    assert predictor.calls[0][1] == 15


def test_far_horizon_blends_profile_with_the_t30_prediction(
    deutsches_status: StationStatus,
) -> None:
    t_last = deutsches_status.timestamp
    profile = ProfileProvider(
        {timedelta(minutes=30): 0.5, timedelta(minutes=45): 0.2}, t_last
    )
    predictor = FixedPredictor(0.0, {30: 0.9})
    service, _ = _service(deutsches_status, predictor, profile=profile)

    result = service.forecast_occupancy(deutsches_status, horizon_min=45)

    expected = 0.2 + (0.9 - 0.5) * math.exp(-15 / 30)
    assert result.prediction_source == "model_profile"
    assert result.predicted_occupancy_ratio == pytest.approx(expected)
    assert result.used_horizon_min == 45
    assert {"PROFILE_BLEND", "BEYOND_MODEL_HORIZON"} <= set(result.flags)
    assert [call[1] for call in predictor.calls] == [30]


def test_far_horizon_without_profile_holds_the_t30_prediction(
    deutsches_status: StationStatus,
) -> None:
    service, _ = _service(deutsches_status, FixedPredictor(0.0, {30: 0.9}))

    result = service.forecast_occupancy(deutsches_status, horizon_min=40)

    assert result.prediction_source == "model"
    assert result.predicted_occupancy_ratio == pytest.approx(0.9)
    assert "PROFILE_UNAVAILABLE" in result.flags


def test_far_horizon_is_capped_at_sixty_minutes(deutsches_status: StationStatus) -> None:
    service, _ = _service(deutsches_status, FixedPredictor(0.5))

    result = service.forecast_occupancy(deutsches_status, horizon_min=90)

    assert result.used_horizon_min == 60
    assert "BEYOND_FORECAST_HORIZON" in result.flags


def test_arrival_forecast_spans_the_milestones_around_the_arrival(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(0.5)
    service, provider = _service(deutsches_status, predictor)

    arrival = service.forecast_arrival(deutsches_status, arrival_min=12)

    assert arrival.arrival_lead_min == 12
    assert arrival.milestones_min == (10, 15, 20, 25, 30, 35, 40)
    assert [item.used_horizon_min for item in arrival.forecasts] == [10, 15, 20, 25, 30, 35, 40]
    assert arrival.at_arrival is arrival.forecasts[1]
    # One window lookup serves every milestone; later requests refresh neighbor observations.
    assert provider.calls == 1
    service.forecast_occupancy(deutsches_status, horizon_min=5)
    assert provider.calls == 2


def test_neighbor_updates_are_read_with_unchanged_station_status(deutsches_status) -> None:
    class NeighborPredictor:
        def predict(self, window, horizon_min):
            return window.nearest_station_occupancy

    service, provider = _service(deutsches_status, NeighborPredictor())
    provider.window_value = _window(deutsches_status).model_copy(
        update={"nearest_station_occupancy": 0.1}
    )
    first = service.forecast_occupancy(deutsches_status, horizon_min=5)
    provider.window_value = provider.window_value.model_copy(
        update={"nearest_station_occupancy": 0.9}
    )
    second = service.forecast_occupancy(deutsches_status, horizon_min=5)
    assert first.predicted_occupancy_ratio == pytest.approx(0.1)
    assert second.predicted_occupancy_ratio == pytest.approx(0.9)


def test_missing_neighbor_can_recover_without_a_new_station_bucket(deutsches_status) -> None:
    service, provider = _service(deutsches_status, FixedPredictor(0.2), window=False)
    first = service.forecast_occupancy(deutsches_status, horizon_min=5)
    assert first.prediction_source == "persistence"
    assert "HISTORY_UNAVAILABLE" in first.flags
    provider.window_value = _window(deutsches_status)
    second = service.forecast_occupancy(deutsches_status, horizon_min=5)
    assert second.prediction_source == "model"


def test_arrival_on_the_grid_starts_at_that_milestone(deutsches_status: StationStatus) -> None:
    service, _ = _service(deutsches_status, FixedPredictor(0.5))

    arrival = service.forecast_arrival(deutsches_status, arrival_min=15)

    assert arrival.milestones_min == (15, 20, 25, 30, 35, 40, 45)
    assert arrival.at_arrival is arrival.forecasts[0]


def test_arrival_before_the_first_milestone_uses_the_current_observation(
    deutsches_status: StationStatus,
) -> None:
    service, _ = _service(deutsches_status, FixedPredictor(0.2))

    arrival = service.forecast_arrival(deutsches_status, arrival_min=3)

    now = arrival.forecasts[0]
    assert arrival.milestones_min[0] == 0
    assert now.used_horizon_min == 0
    assert now.prediction_source == "persistence"
    assert now.predicted_occupied_ports == deutsches_status.occupied_ports
    assert "CURRENT_OBSERVATION" in now.flags
    assert arrival.at_arrival.used_horizon_min == 5
    assert arrival.at_arrival.prediction_source == "model"


def test_arrival_milestones_are_counted_from_the_newest_observation(
    deutsches_status: StationStatus,
) -> None:
    service, _ = _service(deutsches_status, FixedPredictor(0.5), age_min=7)

    arrival = service.forecast_arrival(deutsches_status, arrival_min=5)

    assert arrival.arrival_lead_min == 12
    assert arrival.milestones_min[0] == 10


def test_arrival_forecast_rejects_a_negative_time(deutsches_status: StationStatus) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        OccupancyForecastService().forecast_arrival(deutsches_status, arrival_min=-1)


def test_offline_station_forecast_is_explicit() -> None:
    status = StationStatus.model_validate(
        {
            "station_id": "OFFLINE",
            "timestamp": "2026-09-25T18:00:00+07:00",
            "total_ports": 1,
            "operational_ports": 0,
            "occupied_ports": 0,
            "available_ports": 0,
            "offline_ports": 1,
            "occupancy_ratio": None,
            "queue_length": 0,
            "avg_session_duration_min": 30,
            "data_source": "synthetic",
        }
    )

    result = OccupancyForecastService().forecast_occupancy(status, horizon_min=5)

    assert result.predicted_occupancy_ratio is None
    assert result.predicted_occupied_ports == 0
    assert "STATION_OFFLINE" in result.flags


def test_available_ports_rounds_partial_occupancy_up() -> None:
    assert available_ports(4, 1.0) == 3
    assert available_ports(4, 1.2) == 2
    assert available_ports(4, 5.0) == 0
