"""Stable error envelope for the versioned HTTP API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _default_code(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "HTTP_ERROR")


def _payload(request: Request, status_code: int, detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict) and "code" in detail:
        code = str(detail["code"])
        message = str(detail.get("message", code))
        details = {key: value for key, value in detail.items() if key not in {"code", "message"}}
    else:
        code = _default_code(status_code)
        message = str(detail)
        details = {}
    return {
        "error": {"code": code, "message": message, "details": details},
        "requestId": getattr(request.state, "request_id", "unknown"),
    }


def install_api_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if not request.url.path.startswith("/api/v1"):
            return await http_exception_handler(request, exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(request, exc.status_code, exc.detail),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if not request.url.path.startswith("/api/v1"):
            return await request_validation_exception_handler(request, exc)
        details = {
            "issues": [
                {
                    "location": [str(part) for part in issue["loc"]],
                    "message": issue["msg"],
                    "type": issue["type"],
                }
                for issue in exc.errors()
            ]
        }
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "request validation failed",
                    "details": details,
                },
                "requestId": getattr(request.state, "request_id", "unknown"),
            },
        )
