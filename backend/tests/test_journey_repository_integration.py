"""PostgreSQL/PostGIS integration checks for persistent journey behavior."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from data_platform.release_catalog import ReleaseCatalogVehicle, import_release_catalog
from data_platform.retention import prune_observation_history
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
    DatabaseVehicleRepository,
)
from backend.app.config import load_settings
from backend.app.database import create_database_engine
from backend.app.domain.models import StationCollection
from backend.app.domain.phase7_models import (
    GeoPoint,
    JourneyRecommendationRequest,
    JourneyRecommendationResult,
    LineStringGeometry,
    PlannedArrivalCreateRequest,
    RouteResult,
    TripPositionRequest,
)
from backend.app.domain.realtime import ChargingPortTelemetry, StationTelemetrySnapshot
from backend.app.journey_repository import DatabaseJourneyRepository, IdempotencyConflict
from backend.app.occupancy_history_repository import DatabaseOccupancyHistoryRepository
from backend.app.planned_arrival_repository import DatabasePlannedArrivalRepository
from backend.app.telemetry_repository import DatabaseRealtimeTelemetryStore

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="requires a migrated PostgreSQL/PostGIS integration database",
)


def test_database_rejects_planned_arrival_expiring_at_window_end() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            station_id = connection.scalar(
                text("SELECT id FROM stations WHERE is_active IS TRUE LIMIT 1")
            )
            if station_id is None:
                pytest.skip("integration database has no active station catalog")
            with pytest.raises(IntegrityError) as error:
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO planned_arrivals "
                            "(arrival_id, station_id, eta_at, eta_window_start, "
                            "eta_window_end, expected_energy_kwh, "
                            "expected_charge_duration_min, arrival_probability, "
                            "expires_at, data_source) VALUES "
                            "(:arrival_id, :station_id, :eta_at, :window_start, "
                            ":window_end, 10, 20, 0.8, :expires_at, 'runtime')"
                        ),
                        {
                            "arrival_id": f"CONSTRAINT_{uuid4().hex}",
                            "station_id": station_id,
                            "eta_at": now + timedelta(minutes=10),
                            "window_start": now + timedelta(minutes=5),
                            "window_end": now + timedelta(minutes=15),
                            "expires_at": now + timedelta(minutes=15),
                        },
                    )
            assert "ck_planned_arrivals_expiry_after_eta_window" in str(error.value)
    finally:
        engine.dispose()


def test_api_database_engine_enforces_statement_timeout() -> None:
    engine = create_database_engine(
        load_settings().database_url,
        connect_timeout_s=5,
        statement_timeout_ms=100,
    )
    try:
        with engine.connect() as connection:
            with pytest.raises(OperationalError):
                connection.execute(text("SELECT pg_sleep(0.25)"))
    finally:
        engine.dispose()


def test_database_status_repository_loads_connector_scoped_port_states() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    try:
        status = DatabaseStationStatusRepository(engine).get("ST_VF_LA_VELA")
    finally:
        engine.dispose()

    assert status.port_runtime_statuses is not None
    assert len(status.port_runtime_statuses) == status.total_ports
    assert all(port.connector_types for port in status.port_runtime_statuses)
    assert all(
        port.state in {"available", "charging", "out_of_service", "unknown"}
        for port in status.port_runtime_statuses
    )
    assert "port_runtime_statuses" not in status.model_dump()


def test_postgis_station_radius_and_bbox_search_excludes_synthetic_catalog() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    repository = DatabaseStationRepository(engine)
    first_id, second_id, third_id = uuid4(), uuid4(), uuid4()
    connector_code = f"SEARCH_TEST_{uuid4().hex}"
    first_code = f"SEARCH_TEST_OBSERVED_{first_id.hex}"
    second_code = f"SEARCH_TEST_SYNTHETIC_{second_id.hex}"
    third_code = f"SEARCH_TEST_SYNTHETIC_PROVIDER_{third_id.hex}"
    longitude, latitude = 106.7, 10.78
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO connector_types (code, display_name, current_type) "
                    "VALUES (:code, 'Search test connector', 'DC')"
                ),
                {"code": connector_code},
            )
            for station_id, station_code, provenance, data_origin in (
                (first_id, first_code, "{}", "observed"),
                (
                    second_id,
                    second_code,
                    '{"name":{"origin":"synthetic"}}',
                    "synthetic",
                ),
                (
                    third_id,
                    third_code,
                    '{"name":{"origin":"operator_reviewed",'
                    '"provider":"Synthetic legacy feed"}}',
                    "observed",
                ),
            ):
                connection.execute(
                    text(
                        "INSERT INTO stations "
                        "(id, code, name, address, location, access_level, provenance) "
                        "VALUES (:id, :code, :code, 'Search test', "
                        "ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography, "
                        "'public', CAST(:provenance AS jsonb))"
                    ),
                    {
                        "id": station_id,
                        "code": station_code,
                        "longitude": longitude,
                        "latitude": latitude,
                        "provenance": provenance,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO ports "
                        "(id, station_id, connector_code, label, max_power_kw, data_origin) "
                        "VALUES (:id, :station_id, :connector_code, 'P1', 50, "
                        "CAST(:data_origin AS data_origin))"
                    ),
                    {
                        "id": uuid4(),
                        "station_id": station_id,
                        "connector_code": connector_code,
                        "data_origin": data_origin,
                    },
                )

        radius = repository.within_radius(longitude, latitude, 500, 10)
        bbox = repository.within_bbox(
            longitude - 0.01,
            latitude - 0.01,
            longitude + 0.01,
            latitude + 0.01,
            10,
        )
        radius_ids = {station.station_id for station in radius}
        bbox_ids = {station.station_id for station in bbox}
        assert first_code in radius_ids
        assert second_code not in radius_ids
        assert third_code not in radius_ids
        assert first_code in bbox_ids
        assert second_code not in bbox_ids
        assert third_code not in bbox_ids
        assert repository.filter_ids((first_code, second_code, third_code)) == (first_code,)
        assert repository.filter_ids(
            (first_code, second_code, third_code), include_synthetic=True
        ) == (first_code, second_code, third_code)
        candidate_ids = {
            station.station_id
            for station in repository.candidates(
                longitude - 0.01,
                latitude,
                longitude + 0.01,
                latitude,
                500,
            )
        }
        assert first_code in candidate_ids
        assert second_code not in candidate_ids
        assert third_code not in candidate_ids
        synthetic_candidates = {
            station.station_id
            for station in repository.candidates(
                longitude - 0.01,
                latitude,
                longitude + 0.01,
                latitude,
                500,
                include_synthetic=True,
            )
        }
        assert first_code in synthetic_candidates
        assert second_code in synthetic_candidates
        assert third_code in synthetic_candidates
        all_radius_ids = {
            station.station_id
            for station in repository.within_radius(
                longitude, latitude, 500, 10, include_synthetic=True
            )
        }
        assert {first_code, second_code} <= all_radius_ids
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM stations WHERE id IN "
                    "(:first_id, :second_id, :third_id)"
                ),
                {
                    "first_id": first_id,
                    "second_id": second_id,
                    "third_id": third_id,
                },
            )
            connection.execute(
                text("DELETE FROM connector_types WHERE code=:code"),
                {"code": connector_code},
            )
        engine.dispose()


def test_status_and_latest_telemetry_queries_are_bounded_by_station_ids() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    statuses = DatabaseStationStatusRepository(engine)
    telemetry = DatabaseRealtimeTelemetryStore(engine)
    try:
        all_statuses = statuses.all()
        assert all_statuses, "bootstrap snapshot should include station status rows"
        station_id = all_statuses[0].station_id
        assert statuses.get_many((station_id,)) == (all_statuses[0],)
        assert statuses.get_many((f"missing-{uuid4().hex}",)) == ()
        assert all(
            snapshot.station_id == station_id
            for snapshot in telemetry.get_many((station_id,))
        )
    finally:
        engine.dispose()


def test_database_telemetry_retry_is_idempotent_and_conflicts_are_rejected() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    telemetry = DatabaseRealtimeTelemetryStore(engine)
    observed_at = datetime(2099, 1, 1, 10, 0, tzinfo=UTC)
    station_code: str | None = None
    try:
        with engine.connect() as connection:
            station_code = connection.scalar(
                text("SELECT code FROM stations WHERE is_active IS TRUE LIMIT 1")
            )
        if station_code is None:
            pytest.skip("integration database has no active station catalog")

        snapshot = StationTelemetrySnapshot(
            station_id=station_code,
            observed_at=observed_at,
            ports=(
                ChargingPortTelemetry(
                    port_id="TELEMETRY_RETRY_TEST_PORT",
                    connector_types=("CCS2",),
                    state="available",
                ),
            ),
            data_source="station_api",
        )
        assert telemetry.upsert_with_change(snapshot) == (snapshot, True)
        assert telemetry.upsert_with_change(snapshot) == (snapshot, False)
        newer_snapshot = snapshot.model_copy(
            update={
                "observed_at": observed_at + timedelta(minutes=5),
                "ports": (
                    ChargingPortTelemetry(
                        port_id="TELEMETRY_RETRY_TEST_PORT",
                        connector_types=("CCS2",),
                        state="charging",
                        session_id="TELEMETRY_RETRY_TEST_SESSION",
                    ),
                ),
            }
        )
        assert telemetry.upsert_with_change(newer_snapshot) == (newer_snapshot, True)
        assert telemetry.upsert_with_change(snapshot) == (snapshot, False)
        assert telemetry.get(station_code) == newer_snapshot
        conflicting = snapshot.model_copy(
            update={
                "ports": (
                    ChargingPortTelemetry(
                        port_id="TELEMETRY_RETRY_TEST_PORT",
                        connector_types=("CCS2",),
                        state="offline",
                    ),
                )
            }
        )
        with pytest.raises(
            ValueError, match="different telemetry snapshot already exists"
        ):
            telemetry.upsert(conflicting)
    finally:
        if station_code is not None:
            with engine.begin() as connection:
                station_id = connection.scalar(
                    text("SELECT id FROM stations WHERE code=:code"),
                    {"code": station_code},
                )
                if station_id is not None:
                    connection.execute(
                        text(
                            "DELETE FROM station_telemetry_snapshots "
                            "WHERE station_id=:station_id AND observed_at IN "
                            "(:observed_at, :newer_observed_at)"
                        ),
                        {
                            "station_id": station_id,
                            "observed_at": observed_at,
                            "newer_observed_at": observed_at + timedelta(minutes=5),
                        },
                    )
                    connection.execute(
                        text(
                            "DELETE FROM station_occupancy_5m "
                            "WHERE station_id=:station_id AND bucket_at IN ("
                            "date_bin(interval '5 minutes', :observed_at, "
                            "timestamptz '2000-01-01 00:00:00+00'), "
                            "date_bin(interval '5 minutes', :newer_observed_at, "
                            "timestamptz '2000-01-01 00:00:00+00'))"
                        ),
                        {
                            "station_id": station_id,
                            "observed_at": observed_at,
                            "newer_observed_at": observed_at + timedelta(minutes=5),
                        },
                    )
        engine.dispose()


def test_release_catalog_snapshot_deactivates_missing_reviewed_records() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    first_code = f"RECONCILE_TEST_PRESENT_{uuid4().hex}"
    removed_code = f"RECONCILE_TEST_REMOVED_{uuid4().hex}"
    other_provider_code = f"RECONCILE_TEST_OTHER_PROVIDER_{uuid4().hex}"
    provider = f"RECONCILE_PROVIDER_{uuid4().hex}"
    other_provider = f"RECONCILE_PROVIDER_OTHER_{uuid4().hex}"
    old_vehicle_code = f"RECONCILE_VEHICLE_OLD_{uuid4().hex}"
    current_vehicle_code = f"RECONCILE_VEHICLE_CURRENT_{uuid4().hex}"
    source_updated_at = datetime.now(UTC)

    def make_station(
        code: str,
        station_provider: str = provider,
        port_count: int = 1,
        connector_type: str = "CCS2",
    ) -> dict[str, object]:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [106.7, 10.8]},
            "properties": {
                "station_id": code,
                "provider_station_id": f"provider-{code}",
                "name": "Reviewed reconciliation station",
                "address": "Integration test",
                "operator": "Integration test",
                "total_ports": port_count,
                "connectors": [{
                    "type": connector_type,
                    "current": "AC" if connector_type == "Type2" else "DC",
                    "max_power_kw": 11 if connector_type == "Type2" else 50,
                    "count": port_count, "source": "operator_verified",
                }],
                "amenities": [],
                "opening_hours": None,
                "access": "public",
                "notes": [],
                "source_provider": station_provider,
                "source_updated_at": source_updated_at,
                "synthetic_fields": [],
            },
        }

    def station_snapshot(
        *stations: tuple[str, str],
        port_count_by_code: dict[str, int] | None = None,
        connector_type_by_code: dict[str, str] | None = None,
    ) -> StationCollection:
        return StationCollection.model_validate({
            "type": "FeatureCollection",
            "features": [
                make_station(
                    code,
                    source,
                    (port_count_by_code or {}).get(code, 1),
                    (connector_type_by_code or {}).get(code, "CCS2"),
                )
                for code, source in stations
            ],
        })
    def make_vehicle(code: str) -> ReleaseCatalogVehicle:
        field_provenance = {
            field_name: {
                "origin": "observed",
                "provider": "integration test specification",
                "source_ref": f"test:{code}:{field_name}",
            }
            for field_name in (
                "battery_capacity_kwh",
                "usable_battery_kwh",
                "max_ac_power_kw",
                "max_dc_power_kw",
                "ac_connectors",
                "dc_connectors",
                "consumption_wh_km",
            )
        }
        field_provenance.update(
            {
                field_name: {
                    "origin": "operator_policy",
                    "provider": "integration test policy",
                    "policy_id": f"test-policy:{field_name}",
                }
                for field_name in (
                    "reserve_soc",
                    "default_target_soc",
                    "charging_efficiency",
                )
            }
        )
        return ReleaseCatalogVehicle(
            vehicle_id=code,
            make="Integration",
            model="EV",
            variant=None,
            battery_capacity_kwh=70,
            usable_battery_kwh=65,
            max_ac_power_kw=11,
            max_dc_power_kw=100,
            ac_connectors=("Type2",),
            dc_connectors=("CCS2",),
            consumption_wh_km=180,
            reserve_soc=0.1,
            default_target_soc=0.8,
            charging_efficiency=0.9,
            source="integration test specification",
            is_synthetic=False,
            synthetic_fields=(),
            field_provenance=field_provenance,
        )

    old_vehicle = make_vehicle(old_vehicle_code)
    current_vehicle = make_vehicle(current_vehicle_code)
    try:
        initial = import_release_catalog(
            engine,
            station_snapshot(
                (first_code, provider),
                (removed_code, provider),
                (other_provider_code, other_provider),
            ),
            (old_vehicle,),
            apply=True,
            reviewed_by="integration-test",
            port_external_ids={
                first_code: {"CCS2-1": f"provider-port-old-{first_code}"}
            },
        )
        assert initial["deactivated_stations"] == 0
        assert initial["deactivated_vehicles"] == 0
        assert (
            DatabaseStationRepository(engine)
            .get(first_code)
            .properties.source_updated_at
            == source_updated_at
        )
        assert DatabaseVehicleRepository(engine).get(old_vehicle_code).source == (
            old_vehicle.field_provenance["battery_capacity_kwh"]["source_ref"]
        )
        with engine.connect() as connection:
            initial_port = connection.execute(
                text(
                    "SELECT external_id, provenance->'port_mapping'->>'reviewed_by' "
                    "FROM ports WHERE station_id=(SELECT id FROM stations WHERE code=:code) "
                    "AND label='CCS2-1'"
                ),
                {"code": first_code},
            ).one()
        assert initial_port == (f"provider-port-old-{first_code}", "integration-test")
        import_release_catalog(
            engine,
            station_snapshot(
                (first_code, provider),
                (removed_code, provider),
                (other_provider_code, other_provider),
            ),
            (old_vehicle,),
            apply=True,
            reviewed_by="integration-test-repeat",
        )
        with engine.connect() as connection:
            retained_mapping = connection.execute(
                text(
                    "SELECT external_id, provenance->'port_mapping'->>'reviewed_by' "
                    "FROM ports WHERE station_id=(SELECT id FROM stations WHERE code=:code) "
                    "AND label='CCS2-1'"
                ),
                {"code": first_code},
            ).one()
        assert retained_mapping == (
            f"provider-port-old-{first_code}",
            "integration-test",
        )
        cleared_mapping = import_release_catalog(
            engine,
            station_snapshot(
                (first_code, provider),
                (removed_code, provider),
                (other_provider_code, other_provider),
            ),
            (old_vehicle,),
            apply=True,
            reviewed_by="integration-test-clear",
            port_external_ids={first_code: {"CCS2-1": None}},
        )
        assert cleared_mapping["mapped_port_ids"] == 0
        with engine.connect() as connection:
            cleared_port = connection.execute(
                text(
                    "SELECT external_id, provenance->'port_mapping'->>'reviewed_by', "
                    "provenance->'port_mapping'->'external_id' "
                    "FROM ports WHERE station_id=(SELECT id FROM stations WHERE code=:code) "
                    "AND label='CCS2-1'"
                ),
                {"code": first_code},
            ).one()
        assert cleared_port == (None, "integration-test-clear", None)
        assert DatabaseStationRepository(engine).telemetry_port_inventory(first_code) == (
            ("CCS2-1", "CCS2"),
        )
        observed_at = datetime.now(UTC)
        observed_bucket_at = observed_at.replace(
            minute=(observed_at.minute // 5) * 5, second=0, microsecond=0
        )
        with engine.begin() as connection:
            station_id = connection.scalar(
                text("SELECT id FROM stations WHERE code=:code"),
                {"code": first_code},
            )
            connection.execute(
                text(
                    "INSERT INTO station_telemetry_snapshots "
                    "(station_id, observed_at, data_source, snapshot) "
                    "VALUES (:station_id, :observed_at, 'station_api', '{}'::jsonb)"
                ),
                {"station_id": station_id, "observed_at": observed_at},
            )
            connection.execute(
                text(
                    "INSERT INTO station_occupancy_5m "
                    "(station_id, bucket_at, total_ports, operational_ports, "
                    "occupied_ports, queue_length, data_origin) "
                    "VALUES (:station_id, :observed_at, 1, 1, 0, 0, 'observed')"
                ),
                {"station_id": station_id, "observed_at": observed_bucket_at},
            )

        mapped_again = import_release_catalog(
            engine,
            station_snapshot(
                (first_code, provider),
                (removed_code, provider),
                (other_provider_code, other_provider),
            ),
            (old_vehicle,),
            apply=True,
            reviewed_by="integration-test",
            port_external_ids={
                first_code: {"CCS2-1": f"provider-port-mid-{first_code}"}
            },
        )
        assert mapped_again["invalidated_telemetry_snapshots"] == 1
        observed_at_after_mapping = observed_at + timedelta(minutes=10)
        observed_bucket_after_mapping = observed_bucket_at + timedelta(minutes=10)
        with engine.begin() as connection:
            station_id = connection.scalar(
                text("SELECT id FROM stations WHERE code=:code"),
                {"code": first_code},
            )
            connection.execute(
                text(
                    "INSERT INTO station_telemetry_snapshots "
                    "(station_id, observed_at, data_source, snapshot) "
                    "VALUES (:station_id, :observed_at, 'station_api', '{}'::jsonb)"
                ),
                {"station_id": station_id, "observed_at": observed_at_after_mapping},
            )
            connection.execute(
                text(
                    "INSERT INTO station_occupancy_5m "
                    "(station_id, bucket_at, total_ports, operational_ports, "
                    "occupied_ports, queue_length, data_origin) "
                    "VALUES (:station_id, :observed_at, 1, 1, 0, 0, 'observed')"
                ),
                {
                    "station_id": station_id,
                    "observed_at": observed_bucket_after_mapping,
                },
            )

        reconciled = import_release_catalog(
            engine,
            station_snapshot((first_code, provider), port_count_by_code={first_code: 2}),
            (current_vehicle,),
            apply=True,
            reviewed_by="integration-test",
            replace_snapshot=True,
            port_external_ids={
                first_code: {
                    "CCS2-1": f"provider-port-new-{first_code}-1",
                    "CCS2-2": f"provider-port-new-{first_code}-2",
                }
            },
        )
        assert reconciled["deactivated_stations"] == 1
        assert reconciled["deactivated_vehicles"] == 1
        with engine.connect() as connection:
            states = dict(connection.execute(
                text(
                    "SELECT code, is_active FROM stations "
                    "WHERE code IN (:present, :removed, :other)"
                ),
                {"present": first_code, "removed": removed_code,
                 "other": other_provider_code},
            ).all())
            vehicle_states = dict(connection.execute(
                text(
                    "SELECT code, is_active FROM vehicle_models "
                    "WHERE code IN (:old, :current)"
                ),
                {"old": old_vehicle_code, "current": current_vehicle_code},
            ).all())
            remaining_runtime_snapshots = connection.scalar(
                text(
                    "SELECT count(*) FROM station_telemetry_snapshots "
                    "WHERE station_id=(SELECT id FROM stations WHERE code=:code)"
                ),
                {"code": first_code},
            )
            retained_occupancy = connection.scalar(
                text(
                    "SELECT count(*) FROM station_occupancy_5m "
                    "WHERE station_id=(SELECT id FROM stations WHERE code=:code) "
                    "AND bucket_at=date_bin(interval '5 minutes', :observed_at, "
                    "timestamptz '2000-01-01 00:00:00+00')"
                ),
                {"code": first_code, "observed_at": observed_at},
            )
            retained_mapped_occupancy = connection.scalar(
                text(
                    "SELECT count(*) FROM station_occupancy_5m "
                    "WHERE station_id=(SELECT id FROM stations WHERE code=:code) "
                    "AND bucket_at=:observed_at"
                ),
                {"code": first_code, "observed_at": observed_bucket_after_mapping},
            )
        assert states == {
            first_code: True,
            removed_code: False,
            other_provider_code: True,
        }
        assert vehicle_states == {old_vehicle_code: False, current_vehicle_code: True}
        assert remaining_runtime_snapshots == 0
        assert retained_occupancy == 1
        assert retained_mapped_occupancy == 1
        assert DatabaseStationRepository(engine).telemetry_port_inventory(first_code) == (
            (f"provider-port-new-{first_code}-1", "CCS2"),
            (f"provider-port-new-{first_code}-2", "CCS2"),
        )
        with engine.begin() as connection:
            port_ids = connection.execute(
                text(
                    "SELECT id FROM ports WHERE station_id="
                    "(SELECT id FROM stations WHERE code=:code) ORDER BY label"
                ),
                {"code": first_code},
            ).scalars().all()
            assert len(port_ids) == 2
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE ports SET external_id=:external_id WHERE id=:id"),
                        {
                            "external_id": f"provider-port-new-{first_code}-1",
                            "id": port_ids[1],
                        },
                    )
        connector_replacement = import_release_catalog(
            engine,
            station_snapshot(
                (first_code, provider),
                connector_type_by_code={first_code: "Type2"},
            ),
            (current_vehicle,),
            apply=True,
            reviewed_by="integration-test-connector-change",
            port_external_ids={
                first_code: {"TYPE2-1": f"provider-port-new-{first_code}-1"}
            },
        )
        assert connector_replacement["invalidated_telemetry_snapshots"] == 0
        assert DatabaseStationRepository(engine).telemetry_port_inventory(first_code) == (
            (f"provider-port-new-{first_code}-1", "TYPE2"),
        )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM stations WHERE code IN (:present, :removed, :other)"),
                {"present": first_code, "removed": removed_code,
                 "other": other_provider_code},
            )
            connection.execute(
                text("DELETE FROM vehicle_models WHERE code IN (:old, :current)"),
                {"old": old_vehicle_code, "current": current_vehicle_code},
            )
        engine.dispose()


def _journey_payload(journey_id: str) -> tuple[
    JourneyRecommendationRequest, JourneyRecommendationResult
]:
    origin = GeoPoint(lat=10.7769, lon=106.7008)
    destination = GeoPoint(lat=10.8231, lon=106.6297)
    route = RouteResult(
        route_id=f"INTEGRATION_{journey_id}",
        provider="osrm",
        resolution_source="live",
        origin=origin,
        destination=destination,
        waypoints=(),
        geometry=LineStringGeometry(
            type="LineString",
            coordinates=((origin.lon, origin.lat), (destination.lon, destination.lat)),
        ),
        distance_m=8_000,
        duration_s=900,
    )
    request = JourneyRecommendationRequest(
        vehicle_id="EV_VF5_PLUS",
        initial_soc=0.7,
        target_soc=0.8,
        origin=origin,
        destination=destination,
        departure_at=datetime.now(UTC),
    )
    result = JourneyRecommendationResult(
        scenario_id=None,
        journey_id=journey_id,
        generated_at=request.departure_at,
        vehicle_id="EV_VF5_PLUS",
        direct_route=route,
        outcome="direct_no_charge",
        recommendations=(),
        excluded_candidates=(),
        active_event_ids=(),
    )
    return request, result


def test_journey_create_replay_replan_and_revoke() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    repository = DatabaseJourneyRepository(engine)
    arrival_repository = DatabasePlannedArrivalRepository(engine, ())
    journey_id = uuid4()
    journey_id_text = str(journey_id)
    idempotency_key = f"integration-{uuid4()}"
    access_token = "integration-capability-token"
    request, result = _journey_payload(journey_id_text)
    arrival_id = f"JOURNEY_ARRIVAL_{uuid4().hex.upper()}"

    try:
        saved = repository.save(
            request,
            result,
            access_token=access_token,
            access_token_ttl_days=1,
            idempotency_key=idempotency_key,
            idempotency_request=request,
        )
        assert saved.journey_id == journey_id_text
        loaded = repository.get(journey_id, access_token=access_token)
        assert loaded["recommendation"]["journey_id"] == journey_id_text
        position = TripPositionRequest(
            recorded_at=datetime.now(UTC),
            location=request.origin,
            speed_kmh=23.4567,
            heading=123.4567,
            battery_pct=62.3456,
            distance_km=4.56789,
        )
        first_position = repository.record_position(
            journey_id,
            position,
            access_token=access_token,
            deviation_threshold_m=500,
            min_reroute_interval_min=10,
        )
        repeated_position = repository.record_position(
            journey_id,
            position,
            access_token=access_token,
            deviation_threshold_m=500,
            min_reroute_interval_min=10,
        )
        assert first_position["duplicate"] is False
        assert repeated_position["duplicate"] is True
        early_replay = repository.lookup_idempotent(
            request,
            idempotency_key,
            access_token=access_token,
            access_token_ttl_days=1,
        )
        assert early_replay is not None
        assert early_replay.journey_id == journey_id_text
        with engine.connect() as connection:
            station_code = connection.scalar(
                text("SELECT code FROM stations WHERE is_active ORDER BY code LIMIT 1")
            )
        assert station_code is not None
        now = datetime.now(UTC)
        arrival_request = PlannedArrivalCreateRequest(
            arrival_id=arrival_id,
            journey_id=journey_id,
            station_id=station_code,
            eta_at=now + timedelta(minutes=10),
            eta_window_start=now + timedelta(minutes=5),
            eta_window_end=now + timedelta(minutes=15),
            expected_energy_kwh=10.12345,
            expected_charge_duration_min=20.67895,
            arrival_probability=0.8123456,
            expires_at=now + timedelta(hours=1),
        )
        created_arrival = arrival_repository.register(
            arrival_request,
            created_at=now,
        )
        replayed_arrival = arrival_repository.register(
            arrival_request,
            created_at=now + timedelta(seconds=1),
        )
        assert replayed_arrival.arrival_id == created_arrival.arrival_id
        assert replayed_arrival.created_at == created_arrival.created_at
        assert (
            arrival_repository.active_for_journey(journey_id_text).arrival_id
            == arrival_id
        )

        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM journey_recommendations WHERE journey_id=:id"),
                {"id": journey_id},
            ) == 1

        retry_result = result.model_copy(update={"journey_id": str(uuid4())})
        replayed = repository.save(
            request,
            retry_result,
            access_token=access_token,
            access_token_ttl_days=1,
            idempotency_key=idempotency_key,
            idempotency_request=request,
        )
        assert replayed.journey_id == journey_id_text

        changed_request = request.model_copy(update={"initial_soc": 0.6})
        with pytest.raises(IdempotencyConflict):
            repository.lookup_idempotent(
                changed_request,
                idempotency_key,
                access_token=access_token,
                access_token_ttl_days=1,
            )
        with pytest.raises(IdempotencyConflict):
            repository.save(
                changed_request,
                retry_result,
                access_token=access_token,
                access_token_ttl_days=1,
                idempotency_key=idempotency_key,
                idempotency_request=changed_request,
            )

        replanned_request = request.model_copy(
            update={
                "departure_at": request.departure_at + timedelta(minutes=15),
                "origin": GeoPoint(lat=10.78, lon=106.70),
            }
        )
        replanned_route = result.direct_route.model_copy(
            update={"origin": replanned_request.origin}
        )
        replanned_result = result.model_copy(
            update={
                "generated_at": replanned_request.departure_at,
                "direct_route": replanned_route,
            }
        )
        repository.save_replan(journey_id, replanned_request, replanned_result)
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM journey_recommendations WHERE journey_id=:id"),
                {"id": journey_id},
            ) == 2

        repository.revoke_access(journey_id, access_token=access_token)
        with pytest.raises(PermissionError):
            repository.get(journey_id, access_token=access_token)
        with pytest.raises(IdempotencyConflict, match="revoked"):
            repository.save(
                request,
                retry_result,
                access_token=access_token,
                access_token_ttl_days=1,
                idempotency_key=idempotency_key,
                idempotency_request=request,
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM planned_arrivals WHERE arrival_id=:arrival_id"),
                {"arrival_id": arrival_id},
            )
            connection.execute(
                text("DELETE FROM trips WHERE id=:id"), {"id": journey_id}
            )
        engine.dispose()


def test_occupancy_history_coverage_requires_twelve_recent_contiguous_observations() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    repository = DatabaseOccupancyHistoryRepository(engine)
    station_id = uuid4()
    station_code = f"COVERAGE_TEST_{station_id.hex}"
    now = datetime.now(UTC)
    aligned_now = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
    steps = 12
    oldest_bucket = aligned_now - timedelta(minutes=(steps - 1) * 5)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO stations (id, code, name, address, location, access_level) "
                    "VALUES (:id, :code, 'Coverage test', 'Test', "
                    "ST_SetSRID(ST_MakePoint(0,0),4326)::geography, 'public')"
                ),
                {"id": station_id, "code": station_code},
            )
            for index in range(steps):
                connection.execute(
                    text(
                        "INSERT INTO station_occupancy_5m "
                        "(station_id, bucket_at, total_ports, operational_ports, "
                        "occupied_ports, queue_length, data_origin) VALUES "
                        "(:station_id, :bucket_at, 1, 1, 0, 0, 'observed')"
                    ),
                    {
                        "station_id": station_id,
                        "bucket_at": oldest_bucket + timedelta(minutes=index * 5),
                    },
                )

        assert repository.count_stations_with_complete_history(
            (station_code,), as_of=now, steps=steps
        ) == 1
        observations = repository.get_observations(
            station_code,
            start_at=oldest_bucket,
            end_at=aligned_now,
            limit=steps,
        )
        assert len(observations) == steps
        assert observations[0]["bucket_at"] == oldest_bucket
        assert all(row["data_origin"] == "observed" for row in observations)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM station_occupancy_5m WHERE station_id=:station_id "
                    "AND bucket_at=:bucket_at"
                ),
                {
                    "station_id": station_id,
                    "bucket_at": oldest_bucket + timedelta(minutes=25),
                },
            )
        assert repository.count_stations_with_complete_history(
            (station_code,), as_of=now, steps=steps
        ) == 0
        assert repository.count_stations_with_complete_history(
            (station_code,), as_of=aligned_now + timedelta(minutes=10), steps=steps
        ) == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM stations WHERE id=:id"), {"id": station_id})
        engine.dispose()


def test_database_planned_arrivals_expire_and_stop_affecting_demand() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    repository = DatabasePlannedArrivalRepository(engine, ())
    now = datetime.now(UTC)
    with engine.connect() as connection:
        station_code = connection.scalar(
            text("SELECT code FROM stations WHERE is_active ORDER BY code LIMIT 1")
        )
    if station_code is None:
        engine.dispose()
        pytest.skip("integration database has no active station catalog")

    arrival_id = f"IT_{uuid4().hex.upper()}"
    request = PlannedArrivalCreateRequest(
        arrival_id=arrival_id,
        station_id=station_code,
        eta_at=now + timedelta(minutes=15),
        eta_window_start=now + timedelta(minutes=10),
        eta_window_end=now + timedelta(minutes=20),
        expected_energy_kwh=10,
        expected_charge_duration_min=20,
        arrival_probability=0.7,
        expires_at=now + timedelta(minutes=21),
    )
    try:
        repository.register(request, created_at=now)
        assert arrival_id in {
            arrival.arrival_id
            for arrival in repository.active_for_stations((station_code,))
        }

        expired = repository.expire(now + timedelta(minutes=22))

        assert arrival_id in {arrival.arrival_id for arrival in expired}
        assert repository.get(arrival_id).status == "expired"
        assert arrival_id not in {
            arrival.arrival_id
            for arrival in repository.active_for_stations((station_code,))
        }
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM planned_arrivals WHERE arrival_id=:arrival_id"),
                {"arrival_id": arrival_id},
            )
        engine.dispose()


def test_observation_retention_previews_then_prunes_old_rows_in_batches() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    station_id = uuid4()
    port_id = uuid4()
    station_code = f"RETENTION_TEST_{station_id.hex}"
    cutoff = datetime(2000, 1, 1, tzinfo=UTC)
    old_at = datetime(1999, 12, 1, 12, 0, tzinfo=UTC)
    recent_at = datetime(2001, 1, 1, 12, 0, tzinfo=UTC)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO stations (id, code, name, address, location, access_level) "
                    "VALUES (:id, :code, 'Retention test', 'Test', "
                    "ST_SetSRID(ST_MakePoint(0,0),4326)::geography, 'public')"
                ),
                {"id": station_id, "code": station_code},
            )
            connection.execute(
                text(
                    "INSERT INTO ports (id, station_id, connector_code, label, "
                    "max_power_kw, data_origin) "
                    "VALUES (:id, :station_id, 'CCS2', 'retention-test', 50, 'observed')"
                ),
                {"id": port_id, "station_id": station_id},
            )
            for observed_at in (old_at, recent_at):
                connection.execute(
                    text(
                        "INSERT INTO station_occupancy_5m "
                        "(station_id, bucket_at, total_ports, operational_ports, "
                        "occupied_ports, queue_length, data_origin) "
                        "VALUES (:station_id, :observed_at, 1, 1, 0, 0, 'observed')"
                    ),
                    {"station_id": station_id, "observed_at": observed_at},
                )
                connection.execute(
                    text(
                        "INSERT INTO port_status_history "
                        "(port_id, status, changed_at, data_origin) "
                        "VALUES (:port_id, 'available', :observed_at, 'observed')"
                    ),
                    {"port_id": port_id, "observed_at": observed_at},
                )
                connection.execute(
                    text(
                        "INSERT INTO station_telemetry_snapshots "
                        "(station_id, observed_at, data_source, snapshot) "
                        "VALUES (:station_id, :observed_at, 'station_api', '{}'::jsonb)"
                    ),
                    {"station_id": station_id, "observed_at": observed_at},
                )

        preview = prune_observation_history(engine, cutoff=cutoff, batch_size=1)
        assert preview == {
            "predictions": {"eligible": 0, "deleted": 0},
            "station_occupancy_5m": {"eligible": 1, "deleted": 0},
            "port_status_history": {"eligible": 1, "deleted": 0},
            "station_telemetry_snapshots": {"eligible": 1, "deleted": 0},
        }

        applied = prune_observation_history(
            engine, cutoff=cutoff, apply=True, batch_size=1
        )
        assert applied == {
            "predictions": {"eligible": 0, "deleted": 0},
            "station_occupancy_5m": {"eligible": 1, "deleted": 1},
            "port_status_history": {"eligible": 1, "deleted": 1},
            "station_telemetry_snapshots": {"eligible": 1, "deleted": 1},
        }
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM station_occupancy_5m "
                    "WHERE station_id=:station_id AND bucket_at=:observed_at"
                ),
                {"station_id": station_id, "observed_at": recent_at},
            ) == 1
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM station_telemetry_snapshots "
                    "WHERE station_id=:station_id AND observed_at=:observed_at"
                ),
                {"station_id": station_id, "observed_at": recent_at},
            ) == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM stations WHERE id=:id"), {"id": station_id})
        engine.dispose()
