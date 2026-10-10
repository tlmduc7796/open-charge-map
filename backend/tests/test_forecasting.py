from datetime import datetime

import pytest

from backend.app.config import load_settings
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.models import StationStatus
from backend.app.domain.repositories import load_domain_data


class FixedPredictor:
    def __init__(self, prediction: float) -> None:
        self.prediction = prediction
        self.history_length = 0

    def predict(self, occupancy_history: tuple[float, ...], horizon_min: int) -> float:
        self.history_length = len(occupancy_history)
        assert horizon_min in {5, 10, 15}
        return self.prediction


class FailingPredictor:
    def predict(self, occupancy_history: tuple[float, ...], horizon_min: int) -> float:
        raise RuntimeError("model unavailable")


class MemoryForecastCache:
    def __init__(self) -> None:
        self.values = {}
        self.ttls = []

    def get(self, key):
        return self.values.get(key)

    def set(self, key, result, ttl_s):
        self.values[key] = result
        self.ttls.append(ttl_s)


@pytest.fixture(scope="module")
def deutsches_status() -> StationStatus:
    data = load_domain_data(load_settings().data_dir)
    return data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")


def test_persistence_forecast_uses_latest_occupancy(deutsches_status: StationStatus) -> None:
    result = OccupancyForecastService(model_version="unused-model-v1").forecast_occupancy(
        deutsches_status, horizon_min=10
    )

    assert result.prediction_source == "persistence"
    assert result.model_version is None
    assert result.predicted_occupancy_ratio == 0.75
    assert result.predicted_occupied_ports == 3
    assert result.flags == ("SYNTHETIC_HISTORY", "PERSISTENCE_FALLBACK")


def test_beyond_model_horizon_falls_back_instead_of_using_a_shorter_model(
    deutsches_status: StationStatus,
) -> None:
    class UnexpectedPredictor:
        def predict(self, occupancy_history: tuple[float, ...], horizon_min: int) -> float:
            pytest.fail("forecast beyond the supported horizon must not call the model")

    result = OccupancyForecastService(UnexpectedPredictor()).forecast_occupancy(
        deutsches_status, horizon_min=35
    )

    assert result.used_horizon_min == 30
    assert "BEYOND_MODEL_HORIZON" in result.flags
    assert result.prediction_source == "persistence"
    assert "PERSISTENCE_FALLBACK" in result.flags


def test_model_adapter_gets_twelve_step_shape_and_clamps_output(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(1.2)
    result = OccupancyForecastService(
        predictor, model_version="occupancy-xgb-2026-10-09.1"
    ).forecast_occupancy(deutsches_status, horizon_min=8)

    assert predictor.history_length == 12
    assert result.used_horizon_min == 10
    assert result.predicted_occupancy_ratio == 1
    assert result.prediction_source == "model"
    assert result.model_version == "occupancy-xgb-2026-10-09.1"
    assert "HORIZON_ALIGNED_TO_MODEL" in result.flags
    assert "PREDICTION_CLAMPED" in result.flags
    assert "SYNTHETIC_HISTORY" in result.flags


def test_model_error_falls_back_to_persistence(deutsches_status: StationStatus) -> None:
    result = OccupancyForecastService(FailingPredictor()).forecast_occupancy(
        deutsches_status, horizon_min=5
    )

    assert result.prediction_source == "persistence"
    assert result.predicted_occupancy_ratio == 0.75
    assert "MODEL_INFERENCE_FAILED" in result.flags
    assert "PERSISTENCE_FALLBACK" in result.flags


def test_history_shape_is_validated(deutsches_status: StationStatus) -> None:
    with pytest.raises(ValueError, match="exactly 12"):
        OccupancyForecastService().forecast_occupancy(
            deutsches_status,
            horizon_min=5,
            occupancy_history=(0.5, 0.6),
        )


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


def test_model_forecast_cache_reuses_identical_inputs_and_separates_horizons(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(0.5)
    cache = MemoryForecastCache()
    service = OccupancyForecastService(predictor, cache=cache, cache_ttl_s=45)

    first = service.forecast_occupancy(deutsches_status, horizon_min=5)
    repeated = service.forecast_occupancy(deutsches_status, horizon_min=5)
    other_horizon = service.forecast_occupancy(deutsches_status, horizon_min=10)

    assert first == repeated
    assert other_horizon.requested_horizon_min == 10
    assert len(cache.values) == 2
    assert cache.ttls == [45, 45]
    assert predictor.history_length == 12


def test_persistence_fallback_is_not_cached(deutsches_status: StationStatus) -> None:
    cache = MemoryForecastCache()
    service = OccupancyForecastService(cache=cache)

    service.forecast_occupancy(deutsches_status, horizon_min=5)

    assert cache.values == {}


def test_forecast_cache_isolated_by_model_version(deutsches_status: StationStatus) -> None:
    cache = MemoryForecastCache()
    target_at = datetime.fromisoformat("2026-10-09T10:00:00+00:00")
    first = OccupancyForecastService(
        FixedPredictor(0.2), model_version="occupancy-v1", cache=cache
    ).forecast_occupancy(
        deutsches_status,
        horizon_min=5,
        occupancy_history=(0.5,) * 12,
        forecast_at=target_at,
    )
    second = OccupancyForecastService(
        FixedPredictor(0.8), model_version="occupancy-v2", cache=cache
    ).forecast_occupancy(
        deutsches_status,
        horizon_min=5,
        occupancy_history=(0.5,) * 12,
        forecast_at=target_at,
    )

    assert first.predicted_occupancy_ratio == 0.2
    assert first.model_version == "occupancy-v1"
    assert second.predicted_occupancy_ratio == 0.8
    assert second.model_version == "occupancy-v2"
