"""Occupancy history -> window -> forecast -> `predictions` rows, on a real PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, text

from backend.app.api_v1_models import StationOccupancyUpdate
from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
)
from backend.app.domain.forecasting import MODEL_HORIZONS_MIN, OccupancyForecastService
from backend.app.domain.ml_gateway import DefaultMlGateway
from backend.app.domain.models import OccupancyWindow
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.domain.wait_estimation import WaitEstimator
from backend.app.main import app
from backend.app.occupancy_history_repository import DatabaseOccupancyHistoryRepository
from backend.app.prediction_repository import PredictionWriter
from backend.app.profile_repository import DatabaseOccupancyProfileRepository
from backend.app.station_state_repository import (
    DatabaseStationStateRepository,
    occupancy_bucket,
)
from ml.geo_features import GEO_COLUMNS, NEAREST_STATION_ID_COLUMN

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")
STATION = "ST_VF_NGO_QUYEN"
HEADERS = {"X-API-Key": "integration-test-key"}
REQUIRES_DATABASE = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="PostgreSQL test database required"
)


def _geo_table():
    """One row, self-referencing nearest station: these tests don't exercise geo features."""
    import pandas as pd

    row = {**dict.fromkeys(GEO_COLUMNS, 0.0), NEAREST_STATION_ID_COLUMN: STATION}
    return pd.DataFrame([row], index=pd.Index([STATION], name="station_id"))


class StubPredictor:
    model_version = "stub-test-v1"

    def __init__(self, ratio: float) -> None:
        self.ratio = ratio

    def predict(self, window: OccupancyWindow, horizon_min: int) -> float:
        return self.ratio


def _report(engine, buckets: list[datetime], occupied: list[int]) -> None:
    updates = tuple(
        StationOccupancyUpdate(
            station_id=STATION,
            reported_at=bucket,
            operational_ports=4,
            total_ports=4,
            occupied_ports=count,
        )
        for bucket, count in zip(buckets, occupied, strict=True)
    )
    DatabaseStationStateRepository(engine).record_occupancy(updates)


def _cleanup(engine, buckets: list[datetime]) -> None:
    with engine.begin() as connection:
        params = {"buckets": buckets, "code": STATION}
        connection.execute(
            text(
                "DELETE FROM station_occupancy_5m WHERE bucket_at = ANY(:buckets) "
                "AND station_id = (SELECT id FROM stations WHERE code = :code)"
            ),
            params,
        )
        connection.execute(
            text(
                "DELETE FROM station_occupancy_profile "
                "WHERE station_id = (SELECT id FROM stations WHERE code = :code)"
            ),
            params,
        )
        connection.execute(
            text(
                "UPDATE predictions SET run_at=NULL, predicted_occupancy_ratio=NULL, "
                "operational_ports_at_run=NULL, wait_probability=NULL, mean_wait_minutes=NULL, "
                "p90_wait_minutes=NULL, prediction_source=NULL, model_version=NULL "
                "WHERE station_id = (SELECT id FROM stations WHERE code = :code)"
            ),
            params,
        )


def _prediction_rows(engine) -> list[dict]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT p.horizon_min, p.predicted_occupancy_ratio, "
                    "p.operational_ports_at_run, p.wait_probability, p.mean_wait_minutes, "
                    "p.p90_wait_minutes, p.prediction_source::text AS source, p.model_version "
                    "FROM predictions p JOIN stations s ON s.id = p.station_id "
                    "WHERE s.code = :code ORDER BY p.horizon_min"
                ),
                {"code": STATION},
            ).mappings()
        ]


def _writer(engine, ratio: float) -> PredictionWriter:
    statuses = DatabaseStationStatusRepository(engine, stale_after_s=900)
    forecasting = OccupancyForecastService(
        StubPredictor(ratio),
        supported_model_horizons=MODEL_HORIZONS_MIN,
        window_provider=DatabaseOccupancyHistoryRepository(engine, _geo_table()),
    )
    estimator = WaitEstimator(ml_gateway=DefaultMlGateway())
    return PredictionWriter(engine, statuses, forecasting, estimator)


@REQUIRES_DATABASE
def test_history_window_profile_and_predictions_are_persisted() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    newest = occupancy_bucket(datetime.now(UTC))
    buckets = [newest - timedelta(minutes=5 * index) for index in range(14)]
    occupied = [(index * 3) % 5 for index in range(14)]  # newest first, all <= 4 ports
    try:
        _report(engine, buckets, occupied)

        window = DatabaseOccupancyHistoryRepository(engine, _geo_table()).window(STATION)
        assert window is not None
        assert window.t_last == newest
        assert window.total_ports == 4
        assert window.lags == tuple(count / 4 for count in occupied[:12])

        profile = DatabaseOccupancyProfileRepository(engine)
        assert profile.refresh() >= 1
        value = profile.ratio_at(STATION, newest)
        assert value is not None and 0.0 <= value <= 1.0

        written = _writer(engine, 0.25).refresh([STATION])

        rows = _prediction_rows(engine)
        assert written == len(rows) == 6
        assert [row["horizon_min"] for row in rows] == list(MODEL_HORIZONS_MIN)
        for row in rows:
            assert row["source"] == "model"
            assert row["model_version"] == "stub-test-v1"
            assert float(row["predicted_occupancy_ratio"]) == pytest.approx(0.25)
            assert row["operational_ports_at_run"] == 4
            # 25% of 4 ports busy -> 3 free -> no wait; the distribution is a point mass.
            assert float(row["mean_wait_minutes"]) == 0
            assert float(row["p90_wait_minutes"]) >= float(row["mean_wait_minutes"])
            assert float(row["wait_probability"]) == 0
    finally:
        _cleanup(engine, buckets)


@REQUIRES_DATABASE
def test_busy_station_gets_the_maximum_wait_and_a_gap_removes_the_window() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    newest = occupancy_bucket(datetime.now(UTC))
    buckets = [newest - timedelta(minutes=5 * index) for index in range(12)]
    try:
        _report(engine, buckets, [4] * 12)
        _writer(engine, 1.0).refresh([STATION])

        rows = _prediction_rows(engine)
        assert {float(row["mean_wait_minutes"]) for row in rows} == {30.0}
        assert {float(row["wait_probability"]) for row in rows} == {1.0}

        # Drop a bucket in the middle: the 12-step window is no longer contiguous.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM station_occupancy_5m WHERE bucket_at = :bucket "
                    "AND station_id = (SELECT id FROM stations WHERE code = :code)"
                ),
                {"bucket": buckets[6], "code": STATION},
            )
        assert DatabaseOccupancyHistoryRepository(engine, _geo_table()).window(STATION) is None

        _writer(engine, 1.0).refresh([STATION])
        assert {row["source"] for row in _prediction_rows(engine)} == {"persistence"}
    finally:
        _cleanup(engine, buckets)


@REQUIRES_DATABASE
def test_occupancy_ingest_refreshes_the_prediction_slots() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    newest = occupancy_bucket(datetime.now(UTC))
    history = [newest - timedelta(minutes=5 * index) for index in range(1, 13)]
    statuses = DatabaseStationStatusRepository(engine, stale_after_s=900)
    original = {
        key: getattr(app.state, key)
        for key in (
            "settings", "station_repository", "station_status_repository",
            "station_state_repository", "runtime_state", "prediction_writer",
        )
    }
    app.state.settings = replace(app.state.settings, internal_api_key="integration-test-key")
    app.state.station_repository = DatabaseStationRepository(engine)
    app.state.station_status_repository = statuses
    app.state.station_state_repository = DatabaseStationStateRepository(engine)
    app.state.runtime_state = RuntimeStateStore(statuses)
    app.state.prediction_writer = _writer(engine, 0.5)
    try:
        _report(engine, history, [1] * 12)

        async def post() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post(
                    "/api/v1/internal/station-occupancy",
                    json={
                        "updates": [
                            {
                                "stationId": STATION,
                                "reportedAt": newest.isoformat(),
                                "operationalPorts": 4,
                                "occupiedPorts": 2,
                            }
                        ]
                    },
                    headers=HEADERS,
                )

        response = asyncio.run(post())

        assert response.status_code == 200
        rows = _prediction_rows(engine)
        assert len(rows) == 6
        assert {row["model_version"] for row in rows} == {"stub-test-v1"}
        assert all(float(row["predicted_occupancy_ratio"]) == pytest.approx(0.5) for row in rows)
    finally:
        for key, value in original.items():
            setattr(app.state, key, value)
        _cleanup(engine, [newest, *history])
