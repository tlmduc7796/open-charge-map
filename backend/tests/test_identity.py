import json
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt.exceptions import PyJWKClientConnectionError

from backend.app.identity import verify_access_token


class FakeSigningKey:
    def __init__(self, key) -> None:
        self.key = key


class FakeJwksClient:
    def __init__(self, key) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, _token: str) -> FakeSigningKey:
        return FakeSigningKey(self.key)


class UnavailableJwksClient:
    def get_signing_key_from_jwt(self, _token: str) -> FakeSigningKey:
        raise PyJWKClientConnectionError("JWKS endpoint unavailable")


@pytest.fixture
def oidc_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def oidc_settings():
    return SimpleNamespace(
        oidc_issuer="https://identity.example.com/",
        oidc_audience="smart-ev-api",
    )


def _token(private_key, **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "https://identity.example.com/",
        "aud": "smart-ev-api",
        "sub": "user-123",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **overrides,
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_verify_access_token_accepts_valid_oidc_token(oidc_keys, oidc_settings) -> None:
    private_key, public_key = oidc_keys

    claims = verify_access_token(
        _token(private_key), oidc_settings, FakeJwksClient(public_key)
    )

    assert claims["sub"] == "user-123"


def test_verify_access_token_discovers_signing_key_from_live_jwks_endpoint(
    oidc_keys, oidc_settings
) -> None:
    private_key, public_key = oidc_keys
    key_id = "integration-signing-key"
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    jwk.update({"kid": key_id, "use": "sig", "alg": "RS256"})
    response_body = json.dumps({"keys": [jwk]}).encode("utf-8")

    class JwksHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/.well-known/jwks.json":
                self.send_error(404)
                return
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
    try:
        token = jwt.encode(
            {
                "iss": oidc_settings.oidc_issuer,
                "aud": oidc_settings.oidc_audience,
                "sub": "user-123",
                "iat": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            private_key,
            algorithm="RS256",
            headers={"kid": key_id},
        )
        jwks_client = jwt.PyJWKClient(
            f"http://127.0.0.1:{server.server_port}/.well-known/jwks.json",
            cache_keys=False,
        )

        claims = verify_access_token(token, oidc_settings, jwks_client)

        assert claims["sub"] == "user-123"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "https://attacker.example.com/"),
        ("aud", "other-api"),
        ("exp", datetime.now(UTC) - timedelta(minutes=1)),
        ("sub", ""),
    ],
)
def test_verify_access_token_rejects_invalid_claims(
    oidc_keys, oidc_settings, claim: str, value
) -> None:
    private_key, public_key = oidc_keys

    with pytest.raises(HTTPException) as error:
        verify_access_token(
            _token(private_key, **{claim: value}),
            oidc_settings,
            FakeJwksClient(public_key),
        )

    assert error.value.status_code == 401


def test_verify_access_token_rejects_invalid_signature(oidc_keys, oidc_settings) -> None:
    private_key, _ = oidc_keys
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(HTTPException) as error:
        verify_access_token(
            _token(private_key), oidc_settings, FakeJwksClient(other_key.public_key())
        )

    assert error.value.status_code == 401


def test_verify_access_token_rejects_symmetric_signing_algorithm(
    oidc_keys, oidc_settings
) -> None:
    _, public_key = oidc_keys
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": oidc_settings.oidc_issuer,
            "aud": oidc_settings.oidc_audience,
            "sub": "user-123",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        "attacker-controlled-secret-that-is-long-enough",
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as error:
        verify_access_token(token, oidc_settings, FakeJwksClient(public_key))

    assert error.value.status_code == 401


def test_verify_access_token_reports_jwks_outage_as_service_unavailable(
    oidc_keys, oidc_settings
) -> None:
    private_key, _ = oidc_keys

    with pytest.raises(HTTPException) as error:
        verify_access_token(_token(private_key), oidc_settings, UnavailableJwksClient())

    assert error.value.status_code == 503


def test_verify_access_token_requires_exp_issuer_audience_and_subject(
    oidc_keys, oidc_settings
) -> None:
    private_key, public_key = oidc_keys
    token = jwt.encode(
        {"iss": "https://identity.example.com/", "aud": "smart-ev-api", "sub": "user-123"},
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(HTTPException) as error:
        verify_access_token(token, oidc_settings, FakeJwksClient(public_key))

    assert error.value.status_code == 401
