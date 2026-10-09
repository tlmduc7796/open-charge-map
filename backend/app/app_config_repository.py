"""Operational thresholds, with PostgreSQL overrides for versioned API reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, text

from backend.app.config import Settings


@dataclass(frozen=True)
class OperationalConfig:
    reroute_deviation_m: int
    reroute_eta_delta_min: int
    near_station_radius_m: int
    arrival_radius_m: int
    position_interval_sec: int
    reroute_cooldown_sec: int
    low_battery_pct: int
    availability_green_min: int
    station_status_stale_after_sec: int
    stations_version: str
    vehicles_version: str
    updated_at: datetime


class AppConfigRepository:
    def __init__(self, settings: Settings, engine: Engine | None = None) -> None:
        self._settings = settings
        self._engine = engine

    def read(self) -> OperationalConfig:
        values: dict[str, object] = {}
        updated_at = datetime.fromtimestamp(0, UTC)
        station_version = "fixture"
        vehicle_version = "fixture"
        if self._engine is not None:
            with self._engine.connect() as connection:
                rows = connection.execute(
                    text("SELECT key, value, updated_at FROM app_config")
                ).mappings()
                for row in rows:
                    values[row["key"]] = row["value"]
                    timestamp = row["updated_at"]
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp)
                    updated_at = max(updated_at, timestamp)
                station_version = str(
                    connection.scalar(text("SELECT max(updated_at) FROM stations"))
                )
                vehicle_version = str(
                    connection.scalar(text("SELECT max(updated_at) FROM vehicle_models"))
                )

        defaults = {
            "reroute_deviation_m": 150,
            "reroute_eta_delta_min": 5,
            "near_station_radius_m": 250,
            "arrival_radius_m": 150,
            "position_interval_sec": 10,
            "reroute_cooldown_sec": 60,
            "low_battery_pct": 15,
            "availability_green_min": self._settings.availability_green_min,
            "station_status_stale_after_sec": int(
                self._settings.station_status_stale_after_s
            ),
        }
        resolved: dict[str, int] = {}
        for key, default in defaults.items():
            value = values.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"app_config {key} must be a positive integer")
            resolved[key] = value
        return OperationalConfig(
            **resolved,
            stations_version=station_version,
            vehicles_version=vehicle_version,
            updated_at=(
                updated_at
                if updated_at != datetime.fromtimestamp(0, UTC)
                else datetime.now(UTC)
            ),
        )
