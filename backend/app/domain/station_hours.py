"""Conservative opening-hours check for the formats in the current catalog."""

from __future__ import annotations

from backend.app.domain.models import Station


def is_confirmed_open(station: Station) -> bool:
    hours = station.properties.opening_hours
    if isinstance(hours, str):
        return hours.strip().lower() in {"24/7", "24h", "always open"}
    if isinstance(hours, dict):
        return hours.get("always_open") is True
    return False
