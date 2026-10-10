"""Checks that release lifespan starts the planned-arrival expiry worker."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from threading import Event

from backend.app import main as main_module
from backend.app.main import app


def test_release_lifespan_runs_planned_arrival_expiry(monkeypatch) -> None:
    expired = Event()

    class ExpiringStore:
        def expire(self, evaluation_at: datetime) -> tuple[()]:
            assert evaluation_at.tzinfo is not None
            expired.set()
            return ()

    async def exercise() -> None:
        with monkeypatch.context() as patch:
            patch.setattr(
                app.state,
                "settings",
                replace(app.state.settings, demo_mode=False),
            )
            patch.setattr(app.state, "planned_arrival_store", ExpiringStore())
            patch.setattr(app.state, "redis_client", None)
            patch.setattr(app.state, "redis_sync_client", None)
            patch.setattr(app.state, "database_engine", None)

            async with main_module.lifespan(app):
                assert await asyncio.to_thread(expired.wait, 2)

    asyncio.run(exercise())


def test_lifespan_closes_remaining_resources_after_redis_shutdown_error(monkeypatch) -> None:
    closed: list[str] = []

    class BrokenAsyncRedis:
        async def aclose(self) -> None:
            raise RuntimeError("simulated Redis close failure")

    class SyncRedis:
        def close(self) -> None:
            closed.append("sync_redis")

    class DatabaseEngine:
        def dispose(self) -> None:
            closed.append("database")

    async def exercise() -> None:
        with monkeypatch.context() as patch:
            patch.setattr(
                app.state,
                "settings",
                replace(app.state.settings, demo_mode=True),
            )
            patch.setattr(app.state, "redis_client", BrokenAsyncRedis())
            patch.setattr(app.state, "redis_sync_client", SyncRedis())
            patch.setattr(app.state, "database_engine", DatabaseEngine())

            async with main_module.lifespan(app):
                pass

    asyncio.run(exercise())
    assert closed == ["sync_redis", "database"]
