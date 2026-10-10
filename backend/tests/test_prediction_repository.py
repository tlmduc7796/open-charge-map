from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.domain.models import OccupancyForecastResult
from backend.app.prediction_repository import DatabasePredictionRepository


class _CursorResult:
    rowcount = 1


class _MappingRows:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self._rows


class _Connection:
    def __init__(self, capture: dict) -> None:
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters):
        query = str(statement)
        self.capture.setdefault("statements", []).append(query)
        if query.startswith("SELECT code, id FROM stations"):
            return _MappingRows(
                [{"code": code, "id": f"db-{code}"} for code in parameters["station_codes"]]
            )
        self.capture["statement"] = query
        self.capture["parameters"] = parameters
        return _CursorResult()


class _Engine:
    def __init__(self) -> None:
        self.capture: dict = {}

    def begin(self):
        return _Connection(self.capture)


def _forecast(**updates) -> OccupancyForecastResult:
    values = {
        "station_id": "STATION_A",
        "generated_at": datetime(2026, 10, 9, 10, tzinfo=UTC),
        "target_at": datetime(2026, 10, 9, 10, 5, tzinfo=UTC),
        "requested_horizon_min": 5,
        "used_horizon_min": 5,
        "predicted_occupancy_ratio": 0.5,
        "predicted_occupied_ports": 1,
        "operational_ports": 2,
        "prediction_source": "model",
        "model_version": "occupancy-xgb-v2",
        "flags": (),
    }
    return OccupancyForecastResult(**(values | updates))


def test_prediction_repository_upserts_auditable_model_output() -> None:
    engine = _Engine()
    repository = DatabasePredictionRepository(engine)

    assert repository.save_occupancy_forecast(_forecast()) is True

    assert "ON CONFLICT (station_id, run_at, horizon_min) DO UPDATE" in engine.capture[
        "statement"
    ]
    assert "CAST(:prediction_source AS prediction_source)" in engine.capture["statement"]
    parameters = engine.capture["parameters"][0]
    assert parameters["prediction_source"] == "model"
    assert parameters["model_version"] == "occupancy-xgb-v2"
    assert parameters["station_id"] == "db-STATION_A"


def test_prediction_repository_labels_persistence_output() -> None:
    engine = _Engine()
    repository = DatabasePredictionRepository(engine)

    repository.save_occupancy_forecast(
        _forecast(prediction_source="persistence", model_version=None)
    )

    assert engine.capture["parameters"][0]["model_version"] == "persistence"


def test_prediction_repository_skips_non_product_horizons() -> None:
    engine = _Engine()
    repository = DatabasePredictionRepository(engine)

    assert repository.save_occupancy_forecast(_forecast(requested_horizon_min=35)) is False
    assert engine.capture == {}


def test_prediction_repository_requires_model_provenance() -> None:
    repository = DatabasePredictionRepository(_Engine())

    with pytest.raises(ValueError, match="requires model_version"):
        repository.save_occupancy_forecast(
            _forecast(model_version=None)
        )
