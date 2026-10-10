"""Release readiness against a migrated PostgreSQL/PostGIS integration DB."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from data_platform.release_catalog import ReleaseCatalogVehicle, import_release_catalog
from sqlalchemy import create_engine, text

import backend.app.main as main_module
from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
    DatabaseVehicleRepository,
)
from backend.app.domain.models import StationCollection
from backend.app.domain.realtime import ChargingPortTelemetry, StationTelemetrySnapshot
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.telemetry_repository import DatabaseRealtimeTelemetryStore

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="requires a migrated PostgreSQL/PostGIS integration database",
)


class AvailableRedis:
    async def ping(self) -> bool:
        return True

    async def eval(self, _script: str, _numkeys: int, *_keys_and_args: str) -> list[int]:
        return [1, 60]


class AvailableJwks:
    def get_signing_keys(self) -> list[object]:
        return [object()]


def _release_vehicle(vehicle_id: str) -> ReleaseCatalogVehicle:
    field_provenance = {
        field_name: {
            "origin": "observed",
            "provider": "release-readiness integration fixture",
            "source_ref": f"integration:{vehicle_id}:{field_name}",
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
                "provider": "release-readiness integration policy",
                "policy_id": f"integration-policy:{field_name}",
            }
            for field_name in (
                "reserve_soc",
                "default_target_soc",
                "charging_efficiency",
            )
        }
    )
    return ReleaseCatalogVehicle(
        vehicle_id=vehicle_id,
        make="Integration",
        model="Release EV",
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
        source="release-readiness integration fixture",
        is_synthetic=False,
        synthetic_fields=(),
        field_provenance=field_provenance,
    )


def test_release_readiness_uses_persisted_catalog_and_telemetry(monkeypatch) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration")

    engine = create_engine(database_url, pool_pre_ping=True)
    station_id = f"READINESS_STATION_{uuid4().hex}"
    vehicle_id = f"READINESS_VEHICLE_{uuid4().hex}"
    provider = f"READINESS_PROVIDER_{uuid4().hex}"
    source_updated_at = datetime.now(UTC)
    station_payload = StationCollection.model_validate(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [106.7, 10.8]},
                    "properties": {
                        "station_id": station_id,
                        "provider_station_id": f"provider-{station_id}",
                        "name": "Release readiness integration station",
                        "address": "Integration test",
                        "operator": "Integration test",
                        "total_ports": 1,
                        "connectors": [
                            {
                                "type": "CCS2",
                                "current": "DC",
                                "max_power_kw": 50,
                                "count": 1,
                                "source": "operator_verified",
                            }
                        ],
                        "amenities": [],
                        "opening_hours": None,
                        "access": "public",
                        "notes": [],
                        "source_provider": provider,
                        "source_updated_at": source_updated_at,
                        "synthetic_fields": [],
                    },
                }
            ],
        }
    )
    station_repository = DatabaseStationRepository(engine)
    vehicle_repository = DatabaseVehicleRepository(engine)
    status_repository = DatabaseStationStatusRepository(engine)
    telemetry_store = DatabaseRealtimeTelemetryStore(engine)
    original_state = {
        name: getattr(main_module.app.state, name)
        for name in (
            "database_engine",
            "station_repository",
            "vehicle_repository",
            "station_status_repository",
            "realtime_telemetry_store",
            "runtime_state",
            "redis_client",
            "redis_sync_client",
            "oidc_jwks_client",
            "settings",
        )
    }
    try:
        import_release_catalog(
            engine,
            station_payload,
            (_release_vehicle(vehicle_id),),
            apply=True,
            reviewed_by="integration-test",
        )
        assert station_repository.telemetry_port_inventory(station_id) == (
            ("CCS2-1", "CCS2"),
        )
        provider_port_id = f"provider-port-{station_id}"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ports SET external_id=:external_id "
                    "WHERE station_id=(SELECT id FROM stations WHERE code=:station_id)"
                ),
                {"external_id": provider_port_id, "station_id": station_id},
            )
        assert station_repository.telemetry_port_inventory(station_id) == (
            (provider_port_id, "CCS2"),
        )
        telemetry = StationTelemetrySnapshot(
            station_id=station_id,
            observed_at=datetime.now(UTC),
            ports=(
                ChargingPortTelemetry(
                    port_id=provider_port_id,
                    connector_types=("CCS2",),
                    state="available",
                ),
            ),
            queue=(),
            avg_session_duration_min=30,
            data_source="station_api",
        )

        release_settings = replace(
            main_module.settings,
            demo_mode=False,
            catalog_storage="database",
            catalog_source_max_age_s=30 * 24 * 60 * 60,
            oidc_issuer="https://identity.integration.test/",
            oidc_audience="smart-ev-api",
            oidc_jwks_url="https://identity.integration.test/keys",
            telemetry_ingest_api_key="integration-telemetry-key",
        )
        monkeypatch.setattr(
            main_module,
            "settings",
            release_settings,
        )
        main_module.app.state.settings = release_settings
        main_module.app.state.database_engine = engine
        main_module.app.state.station_repository = station_repository
        main_module.app.state.vehicle_repository = vehicle_repository
        main_module.app.state.station_status_repository = status_repository
        main_module.app.state.realtime_telemetry_store = telemetry_store
        main_module.app.state.runtime_state = RuntimeStateStore(
            status_repository,
            main_module.app.state.domain_data.demo_events,
            telemetry=telemetry_store,
            telemetry_max_age_s=300,
            enforce_freshness=True,
        )
        main_module.app.state.redis_client = AvailableRedis()
        main_module.app.state.redis_sync_client = None
        main_module.app.state.oidc_jwks_client = AvailableJwks()

        async def request_readiness() -> httpx.Response:
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://integration"
            ) as client:
                rejected = await client.put(
                    f"/realtime/stations/{station_id}/telemetry",
                    json=telemetry.model_dump(mode="json"),
                    headers={"X-Telemetry-API-Key": "invalid"},
                )
                assert rejected.status_code == 401
                simulated = await client.put(
                    f"/realtime/stations/{station_id}/telemetry",
                    json=telemetry.model_copy(
                        update={"data_source": "simulated"}
                    ).model_dump(mode="json"),
                    headers={"X-Telemetry-API-Key": "integration-telemetry-key"},
                )
                assert simulated.status_code == 422
                unknown_port = await client.put(
                    f"/realtime/stations/{station_id}/telemetry",
                    json=telemetry.model_copy(
                        update={
                            "ports": (
                                telemetry.ports[0].model_copy(
                                    update={"port_id": "not-the-catalog-port"}
                                ),
                            )
                        }
                    ).model_dump(mode="json"),
                    headers={"X-Telemetry-API-Key": "integration-telemetry-key"},
                )
                assert unknown_port.status_code == 409
                ingested = await client.put(
                    f"/realtime/stations/{station_id}/telemetry",
                    json=telemetry.model_dump(mode="json"),
                    headers={"X-Telemetry-API-Key": "integration-telemetry-key"},
                )
                assert ingested.status_code == 200, ingested.text
                replay = await client.put(
                    f"/realtime/stations/{station_id}/telemetry",
                    json=telemetry.model_dump(mode="json"),
                    headers={"X-Telemetry-API-Key": "integration-telemetry-key"},
                )
                assert replay.status_code == 200, replay.text
                conflict = await client.put(
                    f"/realtime/stations/{station_id}/telemetry",
                    json=telemetry.model_copy(
                        update={"avg_session_duration_min": 31}
                    ).model_dump(mode="json"),
                    headers={"X-Telemetry-API-Key": "integration-telemetry-key"},
                )
                assert conflict.status_code == 409
                stored = await client.get(
                    f"/realtime/stations/{station_id}/telemetry",
                    headers={"X-Telemetry-API-Key": "integration-telemetry-key"},
                )
                assert stored.status_code == 200, stored.text
                stored_observed_at = datetime.fromisoformat(
                    stored.json()["observed_at"].replace("Z", "+00:00")
                )
                assert stored_observed_at == telemetry.observed_at
                return await client.get("/health/ready")

        response = asyncio.run(request_readiness())

        assert response.status_code == 200, response.json()
        checks = response.json()["checks"]
        assert checks["database"]["status"] == "ok"
        assert checks["catalog"]["status"] == "ok"
        assert checks["catalog"]["eligible_stations"] >= 1
        assert checks["catalog"]["eligible_vehicles"] >= 1
        assert checks["station_status"] == {
            "status": "ok",
            "fresh_stations": 1,
            "operational_stations": 1,
            "eligible_stations": checks["catalog"]["eligible_stations"],
        }
        assert checks["identity"] == {"status": "ok", "signing_keys": 1}
        assert checks["redis"] == {"status": "ok"}
    finally:
        for name, value in original_state.items():
            setattr(main_module.app.state, name, value)
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM stations WHERE code=:station_id"),
                {"station_id": station_id},
            )
            connection.execute(
                text("DELETE FROM vehicle_models WHERE code=:vehicle_id"),
                {"vehicle_id": vehicle_id},
            )
        engine.dispose()
