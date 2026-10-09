from __future__ import annotations

from sqlalchemy import create_engine, text

from backend.app.app_config_repository import AppConfigRepository
from backend.app.config import load_settings


def test_database_config_overrides_operational_defaults() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE app_config (key text, value json, updated_at text)")
        )
        connection.execute(text("CREATE TABLE stations (updated_at text)"))
        connection.execute(text("CREATE TABLE vehicle_models (updated_at text)"))
        connection.execute(
            text(
                "INSERT INTO app_config VALUES "
                "('availability_green_min', 4, '2026-10-09T00:00:00+00:00')"
            )
        )
    try:
        config = AppConfigRepository(load_settings(), engine).read()
    finally:
        engine.dispose()

    assert config.availability_green_min == 4
    assert config.reroute_deviation_m == 150
