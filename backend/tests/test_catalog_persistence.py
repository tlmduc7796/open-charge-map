from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from backend.app.api_v1_models import PortStatusUpdate
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
from backend.app.station_state_repository import DatabaseStationStateRepository
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
        # Seed creates one placeholder row per port with status 'unknown': nothing is known
        # to be free, busy or offline until the backend reports.
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
        assert placeholders["ports"] == placeholders["placeholders"] == 200
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


def _restore_placeholders(engine, port_ids: list[str]) -> None:
    """Undo test writes so the shared test database keeps its seeded placeholder state."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE port_status SET status='unknown', session_started_at=NULL, "
                "estimated_finish_at=NULL, reported_at=NULL "
                "WHERE port_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": port_ids},
        )
        connection.execute(
            text(
                "DELETE FROM port_status_history WHERE port_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": port_ids},
        )


@REQUIRES_DATABASE
def test_recommendation_excludes_stations_until_state_and_queue_exist() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    settings = load_settings()
    data = load_domain_data(settings.data_dir)
    stations = DatabaseStationRepository(engine)
    statuses = DatabaseStationStatusRepository(engine)
    vehicles = DatabaseVehicleRepository(engine)
    state = DatabaseStationStateRepository(engine)
    port_ids: list[str] = []
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
            vehicle_id="EV_VF7_ECO",
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

        # 1. Every port is 'unknown': no station is operational, so none can be recommended.
        result = service.recommend(query)
        reasons = {
            item.station_id: set(item.reason_codes) for item in result.excluded_candidates
        }
        assert not result.recommendations
        assert set(reasons) == candidate_ids
        station_id = "ST_VF_LA_VELA"
        assert "STATION_OFFLINE" in reasons[station_id]

        # 2. Once the backend reports port state, the station is no longer offline, but the
        #    demo schema has no queue/session source, so wait estimation still has no input.
        with engine.connect() as connection:
            port_ids = connection.execute(
                text(
                    "SELECT p.id::text FROM ports p JOIN stations s ON s.id = p.station_id "
                    "WHERE s.code = :code"
                ),
                {"code": station_id},
            ).scalars().all()
        now = datetime.now(UTC)
        updated, ignored = state.update_batch(
            tuple(
                PortStatusUpdate(port_id=port_id, status="available", reported_at=now)
                for port_id in port_ids
            ),
            ingested_at=now,
        )
        assert (updated, ignored) == (len(port_ids), 0)
        runtime.refresh()
        after = service.recommend(query)
        codes_after = {
            item.station_id: set(item.reason_codes) for item in after.excluded_candidates
        }
        assert "STATION_OFFLINE" not in codes_after.get(station_id, set())
        assert "WAIT_INPUT_UNAVAILABLE" in codes_after.get(station_id, set())
    finally:
        if port_ids:
            _restore_placeholders(engine, port_ids)
        engine.dispose()
