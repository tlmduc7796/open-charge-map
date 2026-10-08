from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine

from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
    DatabaseVehicleRepository,
)

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

        station_items = stations.all()
        status_items = statuses.all()
        vehicle_items = vehicles.all()

        assert station_items
        assert len({station.station_id for station in station_items}) == len(station_items)
        assert {status.station_id for status in status_items} == {
            station.station_id for station in station_items
        }
        assert all(status.unknown_ports == 0 for status in status_items)
        assert all(status.data_source == "synthetic" for status in status_items)
        assert all(status.queue_length is not None for status in status_items)
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
    finally:
        engine.dispose()
