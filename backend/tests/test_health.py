import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from jwt.exceptions import PyJWKClientConnectionError
from redis.exceptions import ConnectionError as RedisConnectionError

import backend.app.main as main_module
from backend.app.main import app


class AvailableRedis:
    async def ping(self) -> bool:
        return True


class UnavailableRedis:
    async def ping(self) -> bool:
        raise RedisConnectionError("redis unavailable at redis://user:secret@cache.internal")


class AvailableJwks:
    def get_signing_keys(self):
        return [object()]


class UnavailableJwks:
    def get_signing_keys(self):
        raise PyJWKClientConnectionError("jwks unavailable")


def test_health_endpoint() -> None:
    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Smart EV Journey API",
        "environment": "development",
        "demo_mode": True,
    }


def test_liveness_does_not_require_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "database_engine", object())

    def fail_if_database_checked(_engine: object) -> str:
        raise AssertionError("liveness must not check the database")

    monkeypatch.setattr(main_module, "validate_database", fail_if_database_checked)

    async def request_liveness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/live")

    response = asyncio.run(request_liveness())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_persistence_fallback() -> None:
    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"]["database"]["status"] == "not_required"
    assert payload["checks"]["redis"]["status"] == "not_required"
    assert payload["checks"]["occupancy_model"]["prediction_source"] == "persistence"


def test_health_checks_endpoint_returns_dependency_report() -> None:
    async def request_checks() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/checks")

    response = asyncio.run(request_checks())

    assert response.status_code == 200
    assert response.json()["checks"]["redis"]["status"] == "not_required"


def test_readiness_checks_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "redis_client", AvailableRedis())

    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 200
    assert response.json()["checks"]["redis"]["status"] == "ok"


def test_readiness_fails_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "redis_client", UnavailableRedis())

    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 503
    assert response.json()["detail"]["checks"]["redis"] == {
        "status": "unavailable",
        "reason": "rate-limit and realtime storage is unavailable",
    }
    assert "secret" not in response.text


def test_readiness_returns_503_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "database_engine", object())

    def fail_database_check(_engine: object) -> str:
        raise RuntimeError("database unavailable at postgres://user:secret@db.internal")

    monkeypatch.setattr(main_module, "validate_database", fail_database_check)

    async def request_health_endpoints() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            readiness_response = await client.get("/health/ready")
            health_response = await client.get("/health")
            return readiness_response, health_response

    response, health_response = asyncio.run(request_health_endpoints())

    assert response.status_code == 503
    assert response.json()["detail"]["checks"]["database"] == {
        "status": "unavailable",
        "reason": "database is unavailable or its schema is not ready",
    }
    assert "secret" not in response.text
    assert health_response.status_code == 503
    assert "secret" not in health_response.text


def test_application_startup_loaded_domain_data() -> None:
    station_count = len(app.state.domain_data.stations.all())
    assert station_count > 0
    assert len(app.state.domain_data.vehicles.all()) > 0
    assert len(app.state.domain_data.station_statuses.all()) == station_count
    assert len(app.state.domain_data.planned_arrivals.all()) == 4
    assert app.state.occupancy_forecast_service is not None
    assert app.state.wait_estimator is not None


def _configure_release_readiness(
    monkeypatch,
    *,
    has_fresh_status: bool,
    all_ports_unknown: bool = False,
    vehicle_has_synthetic_fields: bool = False,
    catalog_source_updated_at: datetime | None = None,
) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(
            main_module.settings,
            demo_mode=False,
            catalog_storage="database",
            oidc_issuer="https://identity.test/",
            oidc_audience="smart-ev-api",
            oidc_jwks_url="https://identity.test/keys",
            catalog_source_max_age_s=30 * 24 * 60 * 60,
        ),
    )
    station = next(
        item
        for item in app.state.domain_data.stations.all()
        if not main_module._station_has_synthetic_data(item)
    )
    if catalog_source_updated_at is not None:
        station = station.model_copy(
            update={
                "properties": station.properties.model_copy(
                    update={
                        "source_updated_at": catalog_source_updated_at,
                        "source_updated_at_basis": "source",
                    }
                )
            }
        )
    vehicle = app.state.domain_data.vehicles.all()[0].model_copy(
        update={
            "is_synthetic": False,
            "synthetic_fields": (
                ("max_dc_power_kw",) if vehicle_has_synthetic_fields else ()
            ),
        }
    )
    status = app.state.domain_data.station_statuses.get(station.station_id).model_copy(
        update={
            "timestamp": datetime.now(UTC),
            "data_source": "station_api" if has_fresh_status else "unknown",
            "is_stale": not has_fresh_status,
        }
    )
    if all_ports_unknown:
        status = status.model_copy(
            update={
                "operational_ports": 0,
                "occupied_ports": 0,
                "available_ports": 0,
                "offline_ports": 0,
                "unknown_ports": status.total_ports,
                "occupancy_ratio": None,
            }
        )

    class Repository:
        def __init__(self, records):
            self.records = records

        def all(self):
            return self.records

    class RuntimeState:
        def all(self):
            return (status,)

    monkeypatch.setattr(app.state, "database_engine", object())
    monkeypatch.setattr(app.state, "station_repository", Repository((station,)))
    monkeypatch.setattr(app.state, "vehicle_repository", Repository((vehicle,)))
    monkeypatch.setattr(app.state, "runtime_state", RuntimeState())
    monkeypatch.setattr(app.state, "redis_client", AvailableRedis())
    monkeypatch.setattr(app.state, "oidc_jwks_client", AvailableJwks())
    monkeypatch.setattr(main_module, "validate_database", lambda _engine: "test_revision")


def test_release_readiness_requires_fresh_operational_station_status(monkeypatch) -> None:
    _configure_release_readiness(monkeypatch, has_fresh_status=False)

    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 503
    assert response.json()["detail"]["checks"]["station_status"] == {
        "status": "unavailable",
        "fresh_stations": 0,
        "operational_stations": 0,
        "eligible_stations": 1,
    }


def test_release_readiness_passes_with_fresh_operational_station_status(monkeypatch) -> None:
    _configure_release_readiness(monkeypatch, has_fresh_status=True)

    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 200, response.json()
    assert response.json()["checks"]["station_status"] == {
        "status": "ok",
        "fresh_stations": 1,
        "operational_stations": 1,
        "eligible_stations": 1,
    }
    assert response.json()["checks"]["identity"] == {
        "status": "ok",
        "signing_keys": 1,
    }
    assert response.json()["checks"]["catalog"]["source_freshness_status"] == "ok"


def test_release_readiness_rejects_stale_source_catalog_timestamp(monkeypatch) -> None:
    _configure_release_readiness(
        monkeypatch,
        has_fresh_status=True,
        catalog_source_updated_at=datetime.now(UTC) - timedelta(days=31),
    )

    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 503
    catalog = response.json()["detail"]["checks"]["catalog"]
    assert catalog["status"] == "incomplete"
    assert catalog["source_freshness_status"] == "unavailable"
    assert catalog["stale_source_timestamps"] == 1


def test_release_readiness_rejects_vehicles_with_synthetic_fields(monkeypatch) -> None:
    _configure_release_readiness(
        monkeypatch,
        has_fresh_status=True,
        vehicle_has_synthetic_fields=True,
    )

    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 503
    catalog = response.json()["detail"]["checks"]["catalog"]
    assert {
        "status": catalog["status"],
        "eligible_stations": catalog["eligible_stations"],
        "eligible_vehicles": catalog["eligible_vehicles"],
    } == {
        "status": "incomplete",
        "eligible_stations": 1,
        "eligible_vehicles": 0,
    }
    assert catalog["source_timestamp_count"] == 1
    assert catalog["database_timestamp_fallback_count"] == 0
    assert catalog["missing_timestamp_count"] == 0
    assert catalog["future_timestamp_count"] == 0
    assert catalog["oldest_source_timestamp_age_seconds"] >= 0
    assert catalog["oldest_source_timestamp"]
    assert catalog["oldest_catalog_timestamp_age_seconds"] >= 0


def test_release_readiness_rejects_fresh_snapshot_when_all_ports_are_unknown(monkeypatch) -> None:
    _configure_release_readiness(
        monkeypatch, has_fresh_status=True, all_ports_unknown=True
    )

    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 503
    assert response.json()["detail"]["checks"]["station_status"] == {
        "status": "unavailable",
        "fresh_stations": 1,
        "operational_stations": 0,
        "eligible_stations": 1,
    }


def test_release_readiness_fails_when_oidc_jwks_is_unavailable(monkeypatch) -> None:
    _configure_release_readiness(monkeypatch, has_fresh_status=True)
    monkeypatch.setattr(app.state, "oidc_jwks_client", UnavailableJwks())

    async def request_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/ready")

    response = asyncio.run(request_readiness())

    assert response.status_code == 503
    assert response.json()["detail"]["checks"]["identity"] == {
        "status": "unavailable",
        "reason": "identity signing keys are unavailable",
    }
