from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from backend.app.api_v1_models import StationOccupancyUpdate
from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
    DatabaseVehicleRepository,
)
from backend.app.config import load_settings
from backend.app.database import validate_database
from backend.app.domain import load_domain_data
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.phase7_models import (
    GeoPoint,
    JourneyQuery,
    RecommendationPreference,
)
from backend.app.domain.recommendation import (
    RecommendationService,
    RecommendationThresholds,
)
from backend.app.domain.routing import RoutingService
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.domain.wait_estimation import WaitEstimator
from backend.app.station_state_repository import (
    DatabaseStationStateRepository,
    occupancy_bucket,
)
from backend.tests.conftest import StraightLineRoutingProvider

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")
REQUIRES_DATABASE = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="BACKEND_TEST_DATABASE_URL is required for PostgreSQL integration",
)


@REQUIRES_DATABASE
def test_database_catalog_serves_stations_with_unknown_port_status() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        stations = DatabaseStationRepository(engine)
        statuses = DatabaseStationStatusRepository(engine)
        vehicles = DatabaseVehicleRepository(engine)

        assert validate_database(engine) == "ready"

        station_items = stations.all()
        status_items = statuses.all()
        vehicle_items = vehicles.all()

        assert len(station_items) == 11
        assert len({station.station_id for station in station_items}) == len(station_items)
        assert {status.station_id for status in status_items} == {
            station.station_id for station in station_items
        }
        # A freshly bootstrapped database has no station_occupancy_5m bucket: nothing is known
        # to be free, busy or offline until an occupancy report arrives.
        assert all(status.unknown_ports == status.total_ports for status in status_items)
        assert all(status.available_ports == 0 for status in status_items)
        assert all(status.operational_ports == 0 for status in status_items)
        assert all(status.data_source == "unknown" for status in status_items)
        assert all(status.queue_length is None for status in status_items)
        assert all(status.avg_session_duration_min is None for status in status_items)
        assert all(station.properties.amenities == () for station in station_items)

        with engine.connect() as connection:
            readiness = connection.execute(
                text(
                    "SELECT "
                    "count(*) FILTER (WHERE opening_hours IS NULL "
                    "OR opening_hours='null'::jsonb) AS missing_opening, "
                    "count(*) FILTER (WHERE access_level='unknown') AS unknown_access "
                    "FROM stations WHERE is_active"
                )
            ).mappings().one()
            placeholders = connection.execute(
                text(
                    "SELECT count(*) AS ports, "
                    "count(*) FILTER (WHERE status = 'unknown' AND reported_at IS NULL) "
                    "AS placeholders FROM port_status"
                )
            ).mappings().one()
            prediction_slots = connection.execute(
                text(
                    "SELECT count(*) AS slots, "
                    "count(*) FILTER (WHERE run_at IS NULL AND predicted_occupancy_ratio IS NULL "
                    "AND mean_wait_minutes IS NULL AND prediction_source IS NULL) AS empty "
                    "FROM predictions"
                )
            ).mappings().one()
        assert readiness == {"missing_opening": 0, "unknown_access": 0}
        assert placeholders["ports"] == placeholders["placeholders"] > 0
        assert prediction_slots["slots"] == prediction_slots["empty"] == 66

        assert len(vehicle_items) == 18
        assert all(vehicle.battery_capacity_kwh > 0 for vehicle in vehicle_items)
        assert all(vehicle.reserve_soc == 0.1 for vehicle in vehicle_items)
        assert all(vehicle.default_target_soc == 1.0 for vehicle in vehicle_items)
        assert all(vehicle.charging_efficiency == 0.9 for vehicle in vehicle_items)
        assert all(vehicle.make == "VinFast" for vehicle in vehicle_items)
        vf9 = next(vehicle for vehicle in vehicle_items if vehicle.vehicle_id == "VF9_ECO_VN")
        assert vf9.max_dc_power_kw == 50
        assert stations.get(station_items[0].station_id) == station_items[0]
        assert vehicles.get(vehicle_items[0].vehicle_id) == vehicle_items[0]

        candidates = stations.candidates(106.705, 10.7075, 106.687, 10.806, 5_000)
        fixture_data = load_domain_data(load_settings().data_dir)
        assert len(candidates) <= len(station_items)
        assert {station.station_id for station in candidates} <= {
            station.station_id for station in fixture_data.stations.all()
        }
        assert all(station.properties.operator == "VinFast" for station in station_items)
    finally:
        engine.dispose()


def _remove_bucket(engine, station_code: str, bucket_at: datetime) -> None:
    """Undo the test's occupancy write so the shared test database stays as bootstrapped."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM station_occupancy_5m WHERE bucket_at = :bucket_at AND station_id = "
                "(SELECT id FROM stations WHERE code = :code)"
            ),
            {"bucket_at": bucket_at, "code": station_code},
        )


@REQUIRES_DATABASE
def test_recommendation_excludes_stations_until_occupancy_is_reported() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    settings = load_settings()
    data = load_domain_data(settings.data_dir)
    stations = DatabaseStationRepository(engine)
    statuses = DatabaseStationStatusRepository(engine)
    vehicles = DatabaseVehicleRepository(engine)
    state = DatabaseStationStateRepository(engine)
    reported_bucket: datetime | None = None
    try:
        runtime = RuntimeStateStore(statuses)
        service = RecommendationService(
            runtime,
            RoutingService(goong=StraightLineRoutingProvider(), osrm=None),
            OccupancyForecastService(),
            WaitEstimator(data.queue_assumptions, scoring_wait_cap_min=120),
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
        query = JourneyQuery(
            vehicle_id="EV_VF5_PLUS",
            initial_soc=0.55,
            target_soc=0.8,
            origin=GeoPoint(lat=10.7075, lon=106.705),
            destination=GeoPoint(lat=10.806, lon=106.687),
            departure_at=datetime.fromisoformat("2026-09-25T18:00:00+07:00"),
            preference=RecommendationPreference(
                wait_weight=0.25,
                detour_weight=0.25,
                charging_time_weight=0.25,
                soc_risk_weight=0.25,
            ),
        )
        candidate_ids = {
            station.station_id
            for station in stations.candidates(
                query.origin.lon,
                query.origin.lat,
                query.destination.lon,
                query.destination.lat,
                5_000,
            )
        }

        # 1. No station has an occupancy bucket: none is operational, so none can be recommended.
        result = service.recommend(query)
        reasons = {
            item.station_id: set(item.reason_codes) for item in result.excluded_candidates
        }
        assert not result.recommendations
        assert set(reasons) == candidate_ids
        station_id = "ST_VF_LA_VELA"
        assert "STATION_OFFLINE" in reasons[station_id]

        # 2. Once the station reports how many ports are in use, it is no longer offline and
        #    can be recommended (arrival rates come from the fixture baseline).
        with engine.connect() as connection:
            total_ports = connection.scalar(
                text(
                    "SELECT count(*) FROM ports p JOIN stations s ON s.id = p.station_id "
                    "WHERE s.code = :code AND p.is_active"
                ),
                {"code": station_id},
            )
        now = datetime.now(UTC)
        reported_bucket = occupancy_bucket(now)
        written = state.record_occupancy(
            (
                StationOccupancyUpdate(
                    station_id=station_id,
                    reported_at=now,
                    operational_ports=total_ports,
                    occupied_ports=1,
                ),
            )
        )
        assert written == 1
        runtime.refresh()
        status = statuses.get(station_id)
        assert (status.total_ports, status.occupied_ports) == (total_ports, 1)
        assert status.available_ports == total_ports - 1
        after = service.recommend(query)
        codes_after = {
            item.station_id: set(item.reason_codes) for item in after.excluded_candidates
        }
        assert "STATION_OFFLINE" not in codes_after.get(station_id, set())
        assert station_id in {item.station_id for item in after.recommendations}
    finally:
        if reported_bucket is not None:
            _remove_bucket(engine, "ST_VF_LA_VELA", reported_bucket)
        engine.dispose()
