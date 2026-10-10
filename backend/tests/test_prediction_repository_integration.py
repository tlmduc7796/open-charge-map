"""PostgreSQL coverage for persisted model and fallback forecasts."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from backend.app.config import load_settings
from backend.app.domain.models import OccupancyForecastResult
from backend.app.prediction_repository import DatabasePredictionRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="requires a migrated PostgreSQL/PostGIS integration database",
)


def test_prediction_repository_persists_and_updates_forecast_version() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    repository = DatabasePredictionRepository(engine)
    with engine.connect() as connection:
        station_id = connection.execute(
            text("SELECT code FROM stations WHERE is_active ORDER BY code LIMIT 1")
        ).scalar_one()
    run_at = datetime.now(UTC)
    base = OccupancyForecastResult(
        station_id=station_id,
        generated_at=run_at,
        target_at=run_at + timedelta(minutes=5),
        requested_horizon_min=5,
        used_horizon_min=5,
        predicted_occupancy_ratio=0.4,
        predicted_occupied_ports=2,
        operational_ports=5,
        prediction_source="model",
        model_version="occupancy-integration-v1",
        flags=(),
    )
    try:
        repository.save_occupancy_forecast(base)
        repository.save_occupancy_forecast(
            base.model_copy(
                update={
                    "predicted_occupancy_ratio": 0.6,
                    "predicted_occupied_ports": 3,
                    "model_version": "occupancy-integration-v2",
                }
            )
        )
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT predicted_occupancy_ratio, model_version, prediction_source "
                    "FROM predictions WHERE station_id=(SELECT id FROM stations "
                    "WHERE code=:station_id) AND run_at=:run_at AND horizon_min=5"
                ),
                {"station_id": station_id, "run_at": run_at},
            ).mappings().all()
        assert len(rows) == 1
        assert float(rows[0]["predicted_occupancy_ratio"]) == pytest.approx(0.6)
        assert rows[0]["model_version"] == "occupancy-integration-v2"
        assert rows[0]["prediction_source"] == "model"
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM predictions WHERE station_id=(SELECT id FROM stations "
                    "WHERE code=:station_id) AND run_at=:run_at AND horizon_min=5"
                ),
                {"station_id": station_id, "run_at": run_at},
            )
        engine.dispose()
