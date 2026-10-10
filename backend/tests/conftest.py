"""Keep a developer's configured Redis service out of app-singleton unit tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_global_app_redis_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent API unit tests from sharing Redis connections across event loops.

    Redis integration tests create and close their own clients. The global app's
    clients are unrelated to those checks and otherwise leak a live connection
    into tests that assume the development default (Redis disabled).
    """
    if not os.getenv("REDIS_URL"):
        return

    from backend.app.main import app

    monkeypatch.setattr(app.state, "redis_client", None)
    monkeypatch.setattr(app.state, "redis_sync_client", None)
