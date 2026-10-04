"""Hourly weather categories (sunny / cloudy / rain) read from the saved Open-Meteo file."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh has no DST
HOUR = timedelta(hours=1)


def classify(row: dict, weather_config: dict) -> str:
    if row["precipitation_mm"] >= weather_config["rain_min_mm_per_hour"]:
        return "rain"
    if row["is_day"] == 1 and row["cloud_cover_pct"] < weather_config["sunny_max_cloud_cover_pct"]:
        return "sunny"
    return "cloudy"


def load_weather_categories(path: Path, weather_config: dict) -> dict[datetime, str]:
    """Map each local hour start (tz-aware) to its weather category."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        datetime.fromisoformat(row["time"]).replace(tzinfo=LOCAL_TZ): classify(row, weather_config)
        for row in data["hourly"]
    }
