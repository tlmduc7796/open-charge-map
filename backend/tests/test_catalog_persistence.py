from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from backend.app.api_v1_models import ApiPoint, SearchRouteRequest, SearchStationsRequest
from backend.app.arrival_rate_repository import DatabaseArrivalRateRepository
from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
    DatabaseVehicleRepository,
)
from backend.app.config import load_settings
from backend.app.database import REQUIRED_DATABASE_REVISION, validate_database
from backend.app.domain import load_domain_data
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.recommendation import (
    RecommendationService,
    RecommendationThresholds,
)
from backend.app.domain.routing import RoutingService
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.domain.search import SearchService
from backend.app.domain.wait_estimation import WaitEstimator
from backend.app.planned_arrival_repository import DatabasePlannedArrivalRepository
from backend.app.search_store import SearchResultStore

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="BACKEND_TEST_DATABASE_URL is required for PostgreSQL integration",
)
def test_database_catalog_serves_active_records_and_synthetic_status() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        stations = DatabaseStationRepository(engine)
        statuses = DatabaseStationStatusRepository(engine)
        vehicles = DatabaseVehicleRepository(engine)

        assert validate_database(engine) == REQUIRED_DATABASE_REVISION

        station_items = stations.all()
        status_items = statuses.all()
        vehicle_items = vehicles.all()

        assert len(station_items) == 102
        assert len({station.station_id for station in station_items}) == len(station_items)
        assert {status.station_id for status in status_items} == {
            station.station_id for station in station_items
        }
        assert all(status.unknown_ports == 0 for status in status_items)
        assert all(status.data_source == "synthetic" for status in status_items)
        assert all(status.queue_length is not None for status in status_items)
        assert all(
            {
                "port_status",
                "occupancy_ratio",
                "queue_length",
                "avg_session_duration_min",
            }
            <= set(status.synthetic_fields)
            for status in status_items
        )
        with engine.connect() as connection:
            readiness = connection.execute(
                text(
                    "SELECT "
                    "count(*) FILTER (WHERE opening_hours IS NULL "
                    "OR opening_hours='null'::jsonb) AS missing_opening, "
                    "count(*) FILTER (WHERE access_level='unknown') AS unknown_access, "
                    "(SELECT count(*) FROM station_arrival_rates) AS arrival_rates "
                    "FROM stations WHERE is_active"
                )
            ).mappings().one()
        assert readiness == {
            "missing_opening": 0,
            "unknown_access": 0,
            "arrival_rates": 102,
        }
        assert len(vehicle_items) == 20
        assert all(vehicle.battery_capacity_kwh > 0 for vehicle in vehicle_items)
        assert all(vehicle.reserve_soc == 0.1 for vehicle in vehicle_items)
        assert all(vehicle.default_target_soc == 0.8 for vehicle in vehicle_items)
        assert all(vehicle.charging_efficiency == 0.9 for vehicle in vehicle_items)
        assert any(vehicle.vehicle_id == "BYD_ATTO3_DYNAMIC_2024_VN" for vehicle in vehicle_items)
        vf9 = next(vehicle for vehicle in vehicle_items if vehicle.vehicle_id == "VF9_ECO_VN")
        assert vf9.max_dc_power_kw == 50
        assert "max_dc_kw" in vf9.synthetic_fields
        assert stations.get(station_items[0].station_id) == station_items[0]
        assert vehicles.get(vehicle_items[0].vehicle_id) == vehicle_items[0]

        candidates = stations.candidates(
            106.705,
            10.7075,
            106.687,
            10.806,
            5_000,
        )
        fixture_data = load_domain_data(load_settings().data_dir)
        assert len(candidates) < len(station_items)
        assert {station.station_id for station in fixture_data.stations.all()} <= {
            station.station_id for station in candidates
        }
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="BACKEND_TEST_DATABASE_URL is required for PostgreSQL integration",
)
def test_recommendation_reads_database_catalog_and_runtime() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    settings = load_settings()
    data = load_domain_data(settings.data_dir)
    stations = DatabaseStationRepository(engine)
    statuses = DatabaseStationStatusRepository(engine)
    vehicles = DatabaseVehicleRepository(engine)
    arrivals = DatabasePlannedArrivalRepository(engine, data.planned_arrivals.all())
    arrival_rates = DatabaseArrivalRateRepository(engine, data.queue_assumptions)
    try:
        runtime = RuntimeStateStore(statuses, data.demo_events)
        routing = RoutingService(data.routes, goong=None, osrm=None)
        forecasting = OccupancyForecastService()
        wait = WaitEstimator(arrival_rates, scoring_wait_cap_min=120)
        service = RecommendationService(
            data,
            runtime,
            arrivals,
            routing,
            forecasting,
            wait,
            RecommendationThresholds(
                max_detour_min=30,
                max_wait_min=120,
                max_charge_min=90,
                soc_risk_buffer=0.2,
            ),
            vehicle_repository=vehicles,
            station_repository=stations,
            candidate_corridor_m=5_000,
        )

        result = service.recommend("SCN_NORMAL")
        scenario = data.demo_scenarios.get("SCN_NORMAL")
        candidate_ids = {
            station.station_id
            for station in stations.candidates(
                scenario.origin.lon,
                scenario.origin.lat,
                scenario.destination.lon,
                scenario.destination.lat,
                5_000,
            )
        }
        result_ids = {
            *(item.station_id for item in result.recommendations),
            *(item.station_id for item in result.excluded_candidates),
        }

        assert result.recommendations
        assert result_ids == candidate_ids
        assert result.vehicle_id == scenario.vehicle_id

        search = SearchService(
            service, routing, vehicles, stations, statuses, runtime,
            arrivals, forecasting, wait, SearchResultStore(), 2,
        )
        origin = ApiPoint(lat=scenario.origin.lat, lng=scenario.origin.lon)
        destination = ApiPoint(
            lat=scenario.destination.lat, lng=scenario.destination.lon
        )
        station_search = search.search_stations(
            SearchStationsRequest(
                origin=origin, vehicle_id=scenario.vehicle_id, battery_pct=55
            ),
            now=scenario.departure_at,
        )
        route_search = search.search_route(
            SearchRouteRequest(
                origin=origin,
                destination=destination,
                vehicle_id="EV_VF5_PLUS",
                battery_pct=14,
            ),
            now=scenario.departure_at,
        )
        assert station_search.stations
        assert route_search.case == "needCharge"
        assert route_search.stations
    finally:
        engine.dispose()
