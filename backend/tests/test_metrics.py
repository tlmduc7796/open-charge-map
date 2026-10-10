import asyncio
from dataclasses import replace

import httpx

import backend.app.main as main_module
from backend.app.domain.models import OccupancyForecastResult
from backend.app.main import app


def test_prometheus_metrics_expose_http_response_metrics_without_raw_paths() -> None:
    station_status = app.state.domain_data.station_statuses.get("ST_EVO_DEUTSCHES_HAUS")
    forecast = app.state.occupancy_forecast_service.forecast_occupancy(
        station_status,
        horizon_min=10,
    )
    assert forecast.prediction_source == "persistence"

    async def request_unknown_paths_and_metrics() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/not-found/private-journey-123")
            await client.get("/health/live")
            response = await client.get("/metrics")
            public_path_response = await client.get("/api/metrics")
            return response, public_path_response

    metrics, public_path = asyncio.run(request_unknown_paths_and_metrics())
    body = metrics.text

    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain; version=")
    assert "smart_ev_http_responses_total" in body
    assert 'smart_ev_occupancy_forecasts_total{source="persistence"}' in body
    assert 'smart_ev_occupancy_fallbacks_total{reason="model_unavailable"}' in body
    assert "smart_ev_routing_provider_events_total" in body or (
        'smart_ev_routing_provider_events_total{provider="goong",event="failure"}' in body
    )
    assert 'smart_ev_station_status_records{freshness="eligible"}' in body
    assert 'smart_ev_station_status_records{freshness="stale"}' in body
    assert "smart_ev_station_status_metrics_refresh_error" in body
    assert "smart_ev_station_catalog_oldest_source_timestamp_age_seconds" in body
    assert 'smart_ev_station_catalog_timestamp_basis_records{basis="source"}' in body
    assert 'smart_ev_station_catalog_timestamp_basis_records{basis="database_updated_at"}' in body
    assert "smart_ev_station_catalog_future_timestamps" in body
    assert 'smart_ev_occupancy_history_stations{coverage="eligible"}' in body
    assert 'smart_ev_occupancy_history_stations{coverage="covered"}' in body
    assert "smart_ev_occupancy_history_coverage_ratio" in body
    assert "smart_ev_occupancy_history_metrics_refresh_error" in body
    assert 'route="/health/live"' in body
    assert 'route="unmatched"' in body
    assert "/not-found/private-journey-123" not in body
    assert public_path.status_code == 404


def test_occupancy_history_coverage_metrics_use_eligible_stations(monkeypatch) -> None:
    eligible_stations = tuple(
        station
        for station in app.state.domain_data.stations.all()
        if not main_module._station_has_synthetic_data(station)
    )[:2]

    class StationRepository:
        def all(self):
            return eligible_stations

    class CoverageRepository:
        def count_stations_with_complete_history(self, station_ids, *, as_of, steps):
            assert station_ids == tuple(station.station_id for station in eligible_stations)
            assert as_of.tzinfo is not None
            assert steps == app.state.occupancy_forecast_service.lookback_steps
            return 0

    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, demo_mode=False),
    )
    monkeypatch.setattr(app.state, "station_repository", StationRepository())
    monkeypatch.setattr(
        app.state, "occupancy_history_repository", CoverageRepository()
    )

    main_module.record_occupancy_history_coverage(
        tuple(station.station_id for station in eligible_stations)
    )

    assert (
        main_module.occupancy_history_stations.labels("eligible")._value.get()
        == len(eligible_stations)
    )
    assert main_module.occupancy_history_stations.labels("covered")._value.get() == 0
    assert main_module.occupancy_history_coverage_ratio._value.get() == 0
    assert main_module.occupancy_history_metrics_refresh_error._value.get() == 0


def test_forecast_metrics_callback_persists_when_database_is_configured(monkeypatch) -> None:
    class PredictionRepository:
        def __init__(self) -> None:
            self.saved = []

        def save_occupancy_forecasts(self, forecasts) -> int:
            self.saved.extend(forecasts)
            return len(forecasts)

    repository = PredictionRepository()
    monkeypatch.setattr(app.state, "prediction_repository", repository)
    forecast = OccupancyForecastResult(
        station_id="STATION_RELEASE",
        generated_at="2026-10-09T10:00:00Z",
        target_at="2026-10-09T10:05:00Z",
        requested_horizon_min=5,
        used_horizon_min=5,
        predicted_occupancy_ratio=0.5,
        predicted_occupied_ports=1,
        operational_ports=2,
        prediction_source="model",
        model_version="occupancy-release-v1",
        flags=(),
    )

    main_module.persist_occupancy_forecasts((forecast,))

    assert repository.saved == [forecast]


def test_prediction_persistence_failure_does_not_fail_forecast_response(
    monkeypatch, caplog
) -> None:
    class FailingPredictionRepository:
        def save_occupancy_forecasts(self, _forecasts) -> int:
            raise RuntimeError("database host and credentials must not enter logs")

    monkeypatch.setattr(app.state, "prediction_repository", FailingPredictionRepository())
    failures_before = main_module.occupancy_prediction_persistence_failures_total._value.get()
    forecast = OccupancyForecastResult(
        station_id="STATION_RELEASE",
        generated_at="2026-10-09T10:00:00Z",
        target_at="2026-10-09T10:05:00Z",
        requested_horizon_min=5,
        used_horizon_min=5,
        predicted_occupancy_ratio=0.5,
        predicted_occupied_ports=1,
        operational_ports=2,
        prediction_source="persistence",
        model_version=None,
        flags=("OBSERVED_HISTORY_UNAVAILABLE",),
    )

    main_module.persist_occupancy_forecasts((forecast,))

    assert (
        main_module.occupancy_prediction_persistence_failures_total._value.get()
        == failures_before + 1
    )
    assert "database host and credentials" not in caplog.text
