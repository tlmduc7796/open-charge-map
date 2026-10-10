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


@pytest.fixture(scope="module")
def deutsches_status() -> StationStatus:
    data = load_domain_data(load_settings().data_dir)
    return data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")


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


def test_model_adapter_gets_twelve_step_shape_and_clamps_output(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(1.2)
    result = OccupancyForecastService(predictor).forecast_occupancy(
        deutsches_status, horizon_min=8, occupancy_history=(0.75,) * 12
    )

    assert predictor.history_length == 12
    assert result.used_horizon_min == 10
    assert result.predicted_occupancy_ratio == 1
    assert result.prediction_source == "model"
    assert "HORIZON_ALIGNED_TO_MODEL" in result.flags
    assert "PREDICTION_CLAMPED" in result.flags


def test_loaded_model_requires_real_history(deutsches_status: StationStatus) -> None:
    predictor = FixedPredictor(0.5)
    result = OccupancyForecastService(predictor).forecast_occupancy(
        deutsches_status, horizon_min=5
    )

    assert predictor.history_length == 0
    assert result.prediction_source == "persistence"
    assert "HISTORY_UNAVAILABLE" in result.flags


def test_loaded_model_rejects_short_history_without_calling_model(
    deutsches_status: StationStatus,
) -> None:
    predictor = FixedPredictor(0.5)
    result = OccupancyForecastService(predictor).forecast_occupancy(
        deutsches_status, horizon_min=5, occupancy_history=(0.75,) * 11
    )

    assert predictor.history_length == 0
    assert result.prediction_source == "persistence"
    assert "HISTORY_UNAVAILABLE" in result.flags


def test_model_error_falls_back_to_persistence(deutsches_status: StationStatus) -> None:
    result = OccupancyForecastService(FailingPredictor()).forecast_occupancy(
        deutsches_status, horizon_min=5, occupancy_history=(0.75,) * 12
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
