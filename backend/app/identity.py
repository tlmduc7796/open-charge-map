"""OIDC access-token verification for user-authenticated API operations."""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError

BEARER = HTTPBearer(auto_error=False)
ALLOWED_ACCESS_TOKEN_ALGORITHMS = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
)


def verify_access_token(token: str, settings, jwks_client) -> dict[str, Any]:
    """Verify signature, issuer, audience, expiry, and user subject."""
    if not settings.oidc_issuer or not settings.oidc_audience or jwks_client is None:
        raise HTTPException(status_code=503, detail="identity verification is not configured")
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
    except PyJWKClientConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="identity signing keys are temporarily unavailable",
        ) from exc
    except PyJWKClientError as exc:
        raise HTTPException(status_code=401, detail="invalid access token") from exc
    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALLOWED_ACCESS_TOKEN_ALGORITHMS,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid access token") from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status_code=401, detail="access token has no user subject")
    return claims


def require_authenticated_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(BEARER),
) -> dict[str, Any]:
    """FastAPI dependency for OIDC-only customer operations."""
    if request.app.state.settings.demo_mode:
        return {"sub": "demo"}
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_access_token(
        credentials.credentials,
        request.app.state.settings,
        request.app.state.oidc_jwks_client,
    )
