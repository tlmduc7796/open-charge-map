import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient

from backend.app.api import (
    _scope_journey_idempotency_key,
    _station_has_synthetic_data,
)
from backend.app.identity import require_authenticated_user
from backend.app.main import app


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def _enable_release_request_path(monkeypatch) -> None:
    class RedisLimiter:
        async def eval(self, *_args):
            return [1, 60]

    monkeypatch.setattr(
        app.state,
        "settings",
        replace(
            app.state.settings,
            demo_mode=False,
            telemetry_ingest_api_key="t" * 48,
            planned_arrival_admin_api_key="p" * 48,
            incident_review_api_key="i" * 48,
        ),
    )
    monkeypatch.setattr(app.state, "redis_client", RedisLimiter())


def test_release_requires_oidc_for_customer_operations(monkeypatch) -> None:
    _enable_release_request_path(monkeypatch)

    async def request_customer_routes() -> tuple[httpx.Response, ...]:
        return tuple(
            await asyncio.gather(
                _request("GET", "/geocoding/autocomplete?query=Ho%20Chi%20Minh"),
                _request(
                    "POST",
                    "/route",
                    json={
                        "origin": {"lat": 10.7769, "lon": 106.7008},
                        "destination": {"lat": 10.8231, "lon": 106.6297},
                    },
                ),
                _request(
                    "POST",
                    "/journey/recommend",
                    json={
                        "vehicle_id": "EV_VF5_PLUS",
                        "initial_soc": 0.6,
                        "origin": {"lat": 10.7769, "lon": 106.7008},
                        "destination": {"lat": 10.8231, "lon": 106.6297},
                        "departure_at": "2026-10-09T09:00:00+07:00",
                    },
                ),
            ),
        )

    responses = asyncio.run(request_customer_routes())

    assert [response.status_code for response in responses] == [401, 401, 401]


def test_release_customer_route_accepts_bearer_verified_from_live_jwks(monkeypatch) -> None:
    _enable_release_request_path(monkeypatch)
    issuer = "https://identity.integration.test/"
    audience = "smart-ev-api"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_id = "release-auth-integration-key"
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": key_id, "use": "sig", "alg": "RS256"})
    response_body = json.dumps({"keys": [jwk]}).encode("utf-8")

    class JwksHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), JwksHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        app.state,
        "settings",
        replace(
            app.state.settings,
            demo_mode=False,
            oidc_issuer=issuer,
            oidc_audience=audience,
        ),
    )
    monkeypatch.setattr(
        app.state,
        "oidc_jwks_client",
        PyJWKClient(f"http://127.0.0.1:{server.server_port}/jwks", cache_keys=False),
    )

    class GeocodingService:
        def autocomplete(self, query: str):
            return [{"query": query, "provider": "integration"}]

    monkeypatch.setattr(app.state, "geocoding_service", GeocodingService())
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": "integration-user",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )

    async def exercise_route() -> tuple[httpx.Response, httpx.Response]:
        missing_token = await _request(
            "GET", "/geocoding/autocomplete?query=Ho%20Chi%20Minh"
        )
        authenticated = await _request(
            "GET",
            "/geocoding/autocomplete?query=Ho%20Chi%20Minh",
            headers={"Authorization": f"Bearer {token}"},
        )
        return missing_token, authenticated

    try:
        missing_token, authenticated = asyncio.run(exercise_route())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert missing_token.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json() == [
        {"query": "Ho Chi Minh", "provider": "integration"}
    ]


def test_release_idempotent_journey_replay_skips_recommendation(monkeypatch) -> None:
    _enable_release_request_path(monkeypatch)
    signing_key = "journey-signing-key-for-idempotency-tests-123456"
    monkeypatch.setattr(
        app.state,
        "settings",
        replace(
            app.state.settings,
            journey_token_signing_key=signing_key,
            oidc_issuer="https://identity.test/",
        ),
    )
    scenario = app.state.domain_data.demo_scenarios.get("SCN_LOW_SOC")
    stored = app.state.recommendation_service.recommend_scenario(scenario).model_copy(
        update={"scenario_id": None, "journey_id": str(uuid4())}
    )

    class ReplayRepository:
        def lookup_idempotent(self, request, key, **kwargs):
            assert request.vehicle_id == "EV_VF5_PLUS"
            assert key == _scope_journey_idempotency_key(
                "release-retry-key-0001",
                {"sub": "test-user"},
                app.state.settings,
            )
            assert kwargs["access_token_ttl_days"] == app.state.settings.journey_token_ttl_days
            return stored

    class RecommendationTrap:
        def recommend_scenario(self, *_args, **_kwargs):
            raise AssertionError("an idempotent replay must skip recommendation")

    monkeypatch.setattr(app.state, "journey_repository", ReplayRepository())
    monkeypatch.setattr(app.state, "recommendation_service", RecommendationTrap())
    app.dependency_overrides[require_authenticated_user] = lambda: {"sub": "test-user"}

    async def replay():
        return await _request(
            "POST",
            "/journey/recommend",
            headers={"Idempotency-Key": "release-retry-key-0001"},
            json={
                "vehicle_id": "EV_VF5_PLUS",
                "initial_soc": 0.2,
                "origin": {"lat": 10.7769, "lon": 106.7008},
                "destination": {"lat": 10.8231, "lon": 106.6297},
                "departure_at": "2026-10-09T09:00:00+07:00",
            },
        )

    try:
        response = asyncio.run(replay())
    finally:
        app.dependency_overrides.pop(require_authenticated_user, None)

    assert response.status_code == 200
    assert response.json()["journey_id"] == stored.journey_id
    assert response.headers["X-Journey-Access-Token"]


def test_release_idempotency_and_capabilities_are_scoped_to_oidc_identity() -> None:
    signing_key = "journey-signing-key-for-idempotency-tests-123456"
    settings = replace(
        app.state.settings,
        demo_mode=False,
        journey_token_signing_key=signing_key,
        oidc_issuer="https://identity.test/",
    )

    user_a_key = _scope_journey_idempotency_key(
        "same-client-key-0001", {"iss": settings.oidc_issuer, "sub": "user-a"}, settings
    )
    user_a_retry = _scope_journey_idempotency_key(
        "same-client-key-0001", {"iss": settings.oidc_issuer, "sub": "user-a"}, settings
    )
    user_b_key = _scope_journey_idempotency_key(
        "same-client-key-0001", {"iss": settings.oidc_issuer, "sub": "user-b"}, settings
    )

    assert user_a_key == user_a_retry
    assert user_a_key != user_b_key
    assert user_a_key != "same-client-key-0001"


def test_release_catalog_status_and_model_reads_remain_public(monkeypatch) -> None:
    _enable_release_request_path(monkeypatch)
    station = next(
        item
        for item in app.state.station_repository.all()
        if not _station_has_synthetic_data(item)
    )

    async def read_public_routes() -> tuple[httpx.Response, ...]:
        return tuple(
            await asyncio.gather(
                _request("GET", "/stations?limit=1"),
                _request("GET", f"/stations/{station.station_id}/status"),
                _request("GET", "/model/status"),
            )
        )

    responses = asyncio.run(read_public_routes())

    assert [response.status_code for response in responses] == [200, 200, 200]


def test_release_vehicle_catalog_hides_profiles_with_synthetic_fields(monkeypatch) -> None:
    _enable_release_request_path(monkeypatch)
    vehicle = app.state.vehicle_repository.all()[0].model_copy(
        update={"is_synthetic": False, "synthetic_fields": ()}
    )
    field_marked_synthetic = vehicle.model_copy(
        update={"synthetic_fields": ("max_dc_power_kw",)}
    )

    class VehicleRepository:
        def all(self):
            return (vehicle, field_marked_synthetic)

    monkeypatch.setattr(app.state, "vehicle_repository", VehicleRepository())

    response = asyncio.run(_request("GET", "/vehicles"))

    assert response.status_code == 200
    assert [item["vehicle_id"] for item in response.json()] == [vehicle.vehicle_id]


def test_operator_and_telemetry_routes_still_require_their_api_keys(monkeypatch) -> None:
    _enable_release_request_path(monkeypatch)

    async def request_operator_routes() -> tuple[httpx.Response, ...]:
        headers = {"Authorization": "Bearer oidc-token-without-operator-key"}
        return tuple(
            await asyncio.gather(
                _request("GET", "/planned-arrivals", headers=headers),
                _request("GET", "/admin/incidents", headers=headers),
                _request(
                    "GET",
                    "/realtime/stations/ST_EVO_LAVIDA_Q7/telemetry",
                    headers=headers,
                ),
            )
        )

    responses = asyncio.run(request_operator_routes())

    assert [response.status_code for response in responses] == [401, 401, 401]


def test_release_disables_every_demo_simulation_route(monkeypatch) -> None:
    _enable_release_request_path(monkeypatch)
    app.dependency_overrides[require_authenticated_user] = lambda: {"sub": "test-user"}

    async def request_demo_routes() -> tuple[httpx.Response, ...]:
        return tuple(
            await asyncio.gather(
                _request("GET", "/demo/scenarios"),
                _request("POST", "/demo/reset"),
                _request("POST", "/demo/events/EVT_UNKNOWN/apply"),
                _request("GET", "/queue-lab/default-scenario"),
                _request(
                    "POST",
                    "/queue-lab/simulate",
                    json={
                        "evaluation_at": "2026-10-09T09:00:00+07:00",
                        "ports": [
                            {
                                "port_id": "P1",
                                "connector_types": ["CCS2"],
                                "state": "available",
                            }
                        ],
                        "requester_connector_types": ["CCS2"],
                        "requester_charge_duration": {"kind": "fixed", "value_min": 20},
                        "trials": 1,
                    },
                ),
                _request(
                    "POST",
                    "/realtime/stations/ST_EVO_LAVIDA_Q7/simulate-wait",
                    headers={"X-Telemetry-API-Key": "t" * 48},
                    json={
                        "evaluation_at": "2026-10-09T09:00:00+07:00",
                        "compatible_connector_types": ["CCS2"],
                    },
                ),
                _request(
                    "POST",
                    "/journey/recommend",
                    json={"scenario_id": "SCN_NORMAL"},
                ),
                _request(
                    "POST",
                    "/journey/recommend",
                    headers={"Idempotency-Key": "release-demo-event-key-0001"},
                    json={
                        "vehicle_id": "EV_VF5_PLUS",
                        "initial_soc": 0.5,
                        "origin": {"lat": 10.7769, "lon": 106.7008},
                        "destination": {"lat": 10.8231, "lon": 106.6297},
                        "departure_at": "2026-10-09T09:00:00+07:00",
                        "apply_scenario_events": True,
                    },
                ),
            )
        )

    try:
        responses = asyncio.run(request_demo_routes())
    finally:
        app.dependency_overrides.pop(require_authenticated_user, None)

    assert [response.status_code for response in responses] == [403] * 8
    assert [response.json()["error_code"] for response in responses] == [
        "FORBIDDEN"
    ] * 8
